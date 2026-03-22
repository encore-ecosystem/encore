from typing import Optional

from ehir.core.derectives import Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions.base import Assignable
from ehir.core.instructions.control_flow.phi import PhiPair
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mul,
    Instruction_sub,
)
from ehir.core.instructions.operators.base import BinOp
from ehir.core.primitives import Usize
from ehir.core.type import Type
from ehir.core.variable import Parameter, Variable

from encore.translator.lexer import Lexer
from encore.translator.parser import Parser
from encore.translator.parser import statements as s

from .builder import EHIR_Builder, EHIR_Module

BINOP_MAPPING: dict[str, type[BinOp]] = {
    "+": Instruction_add,
    "-": Instruction_sub,
    "*": Instruction_mul,
    "/": Instruction_div,
}


class Translator:
    _funcs: dict[str, Derective_fn]
    _builder: EHIR_Builder
    _module: EHIR_Module

    def __init__(self):
        self._lexer = Lexer()
        self._parser = Parser()
        self._module = EHIR_Module(name="default")
        self._builder = EHIR_Builder(self._module)
        self._current_function = None
        self._current_variable_name = "null"
        self._current_variable_idx = 0
        self._variables: dict[str, dict[str, Variable]] = {}
        self._while_counter = 0
        self._if_counter = 0
        self._loop_stack: list[dict[str, object]] = []
        self._terminated_blocks: set[str] = set()
        self._var_vals: dict[str, Variable] = {}
        self._assignment_targets: dict[str, str] = {}

    def run(self, program: str) -> EHIR_Module:
        self._funcs = {}

        tokens = self._lexer.tokenize(program)
        ast = self._parser.parse(tokens)
        # print(*ast)

        for statement in ast:
            self._translate_statement(statement)

        return self._module

    def _translate_statement(self, statement: s.Statement) -> Derective:
        if isinstance(statement, s.Statement_FunctionDefinition):
            return self._translate_function_definition(statement)
        elif isinstance(statement, s.Statement_StructureDefinition):
            return self._translate_structure_definition(statement)
        elif isinstance(statement, s.Statement_Import):
            return self._translate_import(statement)
        raise NotImplementedError(f"Translation for statement type {type(statement)} is not implemented.")

    def _translate_import(self, statement: s.Statement_Import):
        self._translate_import_pair(prefix=[], pair=statement.pair, is_public=statement.is_public)

    def _translate_import_pair(self, prefix: list[str], pair: s.Statement_Import.ImportPair, is_public: bool):
        match len(pair.dst):
            case 0:
                (self._builder.build_cimp if is_public else self._builder.build_imp)(prefix=prefix, symbol=pair.src)
            case _:
                for dst in pair.dst:
                    self._translate_import_pair(prefix=prefix + [pair.src], pair=dst, is_public=is_public)

    def _translate_structure_definition(self, statement: s.Statement_StructureDefinition):
        self._builder.build_struct(statement.name, [Parameter(name, Type(type)) for (name, type) in statement.fields])

    def _translate_function_definition(self, statement: s.Statement_FunctionDefinition):
        self._builder.build_fn(
            name=statement.name,
            params=[Parameter(name=name, type=Type(name=type)) for name, type in statement.params],
            ret_type=Type(name=statement.type),
        )
        self._var_vals = {}
        self._assignment_targets = {}
        self._terminated_blocks = set()
        self._loop_stack = []
        entry_block = self._builder.append_block("entry")
        self._builder.position_at_end(entry_block)
        self._translate_block(statement.body)

    def _translate_block(self, statement: list[s.Statement_InnerLevel]):
        for inner_statement in statement:
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

        elif isinstance(statement, s.Statement_Assignment):
            return self._translate_assignment(statement)

        raise NotImplementedError(f"Translation for inner statement type {type(statement)} is not implemented.")

    def _translate_let(self, statement: s.Statement_Let):
        val = self._translate_expression(statement.expr, name=statement.name)
        self._var_vals[statement.name] = val.var_out

    def _translate_ret(self, statement: s.Statement_Ret):
        expr = self._translate_expression(expr=statement.expr)
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
        target_name = self._assignment_targets.get(statement.name, statement.name)
        val = self._translate_expression(statement.expr, name=target_name)
        self._var_vals[statement.name] = val.var_out

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

    def _collect_assignments(self, body: list[s.Statement_InnerLevel]) -> set[str]:
        assigned: set[str] = set()
        for stmt in body:
            if isinstance(stmt, s.Statement_Assignment):
                assigned.add(stmt.name)
            elif isinstance(stmt, (s.Statement_While, s.Statement_Loop, s.Statement_DoWhile)):
                assigned |= self._collect_assignments(stmt.body)
            elif isinstance(stmt, s.Statement_If):
                assigned |= self._collect_if_assignments(stmt)
        return assigned

    def _collect_if_assignments(self, statement: s.Statement_If) -> set[str]:
        assigned: set[str] = set()
        for branch in statement.branches:
            assigned |= self._collect_assignments(branch.body)
        if statement.else_body is not None:
            assigned |= self._collect_assignments(statement.else_body)
        return assigned

    def _translate_expression(self, expr: s.Statement_Expression, name: Optional[str] = None) -> Assignable:
        if isinstance(expr, s.Expression_BooleanLiteral):
            return self._builder.build_lcpos(prim=Usize(int(expr.value)), name=name)

        elif isinstance(expr, s.Expression_IntegerLiteral):
            return self._builder.build_lcpos(prim=Usize(int(expr.value)), name=name)

        elif isinstance(expr, s.Expression_VariableAccess):
            if expr.name in self._var_vals:
                return Assignable(self._var_vals[expr.name])
            return self._builder.get_var(expr.name)

        elif isinstance(expr, s.Expression_BinaryOperation):
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
            raise NotImplementedError("Translation for unary operations is not implemented.")

        elif isinstance(expr, s.Expression_Parenthesized):
            return self._translate_expression(expr.expr, name=name)

        elif isinstance(expr, s.Expression_StructInitialization):
            args = [self._translate_expression(arg_exp).var_out for arg_exp in expr.args]
            if expr.name.endswith("<S>"):
                return self._builder.build_scsos(
                    struct_name=expr.name[:-3],
                    args=args,
                    name=name,
                )
            elif expr.name.endswith("<H>"):
                return self._builder.build_scsoh(
                    struct_name=expr.name[:-3],
                    args=args,
                    name=name,
                )

            return self._builder.build_lcsos(
                struct_name=expr.name,
                args=args,
                name=name,
            )

        elif isinstance(expr, s.Expression_StructField):
            return self._builder.build_sgetfield(src=Variable(expr.name), field=Variable(expr.field))

        elif isinstance(expr, s.Expression_Call):
            args = [self._translate_expression(arg_exp).var_out for arg_exp in expr.args]
            return self._builder.build_call(fn_name=expr.name, args=args, name=name)

        raise NotImplementedError(f"Translation for expression type {type(expr)} is not implemented.")

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
        return f"{self._current_variable_name}_{self._current_variable_idx}"
