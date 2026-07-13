from dataclasses import dataclass

from ehir.core.instructions.base import Instruction


@dataclass
class Instruction_comment(Instruction):
    comment: str

    def __post_init__(self):
        if "\n" in self.comment:
            raise ValueError("Comment cannot contain newline characters")

    def __str__(self) -> str:
        return f"; {self.comment}"
