from dataclasses import dataclass

from ehir.core.enum import Enum
from ehir.core.instructions.base import Assignable


@dataclass
class Instruction_capenum(Assignable):
    enum: Enum

    def __str__(self) -> str:
        return f"{super().__str__()}capenum {self.enum}"
