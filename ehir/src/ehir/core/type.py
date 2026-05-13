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


class Reference(Type):
    pointee: Type

    def __init__(self, pointee: Type):
        super().__init__(name=pointee.name, generics=list(pointee.generics))
        self.pointee = pointee

    def __str__(self) -> str:
        return f"&{self.pointee}"

def is_box_type(typ: Type) -> bool:
    return not isinstance(typ, (Pointer, Reference)) and typ.name == "Box" and len(typ.generics) == 1


def box_pointee(typ: Type) -> Type:
    if not is_box_type(typ):
        raise TypeError(f"{typ} is not Box[T]")
    return typ.generics[0]


def mangle_type_name(typ: Type) -> str:
    if isinstance(typ, Pointer):
        return f"{mangle_type_name(typ.pointee)}_ptr"
    if isinstance(typ, Reference):
        return f"{mangle_type_name(typ.pointee)}_ref"
    if not typ.generics:
        return typ.name
    return f"{typ.name}_{'_'.join(mangle_type_name(generic) for generic in typ.generics)}"
