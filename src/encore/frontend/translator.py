from dataclasses import replace
from pathlib import Path
from typing import Optional

from ehir.builder import EHIR_Builder, EHIR_Module
from ehir.core.derectives import (
    Derective_enum,
    Derective_extern_fn,
    Derective_fn,
    Derective_struct,
    TraitMethod,
)
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, EnumVariant, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions.base import Assignable
from ehir.core.instructions import (
    BinOp,
    Instruction_add,
    Instruction_capenum,
    Instruction_capstruct,
    Instruction_div,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_load,
    Instruction_mod,
    Instruction_mul,
    Instruction_put,
    Instruction_salloc,
    Instruction_setfield,
    Instruction_sgetfieldptr,
    Instruction_store,
    Instruction_sub,
    Instruction_wraph,
    Instruction_wraps,
    MatchCase,
)
from ehir.core.primitives import Float, Float_t, Isize, Isize_t, Str, Str_t, Usize, Usize_t
from ehir.core.struct import Struct
from ehir.core.type import HeapSmartPointer, Pointer, SmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter, Variable

from encore.frontend.inference import TypeInferer
from encore.frontend.lexer import Lexer
from encore.frontend.parser import Parser
from encore.frontend.parser import statements as s
from encore.frontend.parser.statements import Block
from encore.frontend.types import (
    AnySmartPointer,
    array_size,
    is_array_type,
    is_mutable_type,
    is_raw_pointer_type,
    is_reference_like_type,
    is_tuple_type,
    make_mutable_type,
    make_tuple_type,
    tuple_arity,
    unwrap_for_storage,
)

MatchArmLike = s.Statement_MatchArm | s.Expression_MatchArm
MatchBodyArmLike = s.Statement_MatchArm | s.Expression_MatchArm
MatchLike = s.Statement_Match | s.Expression_Match
MatchBodyLike = Block | s.Statement_Expression
MatchPatternLike = (
    s.Expression_Path
    | s.Expression_BooleanLiteral
    | s.Expression_IntegerLiteral
    | s.Expression_FloatLiteral
    | s.Expression_StringLiteral
    | None
)

BINOP_MAPPING: dict[str, type[BinOp]] = {
    "+": Instruction_add,
    "-": Instruction_sub,
    "*": Instruction_mul,
    "/": Instruction_div,
    "%": Instruction_mod,
}

COMPOUND_ASSIGNMENT_TO_BINOP: dict[str, str] = {
    "+=": "+",
    "-=": "-",
    "*=": "*",
    "/=": "/",
    "%=": "%",
    "&=": "&",
    "|=": "|",
    "^=": "^",
    "<<=": "<<",
    ">>=": ">>",
}

OPERATOR_MAPPING: dict[str, str] = {
    "==": "ieq",
    "!=": "neq",
    "<": "les",
    "<=": "leq",
    ">": "grt",
    ">=": "geq",
}

OPERATOR_TRAIT_MAPPING: dict[str, str] = {
    "==": "Eq",
    "!=": "Ne",
    "<": "Lt",
    "<=": "Le",
    ">": "Gt",
    ">=": "Ge",
    "+": "Add",
    "-": "Sub",
    "*": "Mul",
    "/": "Div",
    "%": "Rem",
    "&": "BitAnd",
    "|": "BitOr",
    "^": "BitXor",
    "<<": "Shl",
    ">>": "Shr",
}

COMPARISON_OPERATOR_SET = {"==", "!=", "<", "<=", ">", ">="}

BUILTIN_TYPE_NAMES = {
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
    "void",
}


