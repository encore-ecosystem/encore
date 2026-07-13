from copy import deepcopy

from ehir.resolver import EHIR_TypedModule
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_call, Instruction_cfree, Instruction_drop, Instruction_retain
from ehir.core.instructions.base import Instruction
from ehir.core.type import Type, is_box_type
from ehir.core.variable import TypedVariable
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.drop_helper import collect_aggregate_names, drop_function_name, needs_drop, needs_retain, retain_function_name
from ehir.simplifier.normalizer.norm_fn import Normalized_fn


class DropLoweringPass(SimplifierPass):
    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct)
        }
        enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum)
        }
        self._aggregate_names = collect_aggregate_names(structs, enums)
        self._drop_functions = {
            directive.name
            for directive in ast
            if isinstance(directive, (Normalized_fn, Derective_fn, Derective_extern_fn))
        }
        for directive in ast:
            if isinstance(directive, Normalized_fn):
                self._lower_in_fn(directive)
        return ast

    def _lower_in_fn(self, fn: Normalized_fn) -> None:
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            new_body: list[Instruction] = []
            for instr in block.body:
                new_body.extend(self._lower_instruction(instr))
            block.body = new_body

    def _lower_instruction(self, instr: Instruction) -> list[Instruction]:
        if isinstance(instr, Instruction_cfree):
            return self._lower_drop_call(instr.var, TypedVariable(name=f".drop_{instr.var.name}", type=Type("void")))

        if isinstance(instr, Instruction_drop):
            return self._lower_drop_call(instr.var, TypedVariable(name=f".drop_{instr.var.name}", type=Type("void")))

        if isinstance(instr, Instruction_retain):
            return self._lower_retain_call(instr.var)

        if isinstance(instr, Instruction_call) and instr.fn_name == "Drop::drop":
            if len(instr.args) != 1:
                raise TypeError("Drop::drop expects exactly one argument")
            return self._lower_drop_call(instr.args[0], instr.var_out)

        return [instr]

    def _lower_retain_call(self, var) -> list[Instruction]:
        assert var.type is not None
        if not needs_retain(var.type, self._aggregate_names):
            return []
        fn_name = retain_function_name(var.type)
        if fn_name not in self._drop_functions:
            if is_box_type(var.type) or var.type.generics:
                return []
            raise TypeError(f"Unknown concrete retain function '{fn_name}' for type '{var.type}'")
        return [
            Instruction_call(
                var_out=TypedVariable(name=f".retain_{var.name}", type=Type("void")),
                fn_name=fn_name,
                generics=[],
                args=[deepcopy(var)],
            )
        ]

    def _lower_drop_call(self, var, var_out: TypedVariable) -> list[Instruction]:
        assert var.type is not None
        if not needs_drop(var.type, self._aggregate_names):
            return []

        fn_name = drop_function_name(var.type)
        if fn_name not in self._drop_functions:
            if is_box_type(var.type):
                return []
            # Generic aggregate specializations may not have a synthesized concrete drop yet.
            # Keep compilation progressing; dedicated drop synthesis for these types is handled separately.
            if var.type.generics:
                return []
            raise TypeError(f"Unknown concrete drop function '{fn_name}' for type '{var.type}'")
        return [
            Instruction_call(
                var_out=var_out,
                fn_name=fn_name,
                generics=[],
                args=[deepcopy(var)],
            )
        ]
