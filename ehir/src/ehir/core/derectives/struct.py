from dataclasses import dataclass, field

from ehir.core.derectives.base import Derective
from ehir.core.type import Type, mangle_type_name
from ehir.core.variable import StructField


@dataclass
class Derective_struct(Derective):
    name: str
    generics: list[Type]
    params: list[StructField]
    is_public: bool = field(default=False, kw_only=True)
    attrs: tuple[str, ...] = field(default_factory=tuple, kw_only=True)

    def get_conrete_name(self, types: list[Type]) -> str:
        types_repr = "_".join(mangle_type_name(x) for x in types)
        return f"{self.name}_{types_repr}"

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        params_repr = "\n  ".join(str(p) for p in self.params)
        attrs_repr = "".join(f"#attr({attr})\n" for attr in self.attrs)
        visibility_repr = "pub " if self.is_public else ""
        return f"{attrs_repr}{visibility_repr}struct {self.name}{generics_repr} {{\n  {params_repr} \n}}"
