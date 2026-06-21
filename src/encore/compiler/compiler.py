from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.postprocessor import EHIR_ProcessedModule

from ehir import EHIR_ProjectCompiler
from encore.compiler.inference import TypeInferer
from encore.compiler.parser import statements as s
from encore.compiler.translator import EncoreToEHIRTranslator
from encore.lsp import RefrainData, RefrainManager
from encore.utils.diagnostics import with_diagnostic_context


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


@dataclass
class EncoreCompiler:
    refrain_manager: RefrainManager = field(default_factory=RefrainManager)
    targets: list[RefrainData] = field(default_factory=list)

    def add_compile_target(self, path: Path):
        self.targets.append(self.refrain_manager.add_binary_target(path))

    def compile_all_targets(self) -> list[EHIR_ProcessedModule]:
        building_queue = self.refrain_manager.get_building_queue()
        result: list[EHIR_ProcessedModule] = []

        for refrain in building_queue:
            entrypoint = refrain.import_graph.entrypoint if refrain.import_graph is not None else None
            source_text = entrypoint.read_text() if entrypoint is not None and entrypoint.exists() else None
            try:
                self._infer_refrain_modules(refrain)
            except Exception as exc:
                raise with_diagnostic_context(
                    exc,
                    stage="type-inference",
                    module_id=entrypoint,
                    source_text=source_text,
                ) from exc

            try:
                ehir_raw_module = EncoreToEHIRTranslator().translate_ast(refrain.ast, module_id=entrypoint)
                ehir_resolved_module = EHIR_ProjectCompiler().compile_module(ehir_raw_module)
            except Exception as exc:
                raise with_diagnostic_context(
                    exc,
                    stage="translation",
                    module_id=entrypoint,
                    source_text=source_text,
                ) from exc
            result.append(ehir_resolved_module)

        return result

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
