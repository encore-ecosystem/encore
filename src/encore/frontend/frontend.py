import tomllib
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from ehir import EHIR_Frontend
from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_imp, Derective_import

from encore import ENCORE_CACHE_DIR, PROJECT_ROOT
from encore.frontend.lexer import Lexer
from encore.frontend.parser import Parser
from encore.frontend.parser import statements as s
from encore.frontend.translator import Translator
from encore.utils.manifest import ProjectManifest


class ExportKind(StrEnum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()


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
    _cache: dict[Path, EHIR_Module] = field(default_factory=dict)
    _ast_cache: dict[Path, list[s.Statement]] = field(default_factory=dict)
    _index_cache: dict[Path, ModuleIndex] = field(default_factory=dict)
    _dependency_cache: dict[Path, dict[str, Path]] = field(default_factory=dict)
    _lexer: Lexer = field(default_factory=Lexer)
    _parser: Parser = field(default_factory=Parser)

    def get_module_by_id(self, id: Path) -> EHIR_Module:
        if id in self._cache:
            return self._cache[id]

        ast = self._get_ast_by_id(id)
        imported_declarations = self._collect_imported_declarations(id, ast)

        translator = Translator()
        translator.preload_declarations(imported_declarations)
        module = translator.translate_ast(ast)
        module.id = id

        self._cache[id] = module
        return module

    def get_parent_id_of(self, id: Path, derective: Derective_import) -> Path:
        project_root = self._get_project_root_of(id)
        dep_roots = self._get_dependency_roots(project_root)

        match derective.prefix[0]:
            case "refrain":
                dep_filepath = project_root / "src" / Path(*derective.prefix[1:])
            case "repo":
                dep_filepath = self.src_dir / Path(*derective.prefix[1:])
            case dep_name if dep_name in dep_roots:
                dep_root = dep_roots[dep_name]
                if len(derective.prefix) == 1:
                    dep_filepath = dep_root / "src" / "lib"
                else:
                    dep_filepath = dep_root / "src" / Path(*derective.prefix[1:])
            case "std":
                dep_filepath = self._fallback_std_root() / "src" / Path(*derective.prefix[1:])
            case _:
                dep_filepath = id.parent / Path(*derective.prefix)

        dep_filepath = self._resolve_module_path(dep_filepath)

        if not dep_filepath.exists():
            raise RuntimeError(f"Unable to import: {derective} in {id}")
        return dep_filepath

    def _get_ast_by_id(self, id: Path) -> list[s.Statement]:
        if id in self._ast_cache:
            return self._ast_cache[id]

        ast = self._parser.parse(self._lexer.tokenize(id.read_text()))
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

        return declarations

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
            return ExportBinding(statement.name, ExportKind.FUNCTION, id, statement)
        if isinstance(statement, s.Statement_StructureDefinition):
            return ExportBinding(statement.defi.name, ExportKind.STRUCT, id, statement)
        if isinstance(statement, s.Statement_EnumDefinition):
            return ExportBinding(statement.name, ExportKind.ENUM, id, statement)
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

        manifest = self._load_manifest(project_root)
        roots: dict[str, Path] = {}
        for dependency in manifest.project.dependencies:
            dep_path = self._resolve_dependency_ref(project_root, dependency)
            dep_manifest = self._load_manifest(dep_path)
            roots[dep_manifest.project.name] = dep_path

        self._dependency_cache[project_root] = roots
        return roots

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

    def _fallback_std_root(self) -> Path:
        local_std = PROJECT_ROOT.parent / "stdlib"
        if local_std.exists():
            return local_std
        return PROJECT_ROOT / "std"

    def _resolve_module_path(self, path: Path) -> Path:
        if path.with_suffix(".enq").exists():
            return path.with_suffix(".enq")
        return (path / "mod").with_suffix(".enq")

    def get_file_extension(self) -> str:
        return ".enq"
