from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass, replace

from ehir.core.derectives import Derective_enum, Derective_fn, Derective_impl, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import Instruction_call, Instruction_wraps
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type, concrete_box_type_name, mangle_type_name


class MonomorphizationPass:
    _GENERIC_MONO_PASSES = 4

    @staticmethod
    def _generic_clone_name(fn_name: str, signature: str) -> str:
        # Use a dedicated marker to avoid collisions with user-authored names
        # like `foo__T` and to prevent accidental self-recursion after rewrite.
        return f"{fn_name}__mono__{signature}"

    @staticmethod
    def _is_box_template_method_name(name: str) -> bool:
        return name.startswith("Box[T]::") or name.startswith("Box::")

    def run(self, ast: list[Derective]) -> list[Derective]:
        box_struct = next((d for d in ast if isinstance(d, Derective_struct) and d.name == "Box" and d.generics), None)
        if box_struct is None:
            out = ast
            for _ in range(self._GENERIC_MONO_PASSES):
                out = self._monomorphize_generic_functions(out)
            return self._prune_unreferenced_generic_functions(out)

        box_methods = [
            d
            for d in ast
            if isinstance(d, Derective_fn)
            and self._is_box_template_method_name(d.name)
        ]

        concrete_box_types = self._collect_concrete_box_types(ast)
        if not concrete_box_types:
            out = ast
            for _ in range(self._GENERIC_MONO_PASSES):
                out = self._monomorphize_generic_functions(out)
            return self._prune_unreferenced_generic_functions(out)

        new_nodes: list[Derective] = []
        for concrete in concrete_box_types:
            concrete_name = concrete_box_type_name(concrete)
            mapping = {"T": concrete}

            # Struct __Box_<T>
            s = deepcopy(box_struct)
            s.name = concrete_name
            s.generics = []
            s = self._rewrite_types(s, mapping)
            new_nodes.append(s)

            # Methods __Box_<T>::*
            for method in box_methods:
                m = deepcopy(method)
                m.generics = []
                m.name = f"{concrete_name}::{method.name.rsplit('::', 1)[-1]}"
                m = self._rewrite_types(m, mapping)
                m = self._rewrite_box_uses_in_value(m)
                new_nodes.append(m)

        # Rewrite existing AST types and calls from Box[...] / Box[T]::* to concrete symbols.
        for i, directive in enumerate(ast):
            ast[i] = self._rewrite_box_uses_in_value(directive)
        for i, directive in enumerate(new_nodes):
            new_nodes[i] = self._rewrite_box_uses_in_value(directive)
        self._rewrite_box_call_names(ast)
        self._rewrite_box_call_names(new_nodes)
        self._canonicalize_stack_wrap_calls(ast)
        self._canonicalize_stack_wrap_calls(new_nodes)

        all_nodes = ast + new_nodes
        generic_enums = {
            d.name: d
            for d in all_nodes
            if isinstance(d, Derective_enum) and d.generics
        }
        concrete_enums = self._build_concrete_enums(all_nodes, generic_enums)
        if concrete_enums:
            enum_names = set(generic_enums)
            for i, directive in enumerate(ast):
                ast[i] = self._rewrite_enum_uses_in_value(directive, enum_names)
            for i, directive in enumerate(new_nodes):
                new_nodes[i] = self._rewrite_enum_uses_in_value(directive, enum_names)
            new_nodes.extend(concrete_enums)

        # Remove generic Box declarations/methods, append concrete ones.
        filtered: list[Derective] = []
        for d in ast:
            if isinstance(d, Derective_fn) and d.name.endswith("::from_stack"):
                continue
            if isinstance(d, Derective_fn) and self._is_box_template_method_name(d.name):
                continue
            filtered.append(d)
        new_nodes = [d for d in new_nodes if not (isinstance(d, Derective_fn) and d.name.endswith("::from_stack"))]
        filtered.extend(new_nodes)
        out = filtered
        for _ in range(self._GENERIC_MONO_PASSES):
            out = self._monomorphize_generic_functions(out)
        return self._prune_unreferenced_generic_functions(out)

    def _prune_unreferenced_generic_functions(self, ast: list[Derective]) -> list[Derective]:
        referenced_fn_names: set[str] = set()
        for item in self._walk(ast):
            if isinstance(item, Instruction_call):
                referenced_fn_names.add(item.fn_name)
        pruned: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_fn):
                if self._is_unresolved_template_fn(directive) and directive.name not in referenced_fn_names:
                    continue
                pruned.append(directive)
                continue

            if isinstance(directive, Derective_impl):
                kept_methods: list[Derective_fn] = []
                for method in directive.methods:
                    if self._is_unresolved_template_fn(method):
                        continue
                    kept_methods.append(method)
                if not kept_methods and directive.generics:
                    continue
                pruned.append(replace(directive, methods=kept_methods))
                continue

            pruned.append(directive)

        return pruned

    def _is_unresolved_template_fn(self, fn: Derective_fn) -> bool:
        if fn.generics:
            return True
        if self._is_placeholder_type(fn.ret_type):
            return True
        for param in fn.params:
            if self._is_placeholder_type(param.type):
                return True
        return False

    def _monomorphize_generic_functions(self, ast: list[Derective]) -> list[Derective]:
        fn_by_name = {d.name: d for d in ast if isinstance(d, Derective_fn)}
        call_specs: dict[str, dict[str, list[Type]]] = {}
        for item in self._walk(ast):
            if not isinstance(item, Instruction_call):
                continue
            target = fn_by_name.get(item.fn_name)
            if target is None or not target.generics or not item.generics:
                continue
            if len(target.generics) != len(item.generics):
                continue
            if any(self._is_placeholder_type(generic) for generic in item.generics):
                continue
            signature = ",".join(mangle_type_name(generic) for generic in item.generics)
            call_specs.setdefault(item.fn_name, {})[signature] = [deepcopy(generic) for generic in item.generics]

        if not call_specs:
            return ast

        renames: dict[tuple[str, str], str] = {}
        clones: list[Derective_fn] = []
        for fn_name, specs in call_specs.items():
            template = fn_by_name.get(fn_name)
            if template is None or not template.generics:
                continue
            for signature, concrete_generics in specs.items():
                mapping = {
                    generic_param.name: concrete
                    for generic_param, concrete in zip(template.generics, concrete_generics, strict=False)
                }
                clone = deepcopy(template)
                clone.generics = []
                clone.name = self._generic_clone_name(template.name, signature)
                clone = self._rewrite_types(clone, mapping)
                clones.append(clone)
                renames[(fn_name, signature)] = clone.name

        if not clones:
            return ast

        rewritten: list[Derective] = []
        for directive in ast:
            rewritten.append(self._rewrite_generic_calls(directive, renames))
        rewritten.extend(self._rewrite_generic_calls(clone, renames) for clone in clones)

        return rewritten

    def _rewrite_generic_calls(self, value, renames: dict[tuple[str, str], str]):
        if isinstance(value, Type):
            if isinstance(value, Pointer):
                return Pointer(self._rewrite_generic_calls(value.pointee, renames))
            if isinstance(value, Reference):
                return Reference(self._rewrite_generic_calls(value.pointee, renames))
            return Type(value.name, [self._rewrite_generic_calls(generic, renames) for generic in value.generics])
        if isinstance(value, list):
            return [self._rewrite_generic_calls(item, renames) for item in value]
        if isinstance(value, Primitive):
            return value
        if isinstance(value, Instruction_call):
            if value.generics:
                signature = ",".join(mangle_type_name(generic) for generic in value.generics)
                renamed = renames.get((value.fn_name, signature))
                if renamed is not None:
                    return replace(value, fn_name=renamed, generics=[])
            return value
        if not is_dataclass(value):
            return value
        return replace(
            value,
            **{field.name: self._rewrite_generic_calls(getattr(value, field.name), renames) for field in fields(value)},
        )

    def _build_concrete_enums(
        self,
        ast: list[Derective],
        generic_enums: dict[str, Derective_enum],
    ) -> list[Derective_enum]:
        observed: dict[str, Type] = {}
        for item in self._walk(ast):
            if isinstance(item, Type):
                self._collect_concrete_enum_type(item, generic_enums, observed)

        concrete: list[Derective_enum] = []
        for typ in observed.values():
            template = generic_enums[typ.name]
            mapping = {generic.name: actual for generic, actual in zip(template.generics, typ.generics, strict=False)}
            concrete.append(
                Derective_enum(
                    name=mangle_type_name(typ),
                    generics=[],
                    variants=[self._replace_enum_variant_types(v, mapping) for v in template.variants],
                    is_public=template.is_public,
                    attrs=template.attrs,
                )
            )
        return concrete

    def _collect_concrete_enum_type(
        self,
        typ: Type,
        generic_enums: dict[str, Derective_enum],
        out: dict[str, Type],
    ) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_concrete_enum_type(typ.pointee, generic_enums, out)
            return
        for generic in typ.generics:
            self._collect_concrete_enum_type(generic, generic_enums, out)
        if typ.name not in generic_enums or not typ.generics:
            return
        if any(self._is_placeholder_type(generic) for generic in typ.generics):
            return
        out[mangle_type_name(typ)] = deepcopy(typ)

    def _is_placeholder_type(self, typ: Type) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return self._is_placeholder_type(typ.pointee)
        if not typ.generics and (typ.name in {"T", "Self"} or (len(typ.name) == 1 and typ.name.isupper())):
            return True
        return any(self._is_placeholder_type(generic) for generic in typ.generics)

    def _replace_enum_variant_types(
        self,
        variant: UnitLikeVariant | TupleLikeVariant,
        mapping: dict[str, Type],
    ) -> UnitLikeVariant | TupleLikeVariant:
        if isinstance(variant, UnitLikeVariant):
            return UnitLikeVariant(name=variant.name)
        if isinstance(variant, TupleLikeVariant):
            return TupleLikeVariant(
                name=variant.name,
                types=[self._replace_type(t, mapping) for t in variant.types],
            )
        raise TypeError(f"Unknown enum variant kind: {type(variant)}")

    def _canonicalize_stack_wrap_calls(self, directives: list[Derective]) -> None:
        for directive in directives:
            if not isinstance(directive, Derective_fn):
                continue
            for block in directive.body:
                new_body = []
                for instr in block.body:
                    if (
                        isinstance(instr, Instruction_call)
                        and instr.fn_name.endswith("::from_stack")
                        and len(instr.args) == 1
                    ):
                        new_body.append(Instruction_wraps(var_out=instr.var_out, variable=instr.args[0]))
                    else:
                        new_body.append(instr)
                block.body = new_body

    def _collect_concrete_box_types(self, ast: list[Derective]) -> list[Type]:
        observed: dict[str, Type] = {}
        for item in self._walk(ast):
            if isinstance(item, Type):
                self._collect_from_type(item, observed)
        return list(observed.values())

    def _collect_from_type(self, typ: Type, out: dict[str, Type]) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_from_type(typ.pointee, out)
            return
        for g in typ.generics:
            self._collect_from_type(g, out)
        if typ.name == "Box" and len(typ.generics) == 1:
            inner = typ.generics[0]
            if isinstance(inner, PrimitiveType):
                out[str(inner)] = deepcopy(inner)
            elif not inner.generics and inner.name not in {"T", "Self"}:
                out[str(inner)] = deepcopy(inner)

    def _rewrite_box_uses_in_value(self, value):
        if isinstance(value, Type):
            return self._rewrite_box_type(value)
        if isinstance(value, list):
            return [self._rewrite_box_uses_in_value(item) for item in value]
        if isinstance(value, Primitive):
            return value
        if not is_dataclass(value):
            return value
        if isinstance(value, Struct) and value.name == "Box" and len(value.generics) == 1:
            inner = self._rewrite_box_type(value.generics[0])
            if self._is_placeholder_type(inner):
                return replace(
                    value,
                    name="Box",
                    generics=[inner],
                )
            return replace(
                value,
                name=concrete_box_type_name(inner),
                generics=[],
            )
        return replace(
            value,
            **{f.name: self._rewrite_box_uses_in_value(getattr(value, f.name)) for f in fields(value)},
        )

    def _rewrite_enum_uses_in_value(self, value, enum_names: set[str]):
        if isinstance(value, Type):
            return self._rewrite_enum_type(value, enum_names)
        if isinstance(value, list):
            return [self._rewrite_enum_uses_in_value(item, enum_names) for item in value]
        if isinstance(value, Primitive):
            return value
        if not is_dataclass(value):
            return value
        if isinstance(value, Enum):
            rewritten_generics = [self._rewrite_enum_type(generic, enum_names) for generic in value.generics]
            if (
                value.name in enum_names
                and rewritten_generics
                and not any(self._is_placeholder_type(generic) for generic in rewritten_generics)
            ):
                concrete_type = Type(value.name, rewritten_generics)
                return replace(
                    value,
                    name=mangle_type_name(concrete_type),
                    generics=[],
                    args=[self._rewrite_enum_uses_in_value(arg, enum_names) for arg in value.args],
                )
        return replace(
            value,
            **{f.name: self._rewrite_enum_uses_in_value(getattr(value, f.name), enum_names) for f in fields(value)},
        )

    def _rewrite_box_call_names(self, ast: list[Derective]) -> None:
        for item in self._walk(ast):
            if isinstance(item, Instruction_call) and self._is_box_template_method_name(item.fn_name):
                method = item.fn_name.rsplit("::", 1)[-1]
                owner = self._infer_call_owner(item)
                if owner is not None:
                    item.fn_name = f"{owner}::{method}"

    def _infer_call_owner(self, call: Instruction_call) -> str | None:
        if call.args:
            recv = call.args[0]
            if recv.type is not None and recv.type.name.startswith("__Box_"):
                return recv.type.name
        if call.var_out.type is not None and call.var_out.type.name.startswith("__Box_"):
            return call.var_out.type.name
        return None

    def _rewrite_box_type(self, typ: Type) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._rewrite_box_type(typ.pointee))
        if isinstance(typ, Reference):
            return Reference(self._rewrite_box_type(typ.pointee))
        rewritten_generics = [self._rewrite_box_type(g) for g in typ.generics]
        if rewritten_generics and any(self._is_placeholder_type(generic) for generic in rewritten_generics):
            return Type(typ.name, rewritten_generics)
        if typ.name == "Box" and len(rewritten_generics) == 1:
            return Type(concrete_box_type_name(rewritten_generics[0]))
        return Type(typ.name, rewritten_generics)

    def _rewrite_enum_type(self, typ: Type, enum_names: set[str]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._rewrite_enum_type(typ.pointee, enum_names))
        if isinstance(typ, Reference):
            return Reference(self._rewrite_enum_type(typ.pointee, enum_names))
        rewritten_generics = [self._rewrite_enum_type(generic, enum_names) for generic in typ.generics]
        if (
            typ.name in enum_names
            and rewritten_generics
            and not any(self._is_placeholder_type(generic) for generic in rewritten_generics)
        ):
            return Type(mangle_type_name(Type(typ.name, rewritten_generics)))
        return Type(typ.name, rewritten_generics)

    def _rewrite_types(self, value, mapping: dict[str, Type]):
        if isinstance(value, Type):
            return self._replace_type(value, mapping)
        if isinstance(value, list):
            return [self._rewrite_types(item, mapping) for item in value]
        if isinstance(value, Primitive):
            return value
        if not is_dataclass(value):
            return value
        return replace(
            value,
            **{field.name: self._rewrite_types(getattr(value, field.name), mapping) for field in fields(value)},
        )

    def _replace_type(self, typ: Type, mapping: dict[str, Type]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type(typ.pointee, mapping))
        if isinstance(typ, Reference):
            return Reference(self._replace_type(typ.pointee, mapping))
        if not typ.generics and typ.name in mapping:
            return deepcopy(mapping[typ.name])
        return Type(typ.name, [self._replace_type(g, mapping) for g in typ.generics])

    def _walk(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        yield value
        if isinstance(value, dict):
            for k, v in value.items():
                yield from self._walk(k)
                yield from self._walk(v)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from self._walk(item)
            return
        if is_dataclass(value):
            for f in fields(value):
                yield from self._walk(getattr(value, f.name))
