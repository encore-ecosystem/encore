from dataclasses import dataclass

from ehir.core.enum import EnumVariant
from ehir.core.type import Type, mangle_type_name

from .base import Derective


@dataclass
class Derective_enum(Derective):
    name: str
    generics: list[Type]
    variants: list[EnumVariant]

    def get_conrete_name(self, types: list[Type]) -> str:
        types_repr = "_".join(mangle_type_name(x) for x in types)
        return f"{self.name}_{types_repr}"

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        variants_repr = "\n  ".join(str(v) for v in self.variants)
        return f"enum {self.name}{generics_repr} {{\n  {variants_repr} \n}}"
