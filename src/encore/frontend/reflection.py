from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ehir.core.type import Type
from ehir.core.variable import Parameter

from encore.frontend.parser import statements as s


RUNTIME_REFLECT_MODULE_NAME = "__encore_reflect_module"
RUNTIME_REFLECT_SYMBOL_NAME = "__encore_reflect_symbol"
RUNTIME_STR_EQ_EXTERN_NAME = "__ehir_rt_str_eq"
RUNTIME_OPTION_ALIAS = "Option"
RUNTIME_MODULE_INFO_ALIAS = "ReflectModuleInfo"
RUNTIME_SYMBOL_INFO_ALIAS = "ReflectSymbolInfo"
RUNTIME_SYMBOL_KIND_ALIAS = "ReflectSymbolKind"
RUNTIME_REFLECTION_RESERVED_NAMES = {
    RUNTIME_REFLECT_MODULE_NAME,
    RUNTIME_REFLECT_SYMBOL_NAME,
    RUNTIME_STR_EQ_EXTERN_NAME,
}


@dataclass(frozen=True)
class ReflectionImport:
    is_public: bool
    path: str


@dataclass(frozen=True)
class ReflectionParam:
    name: str
    type: Type


@dataclass(frozen=True)
class ReflectionField:
    name: str
    type: Type


@dataclass(frozen=True)
class ReflectionVariant:
    name: str
    generics: list[Type]
    fields: list[ReflectionField]
    is_tuple: bool
    is_unit: bool


@dataclass(frozen=True)
class ReflectionFunction:
    name: str
    qualified_name: str
    is_public: bool
    is_extern: bool
    generics: list[Type]
    params: list[ReflectionParam]
    return_type: Type | None
    owner_kind: str | None = None
    owner_name: str | None = None
    trait_name: str | None = None


@dataclass(frozen=True)
class ReflectionStruct:
    name: str
    is_public: bool
    generics: list[Type]
    fields: list[ReflectionField]
    is_tuple: bool
    is_unit: bool


@dataclass(frozen=True)
class ReflectionEnum:
    name: str
    is_public: bool
    generics: list[Type]
    variants: list[ReflectionVariant]


@dataclass(frozen=True)
class ReflectionTrait:
    name: str
    is_public: bool
    generics: list[Type]
    bases: list[Type]
    methods: list[ReflectionFunction]


@dataclass(frozen=True)
class ReflectionImpl:
    generics: list[Type]
    trait_name: str | None
    trait_args: list[Type]
    target: Type
    methods: list[ReflectionFunction]


@dataclass(frozen=True)
class ModuleReflection:
    module_id: Path
    imports: list[ReflectionImport] = field(default_factory=list)
    functions: list[ReflectionFunction] = field(default_factory=list)
    structs: list[ReflectionStruct] = field(default_factory=list)
    enums: list[ReflectionEnum] = field(default_factory=list)
    traits: list[ReflectionTrait] = field(default_factory=list)
    impls: list[ReflectionImpl] = field(default_factory=list)


@dataclass(frozen=True)
class ReflectionSymbol:
    kind: str
    name: str
    qualified_name: str
    value: object


def build_runtime_reflection_ast(module_id: Path, ast: list[s.Statement], reflection: "ModuleReflection") -> list[s.Statement]:
    _ensure_runtime_reflection_names_available(module_id, ast)
    return [
        *_build_runtime_reflection_imports(),
        *ast,
        _build_runtime_str_eq_extern(),
        _build_runtime_reflect_module_fn(reflection),
        _build_runtime_reflect_symbol_fn(reflection),
    ]