class Translator:
    _funcs: dict[str, Derective_fn | Derective_extern_fn]
    _source_signatures: dict[str, s.FunctionSignature]
    _enums: dict[str, Derective_enum]
    _structs: dict[str, Derective_struct]
    _traits: dict[str, s.Statement_Trait]
    _impl_traits: dict[str, list[str]]
    _builder: EHIR_Builder
    _module: EHIR_Module
    _enum_payload_structs: dict[str, list[s.CLikeStructureDefinition]]
    _emitted_structs: set[str]
    _any_pointer_variants: dict[str, dict[type[Type], str]]
    _current_module_id: Path
    _module_namespace_cache: dict[Path, str]
    _function_aliases: dict[str, str]
    _type_aliases: dict[str, str]
    _trait_aliases: dict[str, str]
    _active_generic_bounds: dict[str, list[Type]]
    _with_cleanup_stack: list[str]

    class _PreparedMatch:
        def __init__(
            self,
            *,
            scrutinee: Assignable,
            base_var_vals: dict[str, Variable],
            base_var_ptrs: dict[str, Variable],
            end_block,
            default_block,
            wildcard_arm: MatchBodyArmLike | None,
            arm_blocks: dict[int, object],
            arm_payload_types: dict[int, Type | None],
            arm_variant_indices: dict[int, int],
        ):
            self.scrutinee = scrutinee
            self.base_var_vals = base_var_vals
            self.base_var_ptrs = base_var_ptrs
            self.end_block = end_block
            self.default_block = default_block
            self.wildcard_arm = wildcard_arm
            self.arm_blocks = arm_blocks
            self.arm_payload_types = arm_payload_types
            self.arm_variant_indices = arm_variant_indices

    class _LoopContext:
        def __init__(self, *, label: str | None, break_target: str, continue_target: str):
            self.label = label
            self.break_target = break_target
            self.continue_target = continue_target

    def __init__(self):
        self._lexer = Lexer()
        self._parser = Parser()
        self._reset_state()

    def _reset_state(self):
        self._module = EHIR_Module(id=Path(), ast=[])
        self._builder = EHIR_Builder(self._module)
        self._current_function = None
        self._current_variable_name = "tmp"
        self._current_variable_idx = 0
        self._unique_variable_idx = 0
        self._variables: dict[str, dict[str, Variable]] = {}
        self._while_counter = 0
        self._if_counter = 0
        self._loop_stack: list[Translator._LoopContext] = []
        self._with_cleanup_stack = []
        self._terminated_blocks: set[str] = set()
        self._var_vals: dict[str, Variable] = {}
        self._var_ptrs: dict[str, Variable] = {}
        self._source_var_types: dict[str, Type] = {}
        self._assignment_targets: dict[str, str] = {}
        self._funcs = {}
        self._source_signatures = {}
        self._enums = {}
        self._structs = {}
        self._extern_fns = {}
        self._traits = {}
        self._impl_traits = {}
        self._unsafe_depth = 0
        self._enum_payload_structs = {}
        self._emitted_structs = set()
        self._any_pointer_variants = {}
        self._current_module_id = Path()
        self._module_namespace_cache = {}
        self._function_aliases = {}
        self._type_aliases = {}
        self._trait_aliases = {}
        self._active_generic_bounds = {}

    def run(self, program: str) -> EHIR_Module:
        self._reset_state()
        tokens = self._lexer.parse(list(program))
        ast = self._parser.parse(tokens)
        TypeInferer().infer(ast)
        return self.translate_ast(ast)

    def translate_ast(
        self,
        ast: list[s.Statement],
        *,
        module_id: Path | None = None,
        imported_declarations: list[object] | None = None,
    ) -> EHIR_Module:
        self._current_module_id = module_id or Path()
        imported_declarations = imported_declarations or []
        declaration_entries = [*self._normalize_declaration_entries(imported_declarations)] + [
            (self._current_module_id, statement, None, None) for statement in ast if isinstance(statement, s.Statement_TopLevel)
        ]
        self.preload_declarations(declaration_entries)
        for statement in ast:
            self._translate_statement(statement)
        # print(self._module)
        # import time

        # time.sleep(0.5)
        return self._module

    def preload_declarations(self, declarations: list[tuple[Path, s.Statement_TopLevel, str | None, str | None]]):
        for module_id, statement, local_name, source_name in declarations:
            self._register_declaration_alias(module_id, statement, local_name=local_name, source_name=source_name)

        for module_id, statement, _, source_name in declarations:
            if isinstance(statement, s.Statement_StructureDefinition):
                signature = statement.signature
                if source_name is not None:
                    signature = replace(signature, name=source_name)
                definition = self._normalize_struct_definition(signature)
                definition = replace(definition, name=self._qualify_type_name(module_id, definition.name))
                self._structs[definition.name] = definition
            elif isinstance(statement, s.Statement_FunctionDefinition):
                signature = statement.signature
                if source_name is not None:
                    signature = replace(signature, name=source_name)
                signature = self._normalize_signature(signature)
                if signature.type is None:
                    continue
                internal_name = self._qualify_function_name(module_id, signature.name)
                internal_signature = replace(signature, name=internal_name)
                self._register_source_signature(internal_signature)
                if self._signature_has_any_pointer(signature):
                    for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                        concrete_sig = self._specialize_signature_any_pointer(internal_signature, pointer_cls)
                        concrete_name = f"{internal_name}{suffix}"
                        self._register_source_signature(replace(concrete_sig, name=concrete_name))
                        self._any_pointer_variants.setdefault(internal_name, {})[pointer_cls] = concrete_name
                        self._funcs[concrete_name] = Derective_fn(
                            name=concrete_name,
                            generics=[self._translate_type(g) for g in concrete_sig.generics],
                            params=self._lower_params(concrete_sig.params),
                            body=[],
                            ret_type=self._translate_type(concrete_sig.type),
                        )
                else:
                    self._funcs[internal_name] = Derective_fn(
                        name=internal_name,
                        generics=[self._translate_type(g) for g in internal_signature.generics],
                        params=self._lower_params(internal_signature.params),
                        body=[],
                        ret_type=self._translate_type(internal_signature.type),
                    )
            elif isinstance(statement, s.Statement_EnumDefinition):
                enum_statement = statement
                if source_name is not None:
                    enum_statement = replace(enum_statement, name=source_name)
                directive = self._build_enum_directive(enum_statement, module_id=module_id)
                self._enums[directive.name] = directive
            elif isinstance(statement, s.FunctionSignature):
                signature = statement if source_name is None else replace(statement, name=source_name)
                self._extern_fns[signature.name] = signature
                self._register_source_signature(signature)
                self._funcs[signature.name] = Derective_extern_fn(
                    name=signature.name,
                    params=self._lower_params(signature.params),
                    ret_type=self._translate_type(signature.type),
                )
            elif isinstance(statement, s.Statement_Trait):
                trait_statement = statement
                if source_name is not None:
                    trait_statement = replace(trait_statement, name=source_name)
                internal_trait_name = self._qualify_trait_name(module_id, trait_statement.name)
                internal_trait = replace(
                    trait_statement,
                    name=internal_trait_name,
                    bases=[self._translate_trait_type(base) for base in trait_statement.bases],
                )
                self._traits[internal_trait_name] = internal_trait
                for method in internal_trait.body:
                    method_signature = self._normalize_signature(
                        replace(method, name=f"{internal_trait_name}::{method.name}")
                    )
                    self._register_source_signature(method_signature)
            elif isinstance(statement, s.Statement_Impl):
                struct_type = self._translate_type(statement.struct)
                if statement.trait_name is not None:
                    resolved_trait_name = self._trait_aliases.get(statement.trait_name, statement.trait_name)
                    self._impl_traits.setdefault(struct_type.name, []).append(resolved_trait_name)
                    continue

                for method in statement.body:
                    if method.type is None:
                        continue

                    impl_generic_names = {generic.name for generic in statement.generics}
                    merged_method_generics = [*statement.generics]
                    for generic in method.generics:
                        if generic.name in impl_generic_names:
                            continue
                        merged_method_generics.append(generic)
                        impl_generic_names.add(generic.name)

                    normalized_signature = self._normalize_signature(
                        replace(
                            method.signature,
                            name=f"{struct_type.name}::{method.name}",
                            generics=merged_method_generics,
                        ),
                        self_type=statement.struct,
                    )
                    self._register_source_signature(normalized_signature)
                    if self._signature_has_any_pointer(normalized_signature):
                        for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                            concrete_sig = self._specialize_signature_any_pointer(normalized_signature, pointer_cls)
                            concrete_name = f"{normalized_signature.name}{suffix}"
                            self._register_source_signature(replace(concrete_sig, name=concrete_name))
                            self._any_pointer_variants.setdefault(normalized_signature.name, {})[pointer_cls] = (
                                concrete_name
                            )
                            self._funcs[concrete_name] = Derective_fn(
                                name=concrete_name,
                                generics=[self._translate_type(g) for g in concrete_sig.generics],
                                params=self._lower_params(concrete_sig.params),
                                body=[],
                                ret_type=self._translate_type(concrete_sig.type),
                            )
                    else:
                        self._funcs[normalized_signature.name] = Derective_fn(
                            name=normalized_signature.name,
                            generics=[self._translate_type(g) for g in normalized_signature.generics],
                            params=self._lower_params(normalized_signature.params),
                            body=[],
                            ret_type=self._translate_type(normalized_signature.type),
                        )

    def _translate_statement(self, statement: s.Statement) -> Derective | None:
        if isinstance(statement, s.Statement_FunctionDefinition):
            return self._translate_function_definition(statement)
        elif isinstance(statement, s.FunctionSignature):
            return self._translate_extern_function_definition(statement)
        elif isinstance(statement, s.Statement_StructureDefinition):
            return self._translate_structure_definition(statement)
        elif isinstance(statement, s.Statement_EnumDefinition):
            return self._translate_enum_definition(statement)
        elif isinstance(statement, s.Statement_Trait):
            return self._translate_trait_definition(statement)
        elif isinstance(statement, s.Statement_Impl):
            return self._translate_impl_definition(statement)
        elif isinstance(statement, s.Statement_Import):
            return self._translate_import(statement)
        raise NotImplementedError(f"Translation for statement type {type(statement)} is not implemented.")

    def _normalize_signature(
        self, signature: s.FunctionSignature, self_type: Type | None = None
    ) -> s.FunctionSignature:
        resolved_self_type = self._resolve_self_type(self_type)
        params = [
            replace(param, type=self._resolve_self_in_type(param.type, resolved_self_type))
            for param in signature.params
        ]
        ret_type = None if signature.type is None else self._resolve_self_in_type(signature.type, resolved_self_type)
        return replace(signature, params=params, type=ret_type)

    def _resolve_self_type(self, self_type: Type | None) -> Type | None:
        if self_type is None:
            return None
        return unwrap_for_storage(self_type)

    def _resolve_self_in_type(self, typ: Type, self_type: Type | None) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._resolve_self_in_type(unwrap_for_storage(typ), self_type))
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if is_raw_pointer_type(typ):
            return Pointer(self._resolve_self_in_type(typ.pointee, self_type))
        if typ.name == "Self" and not typ.generics and self_type is not None:
            return self_type
        return replace(typ, generics=[self._resolve_self_in_type(generic, self_type) for generic in typ.generics])

    def _lookup_trait_method_signature(
        self,
        trait_name: str,
        method_name: str,
        *,
        receiver_type: Type | None = None,
        seen: set[str] | None = None,
    ) -> s.FunctionSignature | None:
        trait = self._traits.get(trait_name)
        if trait is None:
            return None

        seen = seen or set()
        if trait_name in seen:
            return None
        seen.add(trait_name)

        for method in trait.body:
            if method.name == method_name:
                return self._normalize_signature(method, self_type=receiver_type)

        for base in trait.bases:
            signature = self._lookup_trait_method_signature(
                base.name, method_name, receiver_type=receiver_type, seen=seen
            )
            if signature is not None:
                return signature
        return None

    def _collect_generic_bounds(self, generics: list[Type]) -> dict[str, list[Type]]:
        bounds: dict[str, list[Type]] = {}
        for generic in generics:
            if isinstance(generic, s.GenericParam) and generic.bounds:
                bounds[generic.name] = list(generic.bounds)
        return bounds

    def _lookup_active_generic_bounds(self, typ: Type | None) -> list[Type]:
        if typ is None:
            return []
        typ = unwrap_for_storage(typ)
        if is_reference_like_type(typ):
            return self._lookup_active_generic_bounds(typ.pointee)
        if is_raw_pointer_type(typ):
            return self._lookup_active_generic_bounds(typ.pointee)
        return list(self._active_generic_bounds.get(typ.name, []))

    def _resolve_trait_method_call_name(
        self,
        trait_name: str,
        method_name: str,
        *,
        receiver_type: Type | None = None,
    ) -> str:
        if receiver_type is not None:
            receiver_type = unwrap_for_storage(receiver_type)
            receiver_type = receiver_type.pointee if is_reference_like_type(receiver_type) else receiver_type
            for bound in self._lookup_active_generic_bounds(receiver_type):
                resolved_trait_name = self._trait_aliases.get(
                    bound.name,
                    self._qualify_trait_name(self._current_module_id, bound.name),
                )
                if bound.name != trait_name and resolved_trait_name != trait_name:
                    continue
                signature = self._lookup_trait_method_signature(
                    resolved_trait_name,
                    method_name,
                    receiver_type=receiver_type,
                )
                if signature is not None:
                    return f"{resolved_trait_name}::{method_name}"

        if trait_name in OPERATOR_TRAIT_MAPPING.values():
            return f"{trait_name}::{method_name}"

        mapped = self._function_aliases.get(f"{trait_name}::{method_name}")
        if mapped is not None:
            return mapped

        qualified_trait_name = self._qualify_trait_name(self._current_module_id, trait_name)
        qualified_method_name = f"{qualified_trait_name}::{method_name}"
        if qualified_method_name in self._source_signatures:
            return qualified_method_name

        return f"{trait_name}::{method_name}"

    def _resolve_method_callable(
        self,
        receiver_type: Type,
        method_name: str,
    ) -> tuple[str, Derective_fn | Derective_extern_fn | None]:
        def base_type_name(name: str) -> str:
            bracket = name.find("[")
            return name if bracket < 0 else name[:bracket]

        def leaf_type_name(name: str) -> str:
            return base_type_name(name).rsplit("::", 1)[-1]

        def impl_trait_names(type_name: str) -> list[str]:
            out = list(self._impl_traits.get(type_name, []))
            leaf = leaf_type_name(type_name)
            for owner_name, trait_names in self._impl_traits.items():
                if owner_name == type_name:
                    continue
                if leaf_type_name(owner_name) == leaf:
                    for trait_name in trait_names:
                        if trait_name not in out:
                            out.append(trait_name)
            return out

        receiver_type = unwrap_for_storage(receiver_type)
        base_receiver_type = receiver_type.pointee if is_reference_like_type(receiver_type) else receiver_type
        inherent_name = f"{base_receiver_type.name}::{method_name}"
        inherent_callee = self._funcs.get(inherent_name)
        if inherent_callee is not None:
            return inherent_name, inherent_callee
        if inherent_name in self._any_pointer_variants:
            return inherent_name, None

        receiver_base = base_type_name(base_receiver_type.name)
        receiver_leaf = leaf_type_name(base_receiver_type.name)
        inherent_candidates = []
        for candidate_name in self._funcs:
            if not candidate_name.endswith(f"::{method_name}"):
                continue
            parts = candidate_name.rsplit("::", 2)
            if len(parts) < 2:
                continue
            owner_name = base_type_name(parts[-2])
            if owner_name != receiver_base and leaf_type_name(owner_name) != receiver_leaf:
                continue
            inherent_candidates.append(candidate_name)
        if len(inherent_candidates) == 1:
            matched_name = inherent_candidates[0]
            matched_callee = self._funcs.get(matched_name)
            if matched_callee is not None:
                return matched_name, matched_callee
            if matched_name in self._any_pointer_variants:
                return matched_name, None

        for trait_name in impl_trait_names(base_receiver_type.name):
            signature = self._lookup_trait_method_signature(
                trait_name,
                method_name,
                receiver_type=base_receiver_type,
            )
            if signature is None or signature.type is None:
                continue
            return (
                f"{trait_name}::{method_name}",
                Derective_fn(
                    name=f"{trait_name}::{method_name}",
                    generics=[self._translate_type(generic) for generic in signature.generics],
                    params=[Parameter(name=param.name, type=self._translate_type(param.type)) for param in signature.params],
                    body=[],
                    ret_type=self._translate_type(signature.type),
                ),
            )

        for bound in self._lookup_active_generic_bounds(base_receiver_type):
            resolved_trait_name = self._trait_aliases.get(
                bound.name,
                self._qualify_trait_name(self._current_module_id, bound.name),
            )
            signature = self._lookup_trait_method_signature(
                resolved_trait_name,
                method_name,
                receiver_type=base_receiver_type,
            )
            if signature is None or signature.type is None:
                continue

            return (
                f"{resolved_trait_name}::{method_name}",
                Derective_fn(
                    name=f"{resolved_trait_name}::{method_name}",
                    generics=[self._translate_type(generic) for generic in signature.generics],
                    params=[
                        Parameter(name=param.name, type=self._translate_type(param.type)) for param in signature.params
                    ],
                    body=[],
                    ret_type=self._translate_type(signature.type),
                ),
            )

        similar = [name for name in self._funcs if name.endswith(f"::{method_name}")]
        receiver_leaf = leaf_type_name(base_receiver_type.name)
        owner_filtered: list[str] = []
        for candidate_name in similar:
            parts = candidate_name.rsplit("::", 2)
            if len(parts) < 2:
                continue
            owner_name = parts[-2]
            if leaf_type_name(owner_name) == receiver_leaf:
                owner_filtered.append(candidate_name)
        if owner_filtered:
            preferred = [name for name in owner_filtered if "::Iterator::" not in name]
            matched_name = preferred[0] if preferred else owner_filtered[0]
            matched_callee = self._funcs.get(matched_name)
            if matched_callee is not None:
                return matched_name, matched_callee
            if matched_name in self._any_pointer_variants:
                return matched_name, None
        if len(similar) == 1:
            matched_name = similar[0]
            matched_callee = self._funcs.get(matched_name)
            if matched_callee is not None:
                return matched_name, matched_callee
            if matched_name in self._any_pointer_variants:
                return matched_name, None
        raise TypeError(
            f"Method '{method_name}' is not defined for type '{base_receiver_type.name}'. "
            f"inherent_name='{inherent_name}', suffix_matches={len(inherent_candidates)}, method_suffix_matches={len(similar)}"
        )

    def _callable_module_prefix(self, fn_name: str) -> str | None:
        parts = fn_name.split("::")
        if len(parts) < 3:
            return None
        return "::".join(parts[:-2])

    def _qualify_type_for_callable(
        self,
        typ: Type,
        *,
        fn_name: str,
        generic_names: set[str] | None = None,
    ) -> Type:
        generic_names = generic_names or set()
        module_prefix = self._callable_module_prefix(fn_name)
        if module_prefix is None:
            return typ

        def qualify(inner: Type) -> Type:
            if is_mutable_type(inner):
                return make_mutable_type(qualify(unwrap_for_storage(inner)))
            if isinstance(inner, AnySmartPointer):
                return AnySmartPointer(qualify(inner.pointee))
            if isinstance(inner, HeapSmartPointer):
                return HeapSmartPointer(qualify(inner.pointee))
            if isinstance(inner, StackSmartPointer):
                return StackSmartPointer(qualify(inner.pointee))
            if is_raw_pointer_type(inner):
                return Pointer(qualify(inner.pointee))
            if isinstance(inner, (Usize_t, Isize_t, Float_t, Str_t)):
                return inner

            name = inner.name
            generics = [qualify(generic) for generic in inner.generics]
            if (
                "::" not in name
                and name not in generic_names
                and name not in BUILTIN_TYPE_NAMES
                and not name.startswith("__tuple_")
            ):
                name = f"{module_prefix}::{name}"
            return Type(name, generics)

        return qualify(typ)

    def _normalize_struct_definition(self, definition: s.StructureSignature) -> s.CLikeStructureDefinition:
        if isinstance(definition, s.CLikeStructureDefinition):
            return definition
        if isinstance(definition, s.TupleStructureDefinition):
            return definition._to_clike()
        if isinstance(definition, s.UnitStructureDefinition):
            return definition._to_tuple()._to_clike()
        raise NotImplementedError(f"Unsupported structure definition: {type(definition)}")

    def _translate_extern_function_definition(self, statement):
        self._extern_fns[statement.name] = statement
        self._builder.build_extern_fn(
            name=statement.name,
            params=self._lower_params(statement.params),
            ret_type=self._translate_type(statement.type),
        )
        return self._module.ast[-1]

    def _translate_import(self, statement: s.Statement_Import):
        self._translate_import_pair(prefix=[], pair=statement.pair, is_public=statement.is_public)

    def _translate_import_pair(self, prefix: list[str], pair: s.Statement_Import.ImportPair, is_public: bool):
        match len(pair.dst):
            case 0:
                match pair.kind:
                    case s.Statement_Import.ImportKind.PACKAGE:
                        (self._builder.build_cimp if is_public else self._builder.build_imp)(
                            prefix=prefix + [pair.src], symbol="*", alias=pair.alias
                        )
                    case s.Statement_Import.ImportKind.SYMBOL:
                        (self._builder.build_cimp if is_public else self._builder.build_imp)(
                            prefix=prefix, symbol=pair.src, alias=pair.alias
                        )
                    case s.Statement_Import.ImportKind.GLOB:
                        (self._builder.build_cimp if is_public else self._builder.build_imp)(
                            prefix=prefix, symbol="*", alias=pair.alias
                        )
            case _:
                for dst in pair.dst:
                    self._translate_import_pair(prefix=prefix + [pair.src], pair=dst, is_public=is_public)

    def _translate_structure_definition(self, statement: s.Statement_StructureDefinition):
        definition = self._normalize_struct_definition(statement.signature)
        definition = replace(definition, name=self._qualify_type_name(self._current_module_id, definition.name))
        self._structs[definition.name] = definition
        self._emit_struct_definition(definition)

    def _emit_struct_definition(self, definition: s.CLikeStructureDefinition):
        if definition.name in self._emitted_structs:
            return
        self._builder.build_struct(
            name=definition.name,
            generics=[self._translate_type(g) for g in definition.generics],
            params=[Parameter(param.name, self._translate_type(param.type)) for param in definition.fields],
        )
        self._emitted_structs.add(definition.name)

    def _ensure_runtime_tuple_struct(self, arity: int):
        name = f"__tuple_{arity}"
        if name in self._structs:
            return
        generics = [Type(f"T{idx}") for idx in range(arity)]
        fields = [Parameter(str(idx), Type(f"T{idx}")) for idx in range(arity)]
        definition = s.CLikeStructureDefinition(name=name, generics=generics, fields=fields)
        self._structs[name] = definition
        self._emit_struct_definition(definition)

    def _ensure_runtime_array_struct(self, size: int):
        name = f"__array_{size}"
        if name in self._structs:
            return
        generics = [Type("T")]
        fields = [Parameter(str(idx), Type("T")) for idx in range(size)]
        definition = s.CLikeStructureDefinition(name=name, generics=generics, fields=fields)
        self._structs[name] = definition
        self._emit_struct_definition(definition)

    def _build_enum_directive(
        self, statement: s.Statement_EnumDefinition, *, module_id: Path | None = None
    ) -> Derective_enum:
        module_id = module_id or self._current_module_id
        enum_name = self._qualify_type_name(module_id, statement.name)
        variants: list[EnumVariant] = []
        for variant in statement.body:
            if isinstance(variant, s.UnitStructureDefinition):
                variants.append(UnitLikeVariant(name=variant.name))
                continue

            if isinstance(variant, s.TupleStructureDefinition):
                payload_types = [self._translate_type(field) for field in variant.fields]
                variants.append(TupleLikeVariant(name=variant.name, types=payload_types))
                continue

            if isinstance(variant, s.CLikeStructureDefinition):
                payload_struct = self._ensure_enum_payload_struct(statement, variant, module_id=module_id)
                payload_type = self._translate_type(Type(payload_struct.name, list(statement.generics)))
                variants.append(TupleLikeVariant(name=variant.name, types=[payload_type]))
                continue

        return Derective_enum(
            name=enum_name,
            generics=[self._translate_type(generic) for generic in statement.generics],
            variants=variants,
        )

    def _ensure_enum_payload_struct(
        self,
        enum_statement: s.Statement_EnumDefinition,
        variant: s.Statement_StructureDefinition,
        *,
        module_id: Path | None = None,
    ) -> s.CLikeStructureDefinition:
        module_id = module_id or self._current_module_id
        struct_name = f"{self._qualify_type_name(module_id, enum_statement.name)}_{variant.name}_Payload"
        existing = self._structs.get(struct_name)
        if isinstance(existing, s.CLikeStructureDefinition):
            payload = existing
        else:
            if isinstance(variant, s.TupleStructureDefinition):
                fields = [Parameter(f"_{idx}", field) for idx, field in enumerate(variant.fields)]
            elif isinstance(variant, s.CLikeStructureDefinition):
                fields = list(variant.fields)
            else:
                raise NotImplementedError(f"Unsupported enum payload variant shape: {type(variant)}")

            payload = s.CLikeStructureDefinition(
                name=struct_name, generics=list(enum_statement.generics), fields=fields
            )
            self._structs[struct_name] = payload

        enum_key = self._qualify_type_name(module_id, enum_statement.name)
        payloads = self._enum_payload_structs.setdefault(enum_key, [])
        if all(definition.name != payload.name for definition in payloads):
            payloads.append(payload)
        return payload

    def _translate_enum_definition(self, statement: s.Statement_EnumDefinition):
        enum_key = self._qualify_type_name(self._current_module_id, statement.name)
        for payload_struct in self._enum_payload_structs.get(enum_key, []):
            self._emit_struct_definition(payload_struct)
        derective = self._build_enum_directive(statement)
        self._module.ast.append(derective)
        self._enums[derective.name] = derective
        return derective

    def _translate_trait_definition(self, statement: s.Statement_Trait):
        derective = self._builder.build_trait(
            name=self._qualify_trait_name(self._current_module_id, statement.name),
            generics=[self._translate_type(g) for g in statement.generics],
            bounds={"Self": [self._translate_trait_type(base).name for base in statement.bases]} if statement.bases else {},
            methods=[
                TraitMethod(
                    name=method.name,
                    generics=[self._translate_type(g) for g in method.generics],
                    params=[
                        Parameter(name=param.name, type=self._translate_type(param.type)) for param in method.params
                    ],
                    ret_type=self._translate_type(method.type),
                )
                for method in statement.body
            ],
        )
        self._traits[derective.name] = replace(
            statement,
            name=derective.name,
            bases=[self._translate_trait_type(base) for base in statement.bases],
        )
        return derective

    def _translate_impl_definition(self, statement: s.Statement_Impl):
        if statement.trait_name is None:
            struct_type = self._translate_type(statement.struct)
            for method in statement.body:
                impl_generic_names = {generic.name for generic in statement.generics}
                merged_method_generics = [*statement.generics]
                for generic in method.generics:
                    if generic.name in impl_generic_names:
                        continue
                    merged_method_generics.append(generic)
                    impl_generic_names.add(generic.name)

                namespaced_method = replace(
                    method,
                    signature=self._normalize_signature(
                        replace(
                            method.signature,
                            name=f"{struct_type.name}::{method.name}",
                            generics=merged_method_generics,
                        ),
                        self_type=statement.struct,
                    ),
                )
                if self._signature_has_any_pointer(namespaced_method.signature):
                    for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                        concrete_sig = self._specialize_signature_any_pointer(namespaced_method.signature, pointer_cls)
                        concrete_name = f"{namespaced_method.signature.name}{suffix}"
                        concrete_stmt = replace(
                            namespaced_method,
                            signature=replace(concrete_sig, name=concrete_name),
                        )
                        fn = self._translate_nested_function_definition(concrete_stmt)
                        self._module.ast.append(fn)
                        self._funcs[fn.name] = fn
                        self._any_pointer_variants.setdefault(namespaced_method.signature.name, {})[pointer_cls] = (
                            fn.name
                        )
                else:
                    fn = self._translate_nested_function_definition(namespaced_method)
                    self._module.ast.append(fn)
                    self._funcs[fn.name] = fn
            return None

        methods = [
            self._translate_nested_function_definition(
                replace(
                    method,
                    signature=self._normalize_signature(method.signature, self_type=statement.struct),
                )
            )
            for method in statement.body
        ]
        return self._builder.build_impl(
            trait_name=self._trait_aliases.get(statement.trait_name, statement.trait_name),
            trait_args=[self._translate_type(arg) for arg in statement.trait_args],
            for_type=self._translate_type(statement.struct),
            generics=[self._translate_type(generic) for generic in statement.generics],
            methods=methods,
        )

    def _translate_function_definition(self, statement: s.Statement_FunctionDefinition):
        normalized_sig = self._normalize_signature(statement.signature)
        normalized_sig = replace(
            normalized_sig,
            name=self._qualify_function_name(self._current_module_id, normalized_sig.name),
        )
        statement = replace(statement, signature=normalized_sig)
        if self._signature_has_any_pointer(statement.signature):
            emitted = None
            for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                concrete_sig = self._specialize_signature_any_pointer(statement.signature, pointer_cls)
                concrete_stmt = replace(
                    statement, signature=replace(concrete_sig, name=f"{statement.signature.name}{suffix}")
                )
                fn = self._translate_nested_function_definition(concrete_stmt)
                self._module.ast.append(fn)
                self._funcs[fn.name] = fn
                emitted = fn
            return emitted

        fn = self._translate_nested_function_definition(statement)
        self._module.ast.append(fn)
        self._funcs[fn.name] = fn
        return fn

    def _translate_nested_function_definition(self, statement: s.Statement_FunctionDefinition) -> Derective_fn:
        statement = replace(statement, signature=self._normalize_signature(statement.signature))
        assert statement.signature.type is not None
        fn = Derective_fn(
            name=statement.signature.name,
            generics=[self._translate_type(g) for g in statement.signature.generics],
            params=self._lower_params(statement.signature.params),
            body=[],
            ret_type=self._translate_type(statement.signature.type),
        )
        self._translate_function_body(
            fn,
            statement.body,
            source_params=statement.signature.params,
            source_generics=statement.signature.generics,
        )
        return fn

    def _translate_function_body(
        self,
        fn: Derective_fn,
        body: Block,
        *,
        source_params: list[s.Parameter] | None = None,
        source_generics: list[Type] | None = None,
    ):
        prev_current_function = getattr(self._builder, "current_function", None)
        prev_current_block = getattr(self._builder, "current_block", None)
        prev_builder_variables = getattr(self._builder, "variables", {})
        prev_var_vals = self._var_vals
        prev_var_ptrs = self._var_ptrs
        prev_source_var_types = self._source_var_types
        prev_assignment_targets = self._assignment_targets
        prev_terminated_blocks = self._terminated_blocks
        prev_loop_stack = self._loop_stack
        prev_with_cleanup_stack = self._with_cleanup_stack
        prev_generic_bounds = self._active_generic_bounds

        self._builder.current_function = fn
        self._builder.variables = {param.name: param for param in fn.params}
        self._var_vals = {}
        self._var_ptrs = {}
        self._source_var_types = {}
        self._assignment_targets = {}
        self._terminated_blocks = set()
        self._loop_stack = []
        self._with_cleanup_stack = []
        self._active_generic_bounds = self._collect_generic_bounds(source_generics or [])
        source_params = source_params or []
        mutable_params = {param.name for param in source_params if is_mutable_type(param.type)}
        entry_block = self._builder.append_block("entry")
        self._builder.position_at_end(entry_block)

        source_param_types = {param.name: param.type for param in source_params}
        for param in fn.params:
            self._remember_source_type(param, source_param_types.get(param.name, param.type))
            if param.name in mutable_params:
                self._var_ptrs[param.name] = Variable(param.name, param.type)
                continue
            self._var_vals[param.name] = Variable(param.name, param.type)

        self._translate_block(body)

        if prev_current_function is not None:
            self._builder.current_function = prev_current_function
        if prev_current_block is not None:
            self._builder.current_block = prev_current_block
        self._builder.variables = prev_builder_variables
        self._var_vals = prev_var_vals
        self._var_ptrs = prev_var_ptrs
        self._source_var_types = prev_source_var_types
        self._assignment_targets = prev_assignment_targets
        self._terminated_blocks = prev_terminated_blocks
        self._loop_stack = prev_loop_stack
        self._with_cleanup_stack = prev_with_cleanup_stack
        self._active_generic_bounds = prev_generic_bounds

    def _register_source_signature(self, signature: s.FunctionSignature):
        self._source_signatures[signature.name] = signature

    def _normalize_declaration_entries(
        self, declarations: list[object]
    ) -> list[tuple[Path, s.Statement_TopLevel, str | None, str | None]]:
        normalized: list[tuple[Path, s.Statement_TopLevel, str | None, str | None]] = []
        for declaration in declarations:
            module_id = getattr(declaration, "module_id", None)
            statement = getattr(declaration, "statement", None)
            if module_id is None or statement is None:
                raise TypeError(f"Unsupported imported declaration payload: {declaration!r}")
            local_name = getattr(declaration, "local_name", None)
            source_name = getattr(declaration, "source_name", None)
            normalized.append((module_id, statement, local_name, source_name))
        return normalized

    def _register_declaration_alias(
        self,
        module_id: Path,
        statement: s.Statement_TopLevel,
        *,
        local_name: str | None = None,
        source_name: str | None = None,
    ):
        source_name = source_name or local_name
        if isinstance(statement, s.Statement_StructureDefinition):
            local = local_name or statement.signature.name
            source = source_name or statement.signature.name
            self._type_aliases[local] = self._qualify_type_name(module_id, source)
            return
        if isinstance(statement, s.Statement_EnumDefinition):
            local = local_name or statement.name
            source = source_name or statement.name
            self._type_aliases[local] = self._qualify_type_name(module_id, source)
            return
        if isinstance(statement, s.Statement_Trait):
            local = local_name or statement.name
            source = source_name or statement.name
            qualified_trait_name = self._qualify_trait_name(module_id, source)
            self._trait_aliases[local] = qualified_trait_name
            for method in statement.body:
                self._function_aliases[f"{local}::{method.name}"] = f"{qualified_trait_name}::{method.name}"
            return
        if isinstance(statement, s.FunctionSignature):
            local = local_name or statement.name
            source = source_name or statement.name
            self._function_aliases[local] = source
            return
        if isinstance(statement, s.Statement_FunctionDefinition):
            local = local_name or statement.signature.name
            source = source_name or statement.signature.name
            self._function_aliases[local] = self._qualify_function_name(module_id, source)
            return
        if isinstance(statement, s.Statement_Impl) and statement.trait_name is None:
            owner_source = source_name or statement.struct.name
            owner_name = self._type_aliases.get(statement.struct.name, self._qualify_type_name(module_id, owner_source))
            for method in statement.body:
                self._function_aliases[f"{statement.struct.name}::{method.name}"] = f"{owner_name}::{method.name}"

    def _module_namespace(self, module_id: Path) -> str:
        if not module_id:
            return ""
        module_id = module_id.resolve()
        cached = self._module_namespace_cache.get(module_id)
        if cached is not None:
            return cached

        project_root = module_id.parent
        for parent in [module_id.parent, *module_id.parents]:
            if (parent / "encore.toml").exists():
                project_root = parent
                break

        rel_module = module_id.relative_to(project_root).with_suffix("")
        namespace = "::".join([project_root.name, *rel_module.parts])
        self._module_namespace_cache[module_id] = namespace
        return namespace

    def _qualify_type_name(self, module_id: Path, name: str) -> str:
        namespace = self._module_namespace(module_id)
        return f"{namespace}::{name}" if namespace else name

    def _qualify_trait_name(self, module_id: Path, name: str) -> str:
        namespace = self._module_namespace(module_id)
        return f"{namespace}::{name}" if namespace else name

    def _qualify_function_name(self, module_id: Path, name: str) -> str:
        if name == "main":
            return name
        namespace = self._module_namespace(module_id)
        return f"{namespace}::{name}" if namespace else name

    def _translate_trait_type(self, typ: Type) -> Type:
        if typ.name in self._trait_aliases:
            return replace(typ, name=self._trait_aliases[typ.name], generics=[self._translate_type(g) for g in typ.generics])
        return replace(typ, generics=[self._translate_type(g) for g in typ.generics])

    def _lower_param_type(self, typ: Type) -> Type:
        if is_mutable_type(typ):
            return Pointer(self._translate_type(unwrap_for_storage(typ)))
        return self._translate_type(typ)

    def _lower_params(self, params: list[s.Parameter]) -> list[Parameter]:
        return [Parameter(name=param.name, type=self._lower_param_type(param.type)) for param in params]

    def _call_expected_type(self, param_type: Type | None) -> Type | None:
        if param_type is None:
            return None
        concrete_type = unwrap_for_storage(param_type)
        if self._contains_any_pointer(concrete_type):
            return None
        return self._translate_type(concrete_type)

    def _remember_source_type(self, var: Variable, source_type: Type | None) -> None:
        if source_type is None:
            return
        self._source_var_types[var.name] = source_type

    def _source_type_for_var(self, var: Variable) -> Type | None:
        return self._source_var_types.get(var.name)

    def _field_owner_type(self, var: Variable) -> Type | None:
        return self._source_type_for_var(var) or var.type

    def _is_source_reference_like(self, var: Variable) -> bool:
        source_type = self._source_type_for_var(var)
        return is_reference_like_type(source_type) or is_reference_like_type(var.type)

    def _fresh_temp_name(self, prefix: str) -> str:
        self._unique_variable_idx += 1
        return f"{prefix}_{self._unique_variable_idx}"

    def _translate_mutable_argument(
        self,
        expr: s.Statement_Expression,
        value: Variable,
        expected_type: Type,
    ) -> Variable:
        if isinstance(expr, s.Expression_Path) and len(expr.segments) == 1:
            ptr = self._var_ptrs.get(expr.name)
            if ptr is not None:
                return ptr
            return self._create_stack_slot(self._fresh_temp_name(f"{expr.name}_mut_arg"), value, expected_type)

        if isinstance(expr, s.Expression_StructField):
            dst_ptr = Variable(self._fresh_temp_name(expr.field), Pointer(expected_type))
            field = Variable(expr.field)
            lvalue_ptr = self._resolve_struct_lvalue_base_ptr(expr.name)
            if lvalue_ptr is not None:
                self._builder._add(Instruction_getfieldptr(var_out=dst_ptr, src=lvalue_ptr, field=field))
                return dst_ptr

            src = self._resolve_struct_field_chain(expr.name)
            if self._is_source_reference_like(src):
                self._builder._add(Instruction_sgetfieldptr(var_out=dst_ptr, src=src, field=field))
            else:
                self._builder._add(Instruction_getfieldptr(var_out=dst_ptr, src=src, field=field))
            return dst_ptr

        return self._create_stack_slot(self._fresh_temp_name("mut_arg"), value, expected_type)

    def _materialize_call_args(
        self,
        arg_exprs: list[s.Statement_Expression],
        arg_values: list[Assignable],
        source_params: list[s.Parameter] | None,
    ) -> list[Variable]:
        if source_params is None:
            return [arg.var_out for arg in arg_values]

        if len(arg_exprs) != len(source_params) or len(arg_values) != len(source_params):
            raise TypeError("Call argument lowering mismatch")

        args: list[Variable] = []
        for expr, value, param in zip(arg_exprs, arg_values, source_params):
            if not is_mutable_type(param.type):
                args.append(value.var_out)
                continue

            inner_type = unwrap_for_storage(param.type)
            expected_type = (
                value.var_out.type if self._contains_any_pointer(inner_type) else self._translate_type(inner_type)
            )
            if expected_type is None:
                raise TypeError(f"Unable to lower mutable argument for parameter '{param.name}'")
            args.append(self._translate_mutable_argument(expr, value.var_out, expected_type))
        return args

    def _translate_block(self, block: Block):
        for inner_statement in block.body:
            if self._is_current_block_terminated():
                break
            self._translate_inner_statement(inner_statement)

    def _translate_inner_statement(self, statement: s.Statement_InnerLevel):
        if isinstance(statement, s.Statement_Let):
            return self._translate_let(statement)

        elif isinstance(statement, s.Statement_Ret):
            return self._translate_ret(statement)

        elif isinstance(statement, s.Statement_Break):
            return self._translate_break(statement)

        elif isinstance(statement, s.Statement_Continue):
            return self._translate_continue(statement)

        elif isinstance(statement, s.Statement_While):
            return self._translate_while(statement)

        elif isinstance(statement, s.Statement_Loop):
            return self._translate_loop(statement)

        elif isinstance(statement, s.Statement_DoWhile):
            return self._translate_do_while(statement)

        elif isinstance(statement, s.Statement_For):
            return self._translate_for(statement)

        elif isinstance(statement, s.Statement_With):
            return self._translate_with(statement)

        elif isinstance(statement, s.Statement_If):
            return self._translate_if(statement)

        elif isinstance(statement, s.Statement_Match):
            return self._translate_match(statement)

        elif isinstance(statement, s.Statement_Unsafe):
            return self._translate_unsafe(statement)

        elif isinstance(statement, s.Statement_EHIR):
            return self._translate_ehir(statement)

        elif isinstance(statement, s.Statement_Assignment):
            return self._translate_assignment(statement)

        elif isinstance(statement, s.Statement_Expr):
            return self._translate_expression_statement(statement)

        raise NotImplementedError(f"Translation for inner statement type {type(statement)} is not implemented.")

    def _translate_let(self, statement: s.Statement_Let):
        assert statement.type is not None
        self._set_new_variable(statement.name)
        expected_type = self._translate_type(statement.type)

        slot_ptr: Variable
        if isinstance(statement.expr, s.Expression_BooleanLiteral):
            prim = Usize(1 if statement.expr.value else 0, size=1)
            slot_ptr = self._builder.build_cpos(prim=prim, name=statement.name).var_out
        elif isinstance(statement.expr, s.Expression_IntegerLiteral):
            literal_expected = statement.expr.literal_type or expected_type
            if literal_expected is not None:
                literal_expected = unwrap_for_storage(literal_expected)
                base_expected = (
                    literal_expected.pointee if is_reference_like_type(literal_expected) else literal_expected
                )
                if isinstance(base_expected, Float_t) or (
                    isinstance(base_expected, Type)
                    and base_expected.name.startswith("f")
                    and base_expected.name[1:].isdigit()
                ):
                    prim = Float(float(statement.expr.value), size=self._infer_float_size(literal_expected))
                else:
                    prim = self._build_integer_primitive(int(statement.expr.value), literal_expected)
            else:
                prim = self._build_integer_primitive(int(statement.expr.value), literal_expected)
            slot_ptr = self._builder.build_cpos(prim=prim, name=statement.name).var_out
        elif isinstance(statement.expr, s.Expression_FloatLiteral):
            prim = Float(
                float(statement.expr.value), size=self._infer_float_size(statement.expr.literal_type or expected_type)
            )
            slot_ptr = self._builder.build_cpos(prim=prim, name=statement.name).var_out
        elif isinstance(statement.expr, s.Expression_StringLiteral):
            slot_ptr = self._builder.build_cpos(prim=Str(statement.expr.value), name=statement.name).var_out
        else:
            val = self._translate_expression(statement.expr, expected_type=expected_type)
            if val.var_out.type is None:
                val.var_out.type = expected_type
            slot_ptr = self._create_stack_slot(statement.name, val.var_out, expected_type)

        self._remember_source_type(slot_ptr, statement.type)
        self._var_ptrs[statement.name] = slot_ptr

    def _translate_ret(self, statement: s.Statement_Ret):
        self._set_new_variable("ret")
        self._emit_active_with_cleanups()
        expected_type = None
        if hasattr(self._builder, "current_function"):
            expected_type = self._builder.current_function.ret_type
        expr = self._translate_expression(expr=statement.expr, expected_type=expected_type)
        self._builder.build_ret(expr.var_out)
        self._mark_current_block_terminated()

    def _translate_break(self, statement: s.Statement_Break):
        loop_ctx = self._resolve_loop_ctx(statement.label, keyword="break")
        self._emit_active_with_cleanups()
        self._builder.build_br(loop_ctx.break_target)
        self._mark_current_block_terminated()

    def _translate_continue(self, statement: s.Statement_Continue):
        loop_ctx = self._resolve_loop_ctx(statement.label, keyword="continue")
        self._emit_active_with_cleanups()
        self._builder.build_br(loop_ctx.continue_target)
        self._mark_current_block_terminated()

    def _emit_active_with_cleanups(self):
        for resource_name in reversed(self._with_cleanup_stack):
            if self._is_current_block_terminated():
                return
            cleanup_expr = s.Expression_MethodCall(
                receiver=s.Expression_Path([Type(resource_name)]),
                method="with_exit",
                generics=[],
                args=[],
            )
            self._translate_expression(cleanup_expr)

    def _translate_with(self, statement: s.Statement_With):
        self._set_new_variable(statement.name)
        enter_expr = s.Expression_MethodCall(
            receiver=statement.expr,
            method="with_enter",
            generics=[],
            args=[],
        )
        resource = self._translate_expression(enter_expr)
        if resource.var_out.type is None:
            raise TypeError("Unable to infer resource type in with-statement")
        slot_ptr = self._create_stack_slot(statement.name, resource.var_out, resource.var_out.type)

        prev_ptr = self._var_ptrs.get(statement.name)
        prev_val = self._var_vals.get(statement.name)
        prev_source_type = self._source_var_types.get(statement.name)

        self._var_ptrs[statement.name] = slot_ptr
        source_type = self._source_type_for_var(resource.var_out) or resource.var_out.type
        self._remember_source_type(slot_ptr, source_type)

        self._with_cleanup_stack.append(statement.name)
        self._translate_block(statement.body)
        self._with_cleanup_stack.pop()

        if not self._is_current_block_terminated():
            cleanup_expr = s.Expression_MethodCall(
                receiver=s.Expression_Path([Type(statement.name)]),
                method="with_exit",
                generics=[],
                args=[],
            )
            self._translate_expression(cleanup_expr)

        if prev_ptr is not None:
            self._var_ptrs[statement.name] = prev_ptr
        elif statement.name in self._var_ptrs:
            del self._var_ptrs[statement.name]

        if prev_val is not None:
            self._var_vals[statement.name] = prev_val
        elif statement.name in self._var_vals:
            del self._var_vals[statement.name]

        if prev_source_type is not None:
            self._source_var_types[statement.name] = prev_source_type
        elif statement.name in self._source_var_types:
            del self._source_var_types[statement.name]

    def _translate_assignment(self, statement: s.Statement_Assignment):
        assign_expr = self._assignment_expr(statement)

        if isinstance(statement.target, s.Expression_Path) and len(statement.target.segments) == 1:
            target_name = self._assignment_targets.get(statement.name, statement.name)
            self._set_new_variable(target_name)
            expected_type = self._resolve_variable_type(statement.name)
            slot_ptr = self._var_ptrs.get(statement.name)
            expr_name = self._advance_variable() if slot_ptr is not None else target_name
            val = self._translate_expression(
                assign_expr,
                name=expr_name,
                expected_type=expected_type,
            )
            if val.var_out.type is None:
                val.var_out.type = expected_type
            if slot_ptr is not None:
                self._builder._add(Instruction_store(var_src=val.var_out, var_dst=slot_ptr))
            else:
                self._var_vals[statement.name] = val.var_out
                self._remember_source_type(
                    val.var_out,
                    self._source_type_for_var(val.var_out) or expected_type or val.var_out.type,
                )
            return

        if isinstance(statement.target, s.Expression_StructField):
            self._set_new_variable(statement.target.field)
            lvalue_ptr = self._resolve_struct_lvalue_base_ptr(statement.target.name)
            dst_ptr = Variable(self._advance_variable())
            field = Variable(statement.target.field)
            if lvalue_ptr is not None:
                self._builder._add(Instruction_getfieldptr(var_out=dst_ptr, src=lvalue_ptr, field=field))
                expected_type = self._lookup_field_type(lvalue_ptr.type.pointee, statement.target.field)
            else:
                src = self._resolve_struct_field_chain(statement.target.name)
                expected_type = self._lookup_field_type(self._field_owner_type(src), statement.target.field)
                val = self._translate_expression(
                    assign_expr,
                    expected_type=expected_type,
                )
                if self._is_source_reference_like(src):
                    self._builder._add(Instruction_setfield(var=src, field=field, value=val.var_out))
                else:
                    self._builder._add(Instruction_getfieldptr(var_out=dst_ptr, src=src, field=field))
                    self._builder._add(Instruction_store(var_src=val.var_out, var_dst=dst_ptr))
                return

            val = self._translate_expression(
                assign_expr,
                expected_type=expected_type,
            )
            self._builder._add(Instruction_store(var_src=val.var_out, var_dst=dst_ptr))
            return

        raise NotImplementedError(f"Complex assignment target is not implemented: {statement.target}")

    def _assignment_expr(self, statement: s.Statement_Assignment) -> s.Statement_Expression:
        if statement.operator == "=":
            return statement.expr

        if statement.operator not in COMPOUND_ASSIGNMENT_TO_BINOP:
            raise NotImplementedError(f"Assignment operator '{statement.operator}' is not implemented.")

        return s.Expression_BinaryOperation(
            lhs=statement.target,
            operator=COMPOUND_ASSIGNMENT_TO_BINOP[statement.operator],
            rhs=statement.expr,
        )

    def _translate_expression_statement(self, statement: s.Statement_Expr):
        self._translate_expression(statement.expr)

    def _translate_unsafe(self, statement: s.Statement_Unsafe):
        self._unsafe_depth += 1
        try:
            self._translate_block(statement.body)
        finally:
            self._unsafe_depth -= 1

    def _translate_ehir(self, statement: s.Statement_EHIR):
        for instruction in statement.instructions:
            if isinstance(instruction, Assignable):
                if instruction.var_out.name in self._var_ptrs or instruction.var_out.name in self._var_vals:
                    raise TypeError(
                        f"EHIR output '{instruction.var_out.name}' conflicts with existing Encore local. "
                        "Use a distinct raw variable name."
                    )
                self._builder.variables[instruction.var_out.name] = instruction.var_out
            self._builder._add(instruction)

    def _translate_while(self, statement: s.Statement_While):
        while_id = self._while_counter
        self._while_counter += 1

        cond_block = self._builder.append_block(f"while_cond_{while_id}")
        body_block = self._builder.append_block(f"while_body_{while_id}")
        end_block = self._builder.append_block(f"while_end_{while_id}")

        self._builder.build_br(cond_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(cond_block)
        cond = self._translate_expression(statement.expr)
        self._builder.build_cbr(cond.var_out, body_block.name, end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(body_block)
        self._loop_stack.append(
            Translator._LoopContext(
                label=statement.label,
                break_target=end_block.name,
                continue_target=cond_block.name,
            )
        )
        self._translate_block(statement.body)
        self._loop_stack.pop()
        if not self._is_current_block_terminated():
            self._builder.build_br(cond_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)

    def _translate_do_while(self, statement: s.Statement_DoWhile):
        while_id = self._while_counter
        self._while_counter += 1

        body_block = self._builder.append_block(f"do_while_body_{while_id}")
        cond_block = self._builder.append_block(f"do_while_cond_{while_id}")
        end_block = self._builder.append_block(f"do_while_end_{while_id}")

        self._builder.build_br(body_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(body_block)
        self._loop_stack.append(
            Translator._LoopContext(
                label=None,
                break_target=end_block.name,
                continue_target=cond_block.name,
            )
        )
        self._translate_block(statement.body)
        self._loop_stack.pop()
        if not self._is_current_block_terminated():
            self._builder.build_br(cond_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(cond_block)
        cond = self._translate_expression(statement.expr)
        self._builder.build_cbr(cond.var_out, body_block.name, end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)

    def _translate_loop(self, statement: s.Statement_Loop):
        loop_id = self._while_counter
        self._while_counter += 1

        body_block = self._builder.append_block(f"loop_body_{loop_id}")
        latch_block = self._builder.append_block(f"loop_latch_{loop_id}")
        end_block = self._builder.append_block(f"loop_end_{loop_id}")

        self._builder.build_br(body_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(body_block)
        self._loop_stack.append(
            Translator._LoopContext(
                label=statement.label,
                break_target=end_block.name,
                continue_target=latch_block.name,
            )
        )
        self._translate_block(statement.body)
        self._loop_stack.pop()
        if not self._is_current_block_terminated():
            self._builder.build_br(latch_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(latch_block)
        self._builder.build_br(body_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)

    def _translate_for(self, statement: s.Statement_For):
        for_id = self._while_counter
        self._while_counter += 1
        iter_name = f"__for_iter_{for_id}"
        step_name = f"__for_step_{for_id}"
        iter_expr = s.Expression_MethodCall(receiver=statement.iterable, method="iter", generics=[], args=[])
        iter_value = self._translate_expression(iter_expr)
        if iter_value.var_out.type is None:
            raise TypeError("Unable to infer iterator type in `for` loop")
        iter_ptr = self._create_stack_slot(iter_name, iter_value.var_out, iter_value.var_out.type)
        self._var_ptrs[iter_name] = iter_ptr
        self._remember_source_type(iter_ptr, iter_value.var_out.type)

        body_block = self._builder.append_block(f"for_body_{for_id}")
        latch_block = self._builder.append_block(f"for_latch_{for_id}")
        end_block = self._builder.append_block(f"for_end_{for_id}")

        self._builder.build_br(body_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(body_block)
        self._loop_stack.append(
            Translator._LoopContext(
                label=None,
                break_target=end_block.name,
                continue_target=latch_block.name,
            )
        )

        iter_step_generics: list[Type] = []
        iter_base_type = unwrap_for_storage(iter_value.var_out.type)
        if is_reference_like_type(iter_base_type):
            iter_base_type = iter_base_type.pointee
        if iter_base_type.generics:
            iter_step_generics = [iter_base_type.generics[0]]

        next_expr = s.Expression_MethodCall(
            receiver=s.Expression_Path([Type(iter_name)]),
            method="next",
            generics=iter_step_generics,
            args=[],
        )
        step_value = self._translate_expression(next_expr)
        if step_value.var_out.type is None:
            if iter_step_generics:
                option_name = self._type_aliases.get("Option", "Option")
                step_value.var_out.type = make_tuple_type(
                    [iter_value.var_out.type, Type(option_name, [iter_step_generics[0]])]
                )
            else:
                raise TypeError("Unable to infer iterator step type in `for` loop")
        step_ptr = self._create_stack_slot(step_name, step_value.var_out, step_value.var_out.type)
        self._var_ptrs[step_name] = step_ptr
        self._remember_source_type(step_ptr, step_value.var_out.type)

        next_iter = self._translate_expression(s.Expression_StructField(step_name, "0"))
        self._builder._add(Instruction_store(var_src=next_iter.var_out, var_dst=iter_ptr))

        option_name = f"__for_opt_{for_id}"
        option_value = self._translate_expression(s.Expression_StructField(step_name, "1"))
        option_type = option_value.var_out.type
        if option_type is None and iter_step_generics:
            option_name = self._type_aliases.get("Option", "Option")
            option_type = Type(option_name, [iter_step_generics[0]])
            option_value.var_out.type = option_type
        if option_type is None:
            raise TypeError("Unable to infer iterator item option type in `for` loop")
        option_base = unwrap_for_storage(option_type)
        if is_reference_like_type(option_base):
            option_base = option_base.pointee
        if option_base.name.rsplit("::", 1)[-1] != "Option" or len(option_base.generics) != 1:
            raise TypeError(f"For-loop `next` must return Option[T], got {option_type}")
        self._var_vals[option_name] = option_value.var_out
        self._remember_source_type(option_value.var_out, option_type)

        self._translate_match(
            s.Statement_Match(
                expr=s.Expression_Path([Type(option_name)]),
                arms=[
                    s.Statement_MatchArm(
                        pattern=s.Expression_Path([Type("Option"), Type("Some")]),
                        binding=statement.name,
                        body=s.Block(body=[*statement.body.body, s.Statement_Continue(label=None)]),
                    ),
                    s.Statement_MatchArm(
                        pattern=s.Expression_Path([Type("Option"), Type("None")]),
                        binding=None,
                        body=s.Block(body=[s.Statement_Break(label=None)]),
                    ),
                ],
            )
        )

        self._loop_stack.pop()
        self._builder.position_at_end(latch_block)
        if not self._is_current_block_terminated():
            self._builder.build_br(body_block.name)
            self._mark_current_block_terminated()
        self._builder.position_at_end(end_block)

    def _translate_if(self, statement: s.Statement_If):
        if_id = self._if_counter
        self._if_counter += 1

        branch_count = len(statement.branches)
        branch_bodies = [self._builder.append_block(f"if_body_{if_id}_{idx}") for idx in range(branch_count)]
        cond_blocks = [self._builder.current_block] + [
            self._builder.append_block(f"if_cond_{if_id}_{idx}") for idx in range(1, branch_count)
        ]
        else_block = self._builder.append_block(f"if_else_{if_id}") if statement.else_body is not None else None
        end_block = self._builder.append_block(f"if_end_{if_id}") if else_block is None else None

        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)

        def ensure_end_block():
            nonlocal end_block
            if end_block is None:
                end_block = self._builder.append_block(f"if_end_{if_id}")
            return end_block

        for idx, branch in enumerate(statement.branches):
            self._builder.position_at_end(cond_blocks[idx])
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)

            false_target = (
                cond_blocks[idx + 1].name
                if idx + 1 < branch_count
                else (else_block.name if else_block else ensure_end_block().name)
            )
            cond = self._translate_expression(branch.expr)
            self._builder.build_cbr(cond.var_out, branch_bodies[idx].name, false_target)
            self._mark_current_block_terminated()

            self._builder.position_at_end(branch_bodies[idx])
            self._translate_block(branch.body)
            if not self._is_current_block_terminated():
                self._builder.build_br(ensure_end_block().name)
                self._mark_current_block_terminated()

        if else_block is not None:
            assert statement.else_body
            self._builder.position_at_end(else_block)
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)
            self._translate_block(statement.else_body)
            if not self._is_current_block_terminated():
                self._builder.build_br(ensure_end_block().name)
                self._mark_current_block_terminated()

        if end_block is not None:
            self._builder.position_at_end(end_block)
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)

    def _translate_match(self, statement: s.Statement_Match):
        self._translate_match_common(statement, is_expression=False)

    def _translate_match_common(
        self,
        match_expr: MatchLike,
        *,
        is_expression: bool,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable | None:
        match_id = self._if_counter
        self._if_counter += 1

        scrutinee = self._translate_expression(match_expr.expr)
        if scrutinee.var_out.type is None:
            current_fn = getattr(self._builder.current_function, "name", "<unknown>")
            raise TypeError(
                f"Unable to infer match scrutinee type in '{current_fn}' for expression: {match_expr.expr!r}"
            )

        if self._is_builtin_match_type(scrutinee.var_out.type):
            return self._translate_builtin_match(
                match_id=match_id,
                scrutinee=scrutinee,
                arms=match_expr.arms,
                is_expression=is_expression,
                name=name,
                expected_type=expected_type,
            )

        result_name = (name or self._advance_variable()) if is_expression else None
        result_type = expected_type if is_expression else None
        result_slot: Variable | None = (
            self._allocate_stack_slot(f"{result_name}_slot", result_type)
            if is_expression and result_type is not None
            else None
        )

        prepared = self._prepare_match(
            match_id=match_id,
            scrutinee=scrutinee,
            arms=match_expr.arms,
            end_prefix="match_expr_end" if is_expression else "match_end",
            default_prefix="match_expr_default" if is_expression else "match_default",
            arm_prefix="match_expr_arm" if is_expression else "match_arm",
        )

        for idx, arm in enumerate(match_expr.arms):
            if arm.is_wildcard:
                continue

            self._enter_match_arm_scope(prepared, idx, arm)
            body = self._get_match_arm_body(arm)
            if is_expression:
                arm_result = self._translate_match_expression_body(body, expected_type=expected_type)
                result_type = result_type or arm_result.var_out.type
                if result_slot is None:
                    assert result_name is not None and result_type is not None
                    result_slot = self._create_stack_slot(f"{result_name}_slot", arm_result.var_out, result_type)
                else:
                    self._builder._add(Instruction_store(var_src=arm_result.var_out, var_dst=result_slot))
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()
            else:
                self._translate_match_statement_body(body)
                if not self._is_current_block_terminated():
                    self._builder.build_br(prepared.end_block.name)
                    self._mark_current_block_terminated()

        if prepared.wildcard_arm is not None:
            self._enter_match_default_scope(prepared)
            body = self._get_match_arm_body(prepared.wildcard_arm)
            if is_expression:
                default_result = self._translate_match_expression_body(body, expected_type=expected_type)
                result_type = result_type or default_result.var_out.type
                if result_slot is None:
                    assert result_name is not None and result_type is not None
                    result_slot = self._create_stack_slot(f"{result_name}_slot", default_result.var_out, result_type)
                else:
                    self._builder._add(Instruction_store(var_src=default_result.var_out, var_dst=result_slot))
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()
            else:
                self._translate_match_statement_body(body)
                if not self._is_current_block_terminated():
                    self._builder.build_br(prepared.end_block.name)
                    self._mark_current_block_terminated()

        self._builder.position_at_end(prepared.end_block)
        self._var_vals = dict(prepared.base_var_vals)
        self._var_ptrs = dict(prepared.base_var_ptrs)

        if not is_expression:
            return None

        assert result_name is not None and result_type is not None and result_slot is not None
        return self._build_load_from_ptr(result_slot, name=result_name)

    def _enter_match_arm_scope(self, prepared: "_PreparedMatch", idx: int, arm: MatchBodyArmLike):
        self._builder.position_at_end(prepared.arm_blocks[idx])
        self._var_vals = dict(prepared.base_var_vals)
        self._var_ptrs = dict(prepared.base_var_ptrs)
        payload_type = prepared.arm_payload_types[idx]
        if arm.binding is not None and payload_type is not None:
            binding_var = Variable(arm.binding, payload_type)
            variant_field_index = prepared.arm_variant_indices[idx] + 1
            payload_ptr = Variable(self._advance_variable(), Pointer(payload_type))
            self._builder._add(
                Instruction_getfield(
                    var_out=payload_ptr,
                    src=prepared.scrutinee.var_out,
                    field=Variable(str(variant_field_index), Pointer(payload_type)),
                )
            )
            self._builder._add(Instruction_load(var_out=binding_var, var=payload_ptr))
            self._var_vals[arm.binding] = binding_var
            self._remember_source_type(binding_var, payload_type)

    def _enter_match_default_scope(self, prepared: "_PreparedMatch"):
        self._builder.position_at_end(prepared.default_block)
        self._var_vals = dict(prepared.base_var_vals)
        self._var_ptrs = dict(prepared.base_var_ptrs)

    def _get_match_arm_body(self, arm: MatchBodyArmLike) -> MatchBodyLike:
        if isinstance(arm, s.Statement_MatchArm):
            return arm.body
        return arm.expr

    def _translate_match_statement_body(self, body: MatchBodyLike):
        if isinstance(body, Block):
            self._translate_block(body)
            return
        self._translate_expression(body)

    def _translate_match_expression_body(
        self,
        body: MatchBodyLike,
        *,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        if isinstance(body, Block):
            return self._translate_expression_block(body, expected_type=expected_type)
        return self._translate_expression(body, expected_type=expected_type)

    def _translate_builtin_match(
        self,
        *,
        match_id: int,
        scrutinee: Assignable,
        arms: list[MatchBodyArmLike],
        is_expression: bool,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable | None:
        explicit_arms = [arm for arm in arms if not arm.is_wildcard]
        wildcard_arm = next((arm for arm in arms if arm.is_wildcard), None)
        default_arm = wildcard_arm
        if default_arm is None:
            if not explicit_arms:
                raise TypeError("Builtin match must have at least one arm")
            default_arm = explicit_arms[-1]
            explicit_arms = explicit_arms[:-1]

        result_name = (name or self._advance_variable()) if is_expression else None
        result_type = expected_type if is_expression else None
        result_slot: Variable | None = (
            self._allocate_stack_slot(f"{result_name}_slot", result_type)
            if is_expression and result_type is not None
            else None
        )

        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)
        end_block = self._builder.append_block(f"match_builtin_end_{match_id}")

        if explicit_arms:
            cond_blocks = [self._builder.current_block] + [
                self._builder.append_block(f"match_builtin_cond_{match_id}_{idx}") for idx in range(1, len(explicit_arms))
            ]
            arm_blocks = [self._builder.append_block(f"match_builtin_arm_{match_id}_{idx}") for idx in range(len(explicit_arms))]
            default_block = self._builder.append_block(f"match_builtin_default_{match_id}")

            for idx, arm in enumerate(explicit_arms):
                self._builder.position_at_end(cond_blocks[idx])
                self._var_vals = dict(base_var_vals)
                self._var_ptrs = dict(base_var_ptrs)

                cond_var = self._translate_builtin_match_condition(scrutinee.var_out, arm.pattern)
                false_target = cond_blocks[idx + 1].name if idx + 1 < len(explicit_arms) else default_block.name
                self._builder.build_cbr(cond_var, arm_blocks[idx].name, false_target)
                self._mark_current_block_terminated()

                self._builder.position_at_end(arm_blocks[idx])
                self._var_vals = dict(base_var_vals)
                self._var_ptrs = dict(base_var_ptrs)
                body = self._get_match_arm_body(arm)
                if is_expression:
                    arm_result = self._translate_match_expression_body(body, expected_type=expected_type)
                    result_type = result_type or arm_result.var_out.type
                    if result_slot is None:
                        assert result_name is not None and result_type is not None
                        result_slot = self._create_stack_slot(f"{result_name}_slot", arm_result.var_out, result_type)
                    else:
                        self._builder._add(Instruction_store(var_src=arm_result.var_out, var_dst=result_slot))
                    self._builder.build_br(end_block.name)
                    self._mark_current_block_terminated()
                else:
                    self._translate_match_statement_body(body)
                    if not self._is_current_block_terminated():
                        self._builder.build_br(end_block.name)
                        self._mark_current_block_terminated()

            self._builder.position_at_end(default_block)
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)
        else:
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)

        body = self._get_match_arm_body(default_arm)
        if is_expression:
            default_result = self._translate_match_expression_body(body, expected_type=expected_type)
            result_type = result_type or default_result.var_out.type
            if result_slot is None:
                assert result_name is not None and result_type is not None
                result_slot = self._create_stack_slot(f"{result_name}_slot", default_result.var_out, result_type)
            else:
                self._builder._add(Instruction_store(var_src=default_result.var_out, var_dst=result_slot))
            self._builder.build_br(end_block.name)
            self._mark_current_block_terminated()
        else:
            self._translate_match_statement_body(body)
            if not self._is_current_block_terminated():
                self._builder.build_br(end_block.name)
                self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        self._var_vals = dict(base_var_vals)
        self._var_ptrs = dict(base_var_ptrs)

        if not is_expression:
            return None

        assert result_name is not None and result_type is not None and result_slot is not None
        return self._build_load_from_ptr(result_slot, name=result_name)

    def _translate_builtin_match_condition(self, scrutinee: Variable, pattern: MatchPatternLike) -> Variable:
        if pattern is None:
            raise TypeError("Wildcard arm has no explicit pattern")

        rhs = self._translate_expression(pattern, expected_type=scrutinee.type)
        eq_fn_name = self._function_aliases.get("Eq::op", "Eq::op")
        cond = self._builder.build_call(
            fn_name=eq_fn_name,
            generics=[],
            args=[scrutinee, rhs.var_out],
        )
        cond.var_out.type = Usize_t(1)
        return cond.var_out

    def _resolve_match_arm_common(self, scrutinee_type: Type, arm: MatchArmLike) -> tuple[str, int, Optional[Type]]:
        scrutinee_type = unwrap_for_storage(scrutinee_type)
        base_type = scrutinee_type.pointee if is_reference_like_type(scrutinee_type) else scrutinee_type
        enum = self._enums.get(base_type.name)
        if enum is None:
            raise TypeError(f"Match expression must be an enum, got {scrutinee_type}")
        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum.generics, base_type.generics)}

        assert isinstance(arm.pattern, s.Expression_Path)
        if len(arm.pattern.segments) == 1:
            variant_name = arm.pattern.segments[0].name
        elif len(arm.pattern.segments) == 2:
            explicit_enum = arm.pattern.segments[0]
            translated_explicit_enum = self._translate_type(explicit_enum)
            if translated_explicit_enum.name != base_type.name:
                raise TypeError(f"Pattern enum '{explicit_enum.name}' does not match scrutinee type '{base_type.name}'")
            if translated_explicit_enum.generics and not self._types_compatible(translated_explicit_enum, base_type):
                raise TypeError(f"Pattern enum '{explicit_enum}' does not match scrutinee type '{base_type}'")
            variant_name = arm.pattern.segments[1].name
        else:
            raise TypeError(f"Unsupported match pattern: {arm.pattern}")

        for idx, variant in enumerate(enum.variants):
            if variant.name == variant_name:
                payload_type: Type | None = None
                if isinstance(variant, TupleLikeVariant) and variant.types:
                    payload_type = self._specialize_type(variant.types[0], generic_mapping)
                return variant_name, idx, payload_type

        raise TypeError(f"Unknown variant '{variant_name}' for enum '{enum.name}'")

    def _translate_expression(
        self,
        expr: s.Statement_Expression,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        if isinstance(expr, s.Expression_BooleanLiteral):
            return self._builder.build_capprim(prim=Usize(int(expr.value), size=1), name=name)

        elif isinstance(expr, s.Expression_StringLiteral):
            return self._builder.build_capprim(prim=Str(expr.value), name=name)

        elif isinstance(expr, s.Expression_IntegerLiteral):
            int_expected = expr.literal_type or expected_type
            if int_expected is not None:
                int_expected = unwrap_for_storage(int_expected)
                base_expected = int_expected.pointee if is_reference_like_type(int_expected) else int_expected
                if isinstance(base_expected, Float_t) or (
                    isinstance(base_expected, Type)
                    and base_expected.name.startswith("f")
                    and base_expected.name[1:].isdigit()
                ):
                    prim = Float(float(expr.value), size=self._infer_float_size(int_expected))
                    return self._builder.build_capprim(prim=prim, name=name)
            prim = self._build_integer_primitive(int(expr.value), int_expected)
            return self._builder.build_capprim(prim=prim, name=name)

        elif isinstance(expr, s.Expression_FloatLiteral):
            return self._builder.build_capprim(
                prim=Float(
                    float(expr.value),
                    size=self._infer_float_size(expr.literal_type or expected_type),
                ),
                name=name,
            )

        elif isinstance(expr, s.Expression_Path):
            if len(expr.segments) == 1:
                explicit_binding = self._lookup_explicit_path_value(expr.name, result_name=name)
                if explicit_binding is not None:
                    return explicit_binding
                return self._builder.get_var(expr.name)

            enum_expr = self._build_enum_from_path(expr)
            if enum_expr is not None:
                out = Variable(name or self._advance_variable())
                self._builder._add(Instruction_capenum(var_out=out, enum=enum_expr))
                return Assignable(out)

            raise NotImplementedError(f"Translation for path expression {expr.name} is not implemented.")

        elif isinstance(expr, s.Expression_Block):
            return self._translate_expression_block(expr, name=name, expected_type=expected_type)

        elif isinstance(expr, s.Expression_Unsafe):
            self._unsafe_depth += 1
            try:
                return self._translate_expression_block(expr.body, name=name, expected_type=expected_type)
            finally:
                self._unsafe_depth -= 1

        elif isinstance(expr, s.Expression_If):
            return self._translate_if_expression(expr, name=name, expected_type=expected_type)

        elif isinstance(expr, (s.Statement_Match, s.Expression_Match)):
            return self._translate_match_expression(expr, name=name, expected_type=expected_type)

        elif isinstance(expr, s.Expression_BinaryOperation):
            if expr.operator in ("&&", "||"):
                return self._translate_short_circuit_logical(expr, name=name)

            trait_name = OPERATOR_TRAIT_MAPPING.get(expr.operator)
            if trait_name is not None:
                lhs = self._translate_expression(expr.lhs, expected_type=expected_type)
                rhs = self._translate_expression(expr.rhs, expected_type=lhs.var_out.type or expected_type)
                fn_name = self._resolve_trait_method_call_name(trait_name, "op", receiver_type=lhs.var_out.type)
                call = self._builder.build_call(
                    fn_name=fn_name,
                    generics=[],
                    args=[lhs.var_out, rhs.var_out],
                    name=name,
                )
                if expr.operator in COMPARISON_OPERATOR_SET:
                    call.var_out.type = Usize_t(size=1)
                else:
                    call.var_out.type = lhs.var_out.type or rhs.var_out.type
                return call

            lhs = self._translate_expression(expr.lhs, expected_type=expected_type)
            rhs = self._translate_expression(expr.rhs, expected_type=lhs.var_out.type or expected_type)
            return self._builder.build_binop(OPERATOR_MAPPING[expr.operator], lhs.var_out, rhs.var_out, name)

        elif isinstance(expr, s.Expression_UnaryOperation):
            if expr.operator in ("!", "not"):
                operand = self._translate_expression(expr.expr)
                zero = self._builder.build_capprim(prim=Usize(0, size=1))
                return self._builder.build_binop("ieq", operand.var_out, zero.var_out, name)
            raise NotImplementedError(f"Translation for unary operator '{expr.operator}' is not implemented.")

        elif isinstance(expr, s.Expression_Try):
            return self._translate_try_expression(expr, name=name)

        elif isinstance(expr, s.Expression_Parenthesized):
            return self._translate_expression(expr.expr, name=name, expected_type=expected_type)

        elif isinstance(expr, s.Expression_TupleLiteral):
            expected_items: list[Type | None] = [None] * len(expr.items)
            tuple_type = None
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_tuple_type(expected_base):
                    expected_items = list(expected_base.generics)
                    tuple_type = expected_base

            args = [
                self._translate_expression(
                    item, expected_type=expected_items[idx] if idx < len(expected_items) else None
                ).var_out
                for idx, item in enumerate(expr.items)
            ]
            if tuple_type is None:
                if any(arg.type is None for arg in args):
                    raise TypeError("Unable to infer tuple literal type")
                tuple_type = make_tuple_type([arg.type for arg in args if arg.type is not None])
            return self._translate_struct_initialization(self._translate_type(tuple_type), args, name)

        elif isinstance(expr, s.Expression_ArrayRepeat):
            expected_item_type = None
            array_type = None
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_array_type(expected_base):
                    expected_item_type = expected_base.generics[0]
                    array_type = expected_base
            item = self._translate_expression(expr.value, expected_type=expected_item_type).var_out
            if array_type is None:
                if item.type is None:
                    raise TypeError("Unable to infer array repeat item type")
                array_type = Type(f"__array_{expr.size}", [item.type])
            args = [item for _ in range(expr.size)]
            return self._translate_struct_initialization(self._translate_type(array_type), args, name)

        elif isinstance(expr, s.Expression_ArrayLiteral):
            expected_item_type = None
            array_type = None
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_array_type(expected_base):
                    expected_item_type = expected_base.generics[0]
                    array_type = expected_base

            args = [self._translate_expression(item, expected_type=expected_item_type).var_out for item in expr.items]
            if array_type is None:
                if not args:
                    raise TypeError("Unable to infer type of empty array literal")
                if args[0].type is None:
                    raise TypeError("Unable to infer array item type")
                array_type = Type(f"__array_{len(args)}", [args[0].type])
            return self._translate_struct_initialization(self._translate_type(array_type), args, name)

        elif isinstance(expr, s.Expression_StructInitialization):
            field_types = self._lookup_struct_field_types(expr.name)
            args = [
                self._translate_expression(
                    arg_exp,
                    name=f"{name}_{idx}" if name is not None else None,
                    expected_type=field_types[idx] if idx < len(field_types) else None,
                ).var_out
                for idx, arg_exp in enumerate(expr.args)
            ]
            return self._translate_struct_initialization(expr.name, args, name)

        elif isinstance(expr, s.Expression_StructField):
            src = self._resolve_struct_field_chain(expr.name)
            field = Variable(expr.field)
            field_type = self._lookup_field_type(self._field_owner_type(src), expr.field)

            instr = Instruction_getfield(var_out=Variable(name or self._advance_variable()), src=src, field=field)
            if field_type is not None:
                instr.var_out.type = field_type
            self._builder._add(instr)
            return instr

        elif isinstance(expr, s.Expression_Index):
            if not isinstance(expr.index, s.Expression_IntegerLiteral):
                raise TypeError("Only constant integer indexing is currently supported")
            idx = int(expr.index.value)

            src = self._translate_expression(expr.base).var_out
            field = Variable(str(idx))
            field_type = self._lookup_field_type(self._field_owner_type(src), field.name)
            if field_type is None:
                raise TypeError(f"Unable to resolve index '{idx}' for type '{src.type}'")

            instr = Instruction_getfield(var_out=Variable(name or self._advance_variable()), src=src, field=field)
            instr.var_out.type = field_type
            self._builder._add(instr)
            return instr

        elif isinstance(expr, s.Expression_MethodCall):
            receiver = self._translate_expression(expr.receiver).var_out
            if receiver.type is None:
                source_type = self._source_type_for_var(receiver)
                if source_type is not None:
                    receiver.type = self._translate_type(source_type)
                elif isinstance(expr.receiver, s.Expression_Path) and len(expr.receiver.segments) == 1:
                    receiver.type = self._resolve_variable_type(expr.receiver.name)
                if receiver.type is None:
                    raise TypeError(f"Unable to infer receiver type for method call '{expr.method}'")

            fn_name, callee = self._resolve_method_callable(receiver.type, expr.method)
            fn_name = self._function_aliases.get(fn_name, fn_name)

            if fn_name in self._extern_fns and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{fn_name}' can only be called inside unsafe block")

            base_source_signature = self._source_signatures.get(fn_name)
            arg_exprs = [expr.receiver, *expr.args]
            arg_values = [Assignable(receiver)]
            if base_source_signature is not None:
                extra_params = base_source_signature.params[1:]
                arg_values.extend(
                    self._translate_expression(
                        arg_exp,
                        expected_type=self._call_expected_type(param.type),
                    )
                    for arg_exp, param in zip(expr.args, extra_params)
                )
            else:
                arg_values.extend(self._translate_expression(arg_exp) for arg_exp in expr.args)

            fn_name = self._resolve_any_pointer_call_name(fn_name, [arg.var_out for arg in arg_values])
            source_signature = self._source_signatures.get(fn_name, base_source_signature)
            generics = [self._translate_type(g) for g in expr.generics]
            if callee is not None and callee.generics:
                inferred_mapping: dict[str, Type] = {}
                if source_signature is not None and source_signature.params:
                    recv_pattern = self._translate_type(source_signature.params[0].type)
                    self._collect_generic_mapping_from_types(recv_pattern, receiver.type, inferred_mapping)
                if not generics:
                    for generic in callee.generics:
                        concrete = inferred_mapping.get(generic.name)
                        if concrete is not None:
                            generics.append(concrete)
            args = self._materialize_call_args(
                arg_exprs,
                arg_values,
                source_signature.params if source_signature is not None else None,
            )
            callee = self._funcs.get(fn_name, callee)
            call = self._builder.build_call(
                fn_name=fn_name,
                generics=generics,
                args=args,
                name=name,
                is_unsafe=fn_name in self._extern_fns and self._unsafe_depth > 0,
            )
            if source_signature is not None and source_signature.type is not None:
                self._remember_source_type(call.var_out, source_signature.type)
            if callee is not None:
                generic_mapping = {generic.name: concrete for generic, concrete in zip(callee.generics, generics)}
                ret_type = self._specialize_type(callee.ret_type, generic_mapping)
                call.var_out.type = self._qualify_type_for_callable(
                    ret_type,
                    fn_name=fn_name,
                    generic_names={generic.name for generic in callee.generics},
                )
            return call

        elif isinstance(expr, s.Expression_Range):
            range_ctor = s.Expression_Call(
                callee=s.Expression_Path([Type("range_inclusive" if expr.inclusive else "range")]),
                generics=[],
                args=[expr.start, expr.end],
            )
            return self._translate_expression(range_ctor, expected_type=expected_type, name=name)

        elif isinstance(expr, s.Expression_Call):
            enum_expr = self._build_enum_from_call(expr)
            if enum_expr is not None:
                out = Variable(name or self._advance_variable())
                self._builder._add(Instruction_capenum(var_out=out, enum=enum_expr))
                return Assignable(out)

            call_name, call_generics = self._resolve_function_call_target(expr)
            base_source_signature = self._source_signatures.get(call_name)
            if base_source_signature is not None:
                arg_values = [
                    self._translate_expression(arg_exp, expected_type=self._call_expected_type(param.type))
                    for arg_exp, param in zip(expr.args, base_source_signature.params)
                ]
            else:
                arg_values = [self._translate_expression(arg_exp) for arg_exp in expr.args]
            call_name = self._resolve_any_pointer_call_name(call_name, [arg.var_out for arg in arg_values])
            source_signature = self._source_signatures.get(call_name, base_source_signature)
            args = self._materialize_call_args(
                expr.args,
                arg_values,
                source_signature.params if source_signature is not None else None,
            )

            if call_name in self._extern_fns and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{expr.name}' can only be called inside unsafe block")

            generics = [self._translate_type(g) for g in call_generics]
            call = self._builder.build_call(
                fn_name=call_name,
                generics=generics,
                args=args,
                name=name,
                is_unsafe=call_name in self._extern_fns and self._unsafe_depth > 0,
            )
            if source_signature is not None and source_signature.type is not None:
                self._remember_source_type(call.var_out, source_signature.type)
            callee = self._funcs.get(call_name)
            if callee is not None:
                callee_generics = getattr(callee, "generics", [])
                generic_mapping = {generic.name: concrete for generic, concrete in zip(callee_generics, generics)}
                ret_type = self._specialize_type(callee.ret_type, generic_mapping)
                call.var_out.type = self._qualify_type_for_callable(
                    ret_type,
                    fn_name=call_name,
                    generic_names={generic.name for generic in callee_generics},
                )
            return call

        raise NotImplementedError(f"Translation for expression type {type(expr)}:{expr} is not implemented.")

    def _translate_short_circuit_logical(
        self,
        expr: s.Expression_BinaryOperation,
        name: Optional[str] = None,
    ) -> Assignable:
        if expr.operator not in ("&&", "||"):
            raise ValueError(f"Unsupported logical operator for short-circuit: {expr.operator}")

        logical_id = self._if_counter
        self._if_counter += 1

        rhs_block = self._builder.append_block(f"logical_rhs_{logical_id}")
        short_block = self._builder.append_block(f"logical_short_{logical_id}")
        end_block = self._builder.append_block(f"logical_end_{logical_id}")
        result_name = name or self._advance_variable()
        result_slot = self._create_stack_slot(
            f"{result_name}_slot",
            self._builder.build_capprim(prim=Usize(0, size=1)).var_out,
            Usize_t(1),
        )

        lhs = self._translate_expression(expr.lhs, expected_type=Type("bool"))
        lhs_cond = self._ensure_boolean(lhs.var_out, context=f"lhs of '{expr.operator}'")

        if expr.operator == "&&":
            self._builder.build_cbr(lhs_cond, rhs_block.name, short_block.name)
        else:
            self._builder.build_cbr(lhs_cond, short_block.name, rhs_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(rhs_block)
        rhs = self._translate_expression(expr.rhs, expected_type=Type("bool"))
        rhs_cond = self._ensure_boolean(rhs.var_out, context=f"rhs of '{expr.operator}'")
        self._builder._add(Instruction_store(var_src=rhs_cond, var_dst=result_slot))
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(short_block)
        short_value = self._builder.build_capprim(prim=Usize(0 if expr.operator == "&&" else 1, size=1)).var_out
        self._builder._add(Instruction_store(var_src=short_value, var_dst=result_slot))
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        return self._build_load_from_ptr(result_slot, name=result_name)

    def _ensure_boolean(self, var: Variable, *, context: str) -> Variable:
        if var.type is None:
            raise TypeError(f"Unable to infer boolean type for {context}")

        if isinstance(var.type, (Usize_t, Isize_t)) and var.type.size == 1:
            return var
        if var.type.name in {"bool", "u1", "i1"}:
            return var

        raise TypeError(f"Expected bool for {context}, got {var.type}")

    def _translate_try_expression(
        self,
        expr: s.Expression_Try,
        name: Optional[str] = None,
    ) -> Assignable:
        tried = self._translate_expression(expr.expr)
        if tried.var_out.type is None:
            raise TypeError("Unable to infer type of expression used with '?'")

        result_type = tried.var_out.type
        result_type = unwrap_for_storage(result_type)
        base_result_type = result_type.pointee if is_reference_like_type(result_type) else result_type
        if base_result_type.name != "Result" or len(base_result_type.generics) != 2:
            raise TypeError(f"'?' operator expects Result[T, E], got {result_type}")
        ok_type, err_type = base_result_type.generics
        ok_type = self._translate_type(ok_type)
        err_type = self._translate_type(err_type)

        current_fn = getattr(self._builder, "current_function", None)
        if current_fn is None:
            raise TypeError("'?' operator can only be used inside a function")
        fn_ret_type = current_fn.ret_type
        fn_ret_type = unwrap_for_storage(fn_ret_type)
        base_fn_ret_type = fn_ret_type.pointee if is_reference_like_type(fn_ret_type) else fn_ret_type
        if base_fn_ret_type.name != "Result" or len(base_fn_ret_type.generics) != 2:
            raise TypeError("'?' operator can only be used in functions returning Result")
        fn_err_type = base_fn_ret_type.generics[1]
        if not self._types_compatible(fn_err_type, err_type):
            raise TypeError(f"'?' error type mismatch: function expects {fn_err_type}, got {err_type}")

        try_id = self._if_counter
        self._if_counter += 1

        ok_block = self._builder.append_block(f"try_ok_{try_id}")
        err_block = self._builder.append_block(f"try_err_{try_id}")

        ok_payload = Variable(name or self._advance_variable(), ok_type)
        err_payload = Variable(self._advance_variable(), err_type)
        cases = [
            MatchCase(variant="Ok", label=ok_block.name, payload_var=ok_payload),
            MatchCase(variant="Err", label=err_block.name, payload_var=err_payload),
        ]
        self._builder.build_match(cond_var=tried.var_out, default_label=err_block.name, cases=cases)
        self._mark_current_block_terminated()

        self._builder.position_at_end(err_block)
        err_value = Variable(self._advance_variable(), fn_ret_type)
        err_enum = Enum(
            name=base_fn_ret_type.name,
            generics=base_fn_ret_type.generics,
            variant="Err",
            payload=Struct(name=err_type.name, value=err_payload, type=err_type),
        )
        self._builder._add(Instruction_capenum(var_out=err_value, enum=err_enum))
        self._builder.build_ret(err_value)
        self._mark_current_block_terminated()

        self._builder.position_at_end(ok_block)
        return Assignable(ok_payload)

    def _translate_expression_block(
        self,
        block: Block | s.Expression_Block,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        outer_var_vals = self._var_vals
        outer_var_ptrs = self._var_ptrs
        outer_assignment_targets = self._assignment_targets
        self._var_vals = dict(self._var_vals)
        self._var_ptrs = dict(self._var_ptrs)
        self._assignment_targets = dict(self._assignment_targets)

        try:
            statements, tail_expr = self._split_expression_block(block)
            for statement in statements:
                self._translate_expression_block_statement(statement)
            return self._translate_expression(tail_expr, name=name, expected_type=expected_type)
        finally:
            self._var_vals = outer_var_vals
            self._var_ptrs = outer_var_ptrs
            self._assignment_targets = outer_assignment_targets

    def _split_expression_block(
        self,
        block: Block | s.Expression_Block,
    ) -> tuple[list[s.Statement_InnerLevel], s.Statement_Expression]:
        if isinstance(block, s.Expression_Block):
            return list(block.body), block.expr

        if not block.body:
            raise TypeError("Expression block can not be empty")

        *statements, tail = block.body
        if not isinstance(tail, s.Statement_Expr):
            raise TypeError("Expression block must end with an expression statement")
        return statements, tail.expr

    def _translate_expression_block_statement(self, statement: s.Statement_InnerLevel):
        if isinstance(statement, (s.Statement_Ret, s.Statement_Break, s.Statement_Continue)):
            raise TypeError(f"{type(statement).__name__} is not allowed inside expression block")
        self._translate_inner_statement(statement)

    def _translate_if_expression(
        self,
        expr: s.Expression_If,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        if_id = self._if_counter
        self._if_counter += 1

        branch_count = len(expr.branches)
        branch_bodies = [self._builder.append_block(f"if_expr_body_{if_id}_{idx}") for idx in range(branch_count)]
        cond_blocks = [self._builder.current_block] + [
            self._builder.append_block(f"if_expr_cond_{if_id}_{idx}") for idx in range(1, branch_count)
        ]
        else_block = self._builder.append_block(f"if_expr_else_{if_id}")
        end_block = self._builder.append_block(f"if_expr_end_{if_id}")

        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)
        result_name = name or self._advance_variable()
        result_type = expected_type
        result_slot: Variable | None = (
            self._allocate_stack_slot(f"{result_name}_slot", result_type) if result_type is not None else None
        )

        for idx, branch in enumerate(expr.branches):
            self._builder.position_at_end(cond_blocks[idx])
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)

            false_target = cond_blocks[idx + 1].name if idx + 1 < branch_count else else_block.name
            cond = self._translate_expression(branch.expr)
            self._builder.build_cbr(cond.var_out, branch_bodies[idx].name, false_target)
            self._mark_current_block_terminated()

            self._builder.position_at_end(branch_bodies[idx])
            branch_result = self._translate_expression(branch.body, expected_type=expected_type)
            result_type = result_type or branch_result.var_out.type
            if result_slot is None:
                assert result_type is not None
                result_slot = self._create_stack_slot(f"{result_name}_slot", branch_result.var_out, result_type)
            else:
                self._builder._add(Instruction_store(var_src=branch_result.var_out, var_dst=result_slot))
            self._builder.build_br(end_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(else_block)
        self._var_vals = dict(base_var_vals)
        self._var_ptrs = dict(base_var_ptrs)
        else_result = self._translate_expression(expr.else_body, expected_type=expected_type)
        result_type = result_type or else_result.var_out.type
        if result_slot is None:
            assert result_type is not None
            result_slot = self._create_stack_slot(f"{result_name}_slot", else_result.var_out, result_type)
        else:
            self._builder._add(Instruction_store(var_src=else_result.var_out, var_dst=result_slot))
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()

        assert result_type is not None and result_slot is not None
        self._builder.position_at_end(end_block)
        self._var_vals = dict(base_var_vals)
        self._var_ptrs = dict(base_var_ptrs)
        return self._build_load_from_ptr(result_slot, name=result_name)

    def _translate_match_expression(
        self,
        expr: MatchLike,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        result = self._translate_match_common(expr, is_expression=True, name=name, expected_type=expected_type)
        assert result is not None
        return result

    def _prepare_match(
        self,
        *,
        match_id: int,
        scrutinee: Assignable,
        arms: list[MatchBodyArmLike],
        end_prefix: str,
        default_prefix: str,
        arm_prefix: str,
    ) -> "_PreparedMatch":
        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)
        end_block = self._builder.append_block(f"{end_prefix}_{match_id}")
        wildcard_arm = next((arm for arm in arms if arm.is_wildcard), None)
        default_block = (
            self._builder.append_block(f"{default_prefix}_{match_id}") if wildcard_arm is not None else end_block
        )

        arm_blocks: dict[int, object] = {}
        arm_payload_types: dict[int, Type | None] = {}
        arm_variant_indices: dict[int, int] = {}
        cases: list[MatchCase] = []
        for idx, arm in enumerate(arms):
            if arm.is_wildcard:
                continue
            arm_blocks[idx] = self._builder.append_block(f"{arm_prefix}_{match_id}_{idx}")
            variant_name, variant_index, payload_type = self._resolve_match_arm_common(scrutinee.var_out.type, arm)
            arm_variant_indices[idx] = variant_index
            arm_payload_types[idx] = payload_type
            payload_var = (
                Variable(arm.binding, payload_type) if arm.binding is not None and payload_type is not None else None
            )
            cases.append(MatchCase(variant=variant_name, label=arm_blocks[idx].name, payload_var=payload_var))

        self._builder.build_match(cond_var=scrutinee.var_out, default_label=default_block.name, cases=cases)
        self._mark_current_block_terminated()
        return self._PreparedMatch(
            scrutinee=scrutinee,
            base_var_vals=base_var_vals,
            base_var_ptrs=base_var_ptrs,
            end_block=end_block,
            default_block=default_block,
            wildcard_arm=wildcard_arm,
            arm_blocks=arm_blocks,
            arm_payload_types=arm_payload_types,
            arm_variant_indices=arm_variant_indices,
        )

    def _normalize_match_scrutinee_type(self, typ: Type) -> Type:
        typ = unwrap_for_storage(typ)
        return typ.pointee if is_reference_like_type(typ) else typ

    def _is_builtin_match_type(self, typ: Type) -> bool:
        base_type = self._normalize_match_scrutinee_type(typ)
        return (
            base_type.name == "str"
            or base_type.name == "bool"
            or self._is_integer_type_name(base_type.name)
            or self._is_float_type_name(base_type.name)
        )

    @staticmethod
    def _is_integer_type_name(name: str) -> bool:
        return name in ("usize", "isize") or (len(name) > 1 and name[0] in ("u", "i") and name[1:].isdigit())

    @staticmethod
    def _is_float_type_name(name: str) -> bool:
        return len(name) > 1 and name[0] == "f" and name[1:].isdigit()

    def _mark_current_block_terminated(self):
        self._terminated_blocks.add(self._builder.current_block.name)

    def _is_current_block_terminated(self) -> bool:
        return self._builder.current_block.name in self._terminated_blocks

    def _resolve_loop_ctx(self, label: str | None, *, keyword: str) -> _LoopContext:
        if not self._loop_stack:
            raise ValueError(f"{keyword} used outside of a loop")
        if label is None:
            return self._loop_stack[-1]
        for loop_ctx in reversed(self._loop_stack):
            if loop_ctx.label == label:
                return loop_ctx
        raise ValueError(f"{keyword}<'{label}'> targets unknown loop label")

    def _resolve_variable_type(self, name: str) -> Type | None:
        ptr = self._var_ptrs.get(name)
        if ptr is not None and isinstance(ptr.type, Pointer):
            return ptr.type.pointee
        return self._resolve_variable(name).type

    def _build_load_from_ptr(self, ptr: Variable, *, name: str | None = None) -> Assignable:
        pointee_type = ptr.type.pointee if isinstance(ptr.type, Pointer) else None
        if name is None:
            self._unique_variable_idx += 1
            name = f"{ptr.name}_{self._unique_variable_idx}"
        out = Variable(name or self._advance_variable(), pointee_type)
        self._remember_source_type(out, self._source_type_for_var(ptr))
        self._builder._add(Instruction_load(var_out=out, var=ptr))
        return Assignable(out)

    def _allocate_stack_slot(self, slot_name: str, value_type: Type) -> Variable:
        if isinstance(value_type, (Usize_t, Isize_t, Float_t, Str_t)):
            init_prim = self._zero_primitive(value_type)
            slot_ptr = Variable(slot_name, Pointer(value_type))
            self._builder._add(Instruction_salloc(var_out=slot_ptr, type=value_type))
            self._builder._add(Instruction_put(primitive=init_prim, var=slot_ptr))
            return slot_ptr

        slot_ptr = Variable(slot_name, Pointer(value_type))
        self._builder._add(Instruction_salloc(var_out=slot_ptr, type=value_type))
        return slot_ptr

    def _create_stack_slot(self, slot_name: str, value: Variable, value_type: Type) -> Variable:
        slot_ptr = self._allocate_stack_slot(slot_name, value_type)
        self._builder._add(Instruction_store(var_src=value, var_dst=slot_ptr))
        return slot_ptr

    def _zero_primitive(self, typ: Type):
        if isinstance(typ, Usize_t):
            return Usize(0, size=typ.size)
        if isinstance(typ, Isize_t):
            return Isize(0, size=typ.size)
        if isinstance(typ, Float_t):
            return Float(0.0, size=typ.size)
        if isinstance(typ, Str_t):
            return Str("")
        raise TypeError(f"Can not build zero primitive for type '{typ}'")

    #
    # Helpers
    #
    def _set_new_variable(self, name: str):
        self._current_variable_name = name
        self._current_variable_idx = 0
        return name

    def _advance_variable(self) -> str:
        self._current_variable_idx += 1
        self._unique_variable_idx += 1
        return f"{self._current_variable_name}_{self._unique_variable_idx}"

    def _resolve_variable(self, name: str) -> Variable:
        if name in self._var_ptrs:
            return self._build_load_from_ptr(self._var_ptrs[name]).var_out
        if name in self._var_vals:
            return self._var_vals[name]
        try:
            return self._builder.get_var(name).var_out
        except ValueError:
            return Variable(name)

    def _lookup_explicit_path_value(self, binding_name: str, *, result_name: str | None = None) -> Assignable | None:
        ptr = self._var_ptrs.get(binding_name)
        if ptr is not None:
            return self._build_load_from_ptr(ptr, name=result_name)

        var = self._var_vals.get(binding_name)
        if var is not None:
            return Assignable(var)

        var = self._builder.variables.get(binding_name)
        if var is not None:
            return Assignable(var)

        return None

    def _resolve_struct_field_chain(self, name: str) -> Variable:
        parts = name.split(".")
        if not parts:
            return Variable(name)

        src = self._resolve_variable(parts[0])
        for segment in parts[1:]:
            field = Variable(segment)
            field_type = self._lookup_field_type(self._field_owner_type(src), segment)
            instr = Instruction_getfield(var_out=Variable(self._advance_variable()), src=src, field=field)
            self._builder._add(instr)
            if field_type is not None:
                instr.var_out.type = field_type
            src = instr.var_out
        return src

    def _resolve_struct_lvalue_base_ptr(self, name: str) -> Variable | None:
        parts = name.split(".")
        if not parts:
            return None

        root_ptr = self._var_ptrs.get(parts[0])
        if root_ptr is None:
            return None
        if not isinstance(root_ptr.type, Pointer):
            return None
        if is_reference_like_type(self._source_type_for_var(root_ptr)):
            return None
        if isinstance(root_ptr.type.pointee, SmartPointer):
            return None

        src_ptr = root_ptr
        for segment in parts[1:]:
            field_ptr = Variable(self._advance_variable())
            self._builder._add(Instruction_getfieldptr(var_out=field_ptr, src=src_ptr, field=Variable(segment)))
            src_ptr = field_ptr

        return src_ptr

    def _translate_struct_initialization(
        self, typ: Type, args: list[Variable], name: Optional[str] = None
    ) -> Assignable:
        source_type = unwrap_for_storage(typ)
        struct_type = source_type.pointee if is_reference_like_type(source_type) else source_type
        struct_type = self._translate_type(struct_type)
        struct = Struct(struct_type.name, struct_type.generics, args)
        out = Variable(name or self._advance_variable())

        if isinstance(source_type, HeapSmartPointer):
            plain = Variable(self._advance_variable(), struct.as_type())
            self._remember_source_type(plain, source_type.pointee)
            self._builder._add(Instruction_capstruct(var_out=plain, struct=struct))
            out.type = self._translate_type(source_type)
            self._remember_source_type(out, source_type)
            self._builder._add(Instruction_wraph(var_out=out, variable=plain))
            return Assignable(out)

        if isinstance(source_type, StackSmartPointer):
            plain = Variable(self._advance_variable(), struct.as_type())
            self._remember_source_type(plain, source_type.pointee)
            self._builder._add(Instruction_capstruct(var_out=plain, struct=struct))
            out.type = self._translate_type(source_type)
            self._remember_source_type(out, source_type)
            self._builder._add(Instruction_wraps(var_out=out, variable=plain))
            return Assignable(out)

        out.type = struct.as_type()
        self._remember_source_type(out, typ)
        self._builder._add(Instruction_capstruct(var_out=out, struct=struct))
        return Assignable(out)

    def _build_enum_from_path(self, expr: s.Expression_Path) -> Enum | None:
        if len(expr.segments) < 2:
            return None

        enum_type = expr.segments[0]
        variant_name = expr.segments[-1].name
        if len(expr.segments) != 2 or self._lookup_enum(enum_type) is None:
            return None

        translated_enum_type = self._translate_type(enum_type)
        return Enum(name=translated_enum_type.name, generics=translated_enum_type.generics, variant=variant_name, args=[])

    def _build_enum_from_call(self, expr: s.Expression_Call) -> Enum | None:
        if len(expr.callee.segments) != 2:
            return None

        enum_type = expr.callee.segments[0]
        variant_name = expr.callee.segments[1].name
        if self._lookup_enum(enum_type) is None:
            return None
        translated_enum_type = self._translate_type(enum_type)

        payload_var = None
        if expr.args:
            payload_type = self._lookup_enum_variant_type(enum_type, variant_name)
            if payload_type is None:
                raise NotImplementedError(f"Unable to resolve payload type for enum variant '{expr.name}'.")

            payload_field_types = self._lookup_struct_field_types(payload_type)
            if payload_field_types:
                if len(expr.args) == 1:
                    first_expected = payload_field_types[0] if len(payload_field_types) == 1 else None
                    first_arg = self._translate_expression(expr.args[0], expected_type=first_expected).var_out
                    if first_arg.type is not None and self._types_compatible(first_arg.type, payload_type):
                        payload_var = first_arg
                    elif len(payload_field_types) == 1:
                        payload_var = self._translate_struct_initialization(payload_type, [first_arg]).var_out
                    else:
                        raise TypeError(
                            f"Enum variant '{expr.name}' expects {len(payload_field_types)} payload arguments "
                            f"or one composite payload value, got 1"
                        )
                else:
                    if len(payload_field_types) != len(expr.args):
                        raise TypeError(
                            f"Enum variant '{expr.name}' expects {len(payload_field_types)} payload arguments, "
                            f"got {len(expr.args)}"
                        )
                    payload_args = [
                        self._translate_expression(arg_expr, expected_type=payload_field_types[idx]).var_out
                        for idx, arg_expr in enumerate(expr.args)
                    ]
                    payload_var = self._translate_struct_initialization(payload_type, payload_args).var_out
            else:
                if len(expr.args) != 1:
                    raise TypeError(f"Enum variant '{expr.name}' expects a single payload argument")
                payload_var = self._translate_expression(expr.args[0], expected_type=payload_type).var_out

        return Enum(
            name=translated_enum_type.name,
            generics=translated_enum_type.generics,
            variant=variant_name,
            args=[] if payload_var is None else [payload_var],
        )

    def _lookup_enum(self, typ: Type) -> Derective_enum | None:
        return self._enums.get(self._translate_type(typ).name)

    def _lookup_enum_variant_type(self, enum_type: Type, variant_name: str) -> Optional[Type]:
        translated_enum_type = self._translate_type(enum_type)
        enum_def = self._lookup_enum(translated_enum_type)
        if enum_def is None:
            return None

        generic_mapping = {
            generic.name: concrete for generic, concrete in zip(enum_def.generics, translated_enum_type.generics)
        }
        for variant in enum_def.variants:
            if variant.name == variant_name:
                if not isinstance(variant, TupleLikeVariant) or not variant.types:
                    return None
                return self._specialize_type(variant.types[0], generic_mapping)
        return None

    def _specialize_type(self, typ: Type, generic_mapping: dict[str, Type]) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._specialize_type(unwrap_for_storage(typ), generic_mapping))
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if is_raw_pointer_type(typ):
            return Pointer(self._specialize_type(typ.pointee, generic_mapping))
        if not typ.generics and typ.name in generic_mapping:
            return generic_mapping[typ.name]
        return Type(typ.name, [self._specialize_type(generic, generic_mapping) for generic in typ.generics])

    def _collect_generic_mapping_from_types(self, pattern: Type, concrete: Type, mapping: dict[str, Type]) -> None:
        pattern = unwrap_for_storage(pattern)
        concrete = unwrap_for_storage(concrete)
        if isinstance(pattern, Pointer) and isinstance(concrete, Pointer):
            self._collect_generic_mapping_from_types(pattern.pointee, concrete.pointee, mapping)
            return
        if is_reference_like_type(pattern) and is_reference_like_type(concrete):
            self._collect_generic_mapping_from_types(pattern.pointee, concrete.pointee, mapping)
            return
        if not pattern.generics and pattern.name and pattern.name[:1].isupper():
            mapping.setdefault(pattern.name, concrete)
            return
        for left, right in zip(pattern.generics, concrete.generics):
            self._collect_generic_mapping_from_types(left, right, mapping)

    def _lookup_struct_field_types(self, typ: Type) -> list[Type]:
        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        struct_def = self._resolve_struct_definition(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return []
        generic_mapping = {generic.name: concrete for generic, concrete in zip(struct_def.generics, base_type.generics)}
        return [self._translate_type(self._specialize_type(field.type, generic_mapping)) for field in struct_def.fields]

    def _lookup_field_type(self, typ: Optional[Type], field: str) -> Optional[Type]:
        if typ is None:
            return None

        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        struct_def = self._resolve_struct_definition(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return None

        generic_mapping = {generic.name: concrete for generic, concrete in zip(struct_def.generics, base_type.generics)}
        for field_param in struct_def.fields:
            if field_param.name == field:
                return self._translate_type(self._specialize_type(field_param.type, generic_mapping))
        return None

    def _resolve_struct_definition(self, type_name: str) -> s.CLikeStructureDefinition | None:
        struct_def = self._structs.get(type_name)
        if isinstance(struct_def, s.CLikeStructureDefinition):
            return struct_def

        if "::" in type_name:
            return None

        matches = [
            definition
            for name, definition in self._structs.items()
            if isinstance(definition, s.CLikeStructureDefinition) and name.endswith(f"::{type_name}")
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _translate_type(self, typ: Type) -> Type:
        typ = unwrap_for_storage(typ)
        if isinstance(typ, AnySmartPointer):
            raise TypeError(
                f"Ambiguous smart pointer type '{typ}'. "
                "Use a concrete smart pointer ('T<H>' or 'T<S>') or let the type be inferred from initializer."
            )
        if is_tuple_type(typ):
            self._ensure_runtime_tuple_struct(tuple_arity(typ))
            return Type(typ.name, [self._translate_type(generic) for generic in typ.generics])
        if is_array_type(typ):
            self._ensure_runtime_array_struct(array_size(typ))
            return Type(typ.name, [self._translate_type(generic) for generic in typ.generics])
        if isinstance(typ, HeapSmartPointer):
            return Type("Box", [self._translate_type(typ.pointee)])
        if isinstance(typ, StackSmartPointer):
            return Type("Box", [self._translate_type(typ.pointee)])
        if is_raw_pointer_type(typ):
            return Pointer(self._translate_type(typ.pointee))
        if typ.name == "bool":
            return Usize_t(1)
        if typ.name == "usize":
            return Usize_t()
        if typ.name == "isize":
            return Isize_t()
        if typ.name == "str":
            return Str_t()
        if typ.name.startswith("u") and typ.name[1:].isdigit():
            return Usize_t(int(typ.name[1:]))
        if typ.name.startswith("i") and typ.name[1:].isdigit():
            return Isize_t(int(typ.name[1:]))
        if typ.name.startswith("f") and typ.name[1:].isdigit():
            return Float_t(int(typ.name[1:]))
        translated_name = self._type_aliases.get(typ.name, typ.name)
        return Type(translated_name, [self._translate_type(generic) for generic in typ.generics])

    def _contains_any_pointer(self, typ: Type) -> bool:
        if is_mutable_type(typ):
            return self._contains_any_pointer(unwrap_for_storage(typ))
        if isinstance(typ, AnySmartPointer):
            return True
        if isinstance(typ, (HeapSmartPointer, StackSmartPointer)):
            return self._contains_any_pointer(typ.pointee)
        if is_raw_pointer_type(typ):
            return self._contains_any_pointer(typ.pointee)
        return any(self._contains_any_pointer(generic) for generic in typ.generics)

    def _replace_any_pointer(self, typ: Type, pointer_cls: type[SmartPointer]) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._replace_any_pointer(unwrap_for_storage(typ), pointer_cls))
        if isinstance(typ, AnySmartPointer):
            return pointer_cls(self._replace_any_pointer(typ.pointee, pointer_cls))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._replace_any_pointer(typ.pointee, pointer_cls))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._replace_any_pointer(typ.pointee, pointer_cls))
        if is_raw_pointer_type(typ):
            return Pointer(self._replace_any_pointer(typ.pointee, pointer_cls))
        return Type(typ.name, [self._replace_any_pointer(generic, pointer_cls) for generic in typ.generics])

    def _signature_has_any_pointer(self, signature: s.FunctionSignature) -> bool:
        if signature.type is not None and self._contains_any_pointer(signature.type):
            return True
        return any(self._contains_any_pointer(param.type) for param in signature.params)

    def _specialize_signature_any_pointer(
        self, signature: s.FunctionSignature, pointer_cls: type[SmartPointer]
    ) -> s.FunctionSignature:
        params = [replace(param, type=self._replace_any_pointer(param.type, pointer_cls)) for param in signature.params]
        ret_type = None if signature.type is None else self._replace_any_pointer(signature.type, pointer_cls)
        return replace(signature, params=params, type=ret_type)

    def _resolve_any_pointer_call_name(self, fn_name: str, args: list[Variable]) -> str:
        variants = self._any_pointer_variants.get(fn_name)
        if not variants:
            return fn_name

        concrete_kind: type[Type] | None = None
        for arg in args:
            source_type = unwrap_for_storage(self._source_type_for_var(arg) or arg.type) if (self._source_type_for_var(arg) or arg.type) is not None else None
            if isinstance(source_type, HeapSmartPointer):
                if concrete_kind is not None and concrete_kind is not HeapSmartPointer:
                    raise TypeError(f"Mixed smart-pointer kinds in call '{fn_name}' are not supported yet")
                concrete_kind = HeapSmartPointer
            elif isinstance(source_type, StackSmartPointer):
                if concrete_kind is not None and concrete_kind is not StackSmartPointer:
                    raise TypeError(f"Mixed smart-pointer kinds in call '{fn_name}' are not supported yet")
                concrete_kind = StackSmartPointer

        if concrete_kind is None:
            raise TypeError(f"Unable to infer smart-pointer kind for call '{fn_name}'")
        return variants.get(concrete_kind, fn_name)

    def _resolve_function_call_target(self, expr: s.Expression_Call) -> tuple[str, list[Type]]:
        call_name = self._function_aliases.get(expr.name, expr.name)
        explicit_generics = list(expr.generics)
        if call_name in self._funcs or call_name in self._extern_fns:
            return call_name, explicit_generics

        if len(expr.callee.segments) >= 2:
            owner_segments = expr.callee.segments[:-1]
            owner = owner_segments[-1]
            normalized_owner = "::".join(segment.name for segment in owner_segments)
            normalized_name = f"{normalized_owner}::{expr.callee.segments[-1].name}"
            mapped_name = self._function_aliases.get(normalized_name, normalized_name)
            if mapped_name in self._funcs or mapped_name in self._extern_fns:
                if owner.generics:
                    if explicit_generics:
                        raise TypeError(
                            "Associated function generics must be specified either on the owner type or on the call"
                        )
                    explicit_generics = list(owner.generics)
                return mapped_name, explicit_generics

        return call_name, explicit_generics

    def _types_compatible(self, lhs: Type, rhs: Type) -> bool:
        if is_mutable_type(lhs) and not is_mutable_type(rhs):
            return False
        lhs = unwrap_for_storage(lhs)
        rhs = unwrap_for_storage(rhs)
        if isinstance(lhs, AnySmartPointer):
            if not is_reference_like_type(rhs):
                return False
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if isinstance(rhs, AnySmartPointer):
            if not is_reference_like_type(lhs):
                return False
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if isinstance(lhs, HeapSmartPointer) and isinstance(rhs, HeapSmartPointer):
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if isinstance(lhs, StackSmartPointer) and isinstance(rhs, StackSmartPointer):
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if is_raw_pointer_type(lhs) and is_raw_pointer_type(rhs):
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if is_reference_like_type(lhs) or is_reference_like_type(rhs):
            return False
        if is_raw_pointer_type(lhs) or is_raw_pointer_type(rhs):
            return False
        if lhs.name != rhs.name:
            return False
        if len(lhs.generics) != len(rhs.generics):
            return False
        for lg, rg in zip(lhs.generics, rhs.generics):
            if not self._types_compatible(lg, rg):
                return False
        return True

    @staticmethod
    def _infer_int_size(expected_type: Optional[Type]) -> int:
        if expected_type is None:
            return 32

        expected_type = unwrap_for_storage(expected_type)
        base_type = expected_type.pointee if is_reference_like_type(expected_type) else expected_type
        if base_type.name == "usize":
            return 32
        if base_type.name == "isize":
            return 32
        if base_type.name[1:].isdigit() and base_type.name[0] in ("u", "i"):
            return int(base_type.name[1:])
        return 32

    @staticmethod
    def _infer_float_size(expected_type: Optional[Type]) -> int:
        if expected_type is None:
            return 64
        expected_type = unwrap_for_storage(expected_type)
        base_type = expected_type.pointee if is_reference_like_type(expected_type) else expected_type
        if base_type.name.startswith("f") and base_type.name[1:].isdigit():
            return int(base_type.name[1:])
        return 64

    @classmethod
    def _build_integer_primitive(cls, value: int, expected_type: Optional[Type]):
        if expected_type is None:
            return Isize(value, size=32)

        expected_type = unwrap_for_storage(expected_type)
        base_type = expected_type.pointee if is_reference_like_type(expected_type) else expected_type
        if base_type.name == "usize":
            return Usize(value)
        if base_type.name == "isize":
            return Isize(value)
        if base_type.name.startswith("u") and base_type.name[1:].isdigit():
            return Usize(value, size=int(base_type.name[1:]))
        if base_type.name.startswith("i") and base_type.name[1:].isdigit():
            return Isize(value, size=int(base_type.name[1:]))
        return Isize(value, size=32)
