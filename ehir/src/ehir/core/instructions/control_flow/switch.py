from dataclasses import dataclass

from ehir.core.instructions.control_flow.base import ControlFlow
from ehir.core.primitives import Usize
from ehir.core.variable import Variable


@dataclass
class Instruction_switch(ControlFlow):
    cond_var: Variable
    default_case: str
    cases: list[tuple[Usize, str]]

    def __str__(self) -> str:
        first_part = f"switch {self.cond_var}, ${self.default_case} {{"
        if len(self.cases) == 0:
            return first_part + "}"
        else:
            cases_str = "\n  ".join(f"{case[0]} => ${case[1]}" for case in self.cases)
            return f"{first_part}\n  {cases_str}\n}}"
