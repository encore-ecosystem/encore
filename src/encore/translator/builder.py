from dataclasses import dataclass, field
from typing import Optional

from ehir.core.block import Block
from ehir.core.derectives import Derective_cimp, Derective_fn, Derective_imp, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions.base import Assignable, Instruction
from ehir.core.instructions.capture import Instruction_lcpos, Instruction_lcsos, Instruction_scsoh, Instruction_scsos
from ehir.core.instructions.control_flow import Instruction_br, Instruction_call, Instruction_cbr, Instruction_ret
from ehir.core.instructions.control_flow.phi import Instruction_phi, PhiPair
from ehir.core.instructions.memory import Instruction_sgetfield
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mul,
    Instruction_sub,
)
from ehir.core.instructions.operators.comparison import (
    Instruction_geq,
    Instruction_grt,
    Instruction_leq,
    Instruction_les,
)
from ehir.core.instructions.operators.logic import Instruction_ieq, Instruction_neq
from ehir.core.primitives import Usize_t
from ehir.core.primitives.base import Primitive
from ehir.core.struct import Struct
from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter, TypedVariable, Variable


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
    variables: dict[str, Variable]

    def __init__(self, module: EHIR_Module):
        self.module = module
        self.shift = 0

    def build_imp(self, prefix: list[str], symbol: str):
        self.module.ast.append(Derective_imp(prefix=prefix, symbol=symbol))

    def build_cimp(self, prefix: list[str], symbol: str):
        self.module.ast.append(Derective_cimp(prefix=prefix, symbol=symbol))

    def build_struct(self, name: str, params: list[Parameter]):
        self.module.ast.append(
            Derective_struct(
                name=name,
                generics=[],
                params=params,
            )
        )

    def build_fn(self, name: str, params: list[Parameter], ret_type: Type):
        fn = Derective_fn(name=name, generics=[], params=params, body=[], ret_type=ret_type)
        self.module.ast.append(fn)
        self.current_function = fn
        self.variables = {}

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

    def build_sgetfield(self, src: Variable, field: Variable, name: Optional[str] = None) -> Instruction_sgetfield:
        instr = Instruction_sgetfield(self._reserve_variable(name), src, field)
        self._add(instr)
        return instr

    def build_lcpos(self, prim: Primitive, name: Optional[str] = None) -> Instruction_lcpos:
        lcpos = Instruction_lcpos(self._reserve_variable(name, prim.type), prim)
        self._add(lcpos)
        return lcpos

    def build_lcsos(self, struct_name: str, args: list[Variable], name: Optional[str] = None) -> Instruction_lcsos:
        struct = Struct(struct_name, args)
        lcsos = Instruction_lcsos(var_out=self._reserve_variable(name, struct.as_type()), struct=struct)
        self._add(lcsos)
        return lcsos

    def build_scsos(self, struct_name: str, args: list[Variable], name: Optional[str] = None) -> Instruction_scsos:
        struct = Struct(struct_name, args)
        scsos = Instruction_scsos(
            var_out=self._reserve_variable(name, StackSmartPointer(struct.as_type())), struct=struct
        )
        self._add(scsos)
        return scsos

    def build_scsoh(self, struct_name: str, args: list[Variable], name: Optional[str] = None) -> Instruction_scsoh:
        scsoh = Instruction_scsoh(
            var_out=self._reserve_variable(name, HeapSmartPointer(Type(struct_name))), struct=Struct(struct_name, args)
        )
        self._add(scsoh)
        return scsoh

    def build_call(self, fn_name: str, args: list[Variable], name: Optional[str] = None) -> Instruction_call:
        call = Instruction_call(self._reserve_variable(name), fn_name, args)
        self._add(call)
        return call

    def build_ret(self, var: Variable):
        self._add(Instruction_ret(var))

    def build_br(self, label: str):
        self._add(Instruction_br(label=label))

    def build_cbr(self, cond_var: Variable, true_label: str, else_label: str):
        self._add(Instruction_cbr(cond_var=cond_var, true_br_label=true_label, else_br_label=else_label))

    def build_ieq(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_ieq:
        instr = Instruction_ieq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_neq(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_neq:
        instr = Instruction_neq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_les(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_les:
        instr = Instruction_les(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_leq(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_leq:
        instr = Instruction_leq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_grt(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_grt:
        instr = Instruction_grt(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_geq(self, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> Instruction_geq:
        instr = Instruction_geq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
        self._add(instr)
        return instr

    def build_phi(self, name: str, var_type: Optional[Type], pairs: list[PhiPair]) -> Instruction_phi:
        var = self._reserve_variable(name, var_type)
        instr = Instruction_phi(var_out=var, args=pairs)
        self._add(instr)
        return instr

    def get_var(self, name: Optional[str] = None) -> Assignable:
        if name is None:
            raise ValueError
        if var := self.variables.get(name, None):
            return Assignable(var)
        raise ValueError

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

    def _reserve_variable(self, name: Optional[str] = None, type: Optional[Type] = None) -> Variable:
        name = self._process_name(name)
        var = TypedVariable(name, type) if type else Variable(name)
        self.variables[name] = var
        return var
