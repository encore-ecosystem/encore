import hashlib
import pickle
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from git import Repo

from encore import ENCORE_CACHE_DIR, PROJECT_ROOT, __version__
from encore.compiler.lexer import Lexer
from encore.compiler.macro_expander import MacroExpander
from encore.compiler.parser import EncoreParser
from encore.compiler.parser.statements import (
    FunctionSignature,
    Statement,
    Statement_EnumDefinition,
    Statement_FunctionDefinition,
    Statement_Global,
    Statement_Impl,
    Statement_Import,
    Statement_StructureDefinition,
    Statement_TopLevel,
    Statement_Trait,
)
from encore.utils.manifest import ProjectManifest

WORKSPACE_CACHE_SCHEMA = "workspace-v4"


@dataclass(frozen=True)
class SymbolBinding:
    name: str
    source_name: str
    module_id: Path
    statement: Statement_TopLevel
    is_public: bool

    @property
    def local_name(self) -> str:
        return self.name


@dataclass
class SymbolTable:
    resolved: bool = False
    all: dict[str, list[SymbolBinding]] = field(default_factory=dict)
    modules: dict[Path, dict[str, SymbolBinding]] = field(default_factory=dict)
    exports: dict[Path, dict[str, SymbolBinding]] = field(default_factory=dict)
    ast_without_imports: dict[Path, list[Statement]] = field(default_factory=dict)
    local_ast_without_imports: dict[Path, list[Statement]] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportRequest:
    path: tuple[str, ...]
    kind: Statement_Import.ImportKind
    alias: str | None
    is_public: bool


@dataclass(frozen=True)
class ImportEdge:
    source: Path
    target: Path
    import_path: tuple[str, ...]
    symbol_path: tuple[str, ...]
    is_public: bool
    kind: Statement_Import.ImportKind
    alias: str | None


@dataclass
class ImportGraph:
    entrypoint: Path
    modules: dict[Path, list[Statement]] = field(default_factory=dict)
    edges: list[ImportEdge] = field(default_factory=list)
    adjacency: dict[Path, set[Path]] = field(default_factory=dict)

    def add_module(self, module_id: Path, ast: list[Statement]):
        self.modules.setdefault(module_id, ast)
        self.adjacency.setdefault(module_id, set())

    def add_edge(self, edge: ImportEdge):
        self.edges.append(edge)
        self.adjacency.setdefault(edge.source, set()).add(edge.target)
        self.adjacency.setdefault(edge.target, set())


@dataclass
class RefrainVersion:
    major: int
    minor: int
    patch: int

    def __repr__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class RefrainData:
    name: str
    path: Path
    version: RefrainVersion
    symbols: SymbolTable
    target_is_binary: bool
    import_graph: ImportGraph | None = None
    ast: list[Statement] = field(default_factory=list)
    dependencies: list["RefrainData"] = field(default_factory=list)
    workspace_cache_key: str = ""


