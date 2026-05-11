from copy import deepcopy
from dataclasses import dataclass

from ehir.core.struct import Struct
from ehir.core.type import Type


@dataclass
class EnumVariant:
    name: str
    type: Type | None = None

    def __str__(self) -> str:
        if self.type is None:
            return self.name
        return f"{self.name}({self.type})"


@dataclass
class Enum:
    name: str
    generics: list[Type]
    variant: str
    payload: Struct | None = None

    def as_type(self) -> Type:
        return Type(self.name, deepcopy(self.generics))

    def payload_type(self) -> Type | None:
        if self.payload is None:
            return None
        return self.payload.as_type()

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        if self.payload is None:
            return f"{self.name}{generics_repr}::{self.variant}()"
        if self.payload.value is not None:
            return f"{self.name}{generics_repr}::{self.variant}({self.payload.value})"
        return f"{self.name}{generics_repr}::{self.variant}({self.payload})"
