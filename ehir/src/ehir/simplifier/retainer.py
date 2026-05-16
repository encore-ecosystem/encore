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
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_store,
)
from ehir.core.instructions.base import Instruction
from ehir.core.struct import Struct
from ehir.core.type import Type
from ehir.core.variable import TypedVariable, Variable
from ehir.simplifier.drop_helper import (
    collect_aggregate_names,
    drop_function_name,
    needs_retain,
    retain_function_name,
)


class RetainInsertionPass:
    def run(self, ast: list[Derective]) -> list[Derective]:
        structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct) and not directive.generics
        }
        enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum) and not directive.generics
        }
        self._aggregate_names = collect_aggregate_names(structs, enums)
        for directive in ast:
            if isinstance(directive, Derective_fn):
                self._instrument_fn(directive)
        return ast

    def _instrument_fn(self, fn: Derective_fn) -> None:
        if fn.name.startswith("__drop_") or fn.name.startswith("__retain_") or fn.name.startswith("__cfree"):
            return

        arg_names = {param.name for param in fn.params}
        for block in fn.body:
            new_body: list[Instruction] = []
            for instr in block.body:
                new_body.extend(self._instrument_instruction(instr, arg_names, fn.name))
            block.body = new_body

    def _instrument_instruction(self, instr: Instruction, arg_names: set[str], fn_name: str) -> list[Instruction]:
        if isinstance(instr, Instruction_ret):
            if instr.var.name in arg_names:
                return [*self._retain_calls([instr.var]), instr]
            return [instr]

        if isinstance(instr, Instruction_store):
            if self._is_concrete_box_store(fn_name) and self._needs_retain(instr.var_src):
                old = TypedVariable(f".old_{instr.var_dst.name}", deepcopy(instr.var_src.type))
                return [
                    Instruction_load(var_out=old, var=instr.var_dst),
                    Instruction_call(
                        var_out=TypedVariable(f".drop_old_{instr.var_dst.name}", Type("void")),
                        fn_name=drop_function_name(instr.var_src.type),
                        generics=[],
                        args=[deepcopy(old)],
                    ),
                    *self._retain_calls([instr.var_src]),
                    instr,
                ]
            return [*self._retain_calls([instr.var_src]), instr]

        if isinstance(instr, Instruction_setfield):
            return [*self._retain_calls([instr.value]), instr]

        if isinstance(instr, (Instruction_load, Instruction_getfield, Instruction_sgetfield)):
            assert isinstance(instr.var_out, Variable)
            return [instr, *self._retain_calls([instr.var_out])]

        if isinstance(instr, (Instruction_capstruct, Instruction_cstruct, Instruction_scstruct)):
            return [*self._retain_calls(self._struct_args(instr.struct)), instr]

        if isinstance(instr, (Instruction_capenum, Instruction_cenum)):
            return [*self._retain_calls(self._enum_args(instr.enum)), instr]

        return [instr]

    @staticmethod
    def _is_concrete_box_store(fn_name: str) -> bool:
        return fn_name.startswith("__Box_") and fn_name.endswith("::store")

    def _retain_calls(self, vars: list[Variable]) -> list[Instruction_call]:
        result: list[Instruction_call] = []
        for var in vars:
            if not self._needs_retain(var):
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

    def _needs_retain(self, var: Variable) -> bool:
        return var.type is not None and needs_retain(var.type, self._aggregate_names)

    @staticmethod
    def _struct_args(struct: Struct) -> list[Variable]:
        if struct.value is not None:
            return [struct.value]
        return list(struct.fields)

    @staticmethod
    def _enum_args(enum) -> list[Variable]:
        return list(enum.args)
