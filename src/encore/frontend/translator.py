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
from ehir.core.enum import Enum, EnumVariant
from ehir.core.instructions.base import Assignable
from ehir.core.instructions.capture import (
    Instruction_cpos,
    Instruction_lceos,
    Instruction_lcsos,
    Instruction_scsoh,
    Instruction_scsos,
)
from ehir.core.instructions.control_flow import MatchCase
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_load,
    Instruction_salloc,
    Instruction_sgetfieldptr,
    Instruction_store,
)
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mod,
    Instruction_mul,
    Instruction_sub,
)
from ehir.core.instructions.operators.base import BinOp
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
    is_mutable_type,
    is_reference_like_type,
    make_mutable_type,
    unwrap_for_storage,
)

MatchArmLike = s.Statement_MatchArm | s.Expression_MatchArm
MatchBodyArmLike = s.Statement_MatchArm | s.Expression_MatchArm

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
    "+": "add",
    "-": "sub",
    "*": "mul",
    "/": "div",
    "%": "mod",
    "&": "and",
    "|": "or",
    "^": "xor",
    "<<": "shl",
    ">>": "shr",
    "==": "ieq",
    "!=": "neq",
    "<": "les",
    "<=": "leq",
    ">": "grt",
    ">=": "geq",
}


class Translator:
    _funcs: dict[str, Derective_fn | Derective_extern_fn]
    _enums: dict[str, Derective_enum]
    _structs: dict[str, Derective_struct]
    _traits: dict[str, s.Statement_Trait]
    _impl_traits: dict[str, list[str]]
    _builder: EHIR_Builder
    _module: EHIR_Module
    _enum_payload_structs: dict[str, list[s.CLikeStructureDefinition]]
    _emitted_structs: set[str]
    _any_pointer_variants: dict[str, dict[type[Type], str]]

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
        ):
            self.scrutinee = scrutinee
            self.base_var_vals = base_var_vals
            self.base_var_ptrs = base_var_ptrs
            self.end_block = end_block
            self.default_block = default_block
            self.wildcard_arm = wildcard_arm
            self.arm_blocks = arm_blocks
            self.arm_payload_types = arm_payload_types

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
        self._terminated_blocks: set[str] = set()
        self._var_vals: dict[str, Variable] = {}
        self._var_ptrs: dict[str, Variable] = {}
        self._assignment_targets: dict[str, str] = {}
        self._funcs = {}
        self._enums = {}
        self._structs = {}
        self._extern_fns = {}
        self._traits = {}
        self._impl_traits = {}
        self._unsafe_depth = 0
        self._enum_payload_structs = {}
        self._emitted_structs = set()
        self._current_self_type: Type | None = None
        self._any_pointer_variants = {}

    def run(self, program: str) -> EHIR_Module:
        self._reset_state()
        tokens = self._lexer.parse(program)
        ast = self._parser.parse(tokens)
        TypeInferer().infer(ast)
        return self.translate_ast(ast)

    def translate_ast(self, ast: list[s.Statement]) -> EHIR_Module:
        self.preload_declarations([statement for statement in ast if isinstance(statement, s.Statement_TopLevel)])
        for statement in ast:
            self._translate_statement(statement)
        # print(self._module)
        # import time

        # time.sleep(0.5)
        return self._module

    def preload_declarations(self, statements: list[s.Statement_TopLevel]):
        for statement in statements:
            if isinstance(statement, s.Statement_StructureDefinition):
                self._structs[statement.signature.name] = self._normalize_struct_definition(statement.signature)
            elif isinstance(statement, s.Statement_FunctionDefinition):
                statement.signature = self._normalize_signature(statement.signature)
                if statement.signature.type is None:
                    continue
                if self._signature_has_any_pointer(statement.signature):
                    for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                        concrete_sig = self._specialize_signature_any_pointer(statement.signature, pointer_cls)
                        concrete_name = f"{statement.signature.name}{suffix}"
                        self._any_pointer_variants.setdefault(statement.signature.name, {})[pointer_cls] = concrete_name
                        self._funcs[concrete_name] = Derective_fn(
                            name=concrete_name,
                            generics=[self._translate_type(g) for g in concrete_sig.generics],
                            params=[
                                Parameter(name=param.name, type=self._translate_type(param.type))
                                for param in concrete_sig.params
                            ],
                            body=[],
                            ret_type=self._translate_type(concrete_sig.type),
                        )
                else:
                    self._funcs[statement.signature.name] = Derective_fn(
                        name=statement.signature.name,
                        generics=[self._translate_type(g) for g in statement.signature.generics],
                        params=[
                            Parameter(name=param.name, type=self._translate_type(param.type))
                            for param in statement.signature.params
                        ],
                        body=[],
                        ret_type=self._translate_type(statement.signature.type),
                    )
            elif isinstance(statement, s.Statement_EnumDefinition):
                self._enums[statement.name] = self._build_enum_directive(statement)
            elif isinstance(statement, s.FunctionSignature):
                self._extern_fns[statement.name] = statement
                self._funcs[statement.name] = Derective_extern_fn(
                    name=statement.name,
                    params=[
                        Parameter(name=param.name, type=self._translate_type(param.type)) for param in statement.params
                    ],
                    ret_type=self._translate_type(statement.type),
                )
            elif isinstance(statement, s.Statement_Trait):
                self._traits[statement.name] = statement
            elif isinstance(statement, s.Statement_Impl):
                struct_type = self._translate_type(statement.struct)
                if statement.trait_name is not None:
                    self._impl_traits.setdefault(struct_type.name, []).append(statement.trait_name)
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
                    self._funcs[normalized_signature.name] = Derective_fn(
                        name=normalized_signature.name,
                        generics=[self._translate_type(g) for g in normalized_signature.generics],
                        params=[
                            Parameter(name=param.name, type=self._translate_type(param.type))
                            for param in normalized_signature.params
                        ],
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
        self_type = unwrap_for_storage(self_type)
        if self_type.name == "Self" and not self_type.generics:
            return self._current_self_type or self_type
        return self_type

    def _resolve_self_in_type(self, typ: Type, self_type: Type | None) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._resolve_self_in_type(unwrap_for_storage(typ), self_type))
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
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

    def _resolve_method_callable(
        self,
        receiver_type: Type,
        method_name: str,
    ) -> tuple[str, Derective_fn | Derective_extern_fn]:
        receiver_type = unwrap_for_storage(receiver_type)
        base_receiver_type = receiver_type.pointee if is_reference_like_type(receiver_type) else receiver_type
        inherent_name = f"{base_receiver_type.name}::{method_name}"
        inherent_callee = self._funcs.get(inherent_name)
        if inherent_callee is not None:
            return inherent_name, inherent_callee

        for trait_name in self._impl_traits.get(base_receiver_type.name, []):
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
                    params=[
                        Parameter(name=param.name, type=self._translate_type(param.type)) for param in signature.params
                    ],
                    body=[],
                    ret_type=self._translate_type(signature.type),
                ),
            )

        raise TypeError(f"Method '{method_name}' is not defined for type '{base_receiver_type.name}'")

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
            params=[Parameter(name=param.name, type=self._translate_type(param.type)) for param in statement.params],
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
                            prefix=prefix + [pair.src], symbol="*"
                        )
                    case s.Statement_Import.ImportKind.SYMBOL:
                        (self._builder.build_cimp if is_public else self._builder.build_imp)(
                            prefix=prefix, symbol=pair.src
                        )
                    case s.Statement_Import.ImportKind.GLOB:
                        (self._builder.build_cimp if is_public else self._builder.build_imp)(prefix=prefix, symbol="*")
            case _:
                for dst in pair.dst:
                    self._translate_import_pair(prefix=prefix + [pair.src], pair=dst, is_public=is_public)

    def _translate_structure_definition(self, statement: s.Statement_StructureDefinition):
        definition = self._normalize_struct_definition(statement.signature)
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

    def _build_enum_directive(self, statement: s.Statement_EnumDefinition) -> Derective_enum:
        variants: list[EnumVariant] = []
        for variant in statement.body:
            if isinstance(variant, s.UnitStructureDefinition):
                variants.append(EnumVariant(name=variant.name))
                continue

            if isinstance(variant, s.TupleStructureDefinition):
                if len(variant.fields) <= 1:
                    payload_type = self._translate_type(variant.fields[0]) if variant.fields else None
                    variants.append(EnumVariant(name=variant.name, type=payload_type))
                    continue

                payload_struct = self._ensure_enum_payload_struct(statement, variant)
                payload_type = self._translate_type(Type(payload_struct.name, list(statement.generics)))
                variants.append(EnumVariant(name=variant.name, type=payload_type))
                continue

            if isinstance(variant, s.CLikeStructureDefinition):
                payload_struct = self._ensure_enum_payload_struct(statement, variant)
                payload_type = self._translate_type(Type(payload_struct.name, list(statement.generics)))
                variants.append(EnumVariant(name=variant.name, type=payload_type))
                continue

        return Derective_enum(
            name=statement.name,
            generics=[self._translate_type(generic) for generic in statement.generics],
            variants=variants,
        )

    def _ensure_enum_payload_struct(
        self, enum_statement: s.Statement_EnumDefinition, variant: s.Statement_StructureDefinition
    ) -> s.CLikeStructureDefinition:
        struct_name = f"{enum_statement.name}_{variant.name}_Payload"
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

        payloads = self._enum_payload_structs.setdefault(enum_statement.name, [])
        if all(definition.name != payload.name for definition in payloads):
            payloads.append(payload)
        return payload

    def _translate_enum_definition(self, statement: s.Statement_EnumDefinition):
        for payload_struct in self._enum_payload_structs.get(statement.name, []):
            self._emit_struct_definition(payload_struct)
        derective = self._build_enum_directive(statement)
        self._module.ast.append(derective)
        self._enums[statement.name] = derective
        return derective

    def _translate_trait_definition(self, statement: s.Statement_Trait):
        derective = self._builder.build_trait(
            name=statement.name,
            generics=[self._translate_type(g) for g in statement.generics],
            bounds={"Self": [base.name for base in statement.bases]} if statement.bases else {},
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
        self._traits[statement.name] = statement
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
                self._module.ast.append(self._translate_nested_function_definition(namespaced_method))
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
            trait_name=statement.trait_name,
            trait_args=[self._translate_type(arg) for arg in statement.trait_args],
            for_type=self._translate_type(statement.struct),
            generics=[self._translate_type(generic) for generic in statement.generics],
            methods=methods,
        )

    def _translate_function_definition(self, statement: s.Statement_FunctionDefinition):
        normalized_sig = self._normalize_signature(statement.signature)
        statement = replace(statement, signature=normalized_sig)
        if self._signature_has_any_pointer(statement.signature):
            emitted = None
            for pointer_cls, suffix in ((HeapSmartPointer, "__H"), (StackSmartPointer, "__S")):
                concrete_sig = self._specialize_signature_any_pointer(statement.signature, pointer_cls)
                concrete_stmt = replace(statement, signature=replace(concrete_sig, name=f"{statement.signature.name}{suffix}"))
                fn = self._translate_nested_function_definition(concrete_stmt)
                self._module.ast.append(fn)
                self._funcs[fn.name] = fn
                emitted = fn
            return emitted

        fn = self._translate_nested_function_definition(statement)
        self._module.ast.append(fn)
        self._funcs[statement.signature.name] = fn
        return fn

    def _translate_nested_function_definition(self, statement: s.Statement_FunctionDefinition) -> Derective_fn:
        statement = replace(statement, signature=self._normalize_signature(statement.signature))
        assert statement.signature.type is not None
        fn = Derective_fn(
            name=statement.signature.name,
            generics=[self._translate_type(g) for g in statement.signature.generics],
            params=[
                Parameter(name=param.name, type=self._translate_type(param.type))
                for param in statement.signature.params
            ],
            body=[],
            ret_type=self._translate_type(statement.signature.type),
        )
        self._translate_function_body(fn, statement.body)
        return fn

    def _translate_function_body(self, fn: Derective_fn, body: Block):
        prev_current_function = getattr(self._builder, "current_function", None)
        prev_current_block = getattr(self._builder, "current_block", None)
        prev_builder_variables = getattr(self._builder, "variables", {})
        prev_var_vals = self._var_vals
        prev_var_ptrs = self._var_ptrs
        prev_assignment_targets = self._assignment_targets
        prev_terminated_blocks = self._terminated_blocks
        prev_loop_stack = self._loop_stack
        prev_self_type = self._current_self_type

        self._builder.current_function = fn
        self._builder.variables = {param.name: param for param in fn.params}
        self._var_vals = {}
        self._var_ptrs = {}
        self._assignment_targets = {}
        self._terminated_blocks = set()
        self._loop_stack = []
        if fn.params and fn.params[0].name == "self":
            self_type = unwrap_for_storage(fn.params[0].type)
            self._current_self_type = self_type.pointee if is_reference_like_type(self_type) else self_type
        else:
            self._current_self_type = None
        entry_block = self._builder.append_block("entry")
        self._builder.position_at_end(entry_block)
        self._translate_block(body)

        if prev_current_function is not None:
            self._builder.current_function = prev_current_function
        if prev_current_block is not None:
            self._builder.current_block = prev_current_block
        self._builder.variables = prev_builder_variables
        self._var_vals = prev_var_vals
        self._var_ptrs = prev_var_ptrs
        self._assignment_targets = prev_assignment_targets
        self._terminated_blocks = prev_terminated_blocks
        self._loop_stack = prev_loop_stack
        self._current_self_type = prev_self_type

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

        elif isinstance(statement, s.Statement_If):
            return self._translate_if(statement)

        elif isinstance(statement, s.Statement_Match):
            return self._translate_match(statement)

        elif isinstance(statement, s.Statement_Unsafe):
            return self._translate_unsafe(statement)

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

        self._var_ptrs[statement.name] = slot_ptr

    def _translate_ret(self, statement: s.Statement_Ret):
        self._set_new_variable("ret")
        expected_type = None
        if hasattr(self._builder, "current_function"):
            expected_type = self._builder.current_function.ret_type
        expr = self._translate_expression(expr=statement.expr, expected_type=expected_type)
        self._builder.build_ret(expr.var_out)
        self._mark_current_block_terminated()

    def _translate_break(self, statement: s.Statement_Break):
        loop_ctx = self._resolve_loop_ctx(statement.label, keyword="break")
        self._builder.build_br(loop_ctx.break_target)
        self._mark_current_block_terminated()

    def _translate_continue(self, statement: s.Statement_Continue):
        loop_ctx = self._resolve_loop_ctx(statement.label, keyword="continue")
        self._builder.build_br(loop_ctx.continue_target)
        self._mark_current_block_terminated()

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
            return

        if isinstance(statement.target, s.Expression_StructField):
            self._set_new_variable(statement.target.field)
            src = self._resolve_struct_field_chain(statement.target.name)
            dst_ptr = Variable(self._advance_variable())
            field = Variable(statement.target.field)
            if is_reference_like_type(src.type):
                self._builder._add(Instruction_sgetfieldptr(var_out=dst_ptr, src=src, field=field))
            else:
                self._builder._add(Instruction_getfieldptr(var_out=dst_ptr, src=src, field=field))

            val = self._translate_expression(
                assign_expr,
                expected_type=self._lookup_field_type(src.type, statement.target.field),
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

    def _translate_if(self, statement: s.Statement_If):
        if_id = self._if_counter
        self._if_counter += 1

        branch_count = len(statement.branches)
        branch_bodies = [self._builder.append_block(f"if_body_{if_id}_{idx}") for idx in range(branch_count)]
        cond_blocks = [self._builder.current_block] + [
            self._builder.append_block(f"if_cond_{if_id}_{idx}") for idx in range(1, branch_count)
        ]
        else_block = self._builder.append_block(f"if_else_{if_id}") if statement.else_body is not None else None
        end_block = self._builder.append_block(f"if_end_{if_id}")

        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)

        for idx, branch in enumerate(statement.branches):
            self._builder.position_at_end(cond_blocks[idx])
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)

            false_target = (
                cond_blocks[idx + 1].name
                if idx + 1 < branch_count
                else (else_block.name if else_block else end_block.name)
            )
            cond = self._translate_expression(branch.expr)
            self._builder.build_cbr(cond.var_out, branch_bodies[idx].name, false_target)
            self._mark_current_block_terminated()

            self._builder.position_at_end(branch_bodies[idx])
            self._translate_block(branch.body)
            if not self._is_current_block_terminated():
                self._builder.build_br(end_block.name)
                self._mark_current_block_terminated()

        if else_block is not None:
            assert statement.else_body
            self._builder.position_at_end(else_block)
            self._var_vals = dict(base_var_vals)
            self._var_ptrs = dict(base_var_ptrs)
            self._translate_block(statement.else_body)
            if not self._is_current_block_terminated():
                self._builder.build_br(end_block.name)
                self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        self._var_vals = dict(base_var_vals)
        self._var_ptrs = dict(base_var_ptrs)

    def _translate_match(self, statement: s.Statement_Match):
        match_id = self._if_counter
        self._if_counter += 1

        prepared = self._prepare_match(
            match_id=match_id,
            scrutinee_expr=statement.expr,
            arms=statement.arms,
            end_prefix="match_end",
            default_prefix="match_default",
            arm_prefix="match_arm",
        )

        for idx, arm in enumerate(statement.arms):
            if arm.is_wildcard:
                continue

            self._builder.position_at_end(prepared.arm_blocks[idx])
            self._var_vals = dict(prepared.base_var_vals)
            self._var_ptrs = dict(prepared.base_var_ptrs)
            payload_type = prepared.arm_payload_types[idx]

            if arm.binding is not None and payload_type is not None:
                self._var_vals[arm.binding] = Variable(arm.binding, payload_type)

            self._translate_block(arm.body)
            if not self._is_current_block_terminated():
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()

        if prepared.wildcard_arm is not None:
            self._builder.position_at_end(prepared.default_block)
            self._var_vals = dict(prepared.base_var_vals)
            self._var_ptrs = dict(prepared.base_var_ptrs)
            self._translate_block(prepared.wildcard_arm.body)
            if not self._is_current_block_terminated():
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()

        self._builder.position_at_end(prepared.end_block)
        self._var_vals = dict(prepared.base_var_vals)
        self._var_ptrs = dict(prepared.base_var_ptrs)

    def _resolve_match_arm(self, scrutinee_type: Type, arm: s.Statement_MatchArm) -> tuple[str, int, Optional[Type]]:
        if arm.is_wildcard:
            raise TypeError("Wildcard arm has no explicit variant")
        return self._resolve_match_arm_common(scrutinee_type, arm)

    def _resolve_match_arm_common(self, scrutinee_type: Type, arm: MatchArmLike) -> tuple[str, int, Optional[Type]]:
        scrutinee_type = unwrap_for_storage(scrutinee_type)
        base_type = scrutinee_type.pointee if is_reference_like_type(scrutinee_type) else scrutinee_type
        enum = self._enums.get(base_type.name)
        if enum is None:
            raise TypeError(f"Match expression must be an enum, got {scrutinee_type}")
        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum.generics, base_type.generics)}

        assert arm.pattern is not None
        if len(arm.pattern.segments) == 1:
            variant_name = arm.pattern.segments[0].name
        elif len(arm.pattern.segments) == 2:
            explicit_enum = arm.pattern.segments[0]
            if explicit_enum.name != base_type.name:
                raise TypeError(f"Pattern enum '{explicit_enum.name}' does not match scrutinee type '{base_type.name}'")
            if explicit_enum.generics and explicit_enum != base_type:
                raise TypeError(f"Pattern enum '{explicit_enum}' does not match scrutinee type '{base_type}'")
            variant_name = arm.pattern.segments[1].name
        else:
            raise TypeError(f"Unsupported match pattern: {arm.pattern}")

        for idx, variant in enumerate(enum.variants):
            if variant.name == variant_name:
                payload_type = None if variant.type is None else self._specialize_type(variant.type, generic_mapping)
                return variant_name, idx, payload_type

        raise TypeError(f"Unknown variant '{variant_name}' for enum '{enum.name}'")

    def _translate_expression(
        self,
        expr: s.Statement_Expression,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        if isinstance(expr, s.Expression_BooleanLiteral):
            return self._builder.build_lcpos(prim=Usize(int(expr.value), size=1), name=name)

        elif isinstance(expr, s.Expression_StringLiteral):
            return self._builder.build_lcpos(prim=Str(expr.value), name=name)

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
                    return self._builder.build_lcpos(prim=prim, name=name)
            prim = self._build_integer_primitive(int(expr.value), int_expected)
            return self._builder.build_lcpos(prim=prim, name=name)

        elif isinstance(expr, s.Expression_FloatLiteral):
            return self._builder.build_lcpos(
                prim=Float(
                    float(expr.value),
                    size=self._infer_float_size(expr.literal_type or expected_type),
                ),
                name=name,
            )

        elif isinstance(expr, s.Expression_Path):
            if len(expr.segments) == 1:
                ptr = self._var_ptrs.get(expr.name)
                if ptr is not None:
                    return self._build_load_from_ptr(ptr, name=name)
                if expr.name in self._var_vals:
                    return Assignable(self._var_vals[expr.name])
                if self._current_self_type is not None and self._lookup_field_type(self._current_self_type, expr.name):
                    return self._translate_expression(
                        s.Expression_StructField("self", expr.name),
                        name=name,
                        expected_type=expected_type,
                    )
                return self._builder.get_var(expr.name)

            enum_expr = self._build_enum_from_path(expr)
            if enum_expr is not None:
                out = Variable(name or self._advance_variable())
                self._builder._add(Instruction_lceos(var_out=out, enum=enum_expr))
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

        elif isinstance(expr, s.Expression_Match):
            return self._translate_match_expression(expr, name=name, expected_type=expected_type)

        elif isinstance(expr, s.Expression_BinaryOperation):
            if expr.operator in ("&&", "||"):
                return self._translate_short_circuit_logical(expr, name=name)

            lhs = self._translate_expression(expr.lhs, expected_type=expected_type)
            rhs = self._translate_expression(expr.rhs, expected_type=lhs.var_out.type or expected_type)
            return self._builder.build_binop(OPERATOR_MAPPING[expr.operator], lhs.var_out, rhs.var_out, name)

        elif isinstance(expr, s.Expression_UnaryOperation):
            if expr.operator in ("!", "not"):
                operand = self._translate_expression(expr.expr)
                zero = self._builder.build_lcpos(prim=Usize(0, size=1))
                return self._builder.build_binop("ieq", operand.var_out, zero.var_out, name)
            raise NotImplementedError(f"Translation for unary operator '{expr.operator}' is not implemented.")

        elif isinstance(expr, s.Expression_Try):
            return self._translate_try_expression(expr, name=name)

        elif isinstance(expr, s.Expression_Parenthesized):
            return self._translate_expression(expr.expr, name=name, expected_type=expected_type)

        elif isinstance(expr, s.Expression_StructInitialization):
            target_struct_type = self._translate_type(expr.name)
            field_types = self._lookup_struct_field_types(target_struct_type)
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
            field_type_raw = self._lookup_field_type(src.type, expr.field)
            field_type = self._translate_type(field_type_raw) if field_type_raw is not None else None
            if is_reference_like_type(src.type):
                instr = self._builder.build_sgetfield(src=src, field=field)
                if field_type is not None:
                    instr.var_out.type = field_type
                return instr

            instr = Instruction_getfield(var_out=Variable(name or self._advance_variable()), src=src, field=field)
            if field_type is not None:
                instr.var_out.type = field_type
            self._builder._add(instr)
            return instr

        elif isinstance(expr, s.Expression_MethodCall):
            receiver = self._translate_expression(expr.receiver).var_out
            if receiver.type is None:
                raise TypeError(f"Unable to infer receiver type for method call '{expr.method}'")

            fn_name, callee = self._resolve_method_callable(receiver.type, expr.method)

            if fn_name in self._extern_fns and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{fn_name}' can only be called inside unsafe block")

            generics = [self._translate_type(g) for g in expr.generics]
            args = [receiver, *[self._translate_expression(arg_exp).var_out for arg_exp in expr.args]]
            call = self._builder.build_call(
                fn_name=fn_name,
                generics=generics,
                args=args,
                name=name,
                is_unsafe=fn_name in self._extern_fns and self._unsafe_depth > 0,
            )
            generic_mapping = {generic.name: concrete for generic, concrete in zip(callee.generics, generics)}
            call.var_out.type = self._specialize_type(callee.ret_type, generic_mapping)
            return call

        elif isinstance(expr, s.Expression_Call):
            enum_expr = self._build_enum_from_call(expr)
            if enum_expr is not None:
                out = Variable(name or self._advance_variable())
                self._builder._add(Instruction_lceos(var_out=out, enum=enum_expr))
                return Assignable(out)

            call_name = expr.name
            args = [self._translate_expression(arg_exp).var_out for arg_exp in expr.args]
            call_name = self._resolve_any_pointer_call_name(call_name, args)

            if call_name in self._extern_fns and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{expr.name}' can only be called inside unsafe block")

            generics = [self._translate_type(g) for g in expr.generics]
            call = self._builder.build_call(
                fn_name=call_name,
                generics=generics,
                args=args,
                name=name,
                is_unsafe=call_name in self._extern_fns and self._unsafe_depth > 0,
            )
            callee = self._funcs.get(call_name)
            if callee is not None:
                call.var_out.type = self._specialize_type(callee.ret_type, {})
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
            self._builder.build_lcpos(prim=Usize(0, size=1)).var_out,
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
        short_value = self._builder.build_lcpos(prim=Usize(0 if expr.operator == "&&" else 1, size=1)).var_out
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
        self._builder._add(Instruction_lceos(var_out=err_value, enum=err_enum))
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
        result_slot: Variable | None = None

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
        expr: s.Expression_Match,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        match_id = self._if_counter
        self._if_counter += 1

        prepared = self._prepare_match(
            match_id=match_id,
            scrutinee_expr=expr.expr,
            arms=expr.arms,
            end_prefix="match_expr_end",
            default_prefix="match_expr_default",
            arm_prefix="match_expr_arm",
        )
        result_name = name or self._advance_variable()
        result_type = expected_type
        result_slot: Variable | None = None

        for idx, arm in enumerate(expr.arms):
            if arm.is_wildcard:
                continue

            self._builder.position_at_end(prepared.arm_blocks[idx])
            self._var_vals = dict(prepared.base_var_vals)
            self._var_ptrs = dict(prepared.base_var_ptrs)

            payload_type = prepared.arm_payload_types[idx]
            if arm.binding is not None and payload_type is not None:
                self._var_vals[arm.binding] = Variable(arm.binding, payload_type)

            arm_result = self._translate_expression(arm.expr, expected_type=expected_type)
            result_type = result_type or arm_result.var_out.type
            if result_slot is None:
                assert result_type is not None
                result_slot = self._create_stack_slot(f"{result_name}_slot", arm_result.var_out, result_type)
            else:
                self._builder._add(Instruction_store(var_src=arm_result.var_out, var_dst=result_slot))
            self._builder.build_br(prepared.end_block.name)
            self._mark_current_block_terminated()

        if prepared.wildcard_arm is not None:
            self._builder.position_at_end(prepared.default_block)
            self._var_vals = dict(prepared.base_var_vals)
            self._var_ptrs = dict(prepared.base_var_ptrs)
            default_result = self._translate_expression(prepared.wildcard_arm.expr, expected_type=expected_type)
            result_type = result_type or default_result.var_out.type
            if result_slot is None:
                assert result_type is not None
                result_slot = self._create_stack_slot(f"{result_name}_slot", default_result.var_out, result_type)
            else:
                self._builder._add(Instruction_store(var_src=default_result.var_out, var_dst=result_slot))
            self._builder.build_br(prepared.end_block.name)
            self._mark_current_block_terminated()

        assert result_type is not None and result_slot is not None
        self._builder.position_at_end(prepared.end_block)
        self._var_vals = dict(prepared.base_var_vals)
        self._var_ptrs = dict(prepared.base_var_ptrs)
        return self._build_load_from_ptr(result_slot, name=result_name)

    def _prepare_match(
        self,
        *,
        match_id: int,
        scrutinee_expr: s.Statement_Expression,
        arms: list[MatchBodyArmLike],
        end_prefix: str,
        default_prefix: str,
        arm_prefix: str,
    ) -> _PreparedMatch:
        scrutinee = self._translate_expression(scrutinee_expr)
        if scrutinee.var_out.type is None:
            current_fn = getattr(self._builder.current_function, "name", "<unknown>")
            raise TypeError(
                f"Unable to infer match scrutinee type in '{current_fn}' for expression: {scrutinee_expr!r}"
            )
        base_var_vals = dict(self._var_vals)
        base_var_ptrs = dict(self._var_ptrs)
        end_block = self._builder.append_block(f"{end_prefix}_{match_id}")
        wildcard_arm = next((arm for arm in arms if arm.is_wildcard), None)
        default_block = (
            self._builder.append_block(f"{default_prefix}_{match_id}") if wildcard_arm is not None else end_block
        )

        arm_blocks: dict[int, object] = {}
        arm_payload_types: dict[int, Type | None] = {}
        cases: list[MatchCase] = []
        for idx, arm in enumerate(arms):
            if arm.is_wildcard:
                continue
            arm_blocks[idx] = self._builder.append_block(f"{arm_prefix}_{match_id}_{idx}")
            variant_name, _, payload_type = self._resolve_match_arm_common(scrutinee.var_out.type, arm)
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
        )

    def _resolve_expression_match_arm_translation(
        self, scrutinee_type: Type, arm: s.Expression_MatchArm
    ) -> tuple[str, int, Optional[Type]]:
        if arm.is_wildcard:
            raise TypeError("Wildcard arm has no explicit variant")
        return self._resolve_match_arm_common(scrutinee_type, arm)

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
        self._builder._add(Instruction_load(var_out=out, var=ptr))
        return Assignable(out)

    def _create_stack_slot(self, slot_name: str, value: Variable, value_type: Type) -> Variable:
        if isinstance(value_type, (Usize_t, Isize_t, Float_t, Str_t)):
            init_prim = self._zero_primitive(value_type)
            capture = Instruction_cpos(var_out=Variable(slot_name, Pointer(value_type)), primitive=init_prim)
            self._builder._add(capture)
            slot_ptr = capture.var_out
        else:
            slot_ptr = Variable(slot_name, Pointer(value_type))
            self._builder._add(Instruction_salloc(var_out=slot_ptr, type=value_type))

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

    def _resolve_struct_field_chain(self, name: str) -> Variable:
        parts = name.split(".")
        if not parts:
            return Variable(name)

        src = self._resolve_variable(parts[0])
        for segment in parts[1:]:
            field = Variable(segment)
            field_type = self._lookup_field_type(src.type, segment)
            if is_reference_like_type(src.type):
                instr = self._builder.build_sgetfield(src=src, field=field)
            else:
                instr = Instruction_getfield(var_out=Variable(self._advance_variable()), src=src, field=field)
                self._builder._add(instr)
            if field_type is not None:
                instr.var_out.type = field_type
            src = instr.var_out
        return src

    def _translate_struct_initialization(
        self, typ: Type, args: list[Variable], name: Optional[str] = None
    ) -> Assignable:
        struct = Struct(typ.name, typ.generics, args)
        out = Variable(name or self._advance_variable())

        if isinstance(typ, HeapSmartPointer):
            out.type = HeapSmartPointer(struct.as_type())
            self._builder._add(Instruction_scsoh(var_out=out, struct=struct))
            return Assignable(out)

        if isinstance(typ, StackSmartPointer):
            out.type = StackSmartPointer(struct.as_type())
            self._builder._add(Instruction_scsos(var_out=out, struct=struct))
            return Assignable(out)

        out.type = struct.as_type()
        self._builder._add(Instruction_lcsos(var_out=out, struct=struct))
        return Assignable(out)

    def _build_enum_from_path(self, expr: s.Expression_Path) -> Enum | None:
        if len(expr.segments) < 2:
            return None

        enum_type = expr.segments[0]
        variant_name = expr.segments[-1].name
        if len(expr.segments) != 2 or self._lookup_enum(enum_type) is None:
            return None

        return Enum(name=enum_type.name, generics=enum_type.generics, variant=variant_name)

    def _build_enum_from_call(self, expr: s.Expression_Call) -> Enum | None:
        if len(expr.callee.segments) != 2:
            return None

        enum_type = expr.callee.segments[0]
        variant_name = expr.callee.segments[1].name
        if self._lookup_enum(enum_type) is None:
            return None

        payload = None
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

            payload = Struct(name=payload_type.name, value=payload_var, type=payload_type)
        return Enum(name=enum_type.name, generics=enum_type.generics, variant=variant_name, payload=payload)

    def _lookup_enum(self, typ: Type) -> Derective_enum | None:
        return self._enums.get(typ.name)

    def _lookup_enum_variant_type(self, enum_type: Type, variant_name: str) -> Optional[Type]:
        enum_def = self._lookup_enum(enum_type)
        if enum_def is None:
            return None

        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, enum_type.generics)}
        for variant in enum_def.variants:
            if variant.name == variant_name:
                if variant.type is None:
                    return None
                return self._specialize_type(variant.type, generic_mapping)
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
        if not typ.generics and typ.name in generic_mapping:
            return generic_mapping[typ.name]
        return Type(typ.name, [self._specialize_type(generic, generic_mapping) for generic in typ.generics])

    def _lookup_struct_field_types(self, typ: Type) -> list[Type]:
        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        struct_def = self._structs.get(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return []
        return [self._translate_type(field.type) for field in struct_def.fields]

    def _lookup_field_type(self, typ: Optional[Type], field: str) -> Optional[Type]:
        if typ is None:
            return None

        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        struct_def = self._structs.get(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return None

        for field_param in struct_def.fields:
            if field_param.name == field:
                return self._translate_type(field_param.type)
        return None

    def _translate_type(self, typ: Type) -> Type:
        typ = unwrap_for_storage(typ)
        if isinstance(typ, AnySmartPointer):
            raise TypeError(
                f"Ambiguous smart pointer type '{typ}'. "
                "Use a concrete smart pointer ('T<H>' or 'T<S>') or let the type be inferred from initializer."
            )
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._translate_type(typ.pointee))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._translate_type(typ.pointee))
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
        return Type(typ.name, [self._translate_type(generic) for generic in typ.generics])

    def _contains_any_pointer(self, typ: Type) -> bool:
        if is_mutable_type(typ):
            return self._contains_any_pointer(unwrap_for_storage(typ))
        if isinstance(typ, AnySmartPointer):
            return True
        if isinstance(typ, (HeapSmartPointer, StackSmartPointer)):
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
            if isinstance(arg.type, HeapSmartPointer):
                if concrete_kind is not None and concrete_kind is not HeapSmartPointer:
                    raise TypeError(f"Mixed smart-pointer kinds in call '{fn_name}' are not supported yet")
                concrete_kind = HeapSmartPointer
            elif isinstance(arg.type, StackSmartPointer):
                if concrete_kind is not None and concrete_kind is not StackSmartPointer:
                    raise TypeError(f"Mixed smart-pointer kinds in call '{fn_name}' are not supported yet")
                concrete_kind = StackSmartPointer

        if concrete_kind is None:
            raise TypeError(f"Unable to infer smart-pointer kind for call '{fn_name}'")
        return variants.get(concrete_kind, fn_name)

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
        if is_reference_like_type(lhs) or is_reference_like_type(rhs):
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
