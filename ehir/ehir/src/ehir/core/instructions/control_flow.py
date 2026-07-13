from dataclasses import dataclass

from ehir.core.primitives import Usize
from ehir.core.variable import Variable

from .base import Instruction


@dataclass
class ControlFlow(Instruction):
    pass


@dataclass
class Instruction_br(ControlFlow):
    label: str

    def __str__(self) -> str:
        return f"br ${self.label}"


@dataclass
class Instruction_cbr(ControlFlow):
    cond_var: Variable
    true_br_label: str
    else_br_label: str

    def __str__(self) -> str:
        return f"cbr {self.cond_var}, ${self.true_br_label}, ${self.else_br_label}"


@dataclass
class Instruction_switch(ControlFlow):
    cond_var: Variable
    default_case: str
    cases: list[tuple[Usize, str]]

    def __str__(self) -> str:
        first_part = f"switch {self.cond_var}, ${self.default_case} {{"
        if len(self.cases) == 0:
            return first_part + "}"
        cases_str = "\n  ".join(f"{case[0]} => ${case[1]}" for case in self.cases)
        return f"{first_part}\n  {cases_str}\n}}"


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
