from dataclasses import dataclass, field

from ehir.core.derectives.base import Derective
from ehir.core.type import Type
from ehir.core.variable import Parameter


@dataclass
class Derective_extern_fn(Derective):
    name: str
    params: list[Parameter]
    ret_type: Type
    is_public: bool = field(default=False, kw_only=True)
    attrs: tuple[str, ...] = field(default_factory=tuple, kw_only=True)

    def __str__(self) -> str:
        params_repr = ", ".join(str(p) for p in self.params)
        attrs_repr = "".join(f"#attr({attr})\n" for attr in self.attrs)
        visibility_repr = "pub " if self.is_public else ""
        return f"{attrs_repr}{visibility_repr}extern fn {self.name}({params_repr}) -> {self.ret_type}"
