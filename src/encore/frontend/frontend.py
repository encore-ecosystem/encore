import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from typing import Optional

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_imp, Derective_import

from ehir import EHIR_Frontend
from encore import ENCORE_CACHE_DIR
from encore.frontend.inference import TypeInferer
from encore.frontend.lexer import Lexer
from encore.frontend.parser import Parser
from encore.frontend.parser import statements as s
from encore.frontend.translator import Translator
from encore.utils.manifest import ProjectManifest


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


@dataclass
class ModuleIndex:
    module_id: Path
    exports: dict[str, ExportBinding] = field(default_factory=dict)


@dataclass
class EHIR_EncoreFrontend(EHIR_Frontend):
    src_dir: Path
    on_module_load: Callable[[Path], None] | None = None
    _cache: dict[Path, EHIR_Module] = field(default_factory=dict)
    _ast_cache: dict[Path, list[s.Statement]] = field(default_factory=dict)
    _index_cache: dict[Path, ModuleIndex] = field(default_factory=dict)
    _dependency_cache: dict[Path, dict[str, Path]] = field(default_factory=dict)
    _lexer: Lexer = field(default_factory=lambda: Lexer())
    _parser: Parser = field(default_factory=lambda: Parser())

    def get_module_by_id(self, id: Path) -> EHIR_Module:
        if self.on_module_load is not None:
            self.on_module_load(id)

        if id in self._cache:
            return self._cache[id]

        ast = self._get_ast_by_id(id)
        imported_declarations = self._collect_imported_declarations(id, ast)
        TypeInferer().infer(ast, imported_declarations)

        translator = Translator()
        translator.preload_declarations(imported_declarations)
        module = translator.translate_ast(ast)
        module.id = id

        self._cache[id] = module
        return module

    def get_parent_id_of(self, id: Path, derective: Derective_import) -> Path:
        project_root = self._get_project_root_of(id)
        prefix_root = derective.prefix[0]
        suffix = derective.prefix[1:]

        match prefix_root:
            case "refrain":
                dep_filepath = project_root / "src" / ("lib" if not suffix else Path(*suffix))

            case "mod":
                dep_filepath = id.parent if not suffix else id.parent / Path(*suffix)

            case _:
                dep_roots = self._get_dependency_roots(project_root)
                dep_root = dep_roots.get(prefix_root)
                if dep_root is None:
                    raise ImportError(
                        f"Unknown dependency root '{prefix_root}' for import '{derective}' in module '{id}'."
                    )
                dep_filepath = dep_root / "src" / ("lib" if not suffix else Path(*suffix))

        dep_filepath = self._resolve_module_path(dep_filepath)
        if not dep_filepath.exists():
            raise RuntimeError(f"Unable to import: {derective} in {id}")
        return dep_filepath

    def _get_ast_by_id(self, id: Path) -> list[s.Statement]:
        if id in self._ast_cache:
            return self._ast_cache[id]

        tokens = self._lexer.parse(list(id.read_text()))
        ast = self._parser.parse(tokens)
        self._ast_cache[id] = ast
        return ast

    def _collect_imported_declarations(self, id: Path, ast: list[s.Statement]) -> list[s.Statement_TopLevel]:
        declarations: list[s.Statement_TopLevel] = []
        seen: set[tuple[Path, str]] = set()

        for statement in ast:
            if not isinstance(statement, s.Statement_Import):
                continue

            for request in self._expand_import_statement(statement):
                for binding in self._resolve_import_bindings(id, request):
                    key = (binding.module_id, binding.name)
                    if key in seen:
                        continue
                    seen.add(key)
                    declarations.append(binding.statement)
                    if isinstance(binding.statement, s.Statement_StructureDefinition):
                        for idx, assoc_impl in enumerate(
                            self._collect_associated_impls(binding.module_id, binding.name)
                        ):
                            impl_key = (binding.module_id, f"impl::{binding.name}::{idx}")
                            if impl_key in seen:
                                continue
                            seen.add(impl_key)
                            declarations.append(assoc_impl)

        return declarations

    def _collect_associated_impls(self, module_id: Path, struct_name: str) -> list[s.Statement_Impl]:
        ast = self._get_ast_by_id(module_id)
        result: list[s.Statement_Impl] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Impl):
                continue
            if statement.trait_name is not None:
                continue
            if statement.struct.name != struct_name:
                continue
            result.append(statement)
        return result

    def _get_module_index(self, id: Path) -> ModuleIndex:
        if id in self._index_cache:
            return self._index_cache[id]

        ast = self._get_ast_by_id(id)
        index = ModuleIndex(module_id=id)
        self._index_cache[id] = index

        for statement in ast:
            binding = self._build_export_binding(id, statement)
            if binding is not None:
                index.exports.setdefault(binding.name, binding)

        for statement in ast:
            if not isinstance(statement, s.Statement_Import) or not statement.is_public:
                continue
            for request in self._expand_import_statement(statement):
                for binding in self._resolve_import_bindings(id, request):
                    index.exports.setdefault(binding.name, binding)

        return index

    def _build_export_binding(self, id: Path, statement: s.Statement) -> ExportBinding | None:
        if not isinstance(statement, s.Statement_TopLevel) or not statement.is_public:
            return None

        if isinstance(statement, s.Statement_FunctionDefinition):
            return ExportBinding(statement.signature.name, ExportKind.FUNCTION, id, statement)
        if isinstance(statement, s.FunctionSignature):
            return ExportBinding(statement.name, ExportKind.FUNCTION, id, statement)
        if isinstance(statement, s.Statement_StructureDefinition):
            return ExportBinding(statement.signature.name, ExportKind.STRUCT, id, statement)
        if isinstance(statement, s.Statement_EnumDefinition):
            return ExportBinding(statement.name, ExportKind.ENUM, id, statement)
        if isinstance(statement, s.Statement_Trait):
            return ExportBinding(statement.name, ExportKind.TRAIT, id, statement)
        return None

    def _expand_import_statement(self, statement: s.Statement_Import) -> list[Derective_import]:
        requests: list[Derective_import] = []

        def visit(prefix: list[str], pair: s.Statement_Import.ImportPair):
            if pair.dst:
                for child in pair.dst:
                    visit(prefix + [pair.src], child)
                return

            if pair.kind == s.Statement_Import.ImportKind.PACKAGE:
                requests.append(Derective_imp(prefix=prefix + [pair.src], symbol="*"))
            elif pair.kind == s.Statement_Import.ImportKind.SYMBOL:
                requests.append(Derective_imp(prefix=prefix, symbol=pair.src))
            elif pair.kind == s.Statement_Import.ImportKind.GLOB:
                requests.append(Derective_imp(prefix=prefix, symbol="*"))

        visit([], statement.pair)
        return requests

    def _resolve_import_bindings(self, id: Path, request: Derective_import) -> list[ExportBinding]:
        parent_id = self.get_parent_id_of(id, request)
        target_index = self._get_module_index(parent_id)

        if request.symbol == "*":
            return list(target_index.exports.values())

        binding = target_index.exports.get(request.symbol)
        if binding is None:
            raise RuntimeError(f"Unable to import: {request}")
        return [binding]

    def _get_project_root_of(self, id: Path) -> Path:
        for parent in [id.parent, *id.parents]:
            if (parent / ProjectManifest.default_filename()).exists():
                return parent
        raise RuntimeError(f"Unable to find encore.toml for module: {id}")

    def _get_dependency_roots(self, project_root: Path) -> dict[str, Path]:
        if project_root in self._dependency_cache:
            return self._dependency_cache[project_root]

        roots: dict[str, Path] = {}
        self._collect_dependency_roots(project_root, roots, set())

        self._dependency_cache[project_root] = roots
        return roots

    def _collect_dependency_roots(self, project_root: Path, roots: dict[str, Path], visited: set[Path]) -> None:
        if project_root in visited:
            return
        visited.add(project_root)

        manifest = self._load_manifest(project_root)
        for dependency in manifest.project.dependencies:
            dep_path = self._resolve_dependency_ref(project_root, dependency)
            dep_manifest = self._load_manifest(dep_path)
            roots.setdefault(dep_manifest.project.name, dep_path)
            self._collect_dependency_roots(dep_path, roots, visited)

    def _load_manifest(self, path: Path) -> ProjectManifest:
        manifest_path = path / ProjectManifest.default_filename()
        if not manifest_path.exists():
            raise RuntimeError(f"Project {path} is not initialized")
        with manifest_path.open("rb") as f:
            return ProjectManifest(**tomllib.load(f))

    def _resolve_dependency_ref(self, project_root: Path, dependency: str) -> Path:
        if dependency.startswith("path@"):
            return (project_root / dependency.removeprefix("path@")).resolve()

        if dependency.startswith("git@"):
            repo_url = dependency.removeprefix("git@")
            org, repo_name = repo_url.rstrip("/").split("/")[-2:]
            path = ENCORE_CACHE_DIR / "git" / org / repo_name
            if path.exists():
                return path
            raise RuntimeError(f"Dependency is not available locally: {dependency}")

        raise RuntimeError(f"Unable to load dependency: {dependency}")

    def _resolve_module_path(self, path: Path) -> Path:
        if path.with_suffix(".enq").exists():
            return path.with_suffix(".enq")
        return (path / "mod").with_suffix(".enq")

    @staticmethod
    def _fallback_to_manifest(path: Path) -> Optional[Path]:
        assert path.is_absolute()
        for parent in path.parents:
            manifest_path = parent / ProjectManifest.default_filename()
            if manifest_path.exists():
                return manifest_path

    def get_file_extension(self) -> str:
        return ".enq"
