from dataclasses import dataclass

from .base import Derective_import


@dataclass
class Derective_cimp(Derective_import):
    def __str__(self) -> str:
        path = f"cimp {'::'.join(self.prefix + [self.symbol])}"
        return path if self.alias is None else f"{path} as {self.alias}"
