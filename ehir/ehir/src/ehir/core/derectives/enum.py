from dataclasses import dataclass, field

from ehir.core.enum import EnumVariant
from ehir.core.type import Type, mangle_type_name

from .base import Derective


@dataclass
class Derective_enum(Derective):
    name: str
    generics: list[Type]
    variants: list[EnumVariant]
    is_public: bool = field(default=False, kw_only=True)
    attrs: tuple[str, ...] = field(default_factory=tuple, kw_only=True)

    def get_conrete_name(self, types: list[Type]) -> str:
        types_repr = "_".join(mangle_type_name(x) for x in types)
        return f"{self.name}_{types_repr}"

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        variants_repr = "\n  ".join(str(v) for v in self.variants)
        attrs_repr = "".join(f"#attr({attr})\n" for attr in self.attrs)
        visibility_repr = "pub " if self.is_public else ""
        return f"{attrs_repr}{visibility_repr}enum {self.name}{generics_repr} {{\n  {variants_repr} \n}}"
