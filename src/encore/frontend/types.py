from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type


class AnySmartPointer(Type):
    pointee: Type

    def __init__(self, pointee: Type):
        super().__init__(name=pointee.name, generics=list(pointee.generics))
        self.pointee = pointee

    def __str__(self) -> str:
        return f"{self.pointee}&"


class MutableType(Type):
    inner: Type

    def __init__(self, inner: Type):
        super().__init__(name=inner.name, generics=list(inner.generics))
        self.inner = inner

    def __str__(self) -> str:
        return f"mut {self.inner}"


def is_reference_like_type(typ: Type | None) -> bool:
    return isinstance(typ, (AnySmartPointer, HeapSmartPointer, StackSmartPointer))


def is_mutable_type(typ: Type | None) -> bool:
    return isinstance(typ, MutableType)


def make_mutable_type(typ: Type) -> Type:
    return typ if isinstance(typ, MutableType) else MutableType(typ)


def strip_mutability(typ: Type) -> Type:
    if isinstance(typ, MutableType):
        return strip_mutability(typ.inner)
    if isinstance(typ, AnySmartPointer):
        return AnySmartPointer(strip_mutability(typ.pointee))
    if isinstance(typ, HeapSmartPointer):
        return HeapSmartPointer(strip_mutability(typ.pointee))
    if isinstance(typ, StackSmartPointer):
        return StackSmartPointer(strip_mutability(typ.pointee))
    return Type(typ.name, [strip_mutability(generic) for generic in typ.generics])


def reapply_mutability(template: Type, typ: Type) -> Type:
    return make_mutable_type(typ) if isinstance(template, MutableType) else typ


def unwrap_for_storage(typ: Type) -> Type:
    return typ.inner if isinstance(typ, MutableType) else typ
