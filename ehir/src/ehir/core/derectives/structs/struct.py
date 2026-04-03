from dataclasses import dataclass

from ehir.core.derectives.base import Derective
from ehir.core.type import Type, mangle_type_name
from ehir.core.variable import Parameter


@dataclass
class Derective_struct(Derective):
    name: str
    generics: list[Type]
    params: list[Parameter]

    def get_conrete_name(self, types: list[Type]) -> str:
        types_repr = "_".join(mangle_type_name(x) for x in types)
        return f"{self.name}_{types_repr}"

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        params_repr = "\n  ".join(str(p) for p in self.params)
        return f"struct {self.name}{generics_repr} {{\n  {params_repr} \n}}"
