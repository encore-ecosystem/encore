import tomllib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import StrEnum, auto
from pathlib import Path
from typing import Optional, cast

from ehir.builder import EHIR_Module
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type

from encore import ENCORE_CACHE_DIR
from encore.compiler.inference import TypeInferer
from encore.compiler.lexer import Lexer
from encore.compiler.macro_expander import MacroExpander
from encore.compiler.parser import Parser
from encore.compiler.parser import statements as s
from encore.compiler.translator import Translator
from encore.compiler.types import (
    AnySmartPointer,
    is_mutable_type,
    make_mutable_type,
    unwrap_for_storage,
)
from encore.utils.diagnostics import with_diagnostic_context
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
    src_dir: Path
    _lexer: Lexer = field(default_factory=lambda: Lexer())
    _parser: Parser = field(default_factory=lambda: Parser())
    _macro_expander: MacroExpander = field(default_factory=lambda: MacroExpander())

    def get_module_by_id(self, id: Path) -> EHIR_Module:
        if self.on_module_load is not None:
            self.on_module_load(id)

        if id in self._cache:
            return self._cache[id]

        ast = self._get_ast_by_id(id)
        source_text = self._get_source_text_by_id(id)
        try:
            imported_declarations = self._ensure_type_inferred(id, ast)
        except Exception as exc:
            raise with_diagnostic_context(exc, stage="type-inference", module_id=id, source_text=source_text) from exc

        translator = Translator()
        ast_for_translation = self._prepare_imports_for_translation(id, ast)
        try:
            module = translator.translate_ast(
                ast_for_translation, module_id=id, imported_declarations=cast(list[object], imported_declarations)
            )
        except Exception as exc:
            raise with_diagnostic_context(exc, stage="translation", module_id=id, source_text=source_text) from exc
        module.id = id

        self._cache[id] = module
        return module

    def _ensure_type_inferred(
        self, id: Path, ast: list[s.Statement] | None = None
    ) -> list[ImportedTopLevelDeclaration]:
        module_id = id.resolve()
        module_ast = self._get_ast_by_id(module_id) if ast is None else ast
        imported_declarations = self._collect_imported_declarations(module_id, module_ast)

        if module_id in self._inferred_modules:
            return imported_declarations
        if module_id in self._inferring_modules:
            return imported_declarations

        self._inferring_modules.add(module_id)
        try:
            dependency_ids = sorted(
                {
                    declaration.module_id.resolve()
                    for declaration in imported_declarations
                    if declaration.module_id.resolve() != module_id
                }
            )
            for dependency_id in dependency_ids:
                self._ensure_type_inferred(dependency_id)

            TypeInferer().infer(module_ast, cast(list[object], imported_declarations))
            self._inferred_modules.add(module_id)
        finally:
            self._inferring_modules.discard(module_id)

        return imported_declarations

    def _resolve_import_module_id(self, id: Path, path: tuple[str, ...]) -> Path:
        if not path:
            raise RuntimeError(f"Unable to import empty path in {id}")

        project_root = self._get_project_root_of(id)
        project_name = self._load_manifest(project_root).project.name
        prefix_root = path[0]
        suffix = path[1:]
        import_path = "::".join(path)

        match prefix_root:
            case "refrain":
                dep_filepath = project_root / "src" / ("lib" if not suffix else Path(*suffix))

            case "mod":
                dep_filepath = id.parent if not suffix else id.parent / Path(*suffix)

            case _:
                if prefix_root in {project_name, "repo"}:
                    dep_filepath = project_root / "src" / ("lib" if not suffix else Path(*suffix))
                else:
                    dep_roots = self._get_dependency_roots(project_root)
                    dep_root = dep_roots.get(prefix_root)
                    if dep_root is None:
                        raise ImportError(
                            f"Unknown dependency root '{prefix_root}' for import '{import_path}' in module '{id}'."
                        )
                    dep_filepath = dep_root / "src" / ("lib" if not suffix else Path(*suffix))

        dep_filepath = self._resolve_module_path(dep_filepath)
        if not dep_filepath.exists():
            raise RuntimeError(f"Unable to import: {import_path} in {id}")
        return dep_filepath

    def _try_resolve_import_module_id(self, id: Path, path: tuple[str, ...]) -> Path | None:
        try:
            return self._resolve_import_module_id(id, path)
        except (RuntimeError, ImportError):
            return None

    def _get_ast_by_id(self, id: Path) -> list[s.Statement]:
        if id in self._ast_cache:
            return self._ast_cache[id]

        source_ast = self._get_source_ast_by_id(id)
        ast = source_ast
        self._ast_cache[id] = ast
        return ast

    def _get_source_ast_by_id(self, id: Path) -> list[s.Statement]:
        if id in self._source_ast_cache:
            return self._source_ast_cache[id]

        source_text = self._get_source_text_by_id(id)
        try:
            tokens = self._lexer.parse(list(source_text))
            tokens = self._macro_expander.expand(tokens)
            ast = self._parser.parse(tokens, module_id=id, source_text=source_text)
            ast = filter_cfg_items(ast, self.cfg_environment)
        except Exception as exc:
            raise with_diagnostic_context(exc, stage="parse", module_id=id, source_text=source_text) from exc
        ast = self._inject_prelude_imports(id, ast)
        self._source_ast_cache[id] = ast
        return ast

    def _get_source_text_by_id(self, id: Path) -> str:
        if id not in self._source_text_cache:
            self._source_text_cache[id] = id.read_text()
        return self._source_text_cache[id]

    def _inject_prelude_imports(self, id: Path, ast: list[s.Statement]) -> list[s.Statement]:
        project_root = self._get_project_root_of(id)
        manifest = self._load_manifest(project_root)
        dependency_roots = self._get_dependency_roots(project_root)
        prelude_prefix: list[str] | None = None
        cast_prefix: list[str] | None = None

        if manifest.project.name == "core":
            # Do not inject prelude into core::ops itself.
            core_ops_mod = (project_root / "src" / "ops" / "mod.enq").resolve()
            core_cast_mod = (project_root / "src" / "cast" / "mod.enq").resolve()
            if id.resolve() != core_ops_mod:
                prelude_prefix = ["refrain", "ops"]
            if id.resolve() != core_cast_mod:
                cast_prefix = ["refrain", "cast"]
        elif manifest.project.name == "std":
            # Do not inject prelude into std::ops shim itself.
            std_ops_mod = (project_root / "src" / "ops" / "mod.enq").resolve()
            std_cast_mod = (project_root / "src" / "cast" / "mod.enq").resolve()
            if id.resolve() != std_ops_mod:
                prelude_prefix = ["core", "ops"] if "core" in dependency_roots else ["refrain", "ops"]
            if id.resolve() != std_cast_mod:
                cast_prefix = ["core", "cast"] if "core" in dependency_roots else ["refrain", "cast"]
        elif "std" in dependency_roots:
            prelude_prefix = ["std", "ops"]
            cast_prefix = ["std", "cast"]
        elif "core" in dependency_roots:
            prelude_prefix = ["core", "ops"]
            cast_prefix = ["core", "cast"]
        else:
            return ast

        has_ops_glob = False
        has_cast_glob = False
        for statement in ast:
            if not isinstance(statement, s.Statement_Import):
                continue
            for request in self._expand_import_statement(statement):
                if request.kind != "glob":
                    continue
                if list(request.path) in (["std", "ops"], ["core", "ops"], ["refrain", "ops"]):
                    has_ops_glob = True
                if list(request.path) in (["std", "cast"], ["core", "cast"], ["refrain", "cast"]):
                    has_cast_glob = True

        injected: list[s.Statement] = []
        if prelude_prefix is not None and not has_ops_glob:
            injected.append(
                s.Statement_Import(
                    is_public=False,
                    pair=s.Statement_Import.ImportPair(
                        src=prelude_prefix[0],
                        dst=[
                            s.Statement_Import.ImportPair(
                                src=prelude_prefix[1],
                                dst=[
                                    s.Statement_Import.ImportPair(
                                        src="*", dst=[], kind=s.Statement_Import.ImportKind.GLOB
                                    )
                                ],
                            )
                        ],
                    ),
                )
            )
        if cast_prefix is not None and not has_cast_glob:
            injected.append(
                s.Statement_Import(
                    is_public=False,
                    pair=s.Statement_Import.ImportPair(
                        src=cast_prefix[0],
                        dst=[
                            s.Statement_Import.ImportPair(
                                src=cast_prefix[1],
                                dst=[
                                    s.Statement_Import.ImportPair(
                                        src="*", dst=[], kind=s.Statement_Import.ImportKind.GLOB
                                    )
                                ],
                            )
                        ],
                    ),
                )
            )
        return [*injected, *ast] if injected else ast

    def _collect_imported_declarations(self, id: Path, ast: list[s.Statement]) -> list[ImportedTopLevelDeclaration]:
        declarations: list[ImportedTopLevelDeclaration] = []
        seen: set[tuple[Path, str]] = set()
        visited_modules: set[Path] = set()
        local_sources: dict[str, tuple[Path, str]] = {}
        expanded_type_impls: set[tuple[Path, str]] = set()

        def collect_named_types(typ: Type | None) -> set[str]:
            if typ is None:
                return set()
            typ = unwrap_for_storage(typ)
            if isinstance(typ, AnySmartPointer):
                return collect_named_types(typ.pointee)
            if isinstance(typ, HeapSmartPointer):
                return collect_named_types(typ.pointee)
            if isinstance(typ, StackSmartPointer):
                return collect_named_types(typ.pointee)
            if isinstance(typ, Pointer):
                return collect_named_types(typ.pointee)

            names = {typ.name}
            for generic in typ.generics:
                names |= collect_named_types(generic)
            return names

        def find_type_binding(module_id: Path, type_name: str) -> ExportBinding | None:
            leaf = type_name.rsplit("::", 1)[-1]
            index = self._get_module_index(module_id)
            binding = index.exports.get(type_name) or index.exports.get(leaf)
            if binding is None:
                return None
            if binding.kind not in {ExportKind.STRUCT, ExportKind.ENUM, ExportKind.TRAIT}:
                return None
            return binding

        def find_type_statement(
            module_id: Path, type_name: str
        ) -> s.Statement_StructureDefinition | s.Statement_EnumDefinition | s.Statement_Trait | None:
            leaf = type_name.rsplit("::", 1)[-1]
            module_ast = self._get_ast_by_id(module_id)
            for statement in module_ast:
                if isinstance(statement, s.Statement_StructureDefinition) and statement.signature.name == leaf:
                    return statement
                if isinstance(statement, s.Statement_EnumDefinition) and statement.name == leaf:
                    return statement
                if isinstance(statement, s.Statement_Trait) and statement.name == leaf:
                    return statement
            return None

        def append_type_definition(module_id: Path, type_name: str) -> None:
            binding = find_type_binding(module_id, type_name)
            if binding is not None:
                binding_module_id = binding.module_id
                binding_name = binding.name
                source_name = binding.source_name or binding.name
                statement = binding.statement
            else:
                statement = find_type_statement(module_id, type_name)
                if statement is None:
                    return
                binding_module_id = module_id
                binding_name = type_name.rsplit("::", 1)[-1]
                source_name = binding_name

            if not isinstance(
                statement, (s.Statement_StructureDefinition, s.Statement_EnumDefinition, s.Statement_Trait)
            ):
                return

            existing_source = local_sources.get(binding_name)
            current_source = (binding_module_id, source_name)
            if existing_source is not None and existing_source != current_source:
                raise TypeError(
                    f"Ambiguous import for symbol '{binding_name}': "
                    f"{existing_source[0]}::{existing_source[1]} vs {current_source[0]}::{current_source[1]}. "
                    f"Use `as` to disambiguate."
                )
            local_sources.setdefault(binding_name, current_source)

            key = (binding_module_id, binding_name)
            if key in seen:
                return
            seen.add(key)
            declarations.append(
                ImportedTopLevelDeclaration(
                    module_id=binding_module_id,
                    statement=statement,
                    local_name=binding_name,
                    source_name=source_name,
                )
            )
            if isinstance(statement, s.Statement_StructureDefinition):
                for field_param in statement.signature.fields:
                    for dep_type_name in collect_named_types(field_param.type):
                        append_type_definition(binding_module_id, dep_type_name)
            elif isinstance(statement, s.Statement_EnumDefinition):
                for variant in statement.variants:
                    if isinstance(variant, s.TupleStructureDefinition):
                        variant_types = list(variant.fields)
                    elif isinstance(variant, s.CLikeStructureDefinition):
                        variant_types = [field_param.type for field_param in variant.fields]
                    else:
                        variant_types = []
                    for variant_type in variant_types:
                        for dep_type_name in collect_named_types(variant_type):
                            append_type_definition(binding_module_id, dep_type_name)

        def find_function_statement(
            module_id: Path, function_name: str
        ) -> s.Statement_FunctionDefinition | s.FunctionSignature | None:
            if "::" in function_name:
                return None
            module_ast = self._get_ast_by_id(module_id)
            for statement in module_ast:
                if isinstance(statement, s.Statement_FunctionDefinition) and statement.signature.name == function_name:
                    return statement
                if isinstance(statement, s.FunctionSignature) and statement.name == function_name:
                    return statement
            return None

        def append_function_definition(module_id: Path, function_name: str) -> None:
            statement = find_function_statement(module_id, function_name)
            if statement is None:
                return

            key = (module_id, function_name)
            if key in seen:
                return
            seen.add(key)
            declarations.append(
                ImportedTopLevelDeclaration(
                    module_id=module_id,
                    statement=statement,
                    local_name=function_name,
                    source_name=function_name,
                )
            )
            signature = statement.signature if isinstance(statement, s.Statement_FunctionDefinition) else statement
            if signature.type is not None:
                for dep_type_name in collect_named_types(signature.type):
                    append_type_definition(module_id, dep_type_name)
            for param in signature.params:
                for dep_type_name in collect_named_types(param.type):
                    append_type_definition(module_id, dep_type_name)

        def collect_body_call_names(statement: s.Statement_TopLevel) -> set[str]:
            names: set[str] = set()

            def visit_node(node: object) -> None:
                if isinstance(node, s.Expression_Call):
                    names.add(node.name)

                if isinstance(node, (str, int, float, bool, Path, Type)) or node is None:
                    return
                if isinstance(node, list | tuple | set):
                    for item in node:
                        visit_node(item)
                    return
                if isinstance(node, dict):
                    for item in node.values():
                        visit_node(item)
                    return
                if not is_dataclass(node):
                    return

                for item in fields(node):
                    if item.name in {"line", "column", "span_length", "source_line", "module_id"}:
                        continue
                    visit_node(getattr(node, item.name))

            visit_node(statement)
            return names

        def impl_source_key(module_id: Path, impl: s.Statement_Impl) -> tuple[Path, str, str, str, tuple[str, ...]]:
            return (
                module_id,
                "impl",
                impl.trait_name or "",
                str(impl.struct),
                tuple(method.signature.name for method in impl.body),
            )

        def append_associated_type_impls(module_id: Path, type_name: str):
            source_type_name = type_name.rsplit("::", 1)[-1]
            marker = (module_id, source_type_name)
            if marker in expanded_type_impls:
                return
            expanded_type_impls.add(marker)

            append_type_definition(module_id, type_name)
            assoc_impls = self._collect_associated_impls(module_id, source_type_name)
            for assoc_impl in assoc_impls:
                impl_key = impl_source_key(module_id, assoc_impl)
                if impl_key in seen:
                    continue
                seen.add(impl_key)
                declarations.append(
                    ImportedTopLevelDeclaration(
                        module_id=module_id,
                        statement=assoc_impl,
                        local_name=source_type_name,
                        source_name=source_type_name,
                    )
                )

                for method in assoc_impl.body:
                    if method.signature.type is not None:
                        for dep_type_name in collect_named_types(method.signature.type):
                            append_associated_type_impls(module_id, dep_type_name)
                    for param in method.signature.params:
                        for dep_type_name in collect_named_types(param.type):
                            append_associated_type_impls(module_id, dep_type_name)

        def append_binding(binding: ExportBinding):
            existing_source = local_sources.get(binding.name)
            current_source = (binding.module_id, binding.source_name or binding.name)
            if existing_source is not None and existing_source != current_source:
                raise TypeError(
                    f"Ambiguous import for symbol '{binding.name}': "
                    f"{existing_source[0]}::{existing_source[1]} vs {current_source[0]}::{current_source[1]}. "
                    f"Use `as` to disambiguate."
                )
            local_sources.setdefault(binding.name, current_source)

            key = (binding.module_id, binding.name)
            if key not in seen:
                seen.add(key)
                declarations.append(
                    ImportedTopLevelDeclaration(
                        module_id=binding.module_id,
                        statement=binding.statement,
                        local_name=binding.name,
                        source_name=binding.source_name or binding.name,
                    )
                )

            if isinstance(binding.statement, (s.Statement_StructureDefinition, s.Statement_EnumDefinition)):
                lookup_name = binding.source_name or binding.name
                for assoc_impl in self._collect_associated_impls(binding.module_id, lookup_name):
                    impl_key = impl_source_key(binding.module_id, assoc_impl)
                    if impl_key in seen:
                        continue
                    seen.add(impl_key)
                    if binding.source_name is not None:
                        assoc_impl = replace(assoc_impl, struct=replace(assoc_impl.struct, name=binding.name))
                        assoc_impl = self._rewrite_impl_type_aliases(
                            assoc_impl,
                            source_name=lookup_name,
                            target_name=binding.name,
                        )
                    declarations.append(
                        ImportedTopLevelDeclaration(
                            module_id=binding.module_id,
                            statement=assoc_impl,
                            local_name=binding.name,
                            source_name=binding.source_name or binding.name,
                        )
                    )
                    for method in assoc_impl.body:
                        if method.signature.type is not None:
                            for dep_type_name in collect_named_types(method.signature.type):
                                append_associated_type_impls(binding.module_id, dep_type_name)
                        for param in method.signature.params:
                            for dep_type_name in collect_named_types(param.type):
                                append_associated_type_impls(binding.module_id, dep_type_name)
            elif isinstance(binding.statement, s.Statement_Trait):
                lookup_name = binding.source_name or binding.name
                for trait_impl in self._collect_trait_impls(binding.module_id, lookup_name):
                    impl_key = impl_source_key(binding.module_id, trait_impl)
                    if impl_key in seen:
                        continue
                    seen.add(impl_key)
                    if binding.source_name is not None:
                        trait_impl = replace(trait_impl, trait_name=binding.name)
                    declarations.append(
                        ImportedTopLevelDeclaration(
                            module_id=binding.module_id,
                            statement=trait_impl,
                            local_name=binding.name,
                            source_name=binding.source_name or binding.name,
                        )
                    )

        def visit(module_id: Path, module_ast: list[s.Statement]):
            if module_id in visited_modules:
                return
            visited_modules.add(module_id)

            if module_id != id:
                for builtin_impl in self._collect_builtin_associated_impls(module_id):
                    impl_key = impl_source_key(module_id, builtin_impl)
                    if impl_key in seen:
                        continue
                    seen.add(impl_key)
                    declarations.append(
                        ImportedTopLevelDeclaration(
                            module_id=module_id,
                            statement=builtin_impl,
                            local_name=builtin_impl.struct.name,
                            source_name=builtin_impl.struct.name,
                        )
                    )

            for statement in module_ast:
                if not isinstance(statement, s.Statement_Import):
                    continue

                for request in self._expand_import_statement(statement):
                    for binding in self._resolve_import_bindings(module_id, request):
                        append_binding(binding)
                        visit(binding.module_id, self._get_ast_by_id(binding.module_id))

        visit(id, ast)
        processed_dependencies = 0
        while processed_dependencies < len(declarations):
            declaration = declarations[processed_dependencies]
            processed_dependencies += 1
            for function_name in collect_body_call_names(declaration.statement):
                append_function_definition(declaration.module_id, function_name)

        return declarations

    def _collect_associated_impls(self, module_id: Path, struct_name: str) -> list[s.Statement_Impl]:
        def leaf(name: str) -> str:
            return name.rsplit("::", 1)[-1]

        ast = self._get_ast_by_id(module_id)
        result: list[s.Statement_Impl] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Impl):
                continue
            if statement.struct.name != struct_name and leaf(statement.struct.name) != leaf(struct_name):
                continue
            result.append(statement)
        return result

    def _collect_builtin_associated_impls(self, module_id: Path) -> list[s.Statement_Impl]:
        builtin_types = {
            "bool",
            "str",
            "u8",
            "u16",
            "u32",
            "u64",
            "usize",
            "i8",
            "i16",
            "i32",
            "i64",
            "isize",
            "f32",
            "f64",
        }
        ast = self._get_ast_by_id(module_id)
        result: list[s.Statement_Impl] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Impl):
                continue
            if statement.trait_name is not None:
                continue
            if statement.struct.name not in builtin_types:
                continue
            result.append(statement)
        return result

    def _collect_module_inherent_impls(self, module_id: Path) -> list[s.Statement_Impl]:
        ast = self._get_ast_by_id(module_id)
        result: list[s.Statement_Impl] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Impl):
                continue
            if statement.trait_name is not None:
                continue
            result.append(statement)
        return result

    def _collect_trait_impls(self, module_id: Path, trait_name: str) -> list[s.Statement_Impl]:
        ast = self._get_ast_by_id(module_id)
        result: list[s.Statement_Impl] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Impl):
                continue
            if statement.trait_name != trait_name:
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

    def _expand_import_statement(self, statement: s.Statement_Import) -> list[ImportRequest]:
        requests: list[ImportRequest] = []

        def visit(prefix: tuple[str, ...], pair: s.Statement_Import.ImportPair, inherited_alias: str | None = None):
            alias = inherited_alias or pair.alias
            if pair.dst:
                if alias is not None and len(pair.dst) != 1:
                    raise TypeError("Alias cannot be applied to import groups")
                for child in pair.dst:
                    visit(prefix + (pair.src,), child, alias)
                return

            if pair.kind == s.Statement_Import.ImportKind.GLOB:
                if alias is not None:
                    raise TypeError("Wildcard import cannot have alias")
                requests.append(ImportRequest(path=prefix, kind="glob", alias=None))
                return

            requests.append(ImportRequest(path=prefix + (pair.src,), kind="item", alias=alias))

        visit(tuple(), statement.pair)
        return requests

    def _resolve_import_bindings(self, id: Path, request: ImportRequest) -> list[ExportBinding]:
        if request.kind == "glob":
            parent_id = self._resolve_import_module_id(id, request.path)
            target_index = self._get_module_index(parent_id)
            return list(target_index.exports.values())

        module_candidate_id = self._try_resolve_import_module_id(id, request.path)
        symbol_candidate_binding: ExportBinding | None = None
        if len(request.path) >= 2:
            parent_id = self._try_resolve_import_module_id(id, request.path[:-1])
            if parent_id is not None:
                target_index = self._get_module_index(parent_id)
                symbol_candidate_binding = target_index.exports.get(request.path[-1])

        if module_candidate_id is not None and symbol_candidate_binding is not None:
            # Backward compatibility with legacy imports: prefer symbol when both exist.
            if request.alias is None:
                return [symbol_candidate_binding]
            return [self._alias_binding(symbol_candidate_binding, request.alias)]

        if symbol_candidate_binding is not None:
            if request.alias is None:
                return [symbol_candidate_binding]
            return [self._alias_binding(symbol_candidate_binding, request.alias)]

        if module_candidate_id is not None:
            local_module_name = request.alias or request.path[-1]
            return self._resolve_module_import_bindings(module_candidate_id, local_module_name)

        raise RuntimeError(f"Unable to import: {'::'.join(request.path)} in {id}")

    def _prepare_imports_for_translation(self, id: Path, ast: list[s.Statement]) -> list[s.Statement]:
        translated_ast = deepcopy(ast)

        def classify_import_pair(prefix: tuple[str, ...], pair: s.Statement_Import.ImportPair):
            if pair.dst:
                for child in pair.dst:
                    classify_import_pair(prefix + (pair.src,), child)
                return

            if pair.kind == s.Statement_Import.ImportKind.GLOB:
                return

            path = prefix + (pair.src,)
            if self._is_module_import_path(id, path, pair.alias):
                pair.kind = s.Statement_Import.ImportKind.PACKAGE
            else:
                pair.kind = s.Statement_Import.ImportKind.SYMBOL

        for statement in translated_ast:
            if not isinstance(statement, s.Statement_Import):
                continue
            classify_import_pair(tuple(), statement.pair)

        return translated_ast

    def _is_module_import_path(self, id: Path, path: tuple[str, ...], alias: str | None) -> bool:
        module_candidate_id = self._try_resolve_import_module_id(id, path)
        symbol_candidate_exists = False
        if len(path) >= 2:
            parent_id = self._try_resolve_import_module_id(id, path[:-1])
            if parent_id is not None:
                symbol_candidate_exists = self._get_module_index(parent_id).exports.get(path[-1]) is not None

        if module_candidate_id is not None and symbol_candidate_exists:
            # Keep legacy behavior for ambiguous paths.
            return False
        return module_candidate_id is not None and not symbol_candidate_exists

    def _resolve_module_import_bindings(self, module_id: Path, local_module_name: str) -> list[ExportBinding]:
        result: list[ExportBinding] = []
        visited: set[Path] = set()

        def visit(curr_module_id: Path, relative_prefix: tuple[str, ...]):
            if curr_module_id in visited:
                return
            visited.add(curr_module_id)

            index = self._get_module_index(curr_module_id)
            prefix = "::".join((local_module_name, *relative_prefix))
            for binding in index.exports.values():
                local_name = f"{prefix}::{binding.name}"
                result.append(self._alias_binding(binding, local_name))

            for child_name, child_module_id in self._list_child_modules(curr_module_id).items():
                visit(child_module_id, (*relative_prefix, child_name))

        visit(module_id, tuple())
        return result

    def _list_child_modules(self, module_id: Path) -> dict[str, Path]:
        children: dict[str, Path] = {}

        if module_id.stem == "mod":
            base_dir = module_id.parent
            candidates = list(base_dir.glob("*.enq")) + list(base_dir.glob("*/mod.enq"))
        else:
            base_dir = module_id.parent / module_id.stem
            if not base_dir.exists():
                return children
            candidates = list(base_dir.glob("*.enq")) + list(base_dir.glob("*/mod.enq"))

        for candidate in candidates:
            if candidate.resolve() == module_id.resolve():
                continue
            if candidate.name == "mod.enq":
                child_name = candidate.parent.name
            else:
                child_name = candidate.stem
            children.setdefault(child_name, candidate.resolve())

        return children

    def list_child_module_ids(self, id: Path) -> list[Path]:
        return sorted(Path(child_id) for child_id in self._list_child_modules(id).values())

    def _alias_binding(self, binding: ExportBinding, alias: str) -> ExportBinding:
        return replace(binding, name=alias, source_name=binding.name)

    def _rewrite_impl_type_aliases(
        self, impl: s.Statement_Impl, *, source_name: str, target_name: str
    ) -> s.Statement_Impl:
        rewritten_impl_generics = [
            self._replace_type_name(generic, source_name, target_name) for generic in impl.generics
        ]
        rewritten_trait_args = [self._replace_type_name(arg, source_name, target_name) for arg in impl.trait_args]
        rewritten_struct = self._replace_type_name(impl.struct, source_name, target_name)
        rewritten_methods: list[s.Statement_FunctionDefinition] = []
        for method in impl.body:
            params = [
                replace(param, type=self._replace_type_name(param.type, source_name, target_name))
                for param in method.signature.params
            ]
            ret_type = (
                None
                if method.signature.type is None
                else self._replace_type_name(method.signature.type, source_name, target_name)
            )
            generics = [
                self._replace_type_name(generic, source_name, target_name) for generic in method.signature.generics
            ]
            signature = replace(method.signature, generics=generics, params=params, type=ret_type)
            rewritten_methods.append(replace(method, signature=signature))
        return replace(
            impl,
            generics=rewritten_impl_generics,
            trait_args=rewritten_trait_args,
            struct=rewritten_struct,
            body=rewritten_methods,
        )

    def _replace_type_name(self, typ: Type, source_name: str, target_name: str) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._replace_type_name(unwrap_for_storage(typ), source_name, target_name))
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._replace_type_name(typ.pointee, source_name, target_name))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._replace_type_name(typ.pointee, source_name, target_name))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._replace_type_name(typ.pointee, source_name, target_name))
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type_name(typ.pointee, source_name, target_name))

        name = target_name if typ.name == source_name else typ.name
        generics = [self._replace_type_name(generic, source_name, target_name) for generic in typ.generics]
        if isinstance(typ, s.GenericParam):
            bounds = [self._replace_type_name(bound, source_name, target_name) for bound in typ.bounds]
            return s.GenericParam(name=name, generics=generics, bounds=bounds)
        return Type(name, generics)

    def _get_project_root_of(self, id: Path) -> Path:
        for parent in [id.parent, *id.parents]:
            if (parent / ProjectManifest.default_filename()).exists():
                return parent
        raise RuntimeError(f"Unable to find encore.toml for module: {id}")

    def _get_dependency_roots(self, project_root: Path) -> dict[str, Path]:
        if project_root in self._dependency_cache:
            return self._dependency_cache[project_root]

        roots: dict[str, Path] = {}
        visited: set[Path] = set()
        self._collect_dependency_roots(project_root, roots, visited)
        self._inject_mandatory_core_dependency(project_root, roots, visited)

        self._dependency_cache[project_root] = roots
        return roots

    def _inject_mandatory_core_dependency(self, project_root: Path, roots: dict[str, Path], visited: set[Path]) -> None:
        manifest = self._load_manifest(project_root)
        if manifest.project.name == "core":
            return
        if "core" in roots:
            return

        core_root = self._resolve_local_core_root(project_root)
        if core_root is None:
            raise RuntimeError(
                "Unable to resolve mandatory dependency 'core'. "
                "Expected to find it in dependencies or as local 'refrains/core'."
            )

        roots.setdefault("core", core_root)
        self._collect_dependency_roots(core_root, roots, visited)

    def _resolve_local_core_root(self, project_root: Path) -> Optional[Path]:
        from os import getenv

        from encore import PROJECT_ROOT

        canonical_candidates = [
            (PROJECT_ROOT / "core").resolve(),
            (PROJECT_ROOT / "refrains" / "core").resolve(),
        ]
        for candidate in canonical_candidates:
            manifest_path = candidate / ProjectManifest.default_filename()
            if not manifest_path.exists():
                continue
            manifest = self._load_manifest(candidate)
            if manifest.project.name == "core":
                return candidate

        candidates: list[Path] = []
        for base in [project_root, *project_root.parents]:
            candidates.append(base / "refrains" / "core")
            candidates.append(base / "core")
        cwd = Path.cwd().resolve()
        for base in [cwd, *cwd.parents]:
            candidates.append(base / "refrains" / "core")
            candidates.append(base / "core")
        encore_home = getenv("ENCORE_HOME")
        if encore_home:
            base = Path(encore_home).expanduser().resolve()
            candidates.append(base / "refrains" / "core")
            candidates.append(base / "core")
        candidates.append(Path(__file__).resolve().parents[3] / "enc_future" / "refrains" / "core")
        candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "core")
        candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "encore-core")

        seen: set[Path] = set()
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            manifest_path = candidate / ProjectManifest.default_filename()
            if not manifest_path.exists():
                continue
            manifest = self._load_manifest(candidate)
            if manifest.project.name == "core":
                return candidate

        return None

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
