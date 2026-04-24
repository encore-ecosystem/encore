from dataclasses import fields, is_dataclass

from ehir.core.derectives import Derective_fn, Derective_impl, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    Instruction_call,
    Instruction_cenum,
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_gep,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_load,
    Instruction_pcast,
    Instruction_put,
    Instruction_salloc,
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
)
from ehir.core.type import Pointer, Type


UNSAFE_INSTRUCTION_TYPES = (
    # Raw pointer/value capture.
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_cenum,
    # Smart-pointer construction/deref is low-level EHIR machinery.
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    # Raw memory operations.
    Instruction_salloc,
    Instruction_halloc,
    Instruction_hrealloc,
    Instruction_hfree,
    Instruction_load,
    Instruction_store,
    Instruction_put,
    Instruction_pcast,
    Instruction_getptr,
    Instruction_getfieldptr,
    Instruction_gep,
)


class SafetyValidator:
    def run(self, ast: list[Derective]) -> list[Derective]:
        for directive in ast:
            if isinstance(directive, Derective_struct):
                self._validate_struct(directive)
            elif isinstance(directive, Derective_fn):
                self._validate_fn(directive)
            elif isinstance(directive, Derective_impl):
                for method in directive.methods:
                    self._validate_fn(method)
        return ast

    def _validate_struct(self, struct: Derective_struct) -> None:
        if self._has_safe_attr(struct):
            return

        for field in struct.params:
            if self._contains_raw_pointer(field.type):
                raise TypeError(
                    f"Struct '{struct.name}' stores raw pointer field '{field.name}: {field.type}'. "
                    "Add #attr(safe) if this struct is a checked safe abstraction."
                )

    def _validate_fn(self, fn: Derective_fn) -> None:
        if self._has_safe_attr(fn):
            return

        for item in self._walk(fn.body):
            if isinstance(item, Instruction_call) and item.is_unsafe:
                raise TypeError(
                    f"Function '{fn.name}' uses unsafe call '{item.fn_name}' without #attr(safe)"
                )
            if self._is_compiler_safe_lowering(item):
                continue
            if isinstance(item, UNSAFE_INSTRUCTION_TYPES):
                raise TypeError(
                    f"Function '{fn.name}' uses unsafe instruction '{item}' without #attr(safe)"
                )

    def _has_safe_attr(self, value) -> bool:
        return "safe" in getattr(value, "attrs", ())

    def _contains_raw_pointer(self, typ: Type) -> bool:
        if isinstance(typ, Pointer):
            return True
        return any(self._contains_raw_pointer(generic) for generic in typ.generics)

    def _is_compiler_safe_lowering(self, item) -> bool:
        if isinstance(item, Instruction_load):
            return "_match_ptr" in item.var.name
        return False

    def _walk(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        yield value
        if isinstance(value, dict):
            for key, item in value.items():
                yield from self._walk(key)
                yield from self._walk(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from self._walk(item)
            return
        if is_dataclass(value):
            for field in fields(value):
                yield from self._walk(getattr(value, field.name))
