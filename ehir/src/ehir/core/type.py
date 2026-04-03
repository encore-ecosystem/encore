from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Type:
    name: str
    generics: list["Type"] = field(default_factory=list)

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        return f"{self.name}{generics_repr}"

    def __hash__(self) -> int:
        return hash(self.name)


class Pointer(Type):
    pointee: Type

    def __init__(self, pointee: Type):
        super().__init__(name=pointee.name, generics=list(pointee.generics))
        self.pointee = pointee

    def __str__(self) -> str:
        return f"{self.pointee}*"


class SmartPointer(Pointer, ABC):
    @abstractmethod
    def get_name(self) -> str:
        raise NotImplementedError


class HeapSmartPointer(SmartPointer):
    def get_name(self) -> str:
        return f"{self.pointee}_HSP"

    def __str__(self) -> str:
        return f"{self.pointee}<H>"


class StackSmartPointer(SmartPointer):
    def get_name(self) -> str:
        return f"{self.pointee}_SSP"

    def __str__(self) -> str:
        return f"{self.pointee}<S>"


def mangle_type_name(typ: Type) -> str:
    if isinstance(typ, HeapSmartPointer):
        return f"{mangle_type_name(typ.pointee)}_H"
    if isinstance(typ, StackSmartPointer):
        return f"{mangle_type_name(typ.pointee)}_S"
    if isinstance(typ, Pointer):
        return f"{mangle_type_name(typ.pointee)}_ptr"
    if not typ.generics:
        return typ.name
    return f"{typ.name}_{'_'.join(mangle_type_name(generic) for generic in typ.generics)}"
