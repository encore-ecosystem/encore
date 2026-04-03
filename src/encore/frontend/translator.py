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
from ehir.core.instructions.capture import Instruction_lceos, Instruction_lcsos, Instruction_scsoh, Instruction_scsos
from ehir.core.instructions.control_flow import MatchCase
from ehir.core.instructions.control_flow.phi import PhiPair
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
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
from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter, Variable

from encore.frontend.inference import TypeInferer
from encore.frontend.lexer import Lexer
from encore.frontend.parser import Parser
from encore.frontend.parser import statements as s
from encore.frontend.parser.statements import Block

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


class Translator:
    _funcs: dict[str, Derective_fn | Derective_extern_fn]
    _enums: dict[str, Derective_enum]
    _structs: dict[str, Derective_struct]
    _traits: dict[str, s.Statement_Trait]
    _builder: EHIR_Builder
    _module: EHIR_Module
    _enum_payload_structs: dict[str, list[s.CLikeStructureDefinition]]
    _emitted_structs: set[str]

    class _PreparedMatch:
        def __init__(
            self,
            *,
            scrutinee: Assignable,
            base_var_vals: dict[str, Variable],
            end_block,
            default_block,
            wildcard_arm: MatchBodyArmLike | None,
            arm_blocks: dict[int, object],
            arm_payload_types: dict[int, Type | None],
        ):
            self.scrutinee = scrutinee
            self.base_var_vals = base_var_vals
            self.end_block = end_block
            self.default_block = default_block
            self.wildcard_arm = wildcard_arm
            self.arm_blocks = arm_blocks
            self.arm_payload_types = arm_payload_types

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
        self._loop_stack: list[dict[str, object]] = []
        self._terminated_blocks: set[str] = set()
        self._var_vals: dict[str, Variable] = {}
        self._assignment_targets: dict[str, str] = {}
        self._funcs = {}
        self._enums = {}
        self._structs = {}
        self._extern_fns = {}
        self._traits = {}
        self._unsafe_depth = 0
        self._enum_payload_structs = {}
        self._emitted_structs = set()

    def run(self, program: str) -> EHIR_Module:
        self._reset_state()
        tokens = self._lexer.tokenize(program)
        ast = self._parser.parse(tokens)
        TypeInferer().infer(ast)
        return self.translate_ast(ast)

    def translate_ast(self, ast: list[s.Statement]) -> EHIR_Module:
        self.preload_declarations([statement for statement in ast if isinstance(statement, s.Statement_TopLevel)])
        for statement in ast:
            self._translate_statement(statement)

        return self._module

    def preload_declarations(self, statements: list[s.Statement_TopLevel]):
        for statement in statements:
            if isinstance(statement, s.Statement_StructureDefinition):
                self._structs[statement.defi.name] = self._normalize_struct_definition(statement.defi)
            elif isinstance(statement, s.Statement_FunctionDefinition):
                if statement.signature.type is None:
                    continue
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
            elif isinstance(statement, s.Statement_Impl) and statement.trait_name is None:
                struct_type = self._translate_type(statement.struct)
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

                    namespaced_name = f"{struct_type.name}::{method.name}"
                    self._funcs[namespaced_name] = Derective_fn(
                        name=namespaced_name,
                        generics=[self._translate_type(g) for g in merged_method_generics],
                        params=[
                            Parameter(name=param.name, type=self._translate_type(param.type)) for param in method.params
                        ],
                        body=[],
                        ret_type=self._translate_type(method.type),
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

    def _normalize_struct_definition(self, definition: s.Statement_StructureDefinition) -> s.CLikeStructureDefinition:
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
        definition = self._normalize_struct_definition(statement.defi)
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

                namespaced_method = s.Statement_FunctionDefinition(
                    is_public=method.is_public,
                    name=f"{struct_type.name}::{method.name}",
                    generics=merged_method_generics,
                    params=method.params,
                    type=method.type,
                    body=method.body,
                )
                self._module.ast.append(self._translate_nested_function_definition(namespaced_method))
            return None

        methods = [self._translate_nested_function_definition(method) for method in statement.body]
        return self._builder.build_impl(
            trait_name=statement.trait_name,
            trait_args=[self._translate_type(arg) for arg in statement.trait_args],
            for_type=self._translate_type(statement.struct),
            generics=[self._translate_type(generic) for generic in statement.generics],
            methods=methods,
        )

    def _translate_function_definition(self, statement: s.Statement_FunctionDefinition):
        fn = self._translate_nested_function_definition(statement)
        self._module.ast.append(fn)
        self._funcs[statement.signature.name] = fn
        return fn

    def _translate_nested_function_definition(self, statement: s.Statement_FunctionDefinition) -> Derective_fn:
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
        prev_assignment_targets = self._assignment_targets
        prev_terminated_blocks = self._terminated_blocks
        prev_loop_stack = self._loop_stack

        self._builder.current_function = fn
        self._builder.variables = {param.name: param for param in fn.params}
        self._var_vals = {}
        self._assignment_targets = {}
        self._terminated_blocks = set()
        self._loop_stack = []
        entry_block = self._builder.append_block("entry")
        self._builder.position_at_end(entry_block)
        self._translate_block(body)

        if prev_current_function is not None:
            self._builder.current_function = prev_current_function
        if prev_current_block is not None:
            self._builder.current_block = prev_current_block
        self._builder.variables = prev_builder_variables
        self._var_vals = prev_var_vals
        self._assignment_targets = prev_assignment_targets
        self._terminated_blocks = prev_terminated_blocks
        self._loop_stack = prev_loop_stack

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
        val = self._translate_expression(statement.expr, name=statement.name, expected_type=expected_type)
        if val.var_out.type is None:
            val.var_out.type = expected_type
        self._var_vals[statement.name] = val.var_out

    def _translate_ret(self, statement: s.Statement_Ret):
        self._set_new_variable("ret")
        expected_type = None
        if hasattr(self._builder, "current_function"):
            expected_type = self._builder.current_function.ret_type
        expr = self._translate_expression(expr=statement.expr, expected_type=expected_type)
        self._builder.build_ret(expr.var_out)
        self._mark_current_block_terminated()

    def _translate_break(self, statement: s.Statement_Break):
        if not self._loop_stack:
            raise ValueError("break used outside of a loop")

        loop_ctx = self._loop_stack[-1]
        break_inputs = loop_ctx["break_inputs"]
        loop_vars = loop_ctx["loop_vars"]
        current_block = self._builder.current_block.name
        loop_ctx["break_blocks"].append(current_block)  # ty:ignore[unresolved-attribute]

        for var, pairs in break_inputs.items():  # ty:ignore[unresolved-attribute]
            pairs.append(PhiPair(self._var_vals.get(var, loop_vars[var]), current_block))  # ty:ignore[not-subscriptable]

        self._builder.build_br(loop_ctx["break_target"])  # ty:ignore[invalid-argument-type]
        self._mark_current_block_terminated()

    def _translate_continue(self, statement: s.Statement_Continue):
        if not self._loop_stack:
            raise ValueError("continue used outside of a loop")

        loop_ctx = self._loop_stack[-1]
        self._builder.build_br(loop_ctx["continue_target"])  # ty:ignore[invalid-argument-type]
        self._mark_current_block_terminated()

    def _translate_assignment(self, statement: s.Statement_Assignment):
        assign_expr = self._assignment_expr(statement)

        if isinstance(statement.target, s.Expression_Path) and len(statement.target.segments) == 1:
            target_name = self._assignment_targets.get(statement.name, statement.name)
            self._set_new_variable(target_name)
            expected_type = self._resolve_variable(statement.name).type
            val = self._translate_expression(
                assign_expr,
                name=target_name,
                expected_type=expected_type,
            )
            if val.var_out.type is None:
                val.var_out.type = expected_type
            self._var_vals[statement.name] = val.var_out
            return

        if isinstance(statement.target, s.Expression_StructField):
            self._set_new_variable(statement.target.field)
            src = self._resolve_struct_field_chain(statement.target.name)
            dst_ptr = Variable(self._advance_variable())
            field = Variable(statement.target.field)
            if isinstance(src.type, (HeapSmartPointer, StackSmartPointer)):
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

        modified = self._collect_assignments(statement.body) & self._var_vals.keys()

        phi_names: dict[str, tuple[str, str]] = {}
        entry_vals: dict[str, Variable] = {}
        for var in modified:
            phi_names[var] = (f"{var}_phi_{while_id}", f"{var}_next_{while_id}")
            entry_vals[var] = self._var_vals[var]

        entry_block_name = self._builder.current_block.name
        self._builder.build_br(cond_block.name)

        self._builder.position_at_end(cond_block)
        phi_vars: dict[str, Variable] = {}
        for var, (phi_name, next_name) in phi_names.items():
            phi = self._builder.build_phi(
                phi_name,
                entry_vals[var].type,
                [
                    PhiPair(entry_vals[var], entry_block_name),
                    PhiPair(Variable(next_name), body_block.name),
                ],
            )
            self._var_vals[var] = phi.var_out
            phi_vars[var] = phi.var_out

        cond = self._translate_expression(statement.expr)
        self._builder.build_cbr(cond.var_out, body_block.name, end_block.name)

        self._builder.position_at_end(body_block)
        saved_targets = self._assignment_targets
        self._assignment_targets = {**saved_targets, **{var: next_name for var, (_, next_name) in phi_names.items()}}
        loop_ctx = {
            "break_target": end_block.name,
            "continue_target": cond_block.name,
            "break_inputs": {var: [] for var in modified},
            "break_blocks": [],
            "loop_vars": {var: phi_var for var, phi_var in phi_vars.items()},
        }
        self._loop_stack.append(loop_ctx)  # ty:ignore[invalid-argument-type]
        self._translate_block(statement.body)
        self._loop_stack.pop()
        self._assignment_targets = saved_targets
        if not self._is_current_block_terminated():
            self._builder.build_br(cond_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        for var, phi_var in phi_vars.items():
            break_inputs = loop_ctx["break_inputs"][var]
            if break_inputs:
                exit_phi = self._builder.build_phi(
                    f"{var}_exit_{while_id}",
                    entry_vals[var].type,
                    [PhiPair(phi_var, cond_block.name), *break_inputs],
                )
                self._var_vals[var] = exit_phi.var_out
            else:
                self._var_vals[var] = phi_var

    def _translate_do_while(self, statement: s.Statement_DoWhile):
        while_id = self._while_counter
        self._while_counter += 1

        body_block = self._builder.append_block(f"do_while_body_{while_id}")
        cond_block = self._builder.append_block(f"do_while_cond_{while_id}")
        end_block = self._builder.append_block(f"do_while_end_{while_id}")

        modified = self._collect_assignments(statement.body) & self._var_vals.keys()

        phi_names: dict[str, tuple[str, str]] = {}
        entry_vals: dict[str, Variable] = {}
        for var in modified:
            phi_names[var] = (f"{var}_phi_{while_id}", f"{var}_next_{while_id}")
            entry_vals[var] = self._var_vals[var]

        entry_block_name = self._builder.current_block.name
        self._builder.build_br(body_block.name)

        self._builder.position_at_end(body_block)
        phi_vars: dict[str, Variable] = {}
        for var, (phi_name, next_name) in phi_names.items():
            phi = self._builder.build_phi(
                phi_name,
                entry_vals[var].type,
                [
                    PhiPair(entry_vals[var], entry_block_name),
                    PhiPair(Variable(next_name), cond_block.name),
                ],
            )
            self._var_vals[var] = phi.var_out
            phi_vars[var] = phi.var_out

        saved_targets = self._assignment_targets
        self._assignment_targets = {**saved_targets, **{var: next_name for var, (_, next_name) in phi_names.items()}}
        loop_ctx = {
            "break_target": end_block.name,
            "continue_target": cond_block.name,
            "break_inputs": {var: [] for var in modified},
            "break_blocks": [],
            "loop_vars": {var: phi_var for var, phi_var in phi_vars.items()},
        }
        self._loop_stack.append(loop_ctx)  # ty:ignore[invalid-argument-type]
        self._translate_block(statement.body)
        self._loop_stack.pop()
        self._assignment_targets = saved_targets
        if not self._is_current_block_terminated():
            self._builder.build_br(cond_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(cond_block)
        for var, (_, next_name) in phi_names.items():
            self._var_vals[var] = Variable(next_name)

        cond = self._translate_expression(statement.expr)
        self._builder.build_cbr(cond.var_out, body_block.name, end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        for var in phi_vars:
            break_inputs = loop_ctx["break_inputs"][var]
            if break_inputs:
                exit_phi = self._builder.build_phi(
                    f"{var}_exit_{while_id}",
                    entry_vals[var].type,
                    [PhiPair(Variable(phi_names[var][1]), cond_block.name), *break_inputs],
                )
                self._var_vals[var] = exit_phi.var_out
            else:
                self._var_vals[var] = Variable(phi_names[var][1])

    def _translate_loop(self, statement: s.Statement_Loop):
        loop_id = self._while_counter
        self._while_counter += 1

        body_block = self._builder.append_block(f"loop_body_{loop_id}")
        latch_block = self._builder.append_block(f"loop_latch_{loop_id}")
        end_block = self._builder.append_block(f"loop_end_{loop_id}")

        modified = self._collect_assignments(statement.body) & self._var_vals.keys()

        phi_names: dict[str, tuple[str, str]] = {}
        entry_vals: dict[str, Variable] = {}
        for var in modified:
            phi_names[var] = (f"{var}_phi_{loop_id}", f"{var}_next_{loop_id}")
            entry_vals[var] = self._var_vals[var]

        entry_block_name = self._builder.current_block.name
        self._builder.build_br(body_block.name)

        self._builder.position_at_end(body_block)
        phi_vars: dict[str, Variable] = {}
        for var, (phi_name, next_name) in phi_names.items():
            phi = self._builder.build_phi(
                phi_name,
                entry_vals[var].type,
                [
                    PhiPair(entry_vals[var], entry_block_name),
                    PhiPair(Variable(next_name), latch_block.name),
                ],
            )
            self._var_vals[var] = phi.var_out
            phi_vars[var] = phi.var_out

        saved_targets = self._assignment_targets
        self._assignment_targets = {**saved_targets, **{var: next_name for var, (_, next_name) in phi_names.items()}}
        loop_ctx = {
            "break_target": end_block.name,
            "continue_target": latch_block.name,
            "break_inputs": {var: [] for var in modified},
            "break_blocks": [],
            "loop_vars": {var: phi_var for var, phi_var in phi_vars.items()},
        }
        self._loop_stack.append(loop_ctx)  # ty:ignore[invalid-argument-type]
        self._translate_block(statement.body)
        self._loop_stack.pop()
        self._assignment_targets = saved_targets
        if not self._is_current_block_terminated():
            self._builder.build_br(latch_block.name)
            self._mark_current_block_terminated()

        self._builder.position_at_end(latch_block)
        for var, (_, next_name) in phi_names.items():
            self._var_vals[var] = Variable(next_name)
        self._builder.build_br(body_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        if not loop_ctx["break_blocks"]:
            self._mark_current_block_terminated()

        for var in phi_vars:
            break_inputs = loop_ctx["break_inputs"][var]
            if break_inputs:
                exit_phi = self._builder.build_phi(
                    f"{var}_exit_{loop_id}",
                    entry_vals[var].type,
                    break_inputs,
                )
                self._var_vals[var] = exit_phi.var_out

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
        modified = self._collect_if_assignments(statement) & base_var_vals.keys()
        phi_inputs: dict[str, list[PhiPair]] = {var: [] for var in modified}

        for idx, branch in enumerate(statement.branches):
            self._builder.position_at_end(cond_blocks[idx])
            self._var_vals = dict(base_var_vals)

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
                branch_exit = self._builder.current_block.name
                self._builder.build_br(end_block.name)
                self._mark_current_block_terminated()

                for var in modified:
                    phi_inputs[var].append(PhiPair(self._var_vals.get(var, base_var_vals[var]), branch_exit))

        if else_block is not None:
            assert statement.else_body
            self._builder.position_at_end(else_block)
            self._var_vals = dict(base_var_vals)
            self._translate_block(statement.else_body)
            if not self._is_current_block_terminated():
                else_exit = self._builder.current_block.name
                self._builder.build_br(end_block.name)
                self._mark_current_block_terminated()

                for var in modified:
                    phi_inputs[var].append(PhiPair(self._var_vals.get(var, base_var_vals[var]), else_exit))
        else:
            fallthrough_block = cond_blocks[-1].name
            for var in modified:
                phi_inputs[var].append(PhiPair(base_var_vals[var], fallthrough_block))

        self._builder.position_at_end(end_block)
        self._var_vals = dict(base_var_vals)
        for var, pairs in phi_inputs.items():
            phi = self._builder.build_phi(f"{var}_if_{if_id}", base_var_vals[var].type, pairs)
            self._var_vals[var] = phi.var_out

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
        modified = self._collect_match_assignments(statement) & prepared.base_var_vals.keys()
        phi_inputs: dict[str, list[PhiPair]] = {var: [] for var in modified}
        dispatch_block = self._builder.current_block.name

        for idx, arm in enumerate(statement.arms):
            if arm.is_wildcard:
                continue

            self._builder.position_at_end(prepared.arm_blocks[idx])
            self._var_vals = dict(prepared.base_var_vals)
            payload_type = prepared.arm_payload_types[idx]

            if arm.binding is not None and payload_type is not None:
                self._var_vals[arm.binding] = Variable(arm.binding, payload_type)

            self._translate_block(arm.body)
            if not self._is_current_block_terminated():
                arm_exit = self._builder.current_block.name
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()

                for var in modified:
                    phi_inputs[var].append(PhiPair(self._var_vals.get(var, prepared.base_var_vals[var]), arm_exit))

        if prepared.wildcard_arm is not None:
            self._builder.position_at_end(prepared.default_block)
            self._var_vals = dict(prepared.base_var_vals)
            self._translate_block(prepared.wildcard_arm.body)
            if not self._is_current_block_terminated():
                default_exit = self._builder.current_block.name
                self._builder.build_br(prepared.end_block.name)
                self._mark_current_block_terminated()

                for var in modified:
                    phi_inputs[var].append(PhiPair(self._var_vals.get(var, prepared.base_var_vals[var]), default_exit))

        self._builder.position_at_end(prepared.end_block)
        self._var_vals = dict(prepared.base_var_vals)
        if prepared.wildcard_arm is None:
            for var in modified:
                phi_inputs[var].append(PhiPair(prepared.base_var_vals[var], dispatch_block))
        for var, pairs in phi_inputs.items():
            phi = self._builder.build_phi(f"{var}_match_{match_id}", prepared.base_var_vals[var].type, pairs)
            self._var_vals[var] = phi.var_out

    def _collect_assignments(self, block: Block) -> set[str]:
        assigned: set[str] = set()
        for stmt in block.body:
            if isinstance(stmt, s.Statement_Assignment):
                if isinstance(stmt.target, s.Expression_Path) and len(stmt.target.segments) == 1:
                    assigned.add(stmt.name)
            elif isinstance(stmt, (s.Statement_While, s.Statement_Loop, s.Statement_DoWhile)):
                assigned |= self._collect_assignments(stmt.body)
            elif isinstance(stmt, s.Statement_If):
                assigned |= self._collect_if_assignments(stmt)
            elif isinstance(stmt, s.Statement_Match):
                assigned |= self._collect_match_assignments(stmt)
        return assigned

    def _collect_if_assignments(self, statement: s.Statement_If) -> set[str]:
        assigned: set[str] = set()
        for branch in statement.branches:
            assigned |= self._collect_assignments(branch.body)
        if statement.else_body is not None:
            assigned |= self._collect_assignments(statement.else_body)
        return assigned

    def _collect_match_assignments(self, statement: s.Statement_Match) -> set[str]:
        assigned: set[str] = set()
        for arm in statement.arms:
            assigned |= self._collect_assignments(arm.body)
        return assigned

    def _resolve_match_arm(self, scrutinee_type: Type, arm: s.Statement_MatchArm) -> tuple[str, int, Optional[Type]]:
        if arm.is_wildcard:
            raise TypeError("Wildcard arm has no explicit variant")
        return self._resolve_match_arm_common(scrutinee_type, arm)

    def _resolve_match_arm_common(self, scrutinee_type: Type, arm: MatchArmLike) -> tuple[str, int, Optional[Type]]:
        base_type = (
            scrutinee_type.pointee
            if isinstance(scrutinee_type, (HeapSmartPointer, StackSmartPointer))
            else scrutinee_type
        )
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
            prim = self._build_integer_primitive(int(expr.value), expr.literal_type or expected_type)
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
                if expr.name in self._var_vals:
                    return Assignable(self._var_vals[expr.name])
                return self._builder.get_var(expr.name)

            enum_expr = self._build_enum_from_path(expr)
            if enum_expr is not None:
                out = Variable(name or self._advance_variable())
                self._builder._add(Instruction_lceos(var_out=out, enum=enum_expr))
                return Assignable(out)

            raise NotImplementedError(f"Translation for path expression {expr.name} is not implemented.")

        # elif isinstance(expr, s.Expression_Block):
        #     return self._translate_expression_block(expr, name=name, expected_type=expected_type)

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

            lhs = self._translate_expression(expr.lhs)
            rhs = self._translate_expression(expr.rhs)

            match expr.operator:
                case "+":
                    return self._builder.build_add(lhs.var_out, rhs.var_out, name)
                case "-":
                    return self._builder.build_sub(lhs.var_out, rhs.var_out, name)
                case "*":
                    return self._builder.build_mul(lhs.var_out, rhs.var_out, name)
                case "/":
                    return self._builder.build_div(lhs.var_out, rhs.var_out, name)
                case "%":
                    return self._builder.build_mod(lhs.var_out, rhs.var_out, name)
                case "&":
                    return self._builder.build_and(lhs.var_out, rhs.var_out, name)
                case "|":
                    return self._builder.build_or(lhs.var_out, rhs.var_out, name)
                case "^":
                    return self._builder.build_xor(lhs.var_out, rhs.var_out, name)
                case "<<":
                    return self._builder.build_shl(lhs.var_out, rhs.var_out, name)
                case ">>":
                    return self._builder.build_shr(lhs.var_out, rhs.var_out, name)
                case "==":
                    return self._builder.build_ieq(lhs.var_out, rhs.var_out, name)
                case "!=":
                    return self._builder.build_neq(lhs.var_out, rhs.var_out, name)
                case "<":
                    return self._builder.build_les(lhs.var_out, rhs.var_out, name)
                case "<=":
                    return self._builder.build_leq(lhs.var_out, rhs.var_out, name)
                case ">":
                    return self._builder.build_grt(lhs.var_out, rhs.var_out, name)
                case ">=":
                    return self._builder.build_geq(lhs.var_out, rhs.var_out, name)
                case _:
                    raise NotImplementedError(f"Translation for binary operator {expr.operator} is not implemented.")

        elif isinstance(expr, s.Expression_UnaryOperation):
            if expr.operator in ("!", "not"):
                operand = self._translate_expression(expr.expr)
                zero = self._builder.build_lcpos(prim=Usize(0, size=1))
                return self._builder.build_ieq(operand.var_out, zero.var_out, name)
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
            if isinstance(src.type, (HeapSmartPointer, StackSmartPointer)):
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

            receiver_base_type = (
                receiver.type.pointee
                if isinstance(receiver.type, (HeapSmartPointer, StackSmartPointer))
                else receiver.type
            )
            fn_name = f"{receiver_base_type.name}::{expr.method}"
            callee = self._funcs.get(fn_name)
            if callee is None:
                raise TypeError(f"Method '{expr.method}' is not defined for type '{receiver_base_type.name}'")

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

            if expr.name in self._extern_fns and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{expr.name}' can only be called inside unsafe block")

            generics = [self._translate_type(g) for g in expr.generics]
            args = [self._translate_expression(arg_exp).var_out for arg_exp in expr.args]
            call = self._builder.build_call(
                fn_name=expr.name,
                generics=generics,
                args=args,
                name=name,
                is_unsafe=expr.name in self._extern_fns and self._unsafe_depth > 0,
            )
            callee = self._funcs.get(expr.name)
            if callee is not None:
                call.var_out.type = self._specialize_type(callee.ret_type, {})
            return call

        raise NotImplementedError(f"Translation for expression type {type(expr)} is not implemented.")

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
        rhs_exit = self._builder.current_block.name
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(short_block)
        short_value = self._builder.build_lcpos(prim=Usize(0 if expr.operator == "&&" else 1, size=1)).var_out
        short_exit = self._builder.current_block.name
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()

        self._builder.position_at_end(end_block)
        result = self._builder.build_phi(
            name or self._advance_variable(),
            Usize_t(1),
            [PhiPair(rhs_cond, rhs_exit), PhiPair(short_value, short_exit)],
        )
        return Assignable(result.var_out)

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
        base_result_type = (
            result_type.pointee if isinstance(result_type, (HeapSmartPointer, StackSmartPointer)) else result_type
        )
        if base_result_type.name != "Result" or len(base_result_type.generics) != 2:
            raise TypeError(f"'?' operator expects Result[T, E], got {result_type}")
        ok_type, err_type = base_result_type.generics
        ok_type = self._translate_type(ok_type)
        err_type = self._translate_type(err_type)

        current_fn = getattr(self._builder, "current_function", None)
        if current_fn is None:
            raise TypeError("'?' operator can only be used inside a function")
        fn_ret_type = current_fn.ret_type
        base_fn_ret_type = (
            fn_ret_type.pointee if isinstance(fn_ret_type, (HeapSmartPointer, StackSmartPointer)) else fn_ret_type
        )
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
        block: Block,
        name: Optional[str] = None,
        expected_type: Optional[Type] = None,
    ) -> Assignable:
        outer_var_vals = self._var_vals
        outer_assignment_targets = self._assignment_targets
        self._var_vals = dict(self._var_vals)
        self._assignment_targets = dict(self._assignment_targets)

        try:
            for statement in block.body[:-1]:
                self._translate_expression_block_statement(statement)
            return self._translate_expression(block.body[-1], name=name, expected_type=expected_type)
        finally:
            self._var_vals = outer_var_vals
            self._assignment_targets = outer_assignment_targets

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
        phi_pairs: list[PhiPair] = []
        result_name = name or self._advance_variable()
        result_type = expected_type

        for idx, branch in enumerate(expr.branches):
            self._builder.position_at_end(cond_blocks[idx])
            self._var_vals = dict(base_var_vals)

            false_target = cond_blocks[idx + 1].name if idx + 1 < branch_count else else_block.name
            cond = self._translate_expression(branch.expr)
            self._builder.build_cbr(cond.var_out, branch_bodies[idx].name, false_target)
            self._mark_current_block_terminated()

            self._builder.position_at_end(branch_bodies[idx])
            branch_result = self._translate_expression(branch.body, expected_type=expected_type)
            result_type = result_type or branch_result.var_out.type
            branch_exit = self._builder.current_block.name
            self._builder.build_br(end_block.name)
            self._mark_current_block_terminated()
            phi_pairs.append(PhiPair(branch_result.var_out, branch_exit))

        self._builder.position_at_end(else_block)
        self._var_vals = dict(base_var_vals)
        else_result = self._translate_expression(expr.else_body, expected_type=expected_type)
        result_type = result_type or else_result.var_out.type
        else_exit = self._builder.current_block.name
        self._builder.build_br(end_block.name)
        self._mark_current_block_terminated()
        phi_pairs.append(PhiPair(else_result.var_out, else_exit))

        assert result_type is not None
        self._builder.position_at_end(end_block)
        self._var_vals = dict(base_var_vals)
        phi = self._builder.build_phi(result_name, result_type, phi_pairs)
        return Assignable(phi.var_out)

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
        phi_pairs: list[PhiPair] = []
        result_name = name or self._advance_variable()
        result_type = expected_type

        for idx, arm in enumerate(expr.arms):
            if arm.is_wildcard:
                continue

            self._builder.position_at_end(prepared.arm_blocks[idx])
            self._var_vals = dict(prepared.base_var_vals)

            payload_type = prepared.arm_payload_types[idx]
            if arm.binding is not None and payload_type is not None:
                self._var_vals[arm.binding] = Variable(arm.binding, payload_type)

            arm_result = self._translate_expression(arm.expr, expected_type=expected_type)
            result_type = result_type or arm_result.var_out.type
            arm_exit = self._builder.current_block.name
            self._builder.build_br(prepared.end_block.name)
            self._mark_current_block_terminated()
            phi_pairs.append(PhiPair(arm_result.var_out, arm_exit))

        if prepared.wildcard_arm is not None:
            self._builder.position_at_end(prepared.default_block)
            self._var_vals = dict(prepared.base_var_vals)
            default_result = self._translate_expression(prepared.wildcard_arm.expr, expected_type=expected_type)
            result_type = result_type or default_result.var_out.type
            default_exit = self._builder.current_block.name
            self._builder.build_br(prepared.end_block.name)
            self._mark_current_block_terminated()
            phi_pairs.append(PhiPair(default_result.var_out, default_exit))

        assert result_type is not None
        self._builder.position_at_end(prepared.end_block)
        self._var_vals = dict(prepared.base_var_vals)
        phi = self._builder.build_phi(result_name, result_type, phi_pairs)
        return Assignable(phi.var_out)

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
            if isinstance(src.type, (HeapSmartPointer, StackSmartPointer)):
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
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if not typ.generics and typ.name in generic_mapping:
            return generic_mapping[typ.name]
        return Type(typ.name, [self._specialize_type(generic, generic_mapping) for generic in typ.generics])

    def _lookup_struct_field_types(self, typ: Type) -> list[Type]:
        base_type = typ.pointee if isinstance(typ, (HeapSmartPointer, StackSmartPointer)) else typ
        struct_def = self._structs.get(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return []
        return [self._translate_type(field.type) for field in struct_def.fields]

    def _lookup_field_type(self, typ: Optional[Type], field: str) -> Optional[Type]:
        if typ is None:
            return None

        base_type = typ.pointee if isinstance(typ, (HeapSmartPointer, StackSmartPointer)) else typ
        struct_def = self._structs.get(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return None

        for field_param in struct_def.fields:
            if field_param.name == field:
                return self._translate_type(field_param.type)
        return None

    def _translate_type(self, typ: Type) -> Type:
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

    def _types_compatible(self, lhs: Type, rhs: Type) -> bool:
        if isinstance(lhs, HeapSmartPointer) and isinstance(rhs, HeapSmartPointer):
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if isinstance(lhs, StackSmartPointer) and isinstance(rhs, StackSmartPointer):
            return self._types_compatible(lhs.pointee, rhs.pointee)
        if isinstance(lhs, (HeapSmartPointer, StackSmartPointer)) or isinstance(
            rhs, (HeapSmartPointer, StackSmartPointer)
        ):
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

        base_type = (
            expected_type.pointee if isinstance(expected_type, (HeapSmartPointer, StackSmartPointer)) else expected_type
        )
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
        base_type = (
            expected_type.pointee if isinstance(expected_type, (HeapSmartPointer, StackSmartPointer)) else expected_type
        )
        if base_type.name.startswith("f") and base_type.name[1:].isdigit():
            return int(base_type.name[1:])
        return 64

    @classmethod
    def _build_integer_primitive(cls, value: int, expected_type: Optional[Type]):
        if expected_type is None:
            return Isize(value, size=32)

        base_type = (
            expected_type.pointee if isinstance(expected_type, (HeapSmartPointer, StackSmartPointer)) else expected_type
        )
        if base_type.name == "usize":
            return Usize(value)
        if base_type.name == "isize":
            return Isize(value)
        if base_type.name.startswith("u") and base_type.name[1:].isdigit():
            return Usize(value, size=int(base_type.name[1:]))
        if base_type.name.startswith("i") and base_type.name[1:].isdigit():
            return Isize(value, size=int(base_type.name[1:]))
        return Isize(value, size=32)
