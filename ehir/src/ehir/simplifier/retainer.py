from copy import deepcopy

from ehir.core.derectives import Derective_enum, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    Instruction_call,
    Instruction_capenum,
    Instruction_capstruct,
    Instruction_cenum,
    Instruction_cstruct,
    Instruction_getfield,
    Instruction_load,
    Instruction_ret,
    Instruction_scstruct,
    Instruction_sgetfield,
    Instruction_store,
)
from ehir.core.instructions.base import Instruction
from ehir.core.struct import Struct
from ehir.core.type import Type
from ehir.core.variable import TypedVariable, Variable
from ehir.simplifier.drop_helper import needs_retain, retain_function_name


class RetainInsertionPass:
    def run(self, ast: list[Derective]) -> list[Derective]:
        self._aggregate_names = {
            directive.name for directive in ast if isinstance(directive, (Derective_struct, Derective_enum))
        }
        for directive in ast:
            if isinstance(directive, Derective_fn):
                self._instrument_fn(directive)
        return ast

    def _instrument_fn(self, fn: Derective_fn) -> None:
        if fn.name.startswith("__drop_") or fn.name.startswith("__retain_"):
            return

        arg_names = {param.name for param in fn.params}
        for block in fn.body:
            new_body: list[Instruction] = []
            for instr in block.body:
                new_body.extend(self._instrument_instruction(instr, arg_names))
            block.body = new_body

    def _instrument_instruction(self, instr: Instruction, arg_names: set[str]) -> list[Instruction]:
        if isinstance(instr, Instruction_ret):
            if instr.var.name in arg_names:
                return [*self._retain_calls([instr.var]), instr]
            return [instr]

        if isinstance(instr, Instruction_store):
            return [*self._retain_calls([instr.var_src]), instr]

        if isinstance(instr, (Instruction_load, Instruction_getfield, Instruction_sgetfield)):
            assert isinstance(instr.var_out, Variable)
            return [instr, *self._retain_calls([instr.var_out])]

        if isinstance(instr, (Instruction_capstruct, Instruction_cstruct, Instruction_scstruct)):
            return [*self._retain_calls(self._struct_args(instr.struct)), instr]

        if isinstance(instr, (Instruction_capenum, Instruction_cenum)):
            return [*self._retain_calls(self._enum_args(instr.enum)), instr]

        return [instr]

    def _retain_calls(self, vars: list[Variable]) -> list[Instruction_call]:
        result: list[Instruction_call] = []
        for var in vars:
            if var.type is None or not needs_retain(var.type, self._aggregate_names):
                continue
            result.append(
                Instruction_call(
                    var_out=TypedVariable(f".retain_{var.name}", Type("void")),
                    fn_name=retain_function_name(var.type),
                    generics=[],
                    args=[deepcopy(var)],
                )
            )
        return result

    @staticmethod
    def _struct_args(struct: Struct) -> list[Variable]:
        if struct.value is not None:
            return [struct.value]
        return list(struct.fields)

    @staticmethod
    def _enum_args(enum) -> list[Variable]:
        if enum.payload is None:
            return []
        if enum.payload.value is not None:
            return [enum.payload.value]
        return list(enum.payload.args)
