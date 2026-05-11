from dataclasses import dataclass

from ehir.core.variable import Variable

from .control_flow_base import ControlFlow


@dataclass
class Instruction_cbr(ControlFlow):
    cond_var: Variable
    true_br_label: str
    else_br_label: str

    def __str__(self) -> str:
        return f"cbr {self.cond_var}, ${self.true_br_label}, ${self.else_br_label}"
