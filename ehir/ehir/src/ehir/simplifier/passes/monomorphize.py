from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass, replace

from ehir.resolver import EHIR_TypedModule
from ehir.core.derectives import Derective_enum, Derective_fn, Derective_impl, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import Instruction_call, Instruction_callvoid, Instruction_wraps
from ehir.core.primitives import Usize_t
from ehir.core.primitives.base import Primitive
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type, concrete_box_type_name, mangle_type_name
from ehir.core.variable import Parameter
from ehir.simplifier.base import SimplifierPass


class MonomorphizationPass(SimplifierPass):
    _GENERIC_MONO_PASSES = 8
    _known_concrete_type_names: set[str]

    @staticmethod
    def _generic_clone_name(fn_name: str, signature: str) -> str:
        # Use a dedicated marker to avoid collisions with user-authored names
        # like `foo__T` and to prevent accidental self-recursion after rewrite.
        return f"{fn_name}__mono__{signature}"

    @staticmethod
    def _is_box_template_method_name(name: str) -> bool:
        return name.startswith("Box[T]::") or name.startswith("Box::")

    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        self._known_concrete_type_names = {
            d.name for d in ast if isinstance(d, (Derective_struct, Derective_enum))
        }
        box_struct = next((d for d in ast if isinstance(d, Derective_struct) and d.name == "Box" and d.generics), None)
        concrete_box_types = self._collect_concrete_box_types(ast)
        if box_struct is None:
            if concrete_box_types or self._uses_box_type(ast):
                ast = [*ast, *self._builtin_box_structs(ast, concrete_box_types)]
                for i, directive in enumerate(ast):
                    ast[i] = self._rewrite_box_uses_in_value(directive)
                self._rewrite_box_call_names(ast)
                self._canonicalize_stack_wrap_calls(ast)
            out = self._run_generic_monomorphization_fixpoint(ast)
            return self._prune_unreferenced_generic_functions(out)

        box_methods = [
            d
            for d in ast
            if isinstance(d, Derective_fn)
            and self._is_box_template_method_name(d.name)
        ]

        if not concrete_box_types:
            out = self._run_generic_monomorphization_fixpoint(ast)
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
        out = self._run_generic_monomorphization_fixpoint(filtered)
        return self._prune_unreferenced_generic_functions(out)

    def _run_generic_monomorphization_fixpoint(self, ast: list[Derective]) -> list[Derective]:
        out = ast
        for _ in range(self._GENERIC_MONO_PASSES):
            next_out = self._monomorphize_generic_functions(out)
            changed = next_out is not out
            out = next_out
            next_out = self._materialize_concrete_box_uses(out)
            if next_out is not out:
                changed = True
                out = next_out
            if self._rewrite_concrete_trait_calls(out):
                changed = True
            if not changed:
                break
        return out

    def _materialize_concrete_box_uses(self, ast: list[Derective]) -> list[Derective]:
        concrete_box_types = self._collect_concrete_box_types(ast)
        if not concrete_box_types and not self._uses_box_type(ast):
            return ast

        existing_structs = {
            directive.name
            for directive in ast
            if isinstance(directive, Derective_struct)
        }
        new_structs = [
            directive
            for directive in self._builtin_box_structs(ast, concrete_box_types)
            if directive.name not in existing_structs
        ]

        for i, directive in enumerate(ast):
            ast[i] = self._rewrite_box_uses_in_value(directive)
        self._rewrite_box_call_names(ast)
        self._canonicalize_stack_wrap_calls(ast)

        if not new_structs:
            return ast

        out = [*ast, *new_structs]
        self._known_concrete_type_names.update(directive.name for directive in new_structs)
        return out

    def _prune_unreferenced_generic_functions(self, ast: list[Derective]) -> list[Derective]:
        referenced_fn_names: set[str] = set()
        for directive in ast:
            if isinstance(directive, Derective_fn) and self._is_unresolved_template_fn(directive):
                continue
            for item in self._walk(directive):
                if isinstance(item, Instruction_call):
                    referenced_fn_names.add(item.fn_name)
        pruned: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_fn):
                if (
                    self._is_unresolved_template_fn(directive)
                    and directive.name not in referenced_fn_names
                ):
                    continue
                pruned.append(directive)
                continue

            if isinstance(directive, Derective_impl):
                pruned.append(directive)
                continue

            pruned.append(directive)

        return pruned

    def _lifted_impl_template_names(self, ast: list[Derective]) -> set[str]:
        names: set[str] = set()
        for directive in ast:
            if not isinstance(directive, Derective_impl):
                continue
            owner = directive.trait_name if directive.trait_name else str(directive.for_type)
            if not owner:
                continue
            for method in directive.methods:
                method_name = method.name
                if "::" in method_name:
                    names.add(method_name)
                    continue
                if directive.trait_name is not None:
                    suffix = mangle_type_name(directive.for_type)
                    if directive.trait_args:
                        trait_suffix = "_".join(mangle_type_name(arg) for arg in directive.trait_args)
                        if trait_suffix:
                            suffix = f"{suffix}__{trait_suffix}" if suffix else trait_suffix
                    if suffix:
                        method_name = f"{method_name}__{suffix}"
                names.add(f"{owner}::{method_name}")
        return names

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
        self._hydrate_call_arg_types(ast)
        fn_by_name = {d.name: d for d in ast if isinstance(d, Derective_fn)}
        generic_aliases = self._generic_function_aliases(fn_by_name)
        call_specs: dict[str, dict[str, list[Type]]] = {}
        erased_clone_specs: dict[str, tuple[Derective_fn, list[Type]]] = {}
        for item in self._walk(ast):
            if not isinstance(item, (Instruction_call, Instruction_callvoid)):
                continue
            erased_target = self._erased_retain_drop_alias(item.fn_name, fn_by_name)
            if erased_target is not None and item.args and all(arg.type is not None for arg in item.args):
                erased_clone_specs.setdefault(
                    item.fn_name,
                    (erased_target, [deepcopy(arg.type) for arg in item.args if arg.type is not None]),
                )
            resolved = self._resolve_generic_call(item, fn_by_name, generic_aliases)
            if resolved is None:
                continue
            target, concrete_generics = resolved
            if any(self._is_placeholder_type(generic) for generic in concrete_generics):
                continue
            signature = ",".join(mangle_type_name(generic) for generic in concrete_generics)
            call_specs.setdefault(target.name, {})[signature] = [deepcopy(generic) for generic in concrete_generics]

        if not call_specs and not erased_clone_specs:
            return ast

        renames: dict[tuple[str, str], str] = {}
        clones: list[Derective_fn] = []
        existing_names = set(fn_by_name)
        for clone_name, (template, arg_types) in erased_clone_specs.items():
            if clone_name in existing_names:
                continue
            clone = deepcopy(template)
            clone.name = clone_name
            clone.generics = []
            for param, arg_type in zip(clone.params, arg_types, strict=False):
                param.type = deepcopy(arg_type)
            clones.append(clone)
            existing_names.add(clone_name)
        for fn_name, specs in call_specs.items():
            template = fn_by_name.get(fn_name)
            if template is None:
                continue
            template_generics = self._effective_fn_generics(template)
            if not template_generics:
                continue
            for signature, concrete_generics in specs.items():
                mapping = {
                    generic_param.name: concrete
                    for generic_param, concrete in zip(template_generics, concrete_generics, strict=False)
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
            rewritten.append(self._rewrite_generic_calls(directive, renames, fn_by_name, generic_aliases))
        rewritten.extend(self._rewrite_generic_calls(clone, renames, fn_by_name, generic_aliases) for clone in clones)

        return rewritten

    def _hydrate_call_arg_types(self, ast: list[Derective]) -> None:
        for directive in ast:
            if not isinstance(directive, Derective_fn):
                continue
            vars_by_name = {param.name: param.type for param in directive.params}
            for block in directive.body:
                for instr in block.body:
                    if isinstance(instr, (Instruction_call, Instruction_callvoid)):
                        for arg in instr.args:
                            if arg.type is None:
                                arg.type = vars_by_name.get(arg.name)
                    var_out = getattr(instr, "var_out", None)
                    if var_out is not None and var_out.type is not None:
                        vars_by_name[var_out.name] = var_out.type

    def _generic_function_aliases(self, fn_by_name: dict[str, Derective_fn]) -> dict[str, Derective_fn]:
        candidates: dict[str, list[Derective_fn]] = {}
        for fn in fn_by_name.values():
            if not self._effective_fn_generics(fn) or "::" not in fn.name:
                continue
            owner_text, method_name = fn.name.rsplit("::", 1)
            alias = f"{owner_text.split('[', 1)[0]}::{method_name.split('[', 1)[0]}"
            candidates.setdefault(alias, []).append(fn)
        return {alias: fns[0] for alias, fns in candidates.items() if len(fns) == 1}

    def _resolve_generic_call(
        self,
        item: Instruction_call | Instruction_callvoid,
        fn_by_name: dict[str, Derective_fn],
        generic_aliases: dict[str, Derective_fn],
    ) -> tuple[Derective_fn, list[Type]] | None:
        target = (
            fn_by_name.get(item.fn_name)
            or generic_aliases.get(item.fn_name)
            or self._generic_prefix_alias(item.fn_name, fn_by_name)
        )
        if target is None:
            return None
        target_generics = self._effective_fn_generics(target)
        if not target_generics:
            return None
        if item.generics:
            if len(target_generics) != len(item.generics):
                return None
            return target, [deepcopy(generic) for generic in item.generics]

        if len(item.args) != len(target.params):
            return None
        mapping: dict[str, Type] = {}
        for param, arg in zip(target.params, item.args, strict=True):
            if arg.type is None:
                return None
            if not self._bind_template_type(param.type, arg.type, mapping):
                return None
        concrete_generics: list[Type] = []
        for generic in target_generics:
            concrete = mapping.get(generic.name)
            if concrete is None:
                return None
            concrete_generics.append(deepcopy(concrete))
        return target, concrete_generics

    def _generic_prefix_alias(self, call_name: str, fn_by_name: dict[str, Derective_fn]) -> Derective_fn | None:
        if not (call_name.startswith("__drop_") or call_name.startswith("__retain_")):
            return None
        candidates = [
            fn
            for name, fn in fn_by_name.items()
            if call_name.startswith(f"{name}_") and self._effective_fn_generics(fn)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda fn: len(fn.name), reverse=True)
        return candidates[0]

    def _erased_retain_drop_alias(self, call_name: str, fn_by_name: dict[str, Derective_fn]) -> Derective_fn | None:
        if not (call_name.startswith("__drop_") or call_name.startswith("__retain_")):
            return None
        candidates = [
            fn
            for name, fn in fn_by_name.items()
            if call_name.startswith(f"{name}_") and not self._effective_fn_generics(fn)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda fn: len(fn.name), reverse=True)
        return candidates[0]

    def _effective_fn_generics(self, fn: Derective_fn) -> list[Type]:
        if fn.generics:
            return fn.generics
        names: list[str] = []

        def collect(typ: Type) -> None:
            if self._is_placeholder_type(typ) and typ.name not in names:
                names.append(typ.name)
            for generic in typ.generics:
                collect(generic)

        collect(fn.ret_type)
        for param in fn.params:
            collect(param.type)
        return [Type(name) for name in names]

    def _rewrite_generic_calls(
        self,
        value,
        renames: dict[tuple[str, str], str],
        fn_by_name: dict[str, Derective_fn],
        generic_aliases: dict[str, Derective_fn],
    ):
        if isinstance(value, Type):
            if isinstance(value, Pointer):
                return Pointer(self._rewrite_generic_calls(value.pointee, renames, fn_by_name, generic_aliases))
            if isinstance(value, Reference):
                return Reference(self._rewrite_generic_calls(value.pointee, renames, fn_by_name, generic_aliases))
            return Type(
                value.name,
                [self._rewrite_generic_calls(generic, renames, fn_by_name, generic_aliases) for generic in value.generics],
            )
        if isinstance(value, list):
            return [self._rewrite_generic_calls(item, renames, fn_by_name, generic_aliases) for item in value]
        if isinstance(value, Primitive):
            return value
        if isinstance(value, (Instruction_call, Instruction_callvoid)):
            resolved = self._resolve_generic_call(value, fn_by_name, generic_aliases)
            if resolved is not None:
                target, concrete_generics = resolved
                signature = ",".join(mangle_type_name(generic) for generic in concrete_generics)
                renamed = renames.get((target.name, signature))
                if renamed is not None:
                    return replace(value, fn_name=renamed, generics=[])
            return value
        if not is_dataclass(value):
            return value
        return replace(
            value,
            **{
                field.name: self._rewrite_generic_calls(getattr(value, field.name), renames, fn_by_name, generic_aliases)
                for field in fields(value)
            },
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
        if typ.name in self._known_concrete_type_names:
            return any(self._is_placeholder_type(generic) for generic in typ.generics)
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

    def _uses_box_type(self, ast: list[Derective]) -> bool:
        return any(isinstance(item, Type) and item.name == "Box" and len(item.generics) == 1 for item in self._walk(ast))

    def _collect_from_type(self, typ: Type, out: dict[str, Type]) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_from_type(typ.pointee, out)
            return
        for g in typ.generics:
            self._collect_from_type(g, out)
        if typ.name == "Box" and len(typ.generics) == 1:
            inner = typ.generics[0]
            if not self._is_placeholder_type(inner):
                out[str(inner)] = deepcopy(inner)

    def _builtin_box_structs(self, ast: list[Derective], concrete_box_types: list[Type]) -> list[Derective_struct]:
        existing = {directive.name for directive in ast if isinstance(directive, Derective_struct)}
        result: list[Derective_struct] = []
        if "OwnerHeader" not in existing:
            result.append(
                Derective_struct(
                    name="OwnerHeader",
                    generics=[],
                    params=[
                        Parameter("kind", Usize_t(8)),
                        Parameter("ref_count", Usize_t()),
                        Parameter("inner", Usize_t(1)),
                        Parameter("outer", Usize_t(1)),
                        Parameter("active", Usize_t(1)),
                        Parameter("deal", Usize_t(1)),
                    ],
                )
            )
            existing.add("OwnerHeader")
        if "Box" not in existing:
            result.append(
                Derective_struct(
                    name="Box",
                    generics=[Type("T")],
                    params=[
                        Parameter("ptr", Pointer(Type("T"))),
                        Parameter("owner", Pointer(Type("OwnerHeader"))),
                    ],
                )
            )
            existing.add("Box")
        for inner in concrete_box_types:
            name = concrete_box_type_name(inner)
            if name in existing:
                continue
            result.append(
                Derective_struct(
                    name=name,
                    generics=[],
                    params=[
                        Parameter("ptr", Pointer(deepcopy(inner))),
                        Parameter("owner", Pointer(Type("OwnerHeader"))),
                    ],
                )
            )
            existing.add(name)
        return result

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

    def _rewrite_concrete_trait_calls(self, ast: list[Derective]) -> bool:
        impls = [directive for directive in ast if isinstance(directive, Derective_impl) and directive.trait_name]
        fn_by_name = {directive.name: directive for directive in ast if isinstance(directive, Derective_fn)}
        changed = False
        for item in self._walk(ast):
            if not isinstance(item, Instruction_call):
                continue
            if "::" not in item.fn_name or not item.args:
                continue
            trait_name, method_name = item.fn_name.rsplit("::", 1)
            if "__" in method_name and method_name != "op":
                continue
            receiver_type = item.args[0].type
            if receiver_type is None or self._is_placeholder_type(receiver_type):
                continue
            receiver_type = receiver_type.pointee if isinstance(receiver_type, Reference) else receiver_type
            target = self._concrete_trait_call_target(
                trait_name,
                method_name,
                receiver_type,
                impls,
                fn_by_name,
            )
            if target is not None:
                target_name, target_generics = target
                if item.fn_name != target_name or item.generics != target_generics:
                    item.fn_name = target_name
                    item.generics = target_generics
                    changed = True
        return changed

    def _concrete_trait_call_target(
        self,
        trait_name: str,
        method_name: str,
        receiver_type: Type,
        impls: list[Derective_impl],
        fn_by_name: dict[str, Derective_fn],
    ) -> tuple[str, list[Type]] | None:
        for impl in impls:
            if impl.trait_name != trait_name and impl.trait_name.rsplit("::", 1)[-1] != trait_name.rsplit("::", 1)[-1]:
                continue
            mapping: dict[str, Type] = {}
            if not self._bind_template_type(impl.for_type, receiver_type, mapping):
                continue
            method = next((candidate for candidate in impl.methods if candidate.name == method_name), None)
            if method is None:
                continue
            base_name = self._trait_impl_method_name(impl, method, receiver_type)
            direct_name = f"{impl.trait_name}::{base_name}"
            concrete_generics = self._resolve_trait_impl_generics(impl, method, mapping)
            direct_fn = fn_by_name.get(direct_name)
            if direct_fn is not None:
                if direct_fn.generics:
                    if concrete_generics is None:
                        continue
                    return (direct_name, concrete_generics)
                return (direct_name, [])

            if concrete_generics is None:
                continue
            signature = ",".join(mangle_type_name(generic) for generic in concrete_generics)
            mono_name = self._generic_clone_name(direct_name, signature)
            if mono_name in fn_by_name:
                return (mono_name, [])
        return None

    def _trait_impl_method_name(self, impl: Derective_impl, method: Derective_fn, receiver_type: Type) -> str:
        suffix = (
            self._mangle_type_template_name(impl.for_type)
            if impl.generics or method.generics
            else mangle_type_name(receiver_type)
        )
        if impl.trait_args:
            trait_suffix = "_".join(self._mangle_type_template_name(arg) for arg in impl.trait_args)
            if trait_suffix:
                suffix = f"{suffix}__{trait_suffix}" if suffix else trait_suffix
        if not suffix:
            return method.name
        return f"{method.name}__{suffix}"

    def _resolve_trait_impl_generics(
        self,
        impl: Derective_impl,
        method: Derective_fn,
        mapping: dict[str, Type],
    ) -> list[Type] | None:
        merged = self._merge_generics(impl.generics, method.generics)
        result: list[Type] = []
        for generic in merged:
            concrete = mapping.get(generic.name)
            if concrete is None:
                return None
            result.append(deepcopy(concrete))
        return result

    def _merge_generics(self, *generic_groups: list[Type]) -> list[Type]:
        merged: list[Type] = []
        seen: set[str] = set()
        for group in generic_groups:
            for generic in group:
                if generic.name in seen:
                    continue
                seen.add(generic.name)
                merged.append(generic)
        return merged

    def _mangle_type_template_name(self, typ: Type) -> str:
        if isinstance(typ, Pointer):
            return f"{self._mangle_type_template_name(typ.pointee)}_ptr"
        if isinstance(typ, Reference):
            return f"{self._mangle_type_template_name(typ.pointee)}_ref"
        name = typ.name.replace("::", "_")
        if not typ.generics:
            return name
        inner = "_".join(self._mangle_type_template_name(generic) for generic in typ.generics)
        return f"{name}_{inner}"

    def _bind_template_type(self, template: Type, concrete: Type, mapping: dict[str, Type]) -> bool:
        if isinstance(template, Pointer) and isinstance(concrete, Pointer):
            return self._bind_template_type(template.pointee, concrete.pointee, mapping)
        if isinstance(template, Reference) and isinstance(concrete, Reference):
            return self._bind_template_type(template.pointee, concrete.pointee, mapping)
        if not template.generics and self._is_placeholder_type(template):
            existing = mapping.get(template.name)
            if existing is None:
                mapping[template.name] = deepcopy(concrete)
                return True
            return existing == concrete
        if template.name != concrete.name and template.name.rsplit("::", 1)[-1] != concrete.name.rsplit("::", 1)[-1]:
            return False
        if len(template.generics) != len(concrete.generics):
            return False
        for template_generic, concrete_generic in zip(template.generics, concrete.generics, strict=True):
            if not self._bind_template_type(template_generic, concrete_generic, mapping):
                return False
        return True

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
