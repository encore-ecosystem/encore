from copy import deepcopy
from dataclasses import dataclass

from ehir.core.type import Type
from ehir.core.variable import Variable


@dataclass
class EnumVariant:
    name: str


@dataclass
class UnitLikeVariant(EnumVariant):
    def __str__(self) -> str:
        return self.name


@dataclass
class TupleLikeVariant(EnumVariant):
    types: list[Type]

    def __str__(self) -> str:
        return f"{self.name}({', '.join(str(t) for t in self.types)})"


@dataclass
class Enum:
    name: str
    generics: list[Type]
    variant: str
    args: list[Variable]

    def as_type(self) -> Type:
        return Type(self.name, deepcopy(self.generics))

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        args_repr = ", ".join([str(x) for x in self.args])
        return f"{self.name}{generics_repr}::{self.variant}({args_repr})"
