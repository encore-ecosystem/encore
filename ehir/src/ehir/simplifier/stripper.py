from dataclasses import fields, is_dataclass

from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_fn, Derective_impl, Derective_struct, Derective_trait
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_call
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Reference, Type


class UnneededSymbolsStripper:
    def run(self, ast: list[Derective], *, keep_public_api: bool = True) -> list[Derective]:
        fns = {directive.name: directive for directive in ast if isinstance(directive, Derective_fn)}
        reachable_fns = {
            directive.name
            for directive in ast
            if isinstance(directive, (Derective_extern_fn, Derective_fn))
            and (
                directive.name == "main"
                or (keep_public_api and directive.name.startswith("__Box_"))
                or (keep_public_api and directive.name.startswith("__drop___Box_"))
                or (keep_public_api and getattr(directive, "is_public", False))
            )
        }
        extern_fns = {directive.name for directive in ast if isinstance(directive, Derective_extern_fn)}

        pending = list(reachable_fns)
        while pending:
            fn_name = pending.pop()
            fn = fns.get(fn_name)
            if fn is None:
                continue
            for call_name in self._collect_called_function_names(fn):
                if call_name in extern_fns and call_name not in reachable_fns:
                    reachable_fns.add(call_name)
                    continue
                if call_name in fns and call_name not in reachable_fns:
                    reachable_fns.add(call_name)
                    pending.append(call_name)

        reachable_types = set()
        if keep_public_api:
            for directive in ast:
                if isinstance(directive, Derective_struct) and getattr(directive, "is_public", False):
                    reachable_types.add(directive.name)
                elif isinstance(directive, Derective_enum) and getattr(directive, "is_public", False):
                    reachable_types.add(directive.name)
                elif isinstance(directive, Derective_trait) and getattr(directive, "is_public", False):
                    reachable_types.add(directive.name)

        for directive in ast:
            if isinstance(directive, (Derective_extern_fn, Derective_fn)) and directive.name in reachable_fns:
                self._collect_types_from_value(directive, reachable_types)

        result: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_extern_fn) and directive.name not in reachable_fns:
                continue
            if isinstance(directive, Derective_fn) and directive.name not in reachable_fns:
                continue
            if isinstance(directive, Derective_struct):
                is_public = getattr(directive, "is_public", False)
                if directive.name not in reachable_types and not (keep_public_api and is_public):
                    continue
            if isinstance(directive, Derective_enum):
                is_public = getattr(directive, "is_public", False)
                if directive.name not in reachable_types and not (keep_public_api and is_public):
                    continue
            if isinstance(directive, Derective_trait):
                is_public = getattr(directive, "is_public", False)
                if directive.name not in reachable_types and not (keep_public_api and is_public):
                    continue
            if isinstance(directive, Derective_impl):
                if not self._impl_is_reachable(directive, reachable_fns, reachable_types):
                    continue
            result.append(directive)
        return result

    def _impl_is_reachable(self, directive: Derective_impl, reachable_fns: set[str], reachable_types: set[str]) -> bool:
        if directive.trait_name in reachable_types or directive.for_type.name in reachable_types:
            return True
        return any(method.name in reachable_fns for method in directive.methods)

    def _collect_called_function_names(self, value) -> set[str]:
        calls: set[str] = set()
        for item in self._walk(value):
            if isinstance(item, Instruction_call):
                calls.add(item.fn_name)
        return calls

    def _collect_types_from_value(self, value, out: set[str]) -> None:
        for item in self._walk(value):
            if isinstance(item, Type):
                self._collect_type(item, out)

    def _collect_type(self, typ: Type, out: set[str]) -> None:
        if isinstance(typ, PrimitiveType):
            return
        if isinstance(typ, (Pointer, Reference)):
            self._collect_type(typ.pointee, out)
        if typ.name and typ.name.isidentifier():
            out.add(typ.name)
        for generic in typ.generics:
            self._collect_type(generic, out)

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
