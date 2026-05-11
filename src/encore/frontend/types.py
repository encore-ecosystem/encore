from dataclasses import replace

from ehir.core.type import HeapSmartPointer, Pointer, SmartPointer, StackSmartPointer, Type

TUPLE_TYPE_PREFIX = "__tuple_"
ARRAY_TYPE_PREFIX = "__array_"


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


def is_raw_pointer_type(typ: Type | None) -> bool:
    return isinstance(typ, Pointer) and not isinstance(typ, SmartPointer)


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
    if is_raw_pointer_type(typ):
        return Pointer(strip_mutability(typ.pointee))
    return replace(typ, generics=[strip_mutability(generic) for generic in typ.generics])


def reapply_mutability(template: Type, typ: Type) -> Type:
    return make_mutable_type(typ) if isinstance(template, MutableType) else typ


def unwrap_for_storage(typ: Type) -> Type:
    return typ.inner if isinstance(typ, MutableType) else typ


def make_tuple_type(items: list[Type]) -> Type:
    return Type(f"{TUPLE_TYPE_PREFIX}{len(items)}", list(items))


def is_tuple_type(typ: Type | None) -> bool:
    return isinstance(typ, Type) and typ.name.startswith(TUPLE_TYPE_PREFIX)


def tuple_arity(typ: Type) -> int:
    if not is_tuple_type(typ):
        raise TypeError(f"Type '{typ}' is not a tuple type")
    return int(typ.name.removeprefix(TUPLE_TYPE_PREFIX))


def make_array_type(item_type: Type, size: int) -> Type:
    return Type(f"{ARRAY_TYPE_PREFIX}{size}", [item_type])


def is_array_type(typ: Type | None) -> bool:
    return isinstance(typ, Type) and typ.name.startswith(ARRAY_TYPE_PREFIX)


def array_size(typ: Type) -> int:
    if not is_array_type(typ):
        raise TypeError(f"Type '{typ}' is not an array type")
    return int(typ.name.removeprefix(ARRAY_TYPE_PREFIX))
