from dataclasses import dataclass

from .base import Derective_import


@dataclass
class Derective_imp(Derective_import):
    def __str__(self) -> str:
        path = f"imp {'::'.join(self.prefix + [self.symbol])}"
        return path if self.alias is None else f"{path} as {self.alias}"
