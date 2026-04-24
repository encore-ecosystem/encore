from dataclasses import dataclass

from .type import Type


@dataclass
class Variable:
    name: str
    type: Type | None = None

    def __str__(self) -> str:
        type_repr = f": {self.type}" if self.type else ""
        return f"{self.name}{type_repr}"


@dataclass
class TypedVariable(Variable):
    type: Type


@dataclass
class StructField(TypedVariable):
    attrs: tuple[str, ...] = ()

    def __str__(self) -> str:
        attrs_repr = "".join(f"#attr({attr})\n  " for attr in self.attrs)
        return f"{attrs_repr}{self.name}: {self.type}"


Parameter = TypedVariable
