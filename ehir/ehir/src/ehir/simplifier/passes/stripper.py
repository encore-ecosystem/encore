from dataclasses import fields, is_dataclass

from ehir.resolver import EHIR_TypedModule
from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_fn, Derective_impl, Derective_struct, Derective_trait
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_call, Instruction_callvoid
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Reference, Type
from ehir.simplifier.base import SimplifierPass


class StripperPass(SimplifierPass):
    def run(self, module: EHIR_TypedModule, *, keep_public_api: bool = True) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast, keep_public_api=keep_public_api)
        return module

    def _run_ast(self, ast: list[Derective], *, keep_public_api: bool = True) -> list[Derective]:
        public_type_names: set[str] = set()
        if keep_public_api:
            for directive in ast:
                if isinstance(directive, (Derective_struct, Derective_enum, Derective_trait)) and getattr(
                    directive, "is_public", False
                ):
                    public_type_names.add(directive.name)

        fns = {directive.name: directive for directive in ast if isinstance(directive, Derective_fn)}
        for directive in ast:
            if isinstance(directive, Derective_impl):
                for method in directive.methods:
                    fns.setdefault(method.name, method)
        emitted_to_fn = {self._emit_like_symbol_name(name): name for name in fns}
        normalized_to_fn = {self._normalize_fn_lookup_name(name): name for name in fns}
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
        if keep_public_api:
            for directive in ast:
                if not isinstance(directive, Derective_impl):
                    continue
                for method in directive.methods:
                    reachable_fns.add(method.name)

        extern_fns = {directive.name for directive in ast if isinstance(directive, Derective_extern_fn)}

        pending = list(reachable_fns)
        while pending:
            fn_name = pending.pop()
            fn = fns.get(fn_name)
            if fn is None:
                continue
            for call_name in self._collect_called_function_names(fn):
                if call_name.startswith("__dyn_dispatch__"):
                    payload = call_name[len("__dyn_dispatch__") :]
                    if "::" in payload:
                        trait_name, method_name = payload.rsplit("::", 1)
                        method_prefix = f"{trait_name}::{method_name}"
                        for candidate_name in fns:
                            if not candidate_name.startswith(method_prefix):
                                continue
                            tail = candidate_name[len(method_prefix) :]
                            if tail and not tail.startswith("__"):
                                continue
                            if candidate_name not in reachable_fns:
                                reachable_fns.add(candidate_name)
                                pending.append(candidate_name)
                    continue
                canonical_call_name = emitted_to_fn.get(call_name, call_name)
                normalized_call_name = self._normalize_fn_lookup_name(canonical_call_name)
                canonical_call_name = normalized_to_fn.get(normalized_call_name, canonical_call_name)
                if canonical_call_name not in fns and canonical_call_name not in extern_fns:
                    unsuffixed_name = self._strip_method_receiver_suffix(canonical_call_name)
                    canonical_call_name = normalized_to_fn.get(
                        self._normalize_fn_lookup_name(unsuffixed_name),
                        canonical_call_name,
                    )
                if canonical_call_name in extern_fns and canonical_call_name not in reachable_fns:
                    reachable_fns.add(canonical_call_name)
                    continue
                if canonical_call_name in fns and canonical_call_name not in reachable_fns:
                    reachable_fns.add(canonical_call_name)
                    pending.append(canonical_call_name)

        reachable_types = set()
        if keep_public_api:
            reachable_types.update(public_type_names)

        for directive in ast:
            if isinstance(directive, (Derective_extern_fn, Derective_fn)) and directive.name in reachable_fns:
                self._collect_types_from_value(directive, reachable_types)

        result: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_extern_fn) and directive.name not in reachable_fns:
                continue
            if isinstance(directive, Derective_fn) and directive.name not in reachable_fns:
                continue
            # Keep all type declarations. Aggressive type stripping can break lowered
            # layout contracts when instructions still reference a type by name.
            if isinstance(directive, (Derective_struct, Derective_enum, Derective_trait)):
                result.append(directive)
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
            if isinstance(item, (Instruction_call, Instruction_callvoid)):
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
        if typ.name and not self._is_placeholder_type_name(typ.name):
            out.add(typ.name)
        for generic in typ.generics:
            self._collect_type(generic, out)

    def _is_placeholder_type_name(self, name: str) -> bool:
        if name in {"Self", "T"}:
            return True
        return len(name) == 2 and name.startswith("T") and name[1].isdigit()

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

    def _emit_like_symbol_name(self, name: str) -> str:
        if "::" not in name:
            return name
        owner_text, method_name = name.rsplit("::", 1)
        owner_name = owner_text.split("[", 1)[0]
        method = method_name.split("[", 1)[0]
        return f"{owner_name}__{method}"

    def _normalize_fn_lookup_name(self, name: str) -> str:
        text = name
        if text.startswith("[") and "]" in text:
            text = text.split("]", 1)[1]
        if "::" not in text:
            return text.split("[", 1)[0]
        owner_text, method_name = text.rsplit("::", 1)
        owner_name = owner_text.split("[", 1)[0]
        method = method_name.split("[", 1)[0]
        return f"{owner_name}::{method}"

    def _strip_method_receiver_suffix(self, name: str) -> str:
        text = name
        if text.startswith("[") and "]" in text:
            text = text.split("]", 1)[1]
        if "::" not in text:
            return text
        owner_text, method_name = text.rsplit("::", 1)
        method = method_name.split("[", 1)[0]
        if "__" not in method:
            return f"{owner_text}::{method}"
        return f"{owner_text}::{method.split('__', 1)[0]}"


UnneededSymbolsStripper = StripperPass
