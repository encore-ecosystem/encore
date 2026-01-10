from typing import Optional

from ehir.core.derectives import Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions.base import Assignable
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

    def __init__(self):
        self._lexer = Lexer()
        self._parser = Parser()
        self._module = EHIR_Module(name="default")
        self._builder = EHIR_Builder(self._module)
        self._current_function = None
        self._current_variable_name = "null"
        self._current_variable_idx = 0
        self._variables: dict[str, dict[str, Variable]] = {}

    def run(self, program: str) -> EHIR_Module:
        self._funcs = {}

        tokens = self._lexer.tokenize(program)
        ast = self._parser.parse(tokens)

        for statement in ast:
            self._translate_statement(statement)

        return self._module

    def _translate_statement(self, statement: s.Statement) -> Derective:
        if isinstance(statement, s.Statement_FunctionDefinition):
            return self._translate_function_definition(statement)
        elif isinstance(statement, s.Statement_StructureDefinition):
            return self._translate_structure_definition(statement)
        raise NotImplementedError(f"Translation for statement type {type(statement)} is not implemented.")

    def _translate_structure_definition(self, statement: s.Statement_StructureDefinition):
        self._builder.build_struct(statement.name, [Parameter(name, Type(type)) for (name, type) in statement.fields])

    def _translate_function_definition(self, statement: s.Statement_FunctionDefinition):
        self._builder.build_fn(
            name=statement.name,
            params=[Parameter(name=name, type=Type(name=type)) for name, type in statement.params],
            ret_type=Type(name=statement.type),
        )
        entry_block = self._builder.append_block("entry")
        self._builder.position_at_end(entry_block)
        self._translate_block(statement.body)

    def _translate_block(self, statement: list[s.Statement_InnerLevel]):
        for inner_statement in statement:
            self._translate_inner_statement(inner_statement)

    def _translate_inner_statement(self, statement: s.Statement_InnerLevel):
        if isinstance(statement, s.Statement_Let):
            return self._translate_let(statement)

        elif isinstance(statement, s.Statement_Ret):
            return self._translate_ret(statement)

        raise NotImplementedError(f"Translation for inner statement type {type(statement)} is not implemented.")

    def _translate_let(self, statement: s.Statement_Let):
        self._translate_expression(statement.expr, name=statement.name)

    def _translate_ret(self, statement: s.Statement_Ret):
        expr = self._translate_expression(expr=statement.expr)
        self._builder.build_ret(expr.var_out)

    def _translate_expression(self, expr: s.Statement_Expression, name: Optional[str] = None) -> Assignable:
        if isinstance(expr, s.Expression_IntegerLiteral):
            return self._builder.build_lcpos(prim=Usize(int(expr.value)))

        elif isinstance(expr, s.Expression_VariableAccess):
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
                case _:
                    raise NotImplementedError(f"Translation for binary operator {expr.operator} is not implemented.")

        elif isinstance(expr, s.Expression_UnaryOperation):
            raise NotImplementedError("Translation for unary operations is not implemented.")

        elif isinstance(expr, s.Expression_Parenthesized):
            return self._translate_expression(expr.expr)

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
