from dataclasses import dataclass, field

from ehir.core.derectives.fns import Derective_fn
from ehir.core.type import Type

from .base import Derective


@dataclass
class Derective_impl(Derective):
    trait_name: str
    trait_args: list[Type]
    for_type: Type
    generics: list[Type] = field(default_factory=list)
    bounds: dict[str, list[str]] = field(default_factory=dict)
    methods: list[Derective_fn] = field(default_factory=list)

    def __str__(self) -> str:
        trait_args_repr = ("[" + ", ".join(str(x) for x in self.trait_args) + "]") if self.trait_args else ""
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        bounds_repr = ""
        if self.bounds:
            parts = [f"{name}: {' + '.join(traits)}" for name, traits in self.bounds.items()]
            bounds_repr = " where " + ", ".join(parts)
        methods_repr = "\n  ".join("\n".join(f"  {line}" for line in str(m).splitlines()) for m in self.methods)
        return f"impl{generics_repr} {self.trait_name}{trait_args_repr} for {self.for_type}{bounds_repr} {{\n{methods_repr}\n}}"