def build_module_reflection(module_id: Path, ast: list[s.Statement]) -> ModuleReflection:
    imports: list[ReflectionImport] = []
    functions: list[ReflectionFunction] = []
    structs: list[ReflectionStruct] = []
    enums: list[ReflectionEnum] = []
    traits: list[ReflectionTrait] = []
    impls: list[ReflectionImpl] = []

    for statement in ast:
        if isinstance(statement, s.Statement_Import):
            imports.append(ReflectionImport(is_public=statement.is_public, path=repr(statement.pair)))
            continue

        if isinstance(statement, s.Statement_FunctionDefinition):
            functions.append(_function_from_signature(statement.signature))
            continue

        if isinstance(statement, s.Statement_StructureDefinition):
            structs.append(_struct_from_definition(statement))
            continue

        if isinstance(statement, s.Statement_EnumDefinition):
            enums.append(_enum_from_definition(statement))
            continue

        if isinstance(statement, s.Statement_Trait):
            trait_methods = [
                _function_from_signature(method, owner_kind="trait", owner_name=statement.name, trait_name=statement.name)
                for method in statement.body
            ]
            traits.append(
                ReflectionTrait(
                    name=statement.name,
                    is_public=statement.is_public,
                    generics=list(statement.generics),
                    bases=list(statement.bases),
                    methods=trait_methods,
                )
            )
            functions.extend(trait_methods)
            continue

        if isinstance(statement, s.Statement_Impl):
            owner_kind = "trait-impl" if statement.trait_name is not None else "impl"
            owner_name = statement.struct.name
            impl_methods = [
                _function_from_signature(
                    method.signature,
                    owner_kind=owner_kind,
                    owner_name=owner_name,
                    trait_name=statement.trait_name,
                    qualified_name=_qualified_impl_method_name(statement, method.name),
                )
                for method in statement.body
            ]
            impls.append(
                ReflectionImpl(
                    generics=list(statement.generics),
                    trait_name=statement.trait_name,
                    trait_args=list(statement.trait_args),
                    target=statement.struct,
                    methods=impl_methods,
                )
            )
            functions.extend(impl_methods)

    return ModuleReflection(
        module_id=module_id,
        imports=imports,
        functions=functions,
        structs=structs,
        enums=enums,
        traits=traits,
        impls=impls,
    )


def format_module_reflection(reflection: ModuleReflection) -> str:
    lines: list[str] = [f"module {reflection.module_id}"]

    if reflection.imports:
        lines.append("imports:")
        lines.extend(f"  - {('pub ' if item.is_public else '')}{item.path}" for item in reflection.imports)

    if reflection.structs:
        lines.append("structs:")
        lines.extend(f"  - {format_reflection_struct(item)}" for item in reflection.structs)

    if reflection.enums:
        lines.append("enums:")
        lines.extend(f"  - {format_reflection_enum(item)}" for item in reflection.enums)

    if reflection.traits:
        lines.append("traits:")
        lines.extend(f"  - {format_reflection_trait(item)}" for item in reflection.traits)

    if reflection.impls:
        lines.append("impls:")
        lines.extend(f"  - {format_reflection_impl(item)}" for item in reflection.impls)

    if reflection.functions:
        lines.append("functions:")
        lines.extend(f"  - {format_reflection_function(item)}" for item in reflection.functions)

    return "\n".join(lines)


def find_function_reflection(reflection: ModuleReflection, qualified_name: str) -> ReflectionFunction | None:
    for item in reflection.functions:
        if item.qualified_name == qualified_name:
            return item
    return None


def find_struct_reflection(reflection: ModuleReflection, name: str) -> ReflectionStruct | None:
    for item in reflection.structs:
        if item.name == name:
            return item
    return None


def find_enum_reflection(reflection: ModuleReflection, name: str) -> ReflectionEnum | None:
    for item in reflection.enums:
        if item.name == name:
            return item
    return None


def find_trait_reflection(reflection: ModuleReflection, name: str) -> ReflectionTrait | None:
    for item in reflection.traits:
        if item.name == name:
            return item
    return None


def collect_symbol_reflections(reflection: ModuleReflection) -> list[ReflectionSymbol]:
    out: list[ReflectionSymbol] = []

    for item in reflection.functions:
        out.append(
            ReflectionSymbol(
                kind="function",
                name=item.name,
                qualified_name=item.qualified_name,
                value=item,
            )
        )

    for item in reflection.structs:
        out.append(ReflectionSymbol(kind="struct", name=item.name, qualified_name=item.name, value=item))

    for item in reflection.enums:
        out.append(ReflectionSymbol(kind="enum", name=item.name, qualified_name=item.name, value=item))
        for variant in item.variants:
            out.append(
                ReflectionSymbol(
                    kind="enum-variant",
                    name=variant.name,
                    qualified_name=f"{item.name}::{variant.name}",
                    value=variant,
                )
            )

    for item in reflection.traits:
        out.append(ReflectionSymbol(kind="trait", name=item.name, qualified_name=item.name, value=item))

    for item in reflection.impls:
        qualified_name = item.target.name if item.trait_name is None else f"{item.trait_name} for {item.target}"
        out.append(ReflectionSymbol(kind="impl", name=item.target.name, qualified_name=qualified_name, value=item))

    return out


