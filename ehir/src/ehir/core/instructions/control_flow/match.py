from dataclasses import dataclass

from ehir.core.instructions.control_flow.base import ControlFlow
from ehir.core.variable import Variable


@dataclass
class MatchCase:
    variant: str
    label: str
    payload_var: Variable | None = None

    def __str__(self) -> str:
        payload_repr = ""
        if self.payload_var is not None:
            payload_repr = f"({self.payload_var})"
        return f"{self.variant}{payload_repr} => ${self.label}"


@dataclass
class Instruction_match(ControlFlow):
    cond_var: Variable
    default_case: str
    cases: list[MatchCase]

    def __str__(self) -> str:
        first_part = f"match {self.cond_var}, ${self.default_case} {{"
        if len(self.cases) == 0:
            return first_part + "}"
        cases_str = "\n  ".join(str(case) for case in self.cases)
        return f"{first_part}\n  {cases_str}\n}}"
