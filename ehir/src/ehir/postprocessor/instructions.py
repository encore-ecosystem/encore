from abc import ABC
from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.primitives import Usize
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.type import Type
from ehir.core.variable import TypedVariable


@dataclass
class ProcessedInstruction(ABC, Instruction): ...


@dataclass
class ProcessedControlFlow(ProcessedInstruction): ...


@dataclass
class ProcessedInstruction_br(ProcessedControlFlow):
    label: str


@dataclass
class ProcessedInstruction_cbr(ProcessedControlFlow):
    cond_var: TypedVariable
    true_br_label: str
    else_br_label: str


@dataclass
class ProcessedInstruction_switch(ProcessedControlFlow):
    cond_var: TypedVariable
    default_case: str
    cases: list[tuple[Usize, str]]


@dataclass
class ProcessedInstruction_ret(ProcessedControlFlow):
    var: TypedVariable


@dataclass
class ProcessedInstruction_phi(ProcessedInstruction):
    var_out: TypedVariable
    args: list[tuple[TypedVariable, str]]


@dataclass
class ProcessedInstruction_call(ProcessedInstruction):
    var_out: TypedVariable
    fn_name: str
    args: list[TypedVariable]

    def __str__(self) -> str:
        return f"{super().__str__()}call {self.fn_name}({', '.join(str(arg) for arg in self.args)})"


@dataclass
class ProcessedInstruction_salloc(ProcessedInstruction):
    var_out: TypedVariable
    type: Type


@dataclass
class ProcessedInstruction_halloc(ProcessedInstruction):
    var_out: TypedVariable
    type: Type


@dataclass
class ProcessedInstruction_hrealloc(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    count: TypedVariable


@dataclass
class ProcessedInstruction_hfree(ProcessedInstruction):
    var: TypedVariable


@dataclass
class ProcessedInstruction_put(ProcessedInstruction):
    primitive: Primitive
    var: TypedVariable


@dataclass
class ProcessedInstruction_load(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable


@dataclass
class ProcessedInstruction_add(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_sub(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_mul(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_div(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_les(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_leq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_grt(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_geq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_ieq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_neq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_or(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_and(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_xor(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable


@dataclass
class ProcessedInstruction_pcast(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    type: Type


@dataclass
class ProcessedInstruction_store(ProcessedInstruction):
    var_src: TypedVariable
    var_dst: TypedVariable


@dataclass
class ProcessedInstruction_getfieldptr(ProcessedInstruction):
    var_out: TypedVariable
    src: TypedVariable
    field: TypedVariable


@dataclass
class ProcessedInstruction_gep(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    offset: TypedVariable | int