def find_symbol_reflection(reflection: ModuleReflection, query: str) -> ReflectionSymbol | None:
    symbols = collect_symbol_reflections(reflection)

    for item in symbols:
        if item.qualified_name == query:
            return item

    matches = [item for item in symbols if item.name == query]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    variants = ", ".join(item.qualified_name for item in matches)
    raise TypeError(f"Ambiguous reflection lookup for '{query}': {variants}")


def format_symbol_reflection(symbol: ReflectionSymbol) -> str:
    if symbol.kind == "function":
        return format_reflection_function(symbol.value)
    if symbol.kind == "struct":
        return format_reflection_struct(symbol.value)
    if symbol.kind == "enum":
        return format_reflection_enum(symbol.value)
    if symbol.kind == "trait":
        return format_reflection_trait(symbol.value)
    if symbol.kind == "impl":
        return format_reflection_impl(symbol.value)
    if symbol.kind == "enum-variant":
        return _format_variant(symbol.value)
    return f"{symbol.kind} {symbol.qualified_name}"


def format_reflection_function(item: ReflectionFunction) -> str:
    visibility = "pub " if item.is_public else ""
    extern = "extern " if item.is_extern else ""
    owner = f" [{item.owner_kind}:{item.owner_name}]" if item.owner_kind is not None and item.owner_name is not None else ""
    ret = f" -> {item.return_type}" if item.return_type is not None else ""
    return (
        f"{visibility}{extern}fn {item.qualified_name}{s.format_generic_params(item.generics)}"
        f"({', '.join(_format_param(param) for param in item.params)}){ret}{owner}"
    )


def format_reflection_struct(item: ReflectionStruct) -> str:
    visibility = "pub " if item.is_public else ""
    fields = ", ".join(_format_field(field) for field in item.fields)
    shape = "unit"
    if item.is_tuple:
        shape = "tuple"
    elif not item.is_unit:
        shape = "clike"
    return f"{visibility}struct {item.name}{s.format_generic_params(item.generics)} [{shape}] {{{fields}}}"


def format_reflection_enum(item: ReflectionEnum) -> str:
    visibility = "pub " if item.is_public else ""
    variants = ", ".join(_format_variant(variant) for variant in item.variants)
    return f"{visibility}enum {item.name}{s.format_generic_params(item.generics)} {{{variants}}}"


def format_reflection_trait(item: ReflectionTrait) -> str:
    visibility = "pub " if item.is_public else ""
    bases = f" < {', '.join(str(base) for base in item.bases)}" if item.bases else ""
    methods = ", ".join(method.name for method in item.methods)
    return f"{visibility}trait {item.name}{s.format_generic_params(item.generics)}{bases} [{methods}]"


def format_reflection_impl(item: ReflectionImpl) -> str:
    generics = s.format_generic_params(item.generics)
    trait_repr = ""
    if item.trait_name is not None:
        args = f"[{', '.join(str(arg) for arg in item.trait_args)}]" if item.trait_args else ""
        trait_repr = f" {item.trait_name}{args}"
    methods = ", ".join(method.name for method in item.methods)
    return f"impl{generics}{trait_repr} for {item.target} [{methods}]"


def _function_from_signature(
    signature: s.FunctionSignature,
    *,
    owner_kind: str | None = None,
    owner_name: str | None = None,
    trait_name: str | None = None,
    qualified_name: str | None = None,
) -> ReflectionFunction:
    return ReflectionFunction(
        name=signature.name,
        qualified_name=qualified_name or signature.name,
        is_public=signature.is_public,
        is_extern=signature.is_extern,
        generics=list(signature.generics),
        params=[ReflectionParam(name=param.name, type=param.type) for param in signature.params],
        return_type=signature.type,
        owner_kind=owner_kind,
        owner_name=owner_name,
        trait_name=trait_name,
    )


