from dataclasses import dataclass

from ehir.core.derectives.base import Derective


@dataclass
class Derective_import(Derective):
    prefix: list[str]
    symbol: str

    def __post_init__(self):
        assert len(self.prefix) > 0
