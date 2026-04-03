from dataclasses import dataclass

from ehir.core.block import Block, TerminatedBlock
from ehir.core.derectives import Derective_fn
from ehir.core.type import Type
from ehir.core.variable import TypedVariable


@dataclass
class Normalized_fn(Derective_fn):
    entry_block: TerminatedBlock
    body: list[TerminatedBlock]
    exit_block: TerminatedBlock

    @classmethod
    def new(
        cls,
        name: str,
        params: list[TypedVariable],
        ret_type: Type,
        entry_block: TerminatedBlock,
        body: list[TerminatedBlock],
        exit_block: TerminatedBlock,
    ) -> "Normalized_fn":
        return cls(
            name=name,
            generics=[],
            params=params,
            ret_type=ret_type,
            entry_block=entry_block,
            body=body,
            exit_block=exit_block,
        )

    def __post_init__(self):
        assert self.entry_block.name == "entry"
        assert len(self.generics) == 0

    def get_body(self) -> list[Block]:
        return [self.entry_block, *self.body, self.exit_block]
