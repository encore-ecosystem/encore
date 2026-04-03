from dataclasses import dataclass

from ehir.core.derectives.base import Derective
from ehir.core.type import Type
from ehir.core.variable import Parameter


@dataclass
class Derective_extern_fn(Derective):
    name: str
    params: list[Parameter]
    ret_type: Type

    def __str__(self) -> str:
        params_repr = ", ".join(str(p) for p in self.params)
        return f"fn {self.name}({params_repr}) -> {self.ret_type}"
