from ehir.core.derectives import Derective_struct
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Type, is_box_type, mangle_type_name


def needs_drop(typ: Type, aggregate_names: set[str]) -> bool:
    if isinstance(typ, Pointer):
        return False
    if isinstance(typ, PrimitiveType):
        return False
    if typ.name == "void":
        return False
    if is_box_type(typ):
        return True
    return typ.name in aggregate_names


def needs_retain(typ: Type, aggregate_names: set[str]) -> bool:
    return needs_drop(typ, aggregate_names)


def drop_function_name(typ: Type) -> str:
    return f"__drop_{mangle_type_name(typ)}"


def retain_function_name(typ: Type) -> str:
    return f"__retain_{mangle_type_name(typ)}"


def is_box_struct(directive: Derective_struct) -> bool:
    if len(directive.params) != 2:
        return False
    ptr, owner = directive.params
    return (
        ptr.name == "ptr"
        and isinstance(ptr.type, Pointer)
        and owner.name == "owner"
        and isinstance(owner.type, Pointer)
        and owner.type.pointee.name == "OwnerHeader"
    )
