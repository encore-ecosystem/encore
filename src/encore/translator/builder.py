from dataclasses import dataclass, field
from typing import Optional

from ehir.core.block import Block
from ehir.core.derectives import Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions.base import Instruction
from ehir.core.instructions.capture import Instruction_lcpos, Instruction_lcsos
from ehir.core.instructions.control_flow import Instruction_ret
from ehir.core.instructions.memory import Instruction_getfield
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mul,
    Instruction_sub,
)
from ehir.core.primitives.base import Primitive
from ehir.core.struct import Struct
from ehir.core.type import Type
from ehir.core.variable import Parameter, Variable


@dataclass
class EHIR_Module:
    name: str
    ast: list[Derective] = field(default_factory=list)

    def get_raw_program(self) -> str:
        return "\n".join(map(str, self.ast))


class EHIR_Builder:
    module: EHIR_Module
    current_function: Derective_fn
    current_block: Block
    shift: int

    def __init__(self, module: EHIR_Module):
        self.module = module
        self.shift = 0

    def build_struct(self, name: str, args: list[Parameter]):
        self.module.ast.append(
            Derective_struct(
                name,
                args,
            )
        )

    def build_fn(self, name: str, params: list[Parameter], ret_type: Type):
        fn = Derective_fn(name, params, [], ret_type)
        self.module.ast.append(fn)
        self.current_function = fn

    def build_add(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_add:
        instr = Instruction_add(self._reserve_variable(name), lhs, rhs)
        self._add(instr)
        return instr

    def build_sub(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_sub:
        instr = Instruction_sub(self._reserve_variable(name), lhs, rhs)
        self._add(instr)
        return instr

    def build_mul(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_mul:
        instr = Instruction_mul(self._reserve_variable(name), lhs, rhs)
        self._add(instr)
        return instr

    def build_div(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_div:
        instr = Instruction_div(self._reserve_variable(name), lhs, rhs)
        self._add(instr)
        return instr

    def build_getfield(
        self, src: Variable, indexes: list[Variable], name: Optional[str] = None
    ) -> Instruction_getfield:
        instr = Instruction_getfield(self._reserve_variable(name), src, indexes)
        self._add(instr)
        return instr

    def build_lcpos(self, prim: Primitive, name: Optional[str] = None) -> Instruction_lcpos:
        lcpos = Instruction_lcpos(
            var_out=self._reserve_variable(name),
            primitive=prim,
        )
        self._add(lcpos)
        return lcpos

    def build_lcsos(self, struct_name: str, args: list[Variable], name: Optional[str] = None) -> Instruction_lcsos:
        lcsos = Instruction_lcsos(var_out=self._reserve_variable(name), struct=Struct(struct_name, args))
        self._add(lcsos)
        return lcsos

    def build_ret(self, var: Variable):
        self._add(Instruction_ret(var))

    def append_block(self, name: str) -> Block:
        block = Block(name, [])
        self.current_function.body.append(block)
        return block

    def position_at_end(self, block: Block):
        self.current_block = block

    def _add(self, instruction: Instruction):
        self.current_block.body.append(instruction)

    def _process_name(self, name: Optional[str]) -> str:
        if name is None:
            name = f"_{self.shift}"
            self.shift += 1
        return name

    def _reserve_variable(self, name: Optional[str] = None) -> Variable:
        name = self._process_name(name)
        return Variable(name)
