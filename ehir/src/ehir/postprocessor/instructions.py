from abc import ABC
from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.primitives import Usize
from ehir.core.primitives.base import Primitive
from ehir.core.type import Type
from ehir.core.variable import TypedVariable


@dataclass
class ProcessedInstruction(ABC, Instruction): ...


@dataclass
class ProcessedControlFlow(ProcessedInstruction): ...


@dataclass
class ProcessedInstruction_br(ProcessedControlFlow):
    label: str

    def __repr__(self) -> str:
        return f"br {self.label}"


@dataclass
class ProcessedInstruction_cbr(ProcessedControlFlow):
    cond_var: TypedVariable
    true_br_label: str
    else_br_label: str

    def __repr__(self) -> str:
        return f"cbr {self.cond_var}, {self.true_br_label}, {self.else_br_label}"


@dataclass
class ProcessedInstruction_switch(ProcessedControlFlow):
    cond_var: TypedVariable
    default_case: str
    cases: list[tuple[Usize, str]]

    def __repr__(self) -> str:
        cases = ", ".join(f"{value} => {label}" for value, label in self.cases)
        return f"switch {self.cond_var}, {self.default_case} {{{cases}}}"


@dataclass
class ProcessedInstruction_ret(ProcessedControlFlow):
    var: TypedVariable

    def __repr__(self) -> str:
        return f"ret {self.var}"


@dataclass
class ProcessedInstruction_phi(ProcessedInstruction):
    var_out: TypedVariable
    args: list[tuple[TypedVariable, str]]

    def __repr__(self) -> str:
        args = ", ".join(f"{var} {label}" for var, label in self.args)
        return f"{self.var_out} = phi {args}"


@dataclass
class ProcessedInstruction_call(ProcessedInstruction):
    var_out: TypedVariable
    fn_name: str
    args: list[TypedVariable]

    def __repr__(self) -> str:
        return f"{self.var_out} = call {self.fn_name}({', '.join(str(arg) for arg in self.args)})"


@dataclass
class ProcessedInstruction_salloc(ProcessedInstruction):
    var_out: TypedVariable
    type: Type

    def __repr__(self) -> str:
        return f"{self.var_out} = salloc {self.type}"


@dataclass
class ProcessedInstruction_halloc(ProcessedInstruction):
    var_out: TypedVariable
    type: Type

    def __repr__(self) -> str:
        return f"{self.var_out} = halloc {self.type}"


@dataclass
class ProcessedInstruction_hrealloc(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    count: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = hrealloc {self.var}, {self.count}"


@dataclass
class ProcessedInstruction_hfree(ProcessedInstruction):
    var: TypedVariable

    def __repr__(self) -> str:
        return f"hfree {self.var}"


@dataclass
class ProcessedInstruction_put(ProcessedInstruction):
    primitive: Primitive
    var: TypedVariable

    def __repr__(self) -> str:
        return f"put {self.primitive}, {self.var}"


@dataclass
class ProcessedInstruction_load(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = load {self.var}"


@dataclass
class ProcessedInstruction_add(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = add {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_sub(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = sub {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_mul(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = mul {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_div(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = div {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_mod(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = mod {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_shl(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = shl {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_shr(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = shr {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_les(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = les {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_leq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = leq {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_grt(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = grt {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_geq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = geq {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_ieq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = ieq {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_neq(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = neq {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_or(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = or {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_and(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = and {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_xor(ProcessedInstruction):
    var_out: TypedVariable
    lhs: TypedVariable
    rhs: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = xor {self.lhs}, {self.rhs}"


@dataclass
class ProcessedInstruction_pcast(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    type: Type

    def __repr__(self) -> str:
        return f"{self.var_out} = pcast {self.var}, {self.type}"


@dataclass
class ProcessedInstruction_store(ProcessedInstruction):
    var_src: TypedVariable
    var_dst: TypedVariable

    def __repr__(self) -> str:
        return f"store {self.var_src}, {self.var_dst}"


@dataclass
class ProcessedInstruction_getfieldptr(ProcessedInstruction):
    var_out: TypedVariable
    src: TypedVariable
    field: TypedVariable

    def __repr__(self) -> str:
        return f"{self.var_out} = getfieldptr {self.src}, {self.field}"


@dataclass
class ProcessedInstruction_gep(ProcessedInstruction):
    var_out: TypedVariable
    var: TypedVariable
    offset: TypedVariable | int

    def __repr__(self) -> str:
        return f"{self.var_out} = gep {self.var}, {self.offset}"
