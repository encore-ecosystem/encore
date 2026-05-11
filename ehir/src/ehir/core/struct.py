from copy import deepcopy
from dataclasses import dataclass, field

from ehir.core.type import Type
from ehir.core.variable import Variable


@dataclass
class Struct:
    name: str
    generics: list[Type] = field(default_factory=list)
    fields: list[Variable] = field(default_factory=list)
    value: Variable | None = None
    type: Type | None = None

    def __post_init__(self):
        if self.value is not None and self.fields:
            raise ValueError("Struct cannot have both args and captured value")

    def as_type(self) -> Type:
        if self.type is not None:
            return deepcopy(self.type)
        return Type(self.name, deepcopy(self.generics))

    @property
    def is_capture(self) -> bool:
        return self.value is not None

    def __str__(self) -> str:
        type_repr = str(self.as_type())
        if self.value is not None:
            return f"{type_repr}(<- {self.value})"
        params_repr = ", ".join(str(p) for p in self.fields)
        return f"{type_repr}({params_repr})"
