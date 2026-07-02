from ehir_llvm_backend.optimizer import OptimizationProfile
import ast
import hashlib
import json
import re
import subprocess
import time
import pickle
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.compiler import CompileProfileRecord
from ehir_llvm_backend import EHIR_LLVM_Backend

from ehir import EHIR_ProjectCompiler
from encore import __version__
from encore.compiler.inference import TypeInferer
from encore.compiler.parser import statements as s
from encore.compiler.translator import EncoreToEHIRTranslator
from encore.workspace import RefrainData, RefrainManager
from encore.utils.diagnostics import with_diagnostic_context

EHIR_CACHE_SCHEMA = "ehir-resolved-v2"


class ExportKind(StrEnum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    TRAIT = auto()


@dataclass(frozen=True)
class ExportBinding:
    name: str
    kind: ExportKind
    module_id: Path
    statement: s.Statement_TopLevel
    source_name: str | None = None


@dataclass
class ModuleIndex:
    module_id: Path
    exports: dict[str, ExportBinding] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportRequest:
    path: tuple[str, ...]
    kind: str  # "item" | "glob"
    alias: str | None = None


@dataclass(frozen=True)
class ImportedTopLevelDeclaration:
    module_id: Path
    statement: s.Statement_TopLevel
    local_name: str | None = None
    source_name: str | None = None


@dataclass(frozen=True)
class CompiledRefrain:
    refrain: RefrainData
    ehir_module: EHIR_Module
    output_path: Path


@dataclass(frozen=True)
class NativeLinkInputs:
    objects: tuple[Path, ...] = ()
    link_args: tuple[str, ...] = ()


@dataclass
class EncoreCompiler:
    refrain_manager: RefrainManager = field(default_factory=RefrainManager)
    targets: list[RefrainData] = field(default_factory=list)
    profile_records: list[CompileProfileRecord] = field(default_factory=list)

    def add_compile_target(self, path: Path):
        self.targets.append(self.refrain_manager.add_binary_target(path))

    def compile_all_targets(
        self,
        opt_profile: OptimizationProfile,
        *,
        use_cache: bool = True,
    ) -> list[CompiledRefrain]:
        building_queue = self.refrain_manager.get_building_queue()
        result: list[CompiledRefrain] = []
        native_inputs_by_refrain: dict[str, NativeLinkInputs] = {}

        for refrain in building_queue:
            print(f"Compiling {refrain.name}... ", end="")
            start_time = time.perf_counter()

            entrypoint = refrain.import_graph.entrypoint if refrain.import_graph is not None else None
            source_text = entrypoint.read_text() if entrypoint is not None and entrypoint.exists() else None
            cache_path = self._ehir_cache_path_for_refrain(refrain)
            try:
                native_inputs_by_refrain[refrain.name] = self._native_link_inputs_for_refrain(refrain)
            except Exception as exc:
                raise with_diagnostic_context(
                    exc,
                    stage="type-inference",
                    module_id=entrypoint,
                    source_text=source_text,
                ) from exc

            try:
                loaded_from_cache = False
                if use_cache and cache_path.exists():
                    print("cache hit!")
                    with cache_path.open("rb") as f:
                        ehir_resolved_module = pickle.load(f)
                    loaded_from_cache = True
                else:
                    self._infer_refrain_modules(refrain)
                    legacy_cache_path = self._legacy_ehir_cache_path_for_refrain(refrain)
                    if use_cache and legacy_cache_path.exists():
                        print("cache hit! migrated")
                        with legacy_cache_path.open("rb") as f:
                            ehir_resolved_module = pickle.load(f)
                        cache_path.parent.mkdir(exist_ok=True, parents=True)
                        with cache_path.open("wb") as f:
                            pickle.dump(ehir_resolved_module, f)
                        loaded_from_cache = True
                    else:
                        alias_declarations = self._flattened_alias_declarations(refrain)
                        ehir_raw_module = EncoreToEHIRTranslator().translate_ast(
                            refrain.ast,
                            module_id=entrypoint,
                            imported_declarations=alias_declarations,
                        )

                        ehir_compiler = EHIR_ProjectCompiler()
                        ehir_typed_module = ehir_compiler.resolve_module(ehir_raw_module)
                        ehir_resolved_module = ehir_compiler.compile_module(ehir_typed_module)

                        if use_cache:
                            print("cache miss!")
                            cache_path.parent.mkdir(exist_ok=True, parents=True)
                            with cache_path.open("wb") as f:
                                pickle.dump(ehir_resolved_module, f)

                        self.profile_records.extend(
                            CompileProfileRecord(
                                module=refrain.name,
                                stage=record.stage,
                                seconds=record.seconds,
                            )
                            for record in ehir_compiler.pass_timings
                        )
                link_inputs = self._native_link_inputs_for_closure(refrain, native_inputs_by_refrain)
                backend = EHIR_LLVM_Backend()
                output_path = backend.artifact_output_path(ehir_resolved_module, opt_profile=opt_profile)
                if not (
                    loaded_from_cache
                    and output_path.exists()
                    and self._artifact_is_current(output_path, link_inputs)
                ):
                    output_path = backend.compile(
                        ehir_resolved_module,
                        opt_profile=opt_profile,
                        native_objects=list(link_inputs.objects),
                        native_link_args=list(link_inputs.link_args),
                    )
            except Exception as exc:
                raise with_diagnostic_context(
                    exc,
                    stage="translation",
                    module_id=entrypoint,
                    source_text=source_text,
                ) from exc

            time_elapsed = time.perf_counter() - start_time
            print(f"{time_elapsed:.3f} sec.")
            result.append(
                CompiledRefrain(
                    refrain=refrain,
                    ehir_module=ehir_resolved_module,
                    output_path=output_path,
                )
            )

        return result

    def _ehir_cache_path_for_refrain(self, refrain: RefrainData) -> Path:
        hasher = hashlib.sha256()
        hasher.update(EHIR_CACHE_SCHEMA.encode("utf-8"))
        hasher.update(__version__.encode("utf-8"))
        hasher.update(refrain.name.encode("utf-8"))
        hasher.update(str(refrain.version).encode("utf-8"))

        graph = refrain.import_graph
        if graph is not None:
            for module_id in sorted(graph.modules):
                resolved = module_id.resolve()
                hasher.update(str(resolved).encode("utf-8"))
                source = resolved.read_bytes() if resolved.exists() else b""
                hasher.update(hashlib.sha256(source).digest())

        hasher.update(str(refrain.ast).encode("utf-8"))
        cache_file = f"{hasher.hexdigest()}.encache"
        return refrain.path / "target" / ".cache" / cache_file

    def _legacy_ehir_cache_path_for_refrain(self, refrain: RefrainData) -> Path:
        digest = hashlib.sha256(str(refrain.ast).encode("utf-8")).hexdigest()
        return refrain.path / "target" / ".cache" / f"{digest}.encache"

    def _artifact_is_current(self, output_path: Path, link_inputs: NativeLinkInputs) -> bool:
        output_mtime = output_path.stat().st_mtime
        for native_object in link_inputs.objects:
            if native_object.exists() and native_object.stat().st_mtime > output_mtime:
                return False
        return True

    def _native_link_inputs_for_closure(
        self,
        refrain: RefrainData,
        native_inputs_by_refrain: dict[str, NativeLinkInputs],
    ) -> NativeLinkInputs:
        objects: list[Path] = []
        link_args: list[str] = []
        seen_objects: set[Path] = set()
        seen_link_args: set[str] = set()
        visited: set[str] = set()

        def visit(current: RefrainData) -> None:
            if current.name in visited:
                return
            visited.add(current.name)
            for dependency in current.dependencies:
                visit(dependency)
            inputs = native_inputs_by_refrain.get(current.name, NativeLinkInputs())
            for obj in inputs.objects:
                resolved = obj.resolve()
                if resolved in seen_objects:
                    continue
                seen_objects.add(resolved)
                objects.append(resolved)
            for arg in inputs.link_args:
                if arg in seen_link_args:
                    continue
                seen_link_args.add(arg)
                link_args.append(arg)

        visit(refrain)
        return NativeLinkInputs(objects=tuple(objects), link_args=tuple(link_args))

    def _native_link_inputs_for_refrain(self, refrain: RefrainData) -> NativeLinkInputs:
        build_script = refrain.path / "build.enq"
        if not build_script.exists():
            return NativeLinkInputs()

        metadata = self._read_static_build_metadata(build_script)
        native = metadata.get("native", {})
        libraries = native.get("libraries", [])
        search_paths = native.get("search_paths", [])
        frameworks = native.get("frameworks", [])
        raw_link_args = native.get("link_args", [])

        objects: list[Path] = []
        link_args: list[str] = []
        for search_path in search_paths:
            path = self._metadata_path(refrain.path, search_path)
            link_args.append(f"-L{path}")
        for framework in frameworks:
            link_args.extend(["-framework", str(framework)])
        link_args.extend(str(arg) for arg in raw_link_args)

        for library in libraries:
            if not isinstance(library, dict):
                raise RuntimeError(f"Invalid native library entry in {build_script}: {library!r}")
            lib_path = library.get("path")
            lib_name = library.get("name")
            if lib_path is None:
                if lib_name is None:
                    raise RuntimeError(f"Native library entry in {build_script} must contain 'name' or 'path'")
                link_args.append(f"-l{lib_name}")
                continue

            path = self._metadata_path(refrain.path, str(lib_path))
            if path.suffix == ".c":
                objects.append(self._compile_native_c_source(refrain, path))
            else:
                objects.append(path)

            for search_path in library.get("search_paths", []):
                link_args.append(f"-L{self._metadata_path(refrain.path, search_path)}")
            for framework in library.get("frameworks", []):
                link_args.extend(["-framework", str(framework)])
            for arg in library.get("link_args", []):
                link_args.append(str(arg))

        return NativeLinkInputs(objects=tuple(objects), link_args=tuple(link_args))

    def _read_static_build_metadata(self, build_script: Path) -> dict[str, object]:
        source = build_script.read_text()
        match = re.search(r"fn\s+payload\s*\(\s*\)\s*->\s*str\s*\{.*?\bret\s+(\"(?:\\.|[^\"\\])*\")", source, re.S)
        if match is None:
            raise RuntimeError(
                f"Unable to read native metadata from {build_script}. "
                "Current build pipeline expects build.enq to expose `fn payload() -> str` with a JSON string."
            )
        payload = ast.literal_eval(match.group(1))
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Build metadata in {build_script} must be a JSON object")
        return parsed

    def _metadata_path(self, root: Path, value: object) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else root / path

    def _compile_native_c_source(self, refrain: RefrainData, source_path: Path) -> Path:
        if not source_path.exists():
            raise RuntimeError(f"Native source does not exist: {source_path}")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
        object_dir = refrain.path / "target" / "debug" / "build" / "native"
        object_dir.mkdir(parents=True, exist_ok=True)
        object_path = object_dir / f"{source_path.stem}_{digest}.o"
        if object_path.exists() and object_path.stat().st_mtime >= source_path.stat().st_mtime:
            return object_path

        cmd = ["clang", "-std=c11", "-c", str(source_path), "-o", str(object_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Native compile error for {source_path}: {result.stderr}")
        return object_path

    def _flattened_alias_declarations(self, refrain: RefrainData) -> list[object]:
        aliases: list[object] = []
        seen: set[tuple[Path, str, str, int]] = set()
        for module_symbols in refrain.symbols.modules.values():
            for binding in module_symbols.values():
                if binding.name == binding.source_name:
                    continue
                key = (binding.module_id.resolve(), binding.name, binding.source_name, id(binding.statement))
                if key in seen:
                    continue
                seen.add(key)
                aliases.append(binding)
        return aliases

    def _infer_refrain_modules(self, refrain: RefrainData) -> None:
        if refrain.import_graph is None:
            raise RuntimeError(f"Refrain '{refrain.name}' has no import graph")

        for module_id in self._module_building_queue(refrain):
            local_ast = refrain.symbols.local_ast_without_imports.get(module_id, [])
            if not any(isinstance(statement, s.Statement_TopLevel) for statement in local_ast):
                continue
            imported_declarations = self._imported_declarations_for_module(refrain, module_id)
            TypeInferer().infer(local_ast, imported_declarations=imported_declarations)

    def _imported_declarations_for_module(self, refrain: RefrainData, module_id: Path) -> list[object]:
        local_statements = {id(statement) for statement in refrain.symbols.local_ast_without_imports.get(module_id, [])}
        imported: list[object] = []
        seen: set[tuple[Path, str, str, int]] = set()
        for binding in refrain.symbols.modules.get(module_id, {}).values():
            if binding.module_id.resolve() == module_id.resolve() and id(binding.statement) in local_statements:
                continue
            key = (binding.module_id.resolve(), binding.name, binding.source_name, id(binding.statement))
            if key in seen:
                continue
            seen.add(key)
            imported.append(binding)
        for statement in refrain.symbols.ast_without_imports.get(module_id, []):
            if id(statement) in local_statements:
                continue
            source_module_id = getattr(statement, "module_id", None)
            if not isinstance(source_module_id, Path):
                continue
            key = (source_module_id.resolve(), "", "", id(statement))
            if key in seen:
                continue
            seen.add(key)
            imported.append(
                ImportedTopLevelDeclaration(
                    module_id=source_module_id,
                    statement=statement,
                )
            )
        return imported

    def _module_building_queue(self, refrain: RefrainData) -> list[Path]:
        assert refrain.import_graph is not None
        graph = refrain.import_graph
        ordered: list[Path] = []
        visited: set[Path] = set()

        def visit(module_id: Path) -> None:
            module_id = module_id.resolve()
            if module_id in visited:
                return
            visited.add(module_id)
            for dependency_id in sorted(graph.adjacency.get(module_id, set())):
                visit(dependency_id)
            ordered.append(module_id)

        visit(graph.entrypoint)
        return ordered
