from dataclasses import dataclass

from ehir.core.instructions import ControlFlow
from ehir.core.instructions.base import Instruction


@dataclass
class Block:
    name: str
    body: list[Instruction]

    def __str__(self) -> str:
        body_repr = "\n".join("\n".join(f"  {line}" for line in str(b).splitlines()) for b in self.get_body())
        return f"${self.name}:\n{body_repr}"

    def get_body(self) -> list[Instruction]:
        return self.body


@dataclass
class TerminatedBlock(Block):
    term: ControlFlow

    def get_body(self) -> list[Instruction]:
        return [*self.body, self.term]
