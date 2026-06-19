from ehir.core.derectives import Derective_enum, Derective_struct
from ehir.core.primitives import Usize_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Reference, Type, is_box_type, mangle_type_name


def is_reference_runtime_type(typ: Type) -> bool:
    return not isinstance(typ, (Pointer, Reference)) and typ.name == "str"


def is_dyn_type(typ: Type) -> bool:
    return not isinstance(typ, (Pointer, Reference)) and typ.name == "dyn" and len(typ.generics) == 1


def reference_storage_struct(
    directive: Derective_struct,
    structs: dict[str, Derective_struct],
) -> Derective_struct | None:
    if len(directive.params) != 1:
        return None
    storage_field = directive.params[0]
    if storage_field.name != "storage" or not isinstance(storage_field.type, Pointer):
        return None
    storage = structs.get(storage_field.type.pointee.name)
    if storage is None or len(storage.params) < 4:
        return None
    ref_count, ptr, length, cap = storage.params[:4]
    if ref_count.name != "ref_count" or not isinstance(ref_count.type, Usize_t):
        return None
    if ptr.name != "ptr" or not isinstance(ptr.type, Pointer):
        return None
    if length.name != "len" or not isinstance(length.type, Usize_t):
        return None
    if cap.name != "cap" or not isinstance(cap.type, Usize_t):
        return None
    return storage


def needs_drop(typ: Type, aggregate_names: set[str]) -> bool:
    if isinstance(typ, (Pointer, Reference)):
        return False
    if is_reference_runtime_type(typ):
        return True
    if is_dyn_type(typ):
        return True
    if isinstance(typ, PrimitiveType):
        return False
    if typ.name == "void":
        return False
    if is_box_type(typ):
        return True
    return typ.name in aggregate_names and not is_placeholder_type(typ)


def needs_retain(typ: Type, aggregate_names: set[str]) -> bool:
    return needs_drop(typ, aggregate_names)


def collect_aggregate_names(
    structs: dict[str, Derective_struct],
    enums: dict[str, Derective_enum],
) -> set[str]:
    return set(structs) | set(enums)


def is_placeholder_type(typ: Type) -> bool:
    if isinstance(typ, (Pointer, Reference)):
        return is_placeholder_type(typ.pointee)
    if not typ.generics and (typ.name in {"T", "Self"} or (len(typ.name) == 1 and typ.name.isupper())):
        return True
    return any(is_placeholder_type(generic) for generic in typ.generics)


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
