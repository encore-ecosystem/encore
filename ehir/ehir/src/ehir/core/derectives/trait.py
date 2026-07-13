from dataclasses import dataclass, field

from ehir.core.type import Type
from ehir.core.variable import Parameter

from .base import Derective


@dataclass
class TraitMethod:
    name: str
    generics: list[Type]
    params: list[Parameter]
    ret_type: Type

    def __str__(self) -> str:
        params_repr = ", ".join(str(p) for p in self.params)
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        return f"fn {self.name}{generics_repr}({params_repr}) -> {self.ret_type}"


@dataclass
class Derective_trait(Derective):
    name: str
    generics: list[Type]
    parent: str | None = None
    bounds: dict[str, list[str]] = field(default_factory=dict)
    methods: list[TraitMethod] = field(default_factory=list)
    is_public: bool = field(default=False, kw_only=True)
    attrs: tuple[str, ...] = field(default_factory=tuple, kw_only=True)

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        parent_repr = f" < {self.parent}" if self.parent else ""
        bounds_repr = ""
        if self.bounds:
            parts = [f"{name}: {' + '.join(traits)}" for name, traits in self.bounds.items()]
            bounds_repr = " where " + ", ".join(parts)
        methods_repr = "\n  ".join(str(method) for method in self.methods)
        attrs_repr = "".join(f"#attr({attr})\n" for attr in self.attrs)
        visibility_repr = "pub " if self.is_public else ""
        return (
            f"{attrs_repr}{visibility_repr}trait {self.name}{generics_repr}"
            f"{parent_repr}{bounds_repr} {{\n  {methods_repr}\n}}"
        )
