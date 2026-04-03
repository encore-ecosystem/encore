from dataclasses import dataclass

from .base import Derective_import


@dataclass
class Derective_imp(Derective_import):
    def __str__(self) -> str:
        return f"imp {'::'.join(self.prefix + [self.symbol])}"