@dataclass
class RefrainManager:
    """
    Resolve Encore project modules, imports and dependency closures.
    """

    _namespace: dict[str, RefrainData] = field(default_factory=dict)
    _lexer: Lexer = field(default_factory=Lexer)  # ty:ignore[invalid-assignment]
    _parser: EncoreParser = field(default_factory=EncoreParser)  # ty:ignore[invalid-assignment]
    _macro_expander: MacroExpander = field(default_factory=MacroExpander)
    source_overrides: dict[Path, str] = field(default_factory=dict)

    def add_binary_target(self, refrain_root: Path) -> RefrainData:
        return self.add_refrain_with_dependencies(refrain_root, True)

    def add_refrain_with_dependencies(self, refrain_root: Path, target_is_binary: bool) -> RefrainData:
        manifest = ProjectManifest.read_with_default_filename(refrain_root)
        project_name = manifest.project.name
        if project_name in self._namespace:
            cached_refrain = self._namespace[project_name]
            if (cached_path := cached_refrain.path) != refrain_root:
                raise RuntimeError(
                    f"Manifest ({refrain_root}) using project '{project_name}' with 2 different sources: {cached_path} != {refrain_root}"
                )
            else:
                return cached_refrain
        ref_data = RefrainData(
            name=project_name,
            path=refrain_root,
            version=RefrainVersion(0, 0, 0),  # todo (@meshushkevich): fix
            symbols=SymbolTable(),
            target_is_binary=target_is_binary,
        )
        self._namespace[project_name] = ref_data

        for dependency in manifest.project.dependencies:
            dependency_path = self._resolve_dependency(dep=dependency, base_path=refrain_root)
            ref_data.dependencies.append(self.add_refrain_with_dependencies(dependency_path, False))

        return self._resolve_refrain(ref_data, load_cache=not self.source_overrides)

    def get_building_queue(self) -> deque[RefrainData]:
        nodes = dict(self._namespace)
        dependents: dict[str, set[str]] = {name: set() for name in nodes}
        indegree: dict[str, int] = {name: 0 for name in nodes}

        for name, refrain in nodes.items():
            seen_dependencies: set[str] = set()
            for dependency in refrain.dependencies:
                dependency_name = dependency.name
                if dependency_name not in nodes:
                    raise RuntimeError(
                        f"Refrain '{name}' depends on '{dependency_name}', but it is missing from namespace"
                    )
                if dependency_name in seen_dependencies:
                    continue
                seen_dependencies.add(dependency_name)
                dependents[dependency_name].add(name)
                indegree[name] += 1

        ready = deque(sorted(name for name, degree in indegree.items() if degree == 0))
        result: deque[RefrainData] = deque()

        while ready:
            name = ready.popleft()
            result.append(nodes[name])

            for dependent_name in sorted(dependents[name]):
                indegree[dependent_name] -= 1
                if indegree[dependent_name] == 0:
                    ready.append(dependent_name)

        if len(result) != len(nodes):
            cycle = sorted(name for name, degree in indegree.items() if degree > 0)
            raise RuntimeError(f"Dependency graph contains a cycle involving: {', '.join(cycle)}")

        return result

    def _resolve_refrain(self, data: RefrainData, load_cache: bool = False) -> RefrainData:
        if data.symbols.resolved:
            return data

        data.workspace_cache_key = self._workspace_cache_key(data)
        cache_dump_path = ENCORE_CACHE_DIR / "local" / f"{data.workspace_cache_key}.workspace"

        if load_cache and cache_dump_path.exists():
            print(f"[{data.name}] Cache hit")
            with cache_dump_path.open("rb") as f:
                cached: RefrainData = pickle.load(f)
            cached.dependencies = data.dependencies
            cached.target_is_binary = data.target_is_binary
            cached.workspace_cache_key = data.workspace_cache_key
            self._namespace[data.name] = cached
            return cached

        # Build import graph and flatten AST
        data.import_graph = self._build_import_graph(data)
        self._resolve_imports(data, data.import_graph)
        data.ast = self._flatten_import_graph_ast(data.import_graph)
        data.symbols.all = self._collect_flat_symbols(data.ast)
        data.symbols.resolved = True

        # Dump cache
        if load_cache:
            cache_dump_path.parent.mkdir(exist_ok=True)
            with cache_dump_path.open("wb") as f:
                pickle.dump(data, f)

        return data

    def _workspace_cache_key(self, data: RefrainData) -> str:
        hasher = hashlib.sha256()
        hasher.update(WORKSPACE_CACHE_SCHEMA.encode("utf-8"))
        hasher.update(__version__.encode("utf-8"))
        hasher.update(data.name.encode("utf-8"))
        hasher.update(str(data.version).encode("utf-8"))
        hasher.update(b"binary" if data.target_is_binary else b"library")

        manifest_path = data.path / ProjectManifest.default_filename()
        self._hash_file_if_exists(hasher, manifest_path, data.path)
        self._hash_file_if_exists(hasher, data.path / "build.enq", data.path)

        source_root = data.path / "src"
        if source_root.exists():
            for source_path in sorted(source_root.rglob("*.enq")):
                self._hash_file_if_exists(hasher, source_path, data.path)

        for dependency in sorted(data.dependencies, key=lambda item: item.name):
            hasher.update(dependency.name.encode("utf-8"))
            hasher.update(dependency.workspace_cache_key.encode("utf-8"))

        return hasher.hexdigest()

    def _hash_file_if_exists(self, hasher, path: Path, root: Path) -> None:
        resolved = path.resolve()
        hasher.update(str(resolved.relative_to(root.resolve()) if resolved.is_relative_to(root.resolve()) else resolved).encode("utf-8"))
        if not path.exists():
            hasher.update(b"\0missing")
            return
        hasher.update(hashlib.sha256(path.read_bytes()).digest())

    def _resolve_imports(self, data: RefrainData, graph: ImportGraph):
        resolving: set[Path] = set()
        resolved: set[Path] = set()

        def resolve_module(
            module_id: Path,
        ) -> tuple[dict[str, SymbolBinding], dict[str, SymbolBinding], list[Statement]]:
            module_id = module_id.resolve()
            if module_id in resolved:
                return (
                    data.symbols.modules[module_id],
                    data.symbols.exports[module_id],
                    data.symbols.ast_without_imports[module_id],
                )
            if module_id in resolving:
                return (
                    data.symbols.modules.get(module_id, {}),
                    data.symbols.exports.get(module_id, {}),
                    data.symbols.ast_without_imports.get(module_id, []),
                )

            resolving.add(module_id)
            ast = graph.modules[module_id]
            module_symbols: dict[str, SymbolBinding] = {}
            module_exports: dict[str, SymbolBinding] = {}
            local_ast_without_imports: list[Statement] = []

            for statement in ast:
                if isinstance(statement, Statement_Import):
                    continue
                local_ast_without_imports.append(statement)
                own_binding = self._top_level_binding(module_id, statement)
                if own_binding is None:
                    continue
                module_symbols[own_binding.name] = own_binding
                if own_binding.is_public:
                    module_exports[own_binding.name] = own_binding

            data.symbols.modules[module_id] = module_symbols
            data.symbols.exports[module_id] = module_exports
            data.symbols.local_ast_without_imports[module_id] = local_ast_without_imports

            ast_without_imports: list[Statement] = []
            for statement in ast:
                if isinstance(statement, Statement_Import):
                    imported_symbols = self._resolve_import_statement(data, graph, module_id, statement, resolve_module)
                    inserted_import_statements: set[tuple[Path, int]] = set()
                    for binding in imported_symbols:
                        existing = module_symbols.get(binding.name)
                        if existing is not None and existing.module_id != binding.module_id:
                            raise RuntimeError(
                                f"Ambiguous import for symbol '{binding.name}' in {module_id}: "
                                f"{existing.module_id}::{existing.source_name} vs "
                                f"{binding.module_id}::{binding.source_name}"
                            )
                        module_symbols[binding.name] = binding
                        if statement.is_public:
                            module_exports[binding.name] = binding
                        for imported_statement in self._statements_for_binding(graph, binding):
                            statement_key = (binding.module_id, id(imported_statement))
                            if statement_key in inserted_import_statements:
                                continue
                            inserted_import_statements.add(statement_key)
                            ast_without_imports.append(imported_statement)
                    continue

                ast_without_imports.append(statement)

            data.symbols.modules[module_id] = module_symbols
            data.symbols.exports[module_id] = module_exports
            data.symbols.ast_without_imports[module_id] = ast_without_imports
            graph.modules[module_id] = ast_without_imports
            resolving.remove(module_id)
            resolved.add(module_id)
            return module_symbols, module_exports, ast_without_imports

        resolve_module(graph.entrypoint)

    def _flatten_import_graph_ast(self, graph: ImportGraph) -> list[Statement]:
        ordered_modules: list[Path] = []
        visited: set[Path] = set()

        def visit(module_id: Path):
            module_id = module_id.resolve()
            if module_id in visited:
                return
            visited.add(module_id)
            for dependency_id in sorted(graph.adjacency.get(module_id, set())):
                visit(dependency_id)
            ordered_modules.append(module_id)

        visit(graph.entrypoint)

        result: list[Statement] = []
        seen: set[tuple[object, ...]] = set()
        for module_id in ordered_modules:
            for statement in graph.modules[module_id]:
                if isinstance(statement, Statement_Import):
                    continue
                key = self._statement_identity(module_id, statement)
                if key in seen:
                    continue
                seen.add(key)
                result.append(statement)

        return result

    def _collect_flat_symbols(self, ast: list[Statement]) -> dict[str, list[SymbolBinding]]:
        symbols: dict[str, list[SymbolBinding]] = {}
        for statement in ast:
            module_id = getattr(statement, "module_id", None)
            if not isinstance(module_id, Path):
                continue
            binding = self._top_level_binding(module_id, statement)
            if binding is None:
                continue
            symbols.setdefault(binding.name, []).append(binding)
        return symbols

    def _statement_identity(self, current_module_id: Path, statement: Statement) -> tuple[object, ...]:
        source_module_id = getattr(statement, "module_id", None)
        if not isinstance(source_module_id, Path):
            source_module_id = current_module_id
        source_module_id = source_module_id.resolve()

        if isinstance(statement, Statement_Impl):
            return (
                source_module_id,
                "impl",
                statement.trait_name or "",
                str(statement.struct),
                tuple(method.signature.name for method in statement.body),
            )

        if isinstance(statement, Statement_TopLevel):
            name = self._top_level_symbol_name(statement)
            if name is not None:
                return (source_module_id, type(statement).__name__, name)

        return (source_module_id, type(statement).__name__, id(statement))

    def _resolve_import_statement(
        self,
        data: RefrainData,
        graph: ImportGraph,
        source: Path,
        statement: Statement_Import,
        resolve_module,
    ) -> list[SymbolBinding]:
        bindings: list[SymbolBinding] = []
        for request in self._expand_import(statement):
            target, symbol_path = self._resolve_import_target(data, source, request.path)
            _, target_exports, _ = resolve_module(target)

            if request.kind == Statement_Import.ImportKind.GLOB:
                bindings.extend(self._glob_import_bindings(data, target, target_exports))
                continue

            if not symbol_path:
                bindings.extend(self._namespace_import_bindings(request, target_exports))
                continue

            binding = self._lookup_imported_symbol(target_exports, symbol_path, request)
            bindings.append(binding)

        return bindings

    def _glob_import_bindings(
        self,
        data: RefrainData,
        target: Path,
        target_exports: dict[str, SymbolBinding],
    ) -> list[SymbolBinding]:
        bindings = list(target_exports.values())
        for statement in data.symbols.local_ast_without_imports.get(target.resolve(), []):
            if not isinstance(statement, Statement_Impl):
                continue
            impl_name = self._impl_binding_name(statement)
            bindings.append(
                SymbolBinding(
                    name=impl_name,
                    source_name=impl_name,
                    module_id=target.resolve(),
                    statement=statement,
                    is_public=True,
                )
            )
        return bindings

    def _impl_binding_name(self, statement: Statement_Impl) -> str:
        trait_name = statement.trait_name or ""
        methods = ",".join(method.signature.name for method in statement.body)
        return f"impl::{trait_name}::{statement.struct}::{methods}"

    def _namespace_import_bindings(
        self, request: ImportRequest, target_exports: dict[str, SymbolBinding]
    ) -> list[SymbolBinding]:
        namespace = request.alias or request.path[-1]
        return [
            SymbolBinding(
                name=f"{namespace}::{binding.name}",
                source_name=binding.source_name,
                module_id=binding.module_id,
                statement=binding.statement,
                is_public=binding.is_public,
            )
            for binding in target_exports.values()
        ]

    def _lookup_imported_symbol(
        self,
        target_exports: dict[str, SymbolBinding],
        symbol_path: tuple[str, ...],
        request: ImportRequest,
    ) -> SymbolBinding:
        full_name = "::".join(symbol_path)
        binding = target_exports.get(full_name)
        if binding is None and len(symbol_path) == 1:
            binding = target_exports.get(symbol_path[0])
        if binding is None:
            raise RuntimeError(f"Unable to resolve imported symbol '{'::'.join(request.path)}'")

        if request.alias is None:
            return binding

        return SymbolBinding(
            name=request.alias,
            source_name=binding.source_name,
            module_id=binding.module_id,
            statement=binding.statement,
            is_public=binding.is_public,
        )

    def _top_level_binding(self, module_id: Path, statement: Statement) -> SymbolBinding | None:
        if not isinstance(statement, Statement_TopLevel):
            return None
        name = self._top_level_symbol_name(statement)
        if name is None:
            return None
        return SymbolBinding(
            name=name,
            source_name=name,
            module_id=module_id,
            statement=statement,
            is_public=statement.is_public,
        )

    def _top_level_symbol_name(self, statement: Statement_TopLevel) -> str | None:
        if isinstance(statement, Statement_FunctionDefinition):
            return statement.signature.name
        if isinstance(statement, FunctionSignature):
            return statement.name
        if isinstance(statement, Statement_StructureDefinition):
            return statement.signature.name
        if isinstance(statement, Statement_EnumDefinition):
            return statement.name
        if isinstance(statement, Statement_Trait):
            return statement.name
        if isinstance(statement, Statement_Global):
            return statement.name
        if isinstance(statement, Statement_Impl):
            return None
        return None

    def _statements_for_binding(self, graph: ImportGraph, binding: SymbolBinding) -> list[Statement_TopLevel]:
        result: list[Statement_TopLevel] = []
        seen: set[int] = set()
        for statement in graph.modules[binding.module_id]:
            if isinstance(statement, Statement_Import):
                continue
            if not isinstance(statement, Statement_TopLevel):
                continue
            if id(statement) in seen:
                continue
            seen.add(id(statement))
            result.append(statement)
        return result

    def _impl_belongs_to_symbol(self, statement: Statement_Impl, binding: SymbolBinding) -> bool:
        if isinstance(binding.statement, Statement_Trait):
            return statement.trait_name == binding.source_name
        if isinstance(binding.statement, Statement_StructureDefinition | Statement_EnumDefinition):
            return statement.struct.name == binding.source_name
        return False

    def _build_import_graph(self, data: RefrainData) -> ImportGraph:
        entrypoint = self._entrypoint_of(data)
        return self._build_import_graph_from_entrypoint(data, entrypoint)

    def build_import_graph_from_entrypoint(self, data: RefrainData, entrypoint: Path) -> ImportGraph:
        return self._build_import_graph_from_entrypoint(data, entrypoint.resolve())

    def _build_import_graph_from_entrypoint(self, data: RefrainData, entrypoint: Path) -> ImportGraph:
        graph = ImportGraph(entrypoint=entrypoint)
        visited: set[Path] = set()

        def visit(module_id: Path):
            module_id = module_id.resolve()
            if module_id in visited:
                return
            visited.add(module_id)

            ast = self._parse_file(module_id)
            ast = self._inject_prelude_imports(data, module_id, ast)
            graph.add_module(module_id, ast)

            for statement in ast:
                if not isinstance(statement, Statement_Import):
                    continue
                for request in self._expand_import(statement):
                    edge = self._resolve_import_edge(data, module_id, request)
                    graph.add_edge(edge)
                    visit(edge.target)

        visit(entrypoint)
        return graph

    def _entrypoint_of(self, data: RefrainData) -> Path:
        filename = "main.enq" if data.target_is_binary else "lib.enq"
        entrypoint = (data.path / "src" / filename).resolve()
        if not entrypoint.exists():
            raise RuntimeError(f"Unable to find entrypoint for refrain '{data.name}': {entrypoint}")
        return entrypoint

    def _inject_prelude_imports(self, data: RefrainData, module_id: Path, ast: list[Statement]) -> list[Statement]:
        module_id = module_id.resolve()
        imports: list[Statement_Import] = []

        if data.name == "core":
            ops_module = (data.path / "src" / "ops" / "mod.enq").resolve()
            cast_module = (data.path / "src" / "cast" / "mod.enq").resolve()
            if module_id != ops_module and not self._has_glob_import(ast, ("refrain", "ops")):
                imports.append(self._make_glob_import(("refrain", "ops")))
            if module_id != cast_module and not self._has_glob_import(ast, ("refrain", "cast")):
                imports.append(self._make_glob_import(("refrain", "cast")))
        elif self._dependency_by_name(data, "core") is not None:
            if not self._has_glob_import(ast, ("core", "ops")):
                imports.append(self._make_glob_import(("core", "ops")))
            if not self._has_glob_import(ast, ("core", "cast")):
                imports.append(self._make_glob_import(("core", "cast")))

        if not imports:
            return ast
        return [*imports, *ast]

    def _has_glob_import(self, ast: list[Statement], path: tuple[str, ...]) -> bool:
        for statement in ast:
            if not isinstance(statement, Statement_Import):
                continue
            for request in self._expand_import(statement):
                if request.kind == Statement_Import.ImportKind.GLOB and request.path == path:
                    return True
        return False

    def _make_glob_import(self, path: tuple[str, str]) -> Statement_Import:
        return Statement_Import(
            is_public=False,
            pair=Statement_Import.ImportPair(
                path[0],
                [
                    Statement_Import.ImportPair(
                        path[1],
                        [Statement_Import.ImportPair("*", [], Statement_Import.ImportKind.GLOB)],
                    )
                ],
            ),
        )

    def _expand_import(self, statement: Statement_Import) -> list[ImportRequest]:
        requests: list[ImportRequest] = []

        def visit(prefix: tuple[str, ...], pair: Statement_Import.ImportPair, inherited_alias: str | None = None):
            alias = inherited_alias or pair.alias
            if pair.dst:
                for child in pair.dst:
                    visit(prefix + (pair.src,), child, alias)
                return

            if pair.kind == Statement_Import.ImportKind.GLOB and pair.src == "*":
                requests.append(
                    ImportRequest(
                        path=prefix, kind=Statement_Import.ImportKind.GLOB, alias=None, is_public=statement.is_public
                    )
                )
                return

            requests.append(
                ImportRequest(
                    path=prefix + (pair.src,),
                    kind=pair.kind,
                    alias=alias,
                    is_public=statement.is_public,
                )
            )

        visit(tuple(), statement.pair)
        return requests

    def _resolve_import_edge(self, data: RefrainData, source: Path, request: ImportRequest) -> ImportEdge:
        target, symbol_path = self._resolve_import_target(data, source, request.path)
        return ImportEdge(
            source=source,
            target=target,
            import_path=request.path,
            symbol_path=symbol_path,
            is_public=request.is_public,
            kind=request.kind,
            alias=request.alias,
        )

    def _resolve_import_target(
        self, data: RefrainData, source: Path, import_path: tuple[str, ...]
    ) -> tuple[Path, tuple[str, ...]]:
        if not import_path:
            raise RuntimeError(f"Unable to resolve empty import in {source}")

        owner = self._source_owner(data, source)
        root_name = import_path[0]
        suffix = import_path[1:]

        if root_name in {"refrain", "repo", owner.name}:
            base_dir = owner.path / "src"
            parts = suffix
        elif root_name == "mod":
            base_dir = source.parent
            parts = suffix
        else:
            dependency = self._dependency_by_name(owner, root_name) or self._dependency_by_name(data, root_name)
            if dependency is None:
                raise RuntimeError(f"Unknown import root '{root_name}' in {source}: {'::'.join(import_path)}")
            base_dir = dependency.path / "src"
            parts = suffix

        for module_part_count in range(len(parts), -1, -1):
            module_parts = parts[:module_part_count]
            target = self._resolve_module_file(base_dir, module_parts)
            if target is not None:
                return target, tuple(parts[module_part_count:])

        raise RuntimeError(f"Unable to resolve import '{'::'.join(import_path)}' in {source}")

    def _dependency_by_name(self, data: RefrainData, name: str) -> RefrainData | None:
        for dependency in data.dependencies:
            if dependency.name == name:
                return dependency
        return None

    def _source_owner(self, root: RefrainData, source: Path) -> RefrainData:
        source = source.resolve()
        candidates = self._collect_refrain_tree(root)
        candidates.sort(key=lambda item: len(item.path.resolve().parts), reverse=True)
        for candidate in candidates:
            src_root = (candidate.path / "src").resolve()
            try:
                source.relative_to(src_root)
            except ValueError:
                continue
            return candidate
        return root

    def _collect_refrain_tree(self, root: RefrainData) -> list[RefrainData]:
        result: list[RefrainData] = []
        seen: set[Path] = set()

        def visit(data: RefrainData) -> None:
            key = data.path.resolve()
            if key in seen:
                return
            seen.add(key)
            result.append(data)
            for dependency in data.dependencies:
                visit(dependency)

        visit(root)
        return result

    def _resolve_module_file(self, base_dir: Path, module_parts: tuple[str, ...]) -> Path | None:
        module_base = base_dir.joinpath(*module_parts) if module_parts else base_dir / "lib"
        direct_file = module_base.with_suffix(".enq")
        if self._path_exists_case_sensitive(direct_file):
            return direct_file.resolve()

        mod_file = module_base / "mod.enq"
        if self._path_exists_case_sensitive(mod_file):
            return mod_file.resolve()

        return None

    def _path_exists_case_sensitive(self, path: Path) -> bool:
        if not path.exists():
            return False
        parts = path.resolve().parts
        if not parts:
            return False

        current = Path(parts[0])
        for part in parts[1:]:
            try:
                names = {entry.name for entry in current.iterdir()}
            except OSError:
                return False
            if part not in names:
                return False
            current = current / part
        return True

    def _parse_file(self, program_path: Path) -> list[Statement]:
        program_path = program_path.resolve()
        program = self.source_overrides.get(program_path)
        if program is None:
            with program_path.open("r") as f:
                program = f.read()

        tokens = self._lexer.parse(list(program))
        tokens = self._macro_expander.expand(tokens)
        return self._parser.parse(tokens, module_id=program_path, source_text=program)

    @classmethod
    def _resolve_dependency(cls, dep: str, base_path: Path, update: bool = False) -> Path:
        from encore import ENCORE_CACHE_DIR

        ENCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if dep == "sys@core":
            return PROJECT_ROOT / "core"

        if dep.startswith("git@"):
            repo_url = dep.removeprefix("git@")
            org, repo_name = repo_url.split("/")[-2:]
            path = ENCORE_CACHE_DIR / "git" / org / repo_name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not (path / ".git").exists():
                Repo.clone_from(url=repo_url, to_path=path)
            elif update:
                Repo(path).remotes.origin.pull()
        elif dep.startswith("path@"):
            path = (base_path / dep.removeprefix("path@")).resolve()
            manifest_path = path / ProjectManifest.default_filename()
            if not manifest_path.exists():
                raise RuntimeError(
                    f"Unable to load path dependency '{dep}' from {base_path}: "
                    f"{manifest_path} does not exist"
                )

        else:
            raise RuntimeError(f"Unable to load dependency: {dep}")

        return path.resolve()
