from dataclasses import dataclass

from .control_flow_base import ControlFlow


@dataclass
class Instruction_br(ControlFlow):
    label: str

    def __str__(self) -> str:
        return f"br ${self.label}"