def _struct_from_definition(statement: s.Statement_StructureDefinition) -> ReflectionStruct:
    signature = statement.signature
    if isinstance(signature, s.CLikeStructureDefinition):
        fields = [ReflectionField(name=field.name, type=field.type) for field in signature.fields]
        return ReflectionStruct(
            name=signature.name,
            is_public=statement.is_public,
            generics=list(signature.generics),
            fields=fields,
            is_tuple=False,
            is_unit=False,
        )
    if isinstance(signature, s.TupleStructureDefinition):
        fields = [ReflectionField(name=str(idx), type=field) for idx, field in enumerate(signature.fields)]
        return ReflectionStruct(
            name=signature.name,
            is_public=statement.is_public,
            generics=list(signature.generics),
            fields=fields,
            is_tuple=True,
            is_unit=False,
        )
    return ReflectionStruct(
        name=signature.name,
        is_public=statement.is_public,
        generics=list(signature.generics),
        fields=[],
        is_tuple=False,
        is_unit=True,
    )


def _enum_from_definition(statement: s.Statement_EnumDefinition) -> ReflectionEnum:
    variants: list[ReflectionVariant] = []
    for variant in statement.body:
        if isinstance(variant, s.CLikeStructureDefinition):
            fields = [ReflectionField(name=field.name, type=field.type) for field in variant.fields]
            variants.append(
                ReflectionVariant(
                    name=variant.name,
                    generics=list(variant.generics),
                    fields=fields,
                    is_tuple=False,
                    is_unit=False,
                )
            )
            continue
        if isinstance(variant, s.TupleStructureDefinition):
            fields = [ReflectionField(name=str(idx), type=field) for idx, field in enumerate(variant.fields)]
            variants.append(
                ReflectionVariant(
                    name=variant.name,
                    generics=list(variant.generics),
                    fields=fields,
                    is_tuple=True,
                    is_unit=False,
                )
            )
            continue
        variants.append(
            ReflectionVariant(
                name=variant.name,
                generics=list(variant.generics),
                fields=[],
                is_tuple=False,
                is_unit=True,
            )
        )

    return ReflectionEnum(
        name=statement.name,
        is_public=statement.is_public,
        generics=list(statement.generics),
        variants=variants,
    )


def _qualified_impl_method_name(statement: s.Statement_Impl, method_name: str) -> str:
    if statement.trait_name is not None:
        return f"{statement.trait_name}::{method_name}"
    return f"{statement.struct.name}::{method_name}"


def _format_param(param: ReflectionParam) -> str:
    return f"{param.name}: {param.type}"


def _format_field(field: ReflectionField) -> str:
    return f"{field.name}: {field.type}"


def _format_variant(variant: ReflectionVariant) -> str:
    if variant.is_unit:
        return f"{variant.name}{s.format_generic_params(variant.generics)}"
    if variant.is_tuple:
        items = ", ".join(str(field.type) for field in variant.fields)
        return f"{variant.name}{s.format_generic_params(variant.generics)}({items})"
    fields = ", ".join(_format_field(field) for field in variant.fields)
    return f"{variant.name}{s.format_generic_params(variant.generics)} {{{fields}}}"


def _ensure_runtime_reflection_names_available(module_id: Path, ast: list[s.Statement]) -> None:
    for statement in ast:
        names: list[str] = []
        if isinstance(statement, s.Statement_FunctionDefinition):
            names.append(statement.signature.name)
        elif isinstance(statement, s.FunctionSignature):
            names.append(statement.name)
        elif isinstance(statement, s.Statement_StructureDefinition):
            names.append(statement.signature.name)
        elif isinstance(statement, s.Statement_EnumDefinition):
            names.append(statement.name)
        elif isinstance(statement, s.Statement_Trait):
            names.append(statement.name)

        for name in names:
            if name in RUNTIME_REFLECTION_RESERVED_NAMES:
                raise TypeError(f"Runtime reflection helper name '{name}' is reserved in module '{module_id}'")


