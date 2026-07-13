from dataclasses import dataclass

from ehir.core.type import Type


@dataclass
class PrimitiveType(Type):
    pass


@dataclass
class Primitive:
    type: PrimitiveType
