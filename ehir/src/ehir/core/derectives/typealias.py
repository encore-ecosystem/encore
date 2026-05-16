from dataclasses import dataclass, field

from ehir.core.derectives.base import Derective
from ehir.core.type import Type


@dataclass
class Derective_typealias(Derective):
    name: str
    target: Type
    is_public: bool = field(default=False, kw_only=True)
    attrs: tuple[str, ...] = field(default_factory=tuple, kw_only=True)

    def __str__(self) -> str:
        visibility_repr = "pub " if self.is_public else ""
        return f"{visibility_repr}type {self.name} = {self.target}"
