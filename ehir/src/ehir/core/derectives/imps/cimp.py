from dataclasses import dataclass

from .base import Derective_import


@dataclass
class Derective_cimp(Derective_import):
    def __str__(self) -> str:
        return f"cimp {'::'.join(self.prefix + [self.symbol])}"
