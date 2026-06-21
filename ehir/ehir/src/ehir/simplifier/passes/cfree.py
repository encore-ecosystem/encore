from copy import deepcopy

from ehir.builder import EHIR_Module
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions import ControlFlow, Instruction_call, Instruction_cfree
from ehir.core.instructions.base import Instruction
from ehir.core.type import Type
from ehir.core.variable import TypedVariable
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.normalizer.norm_fn import Normalized_fn


class CfreeSimplifierPass(SimplifierPass):
    def run(self, module: EHIR_Module) -> EHIR_Module:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        for derective in ast:
            if isinstance(derective, Normalized_fn):
                self._lower_cfree_in_fn(derective)
        return ast

    def _lower_cfree_in_fn(self, fn: Derective_fn):
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            new_body: list[Instruction] = []
            for instr in block.get_body():
                new_body.extend(self._lower_cfree_instruction(instr))
            term = new_body.pop()
            assert isinstance(term, ControlFlow)
            block.body = new_body
            block.term = term

    def _lower_cfree_instruction(self, instr: Instruction) -> list[Instruction]:
        if isinstance(instr, Instruction_cfree):
            assert instr.var.type is not None
            return [
                Instruction_call(
                    var_out=TypedVariable(name=f".drop_{instr.var.name}", type=Type("void")),
                    fn_name="Drop::drop",
                    generics=[deepcopy(generic) for generic in instr.var.type.generics],
                    args=[TypedVariable(instr.var.name, instr.var.type)],
                )
            ]
        return [instr]


Cfree_Simplifier_Pass = CfreeSimplifierPass