def _build_runtime_reflection_imports() -> list[s.Statement_Import]:
    return [
        s.Statement_Import(
            is_public=False,
            pair=s.Statement_Import.ImportPair(
                src="core",
                dst=[
                    s.Statement_Import.ImportPair(
                        src="option",
                        dst=[s.Statement_Import.ImportPair(src=RUNTIME_OPTION_ALIAS, dst=[])],
                    )
                ],
            ),
        ),
        s.Statement_Import(
            is_public=False,
            pair=s.Statement_Import.ImportPair(
                src="core",
                dst=[
                    s.Statement_Import.ImportPair(
                        src="reflect",
                        dst=[
                            s.Statement_Import.ImportPair(src=RUNTIME_MODULE_INFO_ALIAS, dst=[]),
                            s.Statement_Import.ImportPair(src=RUNTIME_SYMBOL_INFO_ALIAS, dst=[]),
                            s.Statement_Import.ImportPair(src=RUNTIME_SYMBOL_KIND_ALIAS, dst=[]),
                        ],
                    )
                ],
            ),
        ),
    ]


def _build_runtime_str_eq_extern() -> s.FunctionSignature:
    return s.FunctionSignature(
        is_public=False,
        is_extern=True,
        name=RUNTIME_STR_EQ_EXTERN_NAME,
        generics=[],
        params=[Parameter("lhs", Type("str")), Parameter("rhs", Type("str"))],
        type=Type("bool"),
    )


def _build_runtime_reflect_module_fn(reflection: ModuleReflection) -> s.Statement_FunctionDefinition:
    module_expr = s.Expression_StructInitialization(
        name=Type(RUNTIME_MODULE_INFO_ALIAS),
        args=[
            s.Expression_StringLiteral(str(reflection.module_id)),
            _usize_expr(len(reflection.imports)),
            _usize_expr(len(reflection.structs)),
            _usize_expr(len(reflection.enums)),
            _usize_expr(len(reflection.traits)),
            _usize_expr(len(reflection.impls)),
            _usize_expr(len(reflection.functions)),
            s.Expression_StringLiteral(_format_runtime_imports(reflection.imports)),
            s.Expression_StringLiteral(_join_runtime_lines(format_reflection_struct(item) for item in reflection.structs)),
            s.Expression_StringLiteral(_join_runtime_lines(format_reflection_enum(item) for item in reflection.enums)),
            s.Expression_StringLiteral(_join_runtime_lines(format_reflection_trait(item) for item in reflection.traits)),
            s.Expression_StringLiteral(_join_runtime_lines(format_reflection_impl(item) for item in reflection.impls)),
            s.Expression_StringLiteral(_join_runtime_lines(format_reflection_function(item) for item in reflection.functions)),
        ],
    )
    return s.Statement_FunctionDefinition(
        is_public=True,
        signature=s.FunctionSignature(
            is_public=True,
            is_extern=False,
            name=RUNTIME_REFLECT_MODULE_NAME,
            generics=[],
            params=[],
            type=Type(RUNTIME_MODULE_INFO_ALIAS),
        ),
        body=s.Block(body=[s.Statement_Ret(expr=module_expr)]),
    )


def _build_runtime_reflect_symbol_fn(reflection: ModuleReflection) -> s.Statement_FunctionDefinition:
    option_symbol_info_type = Type(RUNTIME_OPTION_ALIAS, [Type(RUNTIME_SYMBOL_INFO_ALIAS)])
    branches = [
        s.Statement_IfBranch(
            expr=s.Expression_Unsafe(
                body=s.Block(
                    body=[
                        s.Statement_Expr(
                            expr=s.Expression_Call(
                                callee=s.Expression_Path([Type(RUNTIME_STR_EQ_EXTERN_NAME)]),
                                generics=[],
                                args=[
                                    s.Expression_Path([Type("query")]),
                                    s.Expression_StringLiteral(query),
                                ],
                            )
                        )
                    ]
                ),
            ),
            body=s.Block(body=[s.Statement_Ret(expr=_build_runtime_symbol_some_expr(symbol))]),
        )
        for query, symbol in _build_runtime_symbol_queries(reflection)
    ]

    body: list[s.Statement_InnerLevel]
    if branches:
        body = [
            s.Statement_If(
                branches=branches,
                else_body=s.Block(body=[s.Statement_Ret(expr=_build_runtime_symbol_none_expr(option_symbol_info_type))]),
            )
        ]
    else:
        body = [s.Statement_Ret(expr=_build_runtime_symbol_none_expr(option_symbol_info_type))]

    return s.Statement_FunctionDefinition(
        is_public=True,
        signature=s.FunctionSignature(
            is_public=True,
            is_extern=False,
            name=RUNTIME_REFLECT_SYMBOL_NAME,
            generics=[],
            params=[Parameter("query", Type("str"))],
            type=option_symbol_info_type,
        ),
        body=s.Block(body=body),
    )


