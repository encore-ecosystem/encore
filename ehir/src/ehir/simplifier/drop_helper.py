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


def drop_function_name(typ: Type) -> str:
    return f"__drop_{mangle_type_name(typ)}"


def is_box_struct(directive: Derective_struct) -> bool:
    if len(directive.params) != 5:
        return False
    ptr, ref_count, inner_reach, outer_reach, outer_visited = directive.params
    return (
        ptr.name == "ptr"
        and isinstance(ptr.type, Pointer)
        and ref_count.name == "ref_count"
        and ref_count.type.name == "usize"
        and inner_reach.name == "inner_reach"
        and inner_reach.type.name == "u1"
        and outer_reach.name == "outer_reach"
        and outer_reach.type.name == "u1"
        and outer_visited.name == "outer_visited"
        and outer_visited.type.name == "u1"
    )