def _build_runtime_symbol_queries(reflection: ModuleReflection) -> list[tuple[str, ReflectionSymbol]]:
    symbols = collect_symbol_reflections(reflection)
    short_name_counts: dict[str, int] = {}
    for symbol in symbols:
        short_name_counts[symbol.name] = short_name_counts.get(symbol.name, 0) + 1

    queries: list[tuple[str, ReflectionSymbol]] = []
    seen_queries: set[str] = set()
    for symbol in symbols:
        for query in (symbol.qualified_name, symbol.name if short_name_counts[symbol.name] == 1 else None):
            if query is None or query in seen_queries:
                continue
            seen_queries.add(query)
            queries.append((query, symbol))

    return queries


def _build_runtime_symbol_some_expr(symbol: ReflectionSymbol) -> s.Expression_Call:
    owner_kind, owner_name = _runtime_symbol_owner(symbol)
    symbol_info_expr = s.Expression_StructInitialization(
        name=Type(RUNTIME_SYMBOL_INFO_ALIAS),
        args=[
            _build_runtime_symbol_kind_expr(symbol.kind),
            s.Expression_StringLiteral(symbol.name),
            s.Expression_StringLiteral(symbol.qualified_name),
            s.Expression_BooleanLiteral(_runtime_symbol_is_public(symbol)),
            s.Expression_StringLiteral(owner_kind),
            s.Expression_StringLiteral(owner_name),
            s.Expression_StringLiteral(format_symbol_reflection(symbol)),
        ],
    )
    return s.Expression_Call(
        callee=s.Expression_Path([Type(RUNTIME_OPTION_ALIAS, [Type(RUNTIME_SYMBOL_INFO_ALIAS)]), Type("Some")]),
        generics=[],
        args=[symbol_info_expr],
    )


def _build_runtime_symbol_none_expr(option_symbol_info_type: Type) -> s.Expression_Path:
    return s.Expression_Path([option_symbol_info_type, Type("None")])


def _build_runtime_symbol_kind_expr(kind: str) -> s.Expression_Path:
    variant = {
        "function": "Function",
        "struct": "Struct",
        "enum": "Enum",
        "enum-variant": "Variant",
        "trait": "Trait",
        "impl": "Impl",
    }.get(kind)
    if variant is None:
        raise TypeError(f"Unsupported runtime reflection symbol kind '{kind}'")
    return s.Expression_Path([Type(RUNTIME_SYMBOL_KIND_ALIAS), Type(variant)])


def _runtime_symbol_is_public(symbol: ReflectionSymbol) -> bool:
    if symbol.kind == "function":
        return symbol.value.is_public
    if symbol.kind == "struct":
        return symbol.value.is_public
    if symbol.kind == "enum":
        return symbol.value.is_public
    if symbol.kind == "trait":
        return symbol.value.is_public
    if symbol.kind == "impl":
        return False
    if symbol.kind == "enum-variant":
        return True
    return False


def _runtime_symbol_owner(symbol: ReflectionSymbol) -> tuple[str, str]:
    if symbol.kind == "function":
        owner_kind = symbol.value.owner_kind or ""
        owner_name = symbol.value.owner_name or ""
        return owner_kind, owner_name
    if symbol.kind == "enum-variant":
        enum_name, _, _ = symbol.qualified_name.partition("::")
        return "enum", enum_name
    return "", ""


def _format_runtime_imports(items: list[ReflectionImport]) -> str:
    return _join_runtime_lines(f"{'pub ' if item.is_public else ''}{item.path}" for item in items)


def _join_runtime_lines(items) -> str:
    values = [item for item in items if item]
    return "\n".join(values)


def _usize_expr(value: int) -> s.Expression_IntegerLiteral:
    return s.Expression_IntegerLiteral(str(value), literal_type=Type("usize"))
