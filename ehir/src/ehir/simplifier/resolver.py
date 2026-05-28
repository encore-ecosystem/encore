from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass

from ehir.core.derectives import (
    Derective_enum,
    Derective_extern_fn,
    Derective_fn,
    Derective_impl,
    Derective_struct,
    Derective_trait,
    Derective_typealias,
)
from ehir.core.derectives.base import Derective
from ehir.core.enum import TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    Instruction_add,
    Instruction_and,
    Instruction_call,
    Instruction_callvoid,
    Instruction_capenum,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_div,
    Instruction_drop,
    Instruction_geq,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_grt,
    Instruction_halloc,
    Instruction_hrealloc,
    Instruction_ieq,
    Instruction_leq,
    Instruction_les,
    Instruction_load,
    Instruction_match,
    Instruction_mod,
    Instruction_mul,
    Instruction_neq,
    Instruction_or,
    Instruction_pcast,
    Instruction_ret,
    Instruction_salloc,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_shl,
    Instruction_shr,
    Instruction_store,
    Instruction_sub,
    Instruction_wraph,
    Instruction_wraps,
    Instruction_xor,
)
from ehir.core.primitives import Char_t, Float_t, Isize_t, Str_t, Usize_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Reference, Type, box_pointee, concrete_box_type_name, is_box_type, mangle_type_name
from ehir.core.variable import Parameter, Variable
from ehir.errors import EhirCompileError

_BOOL = Usize_t(1)
_BIN_SAME = (
    Instruction_add,
    Instruction_sub,
    Instruction_mul,
    Instruction_div,
    Instruction_mod,
    Instruction_shl,
    Instruction_shr,
    Instruction_and,
    Instruction_or,
    Instruction_xor,
)
_BIN_BOOL = (
    Instruction_les,
    Instruction_grt,
    Instruction_leq,
    Instruction_geq,
    Instruction_ieq,
    Instruction_neq,
)


@dataclass
class _MethodSig:
    params: list[Type]
    ret: Type


class Resolver:
    fn: dict[str, Derective_fn | Derective_extern_fn]
    structs: dict[str, Derective_struct]
    enums: dict[str, Derective_enum]
    traits: dict[str, Derective_trait]
    impls: list[Derective_impl]
    type_aliases: dict[str, Type]
    _trait_parents: dict[str, list[str]]

    def run(self, ast: list[Derective]) -> list[Derective]:
        self.fn = {}
        self.structs = {}
        self.enums = {}
        self.traits = {}
        self.impls = []
        self.type_aliases = {}
        self._current_fn_name: str | None = None
        self._trait_parents = {}

        for d in ast:
            if isinstance(d, Derective_typealias):
                self.type_aliases[d.name] = deepcopy(d.target)
            elif isinstance(d, Derective_struct):
                self.structs[d.name] = d
            elif isinstance(d, Derective_enum):
                self.enums[d.name] = d
            elif isinstance(d, Derective_trait):
                self.traits[d.name] = d
            elif isinstance(d, Derective_impl):
                self.impls.append(d)
            elif isinstance(d, (Derective_fn, Derective_extern_fn)):
                if isinstance(d.ret_type, Pointer):
                    short_name = d.name.split("::")[-1]
                    if not short_name.startswith("__"):
                        raise EhirCompileError(
                            f"Returning raw pointers is forbidden in EHIR: {d.name} -> {d.ret_type}", code="EHIR1001"
                        )
                self.fn[d.name] = d

        self._validate_trait_hierarchy()
        self._validate_dyn_trait_usage()
        self._validate_impl_coherence()
        self._expand_inherent_impl_methods(ast)
        self._rewrite_declaration_types(ast)

        for fn in self.fn.values():
            if isinstance(fn, Derective_extern_fn):
                continue
            self._resolve_fn(fn)
        for impl in self.impls:
            for method in impl.methods:
                self._resolve_fn(method)

        return ast

    def _validate_impl_coherence(self) -> None:
        seen_impl_keys: set[tuple[str, str]] = set()
        seen_impl_templates: list[tuple[str, Type, set[str]]] = []
        for impl in self.impls:
            method_names = [method.name for method in impl.methods]
            duplicates = {name for name in method_names if method_names.count(name) > 1}
            if duplicates:
                dup = sorted(duplicates)[0]
                raise EhirCompileError(f"Duplicate method '{dup}' in impl for '{impl.for_type}'", code="EHIR1101")

            if impl.trait_name is None:
                continue

            trait_decl = self.traits.get(impl.trait_name)
            if trait_decl is None:
                short = impl.trait_name.split("::")[-1]
                trait_decl = next((trait for trait in self.traits.values() if trait.name.split("::")[-1] == short), None)
            if trait_decl is None:
                raise EhirCompileError(
                    f"Unknown trait '{impl.trait_name}' in impl for '{impl.for_type}'", code="EHIR1102"
                )

            trait_methods = self._trait_method_names_with_parents(trait_decl.name)
            impl_methods = {method.name for method in impl.methods}
            missing = trait_methods - impl_methods
            extra = impl_methods - trait_methods
            if missing:
                first = sorted(missing)[0]
                raise EhirCompileError(
                    f"Trait impl '{trait_decl.name}' for '{impl.for_type}' misses method '{first}'", code="EHIR1103"
                )
            if extra:
                first = sorted(extra)[0]
                raise EhirCompileError(
                    f"Trait impl '{trait_decl.name}' for '{impl.for_type}' defines unknown method '{first}'",
                    code="EHIR1104",
                )

            key = (trait_decl.name, str(self._resolve_type(impl.for_type)))
            if key in seen_impl_keys:
                raise EhirCompileError(
                    f"Conflicting trait impl: '{trait_decl.name}' already implemented for '{key[1]}'", code="EHIR1105"
                )
            seen_impl_keys.add(key)
            resolved_for = self._resolve_type(impl.for_type)
            current_generic_vars = {generic.name for generic in impl.generics}
            for seen_trait, seen_for, seen_generic_vars in seen_impl_templates:
                if seen_trait != trait_decl.name:
                    continue
                if self._types_overlap(
                    seen_for,
                    resolved_for,
                    left_vars=seen_generic_vars,
                    right_vars=current_generic_vars,
                ):
                    raise EhirCompileError(
                        (
                            f"Conflicting trait impl: '{trait_decl.name}' has overlapping targets "
                            f"'{seen_for}' and '{resolved_for}'"
                        ),
                        code="EHIR1106",
                    )
            seen_impl_templates.append((trait_decl.name, resolved_for, current_generic_vars))

    def _types_overlap(self, left: Type, right: Type, *, left_vars: set[str], right_vars: set[str]) -> bool:
        return self._unify_type_templates(
            left,
            right,
            left_vars=left_vars,
            right_vars=right_vars,
            left_subst={},
            right_subst={},
        )

    def _unify_type_templates(
        self,
        left: Type,
        right: Type,
        *,
        left_vars: set[str],
        right_vars: set[str],
        left_subst: dict[str, Type],
        right_subst: dict[str, Type],
    ) -> bool:
        if not left.generics and self._is_placeholder_type_name(left.name) and left.name in left_vars:
            bound = left_subst.get(left.name)
            if bound is not None:
                return self._unify_type_templates(
                    bound,
                    right,
                    left_vars=left_vars,
                    right_vars=right_vars,
                    left_subst=left_subst,
                    right_subst=right_subst,
                )
            left_subst[left.name] = right
            return True

        if not right.generics and self._is_placeholder_type_name(right.name) and right.name in right_vars:
            bound = right_subst.get(right.name)
            if bound is not None:
                return self._unify_type_templates(
                    left,
                    bound,
                    left_vars=left_vars,
                    right_vars=right_vars,
                    left_subst=left_subst,
                    right_subst=right_subst,
                )
            right_subst[right.name] = left
            return True

        if left.name != right.name:
            return False
        if len(left.generics) != len(right.generics):
            return False
        for left_generic, right_generic in zip(left.generics, right.generics, strict=False):
            if not self._unify_type_templates(
                left_generic,
                right_generic,
                left_vars=left_vars,
                right_vars=right_vars,
                left_subst=left_subst,
                right_subst=right_subst,
            ):
                return False
        return True

    def _validate_trait_hierarchy(self) -> None:
        by_short = {trait.name.split("::")[-1]: trait.name for trait in self.traits.values()}
        self._trait_parents = {}
        for trait in self.traits.values():
            parents: list[str] = []
            if trait.parent is not None:
                full = trait.parent
                if full not in self.traits:
                    full = by_short.get(trait.parent, trait.parent)
                if full not in self.traits:
                    raise EhirCompileError(
                        f"Unknown parent trait '{trait.parent}' for trait '{trait.name}'", code="EHIR1110"
                    )
                parents.append(full)
            self._trait_parents[trait.name] = parents

        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(name: str):
            if name in visited:
                return
            if name in visiting:
                raise EhirCompileError(f"Cyclic trait inheritance detected at '{name}'", code="EHIR1111")
            visiting.add(name)
            for parent in self._trait_parents.get(name, []):
                dfs(parent)
            visiting.remove(name)
            visited.add(name)

        for name in self.traits:
            dfs(name)

    def _validate_dyn_trait_usage(self) -> None:
        for struct_decl in self.structs.values():
            for field in struct_decl.params:
                self._validate_dyn_type(field.type, context=f"struct '{struct_decl.name}' field '{field.name}'")
        for fn_decl in self.fn.values():
            for param in fn_decl.params:
                self._validate_dyn_type(param.type, context=f"fn '{fn_decl.name}' param '{param.name}'")
            self._validate_dyn_type(fn_decl.ret_type, context=f"fn '{fn_decl.name}' return")
        for impl in self.impls:
            self._validate_dyn_type(impl.for_type, context=f"impl target '{impl.for_type}'")
            for method in impl.methods:
                for param in method.params:
                    self._validate_dyn_type(param.type, context=f"method '{method.name}' param '{param.name}'")
                self._validate_dyn_type(method.ret_type, context=f"method '{method.name}' return")

    def _validate_dyn_type(self, typ: Type, *, context: str) -> None:
        if isinstance(typ, Pointer):
            self._validate_dyn_type(typ.pointee, context=context)
            return
        if isinstance(typ, Reference):
            self._validate_dyn_type(typ.pointee, context=context)
            return
        if typ.name == "dyn":
            if len(typ.generics) != 1:
                raise EhirCompileError(f"Invalid dyn type in {context}: expected 'dyn Trait'", code="EHIR1300")
            trait_name = typ.generics[0].name
            trait_decl = self.traits.get(trait_name)
            if trait_decl is None:
                trait_decl = next(
                    (trait for trait in self.traits.values() if trait.name.split("::")[-1] == trait_name),
                    None,
                )
            if trait_decl is None:
                raise EhirCompileError(f"Unknown trait '{trait_name}' in dyn type ({context})", code="EHIR1301")
            if trait_decl.generics:
                raise EhirCompileError(
                    f"dyn for generic trait '{trait_decl.name}' is not supported ({context})", code="EHIR1302"
                )
            for method in self._trait_methods_with_parents(trait_decl.name):
                if method.generics:
                    raise EhirCompileError(
                        f"Trait '{trait_decl.name}' is not object-safe: method '{method.name}' is generic",
                        code="EHIR1303",
                    )
                if self._type_contains_self(method.ret_type):
                    raise EhirCompileError(
                        f"Trait '{trait_decl.name}' is not object-safe: method '{method.name}' returns Self",
                        code="EHIR1304",
                    )
                for index, param in enumerate(method.params):
                    if index == 0:
                        continue
                    if self._type_contains_self(param.type):
                        raise EhirCompileError(
                            (
                                f"Trait '{trait_decl.name}' is not object-safe: method '{method.name}' "
                                "uses Self outside receiver"
                            ),
                            code="EHIR1305",
                        )
            return
        for generic in typ.generics:
            self._validate_dyn_type(generic, context=context)

    def _type_contains_self(self, typ: Type) -> bool:
        if isinstance(typ, Pointer):
            return self._type_contains_self(typ.pointee)
        if isinstance(typ, Reference):
            return self._type_contains_self(typ.pointee)
        if typ.name == "Self" and not typ.generics:
            return True
        return any(self._type_contains_self(generic) for generic in typ.generics)

    def _trait_method_names_with_parents(self, trait_name: str) -> set[str]:
        result: set[str] = set()
        canonical = self._canonical_trait_name(trait_name) or trait_name
        stack = [canonical]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            current = self._canonical_trait_name(current) or current
            if current in seen:
                continue
            seen.add(current)
            trait = self.traits.get(current)
            if trait is None:
                continue
            result |= {method.name for method in trait.methods}
            stack.extend(self._trait_parents.get(current, []))
        return result

    def _trait_methods_with_parents(self, trait_name: str) -> list:
        methods_by_name: dict[str, object] = {}
        canonical = self._canonical_trait_name(trait_name) or trait_name
        stack = [canonical]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            current = self._canonical_trait_name(current) or current
            if current in seen:
                continue
            seen.add(current)
            trait = self.traits.get(current)
            if trait is None:
                continue
            for method in trait.methods:
                methods_by_name.setdefault(method.name, method)
            stack.extend(self._trait_parents.get(current, []))
        return list(methods_by_name.values())

    def _find_trait_method_with_parents(self, trait_name: str, method_name: str):
        for method in self._trait_methods_with_parents(trait_name):
            if method.name == method_name:
                return method
        return None

    def _trait_is_descendant_of(self, child: str, parent: str) -> bool:
        child = self._canonical_trait_name(child) or child
        parent = self._canonical_trait_name(parent) or parent
        if child == parent:
            return True
        stack = list(self._trait_parents.get(child, []))
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            current = self._canonical_trait_name(current) or current
            if current in seen:
                continue
            if current == parent:
                return True
            seen.add(current)
            stack.extend(self._trait_parents.get(current, []))
        return False

    def _canonical_trait_name(self, name: str) -> str | None:
        if name in self.traits:
            return name
        short = name.split("::")[-1]
        matches = [trait_name for trait_name in self.traits if trait_name.split("::")[-1] == short]
        if len(matches) == 1:
            return matches[0]
        return None

    def _expand_inherent_impl_methods(self, ast: list[Derective]) -> None:
        fn_names = {d.name for d in ast if isinstance(d, (Derective_fn, Derective_extern_fn))}
        generated: list[Derective_fn] = []
        for impl in self.impls:
            if impl.trait_name is not None:
                continue
            for method in impl.methods:
                lowered = deepcopy(method)
                merged_generics: list[Type] = []
                known = set()
                for g in [*impl.generics, *method.generics]:
                    if g.name in known:
                        continue
                    known.add(g.name)
                    merged_generics.append(deepcopy(g))
                lowered.generics = merged_generics
                lowered.name = f"{impl.for_type}::{method.name}"
                self._replace_self(lowered, impl.for_type)
                if lowered.name in fn_names:
                    continue
                fn_names.add(lowered.name)
                generated.append(lowered)
                self.fn[lowered.name] = lowered
        ast.extend(generated)

    def _replace_self(self, value, self_type: Type):
        if isinstance(value, Type):
            if isinstance(value, Pointer):
                return Pointer(self._replace_self(value.pointee, self_type))
            if isinstance(value, Reference):
                return Reference(self._replace_self(value.pointee, self_type))
            if value.name == "Self" and not value.generics:
                return deepcopy(self_type)
            return Type(value.name, [self._replace_self(g, self_type) for g in value.generics])
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = self._replace_self(item, self_type)
            return value
        if not is_dataclass(value):
            return value
        for f in fields(value):
            setattr(value, f.name, self._replace_self(getattr(value, f.name), self_type))
        return value

    def _rewrite_declaration_types(self, ast: list[Derective]) -> None:
        for d in ast:
            self._rewrite_types(d)

    def _resolve_fn(self, fn: Derective_fn) -> None:
        self._current_fn_name = fn.name
        vars_by_name: dict[str, Type | None] = {}
        for p in fn.params:
            vars_by_name[p.name] = p.type

        changed = True
        rounds = 0
        while changed and rounds < 32:
            rounds += 1
            changed = False
            for block in fn.body:
                for instr in block.get_body():
                    changed |= self._resolve_instr(instr, fn.ret_type, vars_by_name)

        for block in fn.body:
            for instr in block.get_body():
                self._commit_instr_vars(instr, vars_by_name)
        for i, p in enumerate(fn.params):
            fn.params[i] = Parameter(p.name, self._must_get(vars_by_name, p.name, fn.name))
        self._current_fn_name = None

    def _resolve_instr(self, instr, fn_ret_type: Type, vars_by_name: dict[str, Type | None]) -> bool:
        if isinstance(instr, Instruction_capprim):
            return self._set_var(vars_by_name, instr.var_out, instr.primitive.type)

        if isinstance(instr, Instruction_ret):
            return self._unify_var(vars_by_name, instr.var, fn_ret_type)

        if isinstance(instr, _BIN_SAME):
            changed = self._unify_pair(vars_by_name, instr.lhs, instr.rhs)
            t = self._var_type(vars_by_name, instr.lhs) or self._var_type(vars_by_name, instr.rhs)
            if t is not None:
                changed |= self._set_var(vars_by_name, instr.var_out, t)
            return changed

        if isinstance(instr, _BIN_BOOL):
            changed = self._unify_pair(vars_by_name, instr.lhs, instr.rhs)
            changed |= self._set_var(vars_by_name, instr.var_out, _BOOL)
            return changed

        if isinstance(instr, Instruction_salloc):
            return self._set_var(vars_by_name, instr.var_out, Pointer(instr.type))

        if isinstance(instr, Instruction_halloc):
            return self._set_var(vars_by_name, instr.var_out, Pointer(instr.type))

        if isinstance(instr, Instruction_load):
            ptr_t = self._var_type(vars_by_name, instr.var)
            changed = False
            if isinstance(ptr_t, Pointer):
                changed |= self._set_var(vars_by_name, instr.var_out, ptr_t.pointee)
            out_t = self._var_type(vars_by_name, instr.var_out)
            if out_t is not None:
                changed |= self._unify_var(vars_by_name, instr.var, Pointer(out_t))
            return changed

        if isinstance(instr, Instruction_store):
            src_t = self._var_type(vars_by_name, instr.var_src)
            changed = False
            if src_t is not None:
                changed |= self._unify_var(vars_by_name, instr.var_dst, Pointer(src_t))
            dst_t = self._var_type(vars_by_name, instr.var_dst)
            if isinstance(dst_t, Pointer):
                changed |= self._unify_var(vars_by_name, instr.var_src, dst_t.pointee)
            return changed

        if isinstance(instr, Instruction_pcast):
            return self._set_var(vars_by_name, instr.var_out, instr.type)

        if isinstance(instr, (Instruction_wraps, Instruction_wraph)):
            value_t = self._var_type(vars_by_name, instr.variable)
            if value_t is None:
                return False
            current_t = self._var_type(vars_by_name, instr.var_out)
            if current_t is not None and current_t.name == concrete_box_type_name(value_t):
                return False
            return self._set_var(vars_by_name, instr.var_out, Type("Box", [value_t]))

        if isinstance(instr, Instruction_capstruct):
            return self._resolve_capstruct(instr, vars_by_name)

        if isinstance(instr, Instruction_capenum):
            return self._resolve_capenum(instr, vars_by_name)

        if isinstance(instr, Instruction_call):
            return self._resolve_call(instr, vars_by_name)
        if isinstance(instr, Instruction_callvoid):
            return self._resolve_callvoid(instr, vars_by_name)

        if isinstance(instr, Instruction_getfield):
            return self._resolve_getfield(instr, vars_by_name, as_ptr=False)

        if isinstance(instr, Instruction_getfieldptr):
            return self._resolve_getfield(instr, vars_by_name, as_ptr=True)

        if isinstance(instr, Instruction_sgetfield):
            return self._resolve_static_getfield(instr, vars_by_name, as_ptr=False)

        if isinstance(instr, Instruction_sgetfieldptr):
            return self._resolve_static_getfield(instr, vars_by_name, as_ptr=True)

        if isinstance(instr, Instruction_setfield):
            field_t = self._field_path_type(vars_by_name, instr.var, [instr.field, *instr.field_path])
            if field_t is None:
                return False
            return self._unify_var(vars_by_name, instr.value, field_t)

        if isinstance(instr, Instruction_match):
            return self._resolve_match(instr, vars_by_name)

        if isinstance(instr, Instruction_hrealloc):
            # keep pointer-kind
            return self._unify_pair(vars_by_name, instr.var_out, instr.var)

        if isinstance(instr, Instruction_drop):
            return False

        return False

    def _resolve_capstruct(self, instr: Instruction_capstruct, vars_by_name: dict[str, Type | None]) -> bool:
        struct_decl = self.structs.get(instr.struct.name)
        if struct_decl is None:
            return False
        changed = False
        concrete_generics = list(instr.struct.generics)
        if not concrete_generics and struct_decl.generics:
            mapping: dict[str, Type] = {}
            for p, arg in zip(struct_decl.params, instr.struct.fields, strict=False):
                arg_t = self._var_type(vars_by_name, arg)
                if arg_t is None:
                    continue
                if p.type.name in {g.name for g in struct_decl.generics} and not p.type.generics:
                    mapping[p.type.name] = arg_t
            if len(mapping) == len(struct_decl.generics):
                concrete_generics = [mapping[g.name] for g in struct_decl.generics]
                instr.struct.generics = deepcopy(concrete_generics)
                changed = True

        param_types = self._specialize_params(struct_decl.params, struct_decl.generics, concrete_generics)
        for p, arg in zip(param_types, instr.struct.fields, strict=False):
            changed |= self._unify_var(vars_by_name, arg, p.type)

        out_t = Type(instr.struct.name, deepcopy(concrete_generics))
        changed |= self._set_var(vars_by_name, instr.var_out, self._resolve_type(out_t))
        return changed

    def _resolve_match(self, instr: Instruction_match, vars_by_name: dict[str, Type | None]) -> bool:
        cond_t = self._var_type(vars_by_name, instr.cond_var)
        if cond_t is None:
            return False
        enum_t = cond_t.pointee if isinstance(cond_t, Reference) else cond_t
        enum_t = self._resolve_type(enum_t)
        enum_decl = self.enums.get(enum_t.name)
        if enum_decl is None:
            return False

        changed = False
        for case in instr.cases:
            variant_decl = next((variant for variant in enum_decl.variants if variant.name == case.variant), None)
            if variant_decl is None:
                continue
            if not isinstance(variant_decl, TupleLikeVariant):
                continue
            if case.payload_var is None:
                continue
            if len(variant_decl.types) != 1:
                continue
            payload_t = self._resolve_type(
                self._specialize_type(variant_decl.types[0], enum_decl.generics, enum_t.generics)
            )
            changed |= self._set_var(vars_by_name, case.payload_var, payload_t)
        return changed

    def _resolve_capenum(self, instr: Instruction_capenum, vars_by_name: dict[str, Type | None]) -> bool:
        enum_decl = self.enums.get(instr.enum.name)
        if enum_decl is None:
            return False
        variant = next((v for v in enum_decl.variants if v.name == instr.enum.variant), None)
        if variant is None:
            raise EhirCompileError(f"Unknown variant '{instr.enum.variant}' for enum '{instr.enum.name}'")

        changed = False
        concrete_generics = list(instr.enum.generics)
        if not concrete_generics and enum_decl.generics and isinstance(variant, TupleLikeVariant):
            mapping: dict[str, Type] = {}
            for exp_t, arg in zip(variant.types, instr.enum.args, strict=False):
                arg_t = self._var_type(vars_by_name, arg)
                if arg_t is None:
                    continue
                if exp_t.name in {g.name for g in enum_decl.generics} and not exp_t.generics:
                    mapping[exp_t.name] = arg_t
            if len(mapping) == len(enum_decl.generics):
                concrete_generics = [mapping[g.name] for g in enum_decl.generics]
                instr.enum.generics = deepcopy(concrete_generics)
                changed = True

        if isinstance(variant, UnitLikeVariant):
            if instr.enum.args:
                raise EhirCompileError(f"Unit variant '{variant.name}' does not accept payload")
        elif isinstance(variant, TupleLikeVariant):
            spec_types = self._specialize_types(variant.types, enum_decl.generics, concrete_generics)
            for exp_t, arg in zip(spec_types, instr.enum.args, strict=False):
                changed |= self._unify_var(vars_by_name, arg, exp_t)

        changed |= self._set_var(
            vars_by_name, instr.var_out, self._resolve_type(Type(instr.enum.name, concrete_generics))
        )
        return changed

    def _resolve_call(self, instr: Instruction_call, vars_by_name: dict[str, Type | None]) -> bool:
        self._rewrite_instance_method_call(instr, vars_by_name)
        resolved = self._resolve_callable_signature(instr, vars_by_name)
        if resolved is None:
            return False
        sig, resolved_name = resolved
        instr.fn_name = resolved_name
        changed = False
        for arg, exp_t in zip(instr.args, sig.params, strict=False):
            changed |= self._unify_expected(vars_by_name, arg, exp_t)
        changed |= self._set_var(vars_by_name, instr.var_out, sig.ret)
        return changed

    def _resolve_callvoid(self, instr: Instruction_callvoid, vars_by_name: dict[str, Type | None]) -> bool:
        self._rewrite_instance_method_call(instr, vars_by_name)
        tmp_out = Variable(name=".callvoid_out", type=None)
        proxy = Instruction_call(
            var_out=tmp_out,
            fn_name=instr.fn_name,
            generics=deepcopy(instr.generics),
            args=deepcopy(instr.args),
            is_unsafe=instr.is_unsafe,
        )
        resolved = self._resolve_callable_signature(proxy, vars_by_name)
        if resolved is None:
            return False
        sig, resolved_name = resolved
        instr.fn_name = resolved_name
        instr.generics = proxy.generics
        changed = False
        for arg, exp_t in zip(instr.args, sig.params, strict=False):
            changed |= self._unify_expected(vars_by_name, arg, exp_t)
        if instr.assign_to is not None:
            changed |= self._set_var(vars_by_name, instr.assign_to, sig.ret)
        return changed

    def _rewrite_instance_method_call(
        self,
        instr: Instruction_call | Instruction_callvoid,
        vars_by_name: dict[str, Type | None],
    ) -> None:
        if "::" not in instr.fn_name:
            return
        owner_text, method_name = instr.fn_name.rsplit("::", 1)
        owner_type = vars_by_name.get(owner_text)
        if owner_type is None:
            return
        receiver = Variable(name=owner_text, type=owner_type)
        if isinstance(instr, Instruction_callvoid):
            instr.assign_to = Variable(name=owner_text, type=owner_type)
        owner_base = owner_type.pointee if isinstance(owner_type, Reference) else owner_type
        if owner_base.generics:
            generic_owner = Type(owner_base.name, [Type("T") for _ in owner_base.generics])
            instr.fn_name = f"{generic_owner}::{method_name}"
        else:
            instr.fn_name = f"{owner_base}::{method_name}"
        instr.args = [receiver, *instr.args]

    def _resolve_callable_signature(
        self, instr: Instruction_call, vars_by_name: dict[str, Type | None]
    ) -> tuple[_MethodSig, str] | None:
        instr.fn_name = self._normalize_call_name(instr.fn_name)
        if instr.fn_name.startswith("__dyn_dispatch__"):
            payload = instr.fn_name[len("__dyn_dispatch__") :]
            if "::" not in payload:
                raise EhirCompileError(f"Invalid dyn dispatch call name '{instr.fn_name}'", code="EHIR1310")
            trait_name, method_name = payload.rsplit("::", 1)
            trait_decl = self.traits.get(trait_name)
            if trait_decl is None:
                trait_decl = next(
                    (trait for trait in self.traits.values() if trait.name.split("::")[-1] == trait_name),
                    None,
                )
            if trait_decl is None:
                raise EhirCompileError(f"Unknown trait '{trait_name}' in dyn dispatch", code="EHIR1301")
            trait_method = self._find_trait_method_with_parents(trait_decl.name, method_name)
            if trait_method is None:
                raise EhirCompileError(
                    f"Unknown method '{method_name}' for trait '{trait_decl.name}'",
                    code="EHIR1309",
                )
            if not instr.args:
                raise EhirCompileError("dyn dispatch call requires receiver argument", code="EHIR1311")
            recv_t = self._var_type(vars_by_name, instr.args[0])
            if recv_t is None:
                return None
            recv_base = recv_t.pointee if isinstance(recv_t, Reference) else recv_t
            params: list[Type] = [recv_base]
            for index, param in enumerate(trait_method.params):
                if index == 0:
                    continue
                params.append(self._resolve_type(param.type))
            ret_t = self._resolve_type(trait_method.ret_type)
            return _MethodSig(params=params, ret=ret_t), instr.fn_name

        def _owner_self_type_from_name(name: str) -> Type | None:
            if "::" not in name:
                return None
            owner_text, _ = name.rsplit("::", 1)
            owner = self._parse_type_text(owner_text)
            if owner is None:
                return None
            owner = self._resolve_type(owner)
            return owner.pointee if isinstance(owner, Reference) else owner

        def _apply_self_type(typ: Type, self_type: Type | None) -> Type:
            if self_type is None:
                return typ
            return self._replace_type(typ, {}, self_type)

        def build_sig(fn_directive, self_type: Type | None = None) -> _MethodSig:
            fn_generics = getattr(fn_directive, "generics", [])
            if fn_generics:
                explicit_generics = [self._resolve_type(generic) for generic in instr.generics]
                if len(explicit_generics) == len(fn_generics):
                    mapping = {
                        generic_param.name: concrete
                        for generic_param, concrete in zip(fn_generics, explicit_generics, strict=False)
                    }
                    inferred = self._infer_fn_generic_mapping(fn_directive, instr, vars_by_name)
                    if inferred is None and instr.args:
                        recv_t = self._var_type(vars_by_name, instr.args[0])
                        recv_base = recv_t.pointee if isinstance(recv_t, Reference) else recv_t
                        if recv_base is not None and len(recv_base.generics) == len(fn_generics):
                            inferred = {
                                generic_param.name: deepcopy(concrete)
                                for generic_param, concrete in zip(fn_generics, recv_base.generics, strict=False)
                            }
                    if inferred is not None:
                        for generic_param in fn_generics:
                            explicit = mapping.get(generic_param.name)
                            if explicit is None:
                                continue
                            explicit_is_placeholder = (
                                not explicit.generics
                                and explicit.name == generic_param.name
                            )
                            if explicit_is_placeholder and generic_param.name in inferred:
                                mapping[generic_param.name] = deepcopy(inferred[generic_param.name])
                    return _MethodSig(
                        params=[
                            self._resolve_type(
                                _apply_self_type(self._replace_generics_by_name(param.type, mapping), self_type)
                            )
                            for param in fn_directive.params
                        ],
                        ret=self._resolve_type(
                            _apply_self_type(self._replace_generics_by_name(fn_directive.ret_type, mapping), self_type)
                        ),
                    )
                inferred = self._infer_fn_generic_mapping(fn_directive, instr, vars_by_name)
                if inferred is not None and len(inferred) == len(fn_generics):
                    instr.generics = [deepcopy(inferred[g.name]) for g in fn_generics]
                    mapping = {g.name: deepcopy(inferred[g.name]) for g in fn_generics}
                    return _MethodSig(
                        params=[
                            self._resolve_type(
                                _apply_self_type(self._replace_generics_by_name(param.type, mapping), self_type)
                            )
                            for param in fn_directive.params
                        ],
                        ret=self._resolve_type(
                            _apply_self_type(self._replace_generics_by_name(fn_directive.ret_type, mapping), self_type)
                        ),
                    )
            return _MethodSig(
                params=[self._resolve_type(_apply_self_type(param.type, self_type)) for param in fn_directive.params],
                ret=self._resolve_type(_apply_self_type(fn_directive.ret_type, self_type)),
            )

        trait_owner_call = False
        owner_text_for_trait: str | None = None
        if "::" in instr.fn_name:
            owner_text_for_trait, trait_method_for_trait = instr.fn_name.rsplit("::", 1)
            is_specialized_method_name = "__" in trait_method_for_trait and trait_method_for_trait != "op"
            owner_type_for_trait = self._parse_type_text(owner_text_for_trait)
            if owner_type_for_trait is not None and not is_specialized_method_name:
                owner_base_name = owner_type_for_trait.name
                owner_short_name = owner_base_name.split("::")[-1]
                if owner_base_name in self.traits or any(
                    trait.name.split("::")[-1] == owner_short_name for trait in self.traits.values()
                ):
                    trait_owner_call = True

        if not trait_owner_call:
            direct = self.fn.get(instr.fn_name)
            if direct is not None:
                return (build_sig(direct, _owner_self_type_from_name(instr.fn_name)), direct.name)

        if "::" in instr.fn_name:
            parts = instr.fn_name.split("::")
            if len(parts) >= 2:
                tail = "::".join(parts[-2:])
                tail_direct = self.fn.get(tail)
                if tail_direct is not None and not trait_owner_call:
                    return (build_sig(tail_direct, _owner_self_type_from_name(instr.fn_name)), tail_direct.name)

        if "::" not in instr.fn_name:
            raise EhirCompileError(f"Unknown function '{instr.fn_name}'")
        owner_text, method_name = instr.fn_name.rsplit("::", 1)
        owner_type = self._parse_type_text(owner_text)
        if owner_type is None:
            if "::" in owner_text:
                short_owner = owner_text.split("::")[-1]
                short_name = f"{short_owner}::{method_name}"
                short_direct = self.fn.get(short_name)
                if short_direct is not None:
                    return (build_sig(short_direct), short_direct.name)
            raise EhirCompileError(f"Unknown function '{instr.fn_name}'")
        owner_type = self._resolve_type(owner_type)
        owner_base = owner_type.pointee if isinstance(owner_type, Reference) else owner_type
        if not owner_base.generics and instr.args:
            recv_t = self._var_type(vars_by_name, instr.args[0])
            if recv_t is not None:
                recv_base = recv_t.pointee if isinstance(recv_t, Reference) else recv_t
                owner_short = owner_base.name.split("::")[-1]
                recv_short = recv_base.name.split("::")[-1]
                if owner_short == recv_short and recv_base.generics:
                    owner_base = recv_base

        owner_suffix = self._mangle_type_name(owner_base)
        if owner_suffix:
            mangled_suffix = f"::{method_name}__{owner_suffix}"
            mangled_candidates = [name for name in self.fn if name.endswith(mangled_suffix)]
            if len(mangled_candidates) == 1:
                mangled_direct = self.fn[mangled_candidates[0]]
                return (build_sig(mangled_direct), mangled_direct.name)

        # Trait call form: Trait::method(arg0, ...)
        if instr.args:
            recv_t = self._var_type(vars_by_name, instr.args[0])
            if recv_t is not None:
                recv_base = recv_t.pointee if isinstance(recv_t, Reference) else recv_t
                if recv_base.name == "dyn":
                    if len(recv_base.generics) != 1:
                        raise EhirCompileError("Invalid dyn receiver type", code="EHIR1307")
                    dyn_trait_name = recv_base.generics[0].name
                    trait_decl = self.traits.get(dyn_trait_name)
                    if trait_decl is None:
                        trait_decl = next(
                            (trait for trait in self.traits.values() if trait.name.split("::")[-1] == dyn_trait_name),
                            None,
                        )
                    if trait_decl is None:
                        raise EhirCompileError(
                            f"Unknown trait '{dyn_trait_name}' in dyn dispatch receiver",
                            code="EHIR1301",
                        )
                    owner_name = owner_base.name
                    owner_full = owner_name if owner_name in self.traits else next(
                        (name for name in self.traits if name.split("::")[-1] == owner_name),
                        owner_name,
                    )
                    owner_canonical = self._canonical_trait_name(owner_full)
                    if owner_canonical is None or not self._trait_is_descendant_of(trait_decl.name, owner_canonical):
                        raise EhirCompileError(
                            f"Trait call '{instr.fn_name}' does not match receiver dyn {trait_decl.name}",
                            code="EHIR1308",
                        )
                    trait_method = self._find_trait_method_with_parents(trait_decl.name, method_name)
                    if trait_method is None:
                        raise EhirCompileError(
                            f"Unknown method '{method_name}' for trait '{trait_decl.name}'",
                            code="EHIR1309",
                        )
                    params: list[Type] = [recv_base]
                    for index, param in enumerate(trait_method.params):
                        if index == 0:
                            continue
                        params.append(self._resolve_type(param.type))
                    ret_t = self._resolve_type(trait_method.ret_type)
                    resolved_name = f"__dyn_dispatch__{trait_decl.name}::{method_name}"
                    return _MethodSig(params=params, ret=ret_t), resolved_name
                for impl in self.impls:
                    trait_name = impl.trait_name
                    if trait_name is None:
                        continue
                    trait_short = trait_name.split("::")[-1]
                    owner_name = owner_base.name
                    owner_full = owner_name if owner_name in self.traits else next(
                        (name for name in self.traits if name.split("::")[-1] == owner_name),
                        owner_name,
                    )
                    if not self._trait_is_descendant_of(trait_name, owner_full) and trait_short != owner_name:
                        continue
                    mapping: dict[str, Type] = {}
                    if not self._bind_generic_from_types(impl.for_type, recv_base, mapping):
                        continue
                    method = next((m for m in impl.methods if m.name == method_name), None)
                    if method is None:
                        continue
                    params = [self._resolve_type(self._replace_type(p.type, mapping, recv_base)) for p in method.params]
                    ret_t = self._resolve_type(self._replace_type(method.ret_type, mapping, recv_base))
                    resolved_method = self._trait_impl_method_name(impl, method, recv_base)
                    resolved_generics = self._resolve_trait_impl_generics(impl, method, mapping)
                    if resolved_generics is not None:
                        instr.generics = resolved_generics
                    resolved_name = f"{trait_name}::{resolved_method}"
                    return _MethodSig(params=params, ret=ret_t), resolved_name

        # Fallback: resolve through trait declaration signature even if concrete impl
        # is not selected at this point. This preserves result typing for downstream passes.
        trait_decl = self.traits.get(owner_base.name)
        if trait_decl is None:
            owner_short = owner_base.name.split("::")[-1]
            for trait in self.traits.values():
                if trait.name.split("::")[-1] == owner_short:
                    trait_decl = trait
                    break
        if trait_decl is not None:
            trait_method = next((m for m in trait_decl.methods if m.name == method_name), None)
            if trait_method is not None:
                recv_t = self._var_type(vars_by_name, instr.args[0]) if instr.args else None
                recv_base = recv_t.pointee if isinstance(recv_t, Reference) else recv_t
                params = []
                for param in trait_method.params:
                    param_t = self._resolve_type(param.type)
                    if recv_base is not None and param_t.name == "Self":
                        params.append(recv_base)
                    else:
                        params.append(param_t)
                ret_t = self._resolve_type(trait_method.ret_type)
                if recv_base is not None and ret_t.name == "Self":
                    ret_t = recv_base
                resolved_method = trait_method.name
                if resolved_method != "op" and recv_base is not None:
                    suffix = self._mangle_type_name(recv_base)
                    if suffix:
                        resolved_method = f"{resolved_method}__{suffix}"
                resolved_name = f"{trait_decl.name}::{resolved_method}"
                return _MethodSig(params=params, ret=ret_t), resolved_name

        for impl in self.impls:
            if impl.trait_name is not None:
                continue
            owner_short = owner_base.name.split("::")[-1]
            impl_short = impl.for_type.name.split("::")[-1]
            if impl.for_type.name != owner_base.name and impl_short != owner_short:
                continue
            method = next(
                (
                    m
                    for m in impl.methods
                    if m.name == method_name or m.name.startswith(f"{method_name}__")
                ),
                None,
            )
            if method is None:
                continue
            mapping = self._impl_generic_mapping(impl.for_type, owner_base)
            params = [self._resolve_type(self._replace_type(p.type, mapping, owner_base)) for p in method.params]
            ret_t = self._resolve_type(self._replace_type(method.ret_type, mapping, owner_base))
            resolved_method = method.name
            if resolved_method != "op":
                suffix = self._mangle_type_name(owner_base)
                if suffix:
                    resolved_method = f"{resolved_method}__{suffix}"
            resolved_name = f"{impl.for_type}::{resolved_method}"
            return _MethodSig(params=params, ret=ret_t), resolved_name

        if owner_type.generics:
            generic_owner = Type(owner_type.name, [Type("T") for _ in owner_type.generics])
            generic_name = f"{generic_owner}::{method_name}"
            generic_fn = self.fn.get(generic_name)
            if generic_fn is not None:
                mapping = {f"T{i}": g for i, g in enumerate(owner_type.generics)}
                if owner_type.generics:
                    mapping["T"] = owner_type.generics[0]
                params = [
                    self._resolve_type(self._replace_generics_by_name(p.type, mapping)) for p in generic_fn.params
                ]
                ret = self._resolve_type(self._replace_generics_by_name(generic_fn.ret_type, mapping))
                return (
                    _MethodSig(params=params, ret=ret),
                    generic_name,
                )
        raise EhirCompileError(f"Unknown function '{instr.fn_name}'")

    def _normalize_call_name(self, fn_name: str) -> str:
        # Canonicalize legacy trait-op aliases from `<module>::Trait__op`
        # into `<module>::Trait::op` so resolver/codegen operate on one naming scheme.
        if "::" not in fn_name:
            return fn_name
        owner_text, method_name = fn_name.rsplit("::", 1)
        if method_name.endswith("__op"):
            trait_name = method_name[: -len("__op")]
            if trait_name:
                return f"{owner_text}::{trait_name}::op"
        return fn_name

    def _trait_impl_method_name(self, impl, method: Derective_fn, recv_type: Type) -> str:
        suffix = (
            self._mangle_type_template_name(impl.for_type)
            if impl.generics or method.generics
            else self._mangle_type_name(recv_type)
        )
        if not suffix:
            return method.name
        return f"{method.name}__{suffix}"

    def _resolve_trait_impl_generics(
        self,
        impl,
        method: Derective_fn,
        mapping: dict[str, Type],
    ) -> list[Type] | None:
        merged = self._merge_generics(impl.generics, method.generics)
        if not merged:
            return []

        resolved: list[Type] = []
        for generic in merged:
            concrete = mapping.get(generic.name)
            if concrete is None:
                return None
            resolved.append(deepcopy(concrete))
        return resolved

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

    def _mangle_type_name(self, typ: Type) -> str:
        if self._is_placeholder_type_name(typ.name):
            return ""
        if typ.generics:
            mangled_generics = [self._mangle_type_name(generic) for generic in typ.generics]
            if any(not part for part in mangled_generics):
                return ""
            inner = "_".join(mangled_generics)
            return f"{typ.name.replace('::', '_')}_{inner}"
        return typ.name.replace("::", "_")

    def _is_placeholder_type_name(self, name: str) -> bool:
        if name in {"Self", "T"}:
            return True
        if len(name) == 1 and name.isupper():
            return True
        return len(name) > 1 and name.startswith("T") and name[1:].isdigit()

    def _infer_fn_generic_mapping(
        self,
        fn_directive,
        instr: Instruction_call,
        vars_by_name: dict[str, Type | None],
    ) -> dict[str, Type] | None:
        fn_generics = getattr(fn_directive, "generics", [])
        if not fn_generics:
            return {}
        if len(instr.args) != len(fn_directive.params):
            return None

        mapping: dict[str, Type] = {}
        for arg, param in zip(instr.args, fn_directive.params, strict=True):
            arg_t = self._var_type(vars_by_name, arg)
            if arg_t is None:
                return None
            if not self._bind_generic_from_types(param.type, arg_t, mapping):
                return None

        out_t = self._var_type(vars_by_name, instr.var_out)
        if out_t is not None:
            if not self._bind_generic_from_types(fn_directive.ret_type, out_t, mapping):
                return None

        if any(g.name not in mapping for g in fn_generics):
            return None
        return mapping

    def _bind_generic_from_types(self, template: Type, concrete: Type, mapping: dict[str, Type]) -> bool:
        if isinstance(template, Pointer) and isinstance(concrete, Pointer):
            return self._bind_generic_from_types(template.pointee, concrete.pointee, mapping)
        if isinstance(template, Reference) and isinstance(concrete, Reference):
            return self._bind_generic_from_types(template.pointee, concrete.pointee, mapping)

        if not template.generics and template.name and template.name[0].isupper():
            existed = mapping.get(template.name)
            if existed is None:
                mapping[template.name] = deepcopy(concrete)
                return True
            return self._types_compatible(existed, concrete)

        if template.name != concrete.name:
            return False
        if len(template.generics) != len(concrete.generics):
            return False
        for t_g, c_g in zip(template.generics, concrete.generics, strict=True):
            if not self._bind_generic_from_types(t_g, c_g, mapping):
                return False
        return True

    def _replace_generics_by_name(self, typ: Type, mapping: dict[str, Type]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._replace_generics_by_name(typ.pointee, mapping))
        if isinstance(typ, Reference):
            return Reference(self._replace_generics_by_name(typ.pointee, mapping))
        if not typ.generics and typ.name in mapping:
            return deepcopy(mapping[typ.name])
        return Type(typ.name, [self._replace_generics_by_name(g, mapping) for g in typ.generics])

    def _resolve_getfield(
        self, instr: Instruction_getfield | Instruction_getfieldptr, vars_by_name: dict[str, Type | None], as_ptr: bool
    ) -> bool:
        field_t = self._field_path_type(vars_by_name, instr.src, [instr.field, *instr.field_path])
        if field_t is None:
            return False
        if as_ptr:
            field_t = Pointer(field_t)
        return self._set_var(vars_by_name, instr.var_out, field_t)

    def _resolve_static_getfield(
        self,
        instr: Instruction_sgetfield | Instruction_sgetfieldptr,
        vars_by_name: dict[str, Type | None],
        as_ptr: bool,
    ) -> bool:
        src_t = self._var_type(vars_by_name, instr.src)
        if src_t is None:
            return False

        owner_t = src_t.pointee if isinstance(src_t, (Reference, Pointer)) else src_t
        decl = self.structs.get(owner_t.name)
        if decl is None:
            return False

        field_decl = next((p for p in decl.params if p.name == instr.field.name), None)
        if field_decl is None and instr.field.name.isdigit():
            index = int(instr.field.name)
            if 0 <= index < len(decl.params):
                field_decl = decl.params[index]
        if field_decl is None:
            raise EhirCompileError(f"Unknown field '{instr.field.name}' for struct '{decl.name}'")

        field_t = self._resolve_type(self._specialize_type(field_decl.type, decl.generics, owner_t.generics))
        instr.field.type = field_t
        if as_ptr:
            field_t = Pointer(field_t)
        return self._set_var(vars_by_name, instr.var_out, field_t)

    def _field_path_type(
        self, vars_by_name: dict[str, Type | None], src: Variable, path: list[Variable]
    ) -> Type | None:
        src_t = self._var_type(vars_by_name, src)
        if src_t is None:
            return None
        current = src_t.pointee if isinstance(src_t, (Reference, Pointer)) else src_t
        for seg in path:
            decl = self.structs.get(current.name)
            if is_box_type(current):
                # Safe field access through Box[T] behaves like access through &T.
                pointee = box_pointee(current)
                pointee_decl = self.structs.get(pointee.name)
                if pointee_decl is not None and any(p.name == seg.name for p in pointee_decl.params):
                    current = pointee
                    decl = pointee_decl
            if decl is None:
                return None
            field = next((p for p in decl.params if p.name == seg.name), None)
            if field is None:
                raise EhirCompileError(f"Unknown field '{seg.name}' for struct '{decl.name}'")
            spec = self._specialize_type(field.type, decl.generics, current.generics)
            current = self._resolve_type(spec)
            seg.type = current
        return current

    def _commit_instr_vars(self, instr, vars_by_name: dict[str, Type | None]) -> None:
        self._commit_value(instr, vars_by_name)

    def _commit_value(self, value, vars_by_name: dict[str, Type | None]) -> None:
        if isinstance(value, Variable):
            value.type = vars_by_name.get(value.name) or value.type
            return
        if isinstance(value, list):
            for item in value:
                self._commit_value(item, vars_by_name)
            return
        if not is_dataclass(value):
            return
        for field in fields(value):
            self._commit_value(getattr(value, field.name), vars_by_name)

    def _set_var(self, vars_by_name: dict[str, Type | None], v: Variable, t: Type) -> bool:
        t = self._resolve_type(t)
        curr = vars_by_name.get(v.name) or v.type
        if curr is None:
            vars_by_name[v.name] = t
            return True
        curr = self._resolve_type(curr)
        curr_base = curr.name.rsplit("::", 1)[-1]
        t_base = t.name.rsplit("::", 1)[-1]
        if curr.name == t.name:
            if not curr.generics and t.generics:
                vars_by_name[v.name] = t
                return True
            if curr.generics and not t.generics:
                return False
        if curr_base == t_base and len(curr.generics) == len(t.generics) and curr.generics:
            can_specialize = True
            for lhs_g, rhs_g in zip(curr.generics, t.generics):
                lhs_g = self._resolve_type(lhs_g)
                rhs_g = self._resolve_type(rhs_g)
                if lhs_g == rhs_g:
                    continue
                if not self._contains_unbound_generic(lhs_g):
                    can_specialize = False
                    break
            if can_specialize:
                vars_by_name[v.name] = t
                return True
        if not self._types_compatible(curr, t):
            where = f" in fn '{self._current_fn_name}'" if self._current_fn_name else ""
            raise EhirCompileError(f"Type mismatch: {curr} != {t} for '{v.name}'{where}", code="EHIR1201")
        return False

    def _unify_var(self, vars_by_name: dict[str, Type | None], v: Variable, t: Type) -> bool:
        return self._set_var(vars_by_name, v, t)

    def _unify_expected(self, vars_by_name: dict[str, Type | None], v: Variable, expected: Type) -> bool:
        vt = self._var_type(vars_by_name, v)
        if isinstance(expected, Reference):
            if vt is not None and is_box_type(vt) and self._types_compatible(box_pointee(vt), expected.pointee):
                return False
            if vt is not None and self._types_compatible(vt, expected.pointee):
                return False
            return self._set_var(vars_by_name, v, Type("Box", [expected.pointee]))
        if vt is not None and self._can_pass_as(vt, expected):
            return False
        return self._set_var(vars_by_name, v, expected)

    def _unify_pair(self, vars_by_name: dict[str, Type | None], a: Variable, b: Variable) -> bool:
        ta = self._var_type(vars_by_name, a)
        tb = self._var_type(vars_by_name, b)
        if ta is not None and tb is None:
            return self._set_var(vars_by_name, b, ta)
        if tb is not None and ta is None:
            return self._set_var(vars_by_name, a, tb)
        if ta is not None and tb is not None and not self._types_compatible(ta, tb):
            raise EhirCompileError(f"Type mismatch: {ta} != {tb}", code="EHIR1201")
        return False

    def _var_type(self, vars_by_name: dict[str, Type | None], v: Variable) -> Type | None:
        return vars_by_name.get(v.name) or v.type

    def _types_compatible(self, lhs: Type, rhs: Type) -> bool:
        lhs = self._resolve_type(lhs)
        rhs = self._resolve_type(rhs)
        if lhs == rhs:
            return True
        if is_box_type(lhs):
            expected_concrete = concrete_box_type_name(lhs.generics[0])
            if rhs.name == expected_concrete and not rhs.generics:
                return True
        if is_box_type(rhs):
            expected_concrete = concrete_box_type_name(rhs.generics[0])
            if lhs.name == expected_concrete and not lhs.generics:
                return True
        if mangle_type_name(lhs) == mangle_type_name(rhs):
            return True
        if not lhs.generics and lhs.name and lhs.name[0].isupper():
            return True
        if not rhs.generics and rhs.name and rhs.name[0].isupper():
            return True
        if isinstance(lhs, Reference):
            return lhs.pointee == rhs
        if isinstance(rhs, Reference):
            return rhs.pointee == lhs
        lhs_base = lhs.name.split("::")[-1]
        rhs_base = rhs.name.split("::")[-1]
        if lhs.name == rhs.name or lhs_base == rhs_base:
            if not lhs.generics or not rhs.generics:
                return True
            if len(lhs.generics) != len(rhs.generics):
                return False
            return all(self._types_compatible(a, b) for a, b in zip(lhs.generics, rhs.generics, strict=True))
        return False

    def _can_pass_as(self, actual: Type, expected: Type) -> bool:
        actual = self._resolve_type(actual)
        expected = self._resolve_type(expected)
        if self._types_compatible(actual, expected):
            return True
        if isinstance(actual, Usize_t) and isinstance(expected, Usize_t):
            return self._primitive_bits(actual) <= self._primitive_bits(expected)
        if isinstance(actual, Isize_t) and isinstance(expected, Isize_t):
            return self._primitive_bits(actual) <= self._primitive_bits(expected)
        if isinstance(actual, Float_t) and isinstance(expected, Float_t):
            return actual.size <= expected.size
        return False

    def _primitive_bits(self, typ: Usize_t | Isize_t) -> int:
        return 64 if typ.size is None else typ.size

    def _contains_unbound_generic(self, typ: Type) -> bool:
        typ = self._resolve_type(typ)
        if isinstance(typ, Pointer):
            return self._contains_unbound_generic(typ.pointee)
        if isinstance(typ, Reference):
            return self._contains_unbound_generic(typ.pointee)
        is_symbolic = (
            typ.name not in self.structs
            and typ.name not in self.enums
            and typ.name[:1].isupper()
        )
        if is_symbolic:
            return True
        return any(self._contains_unbound_generic(generic) for generic in typ.generics)

    def _must_get(self, vars_by_name: dict[str, Type | None], name: str, fn_name: str) -> Type:
        t = vars_by_name.get(name)
        if t is None:
            raise EhirCompileError(f"Unable to infer type of variable '{name}' in fn '{fn_name}'", code="EHIR1202")
        return t

    def _resolve_type(self, typ: Type) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._resolve_type(typ.pointee))
        if isinstance(typ, Reference):
            return Reference(self._resolve_type(typ.pointee))
        if isinstance(typ, PrimitiveType):
            return deepcopy(typ)
        if not typ.generics and typ.name in self.type_aliases:
            return self._resolve_type(deepcopy(self.type_aliases[typ.name]))
        if typ.name == "usize":
            return Usize_t()
        if typ.name == "isize":
            return Isize_t()
        if typ.name == "bool":
            return _BOOL
        if typ.name == "char":
            return Char_t()
        if typ.name == "str":
            return Str_t()
        if typ.name.startswith("u") and typ.name[1:].isdigit():
            return Usize_t(int(typ.name[1:]))
        if typ.name.startswith("i") and typ.name[1:].isdigit():
            return Isize_t(int(typ.name[1:]))
        if typ.name.startswith("f") and typ.name[1:].isdigit():
            return Float_t(int(typ.name[1:]))
        return Type(typ.name, [self._resolve_type(g) for g in typ.generics])

    def _replace_type(self, typ: Type, mapping: dict[str, Type], self_type: Type) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type(typ.pointee, mapping, self_type))
        if isinstance(typ, Reference):
            return Reference(self._replace_type(typ.pointee, mapping, self_type))
        if typ.name == "Self" and not typ.generics:
            return deepcopy(self_type)
        if not typ.generics and typ.name in mapping:
            return deepcopy(mapping[typ.name])
        return Type(typ.name, [self._replace_type(g, mapping, self_type) for g in typ.generics])

    def _impl_generic_mapping(self, template: Type, concrete: Type) -> dict[str, Type]:
        mapping: dict[str, Type] = {}
        for t, c in zip(template.generics, concrete.generics, strict=False):
            if not t.generics:
                mapping[t.name] = deepcopy(c)
        return mapping

    def _specialize_types(self, params: list[Type], gdecl: list[Type], gargs: list[Type]) -> list[Type]:
        return [self._specialize_type(p, gdecl, gargs) for p in params]

    def _specialize_type(self, typ: Type, gdecl: list[Type], gargs: list[Type]) -> Type:
        mapping = {a.name: b for a, b in zip(gdecl, gargs, strict=False)}
        return self._replace_type(typ, mapping, Type("Self"))

    def _specialize_params(self, params: list[Parameter], gdecl: list[Type], gargs: list[Type]) -> list[Parameter]:
        out: list[Parameter] = []
        for p in params:
            out.append(Parameter(name=p.name, type=self._specialize_type(p.type, gdecl, gargs)))
        return out

    def _parse_type_text(self, text: str) -> Type | None:
        s = text.strip()
        if not s:
            return None
        if s.startswith("dyn "):
            tail = s[4:].strip()
            if not tail:
                return None
            return Type("dyn", [Type(tail)])
        if s.startswith("&"):
            inner = self._parse_type_text(s[1:])
            return Reference(inner) if inner is not None else None
        if s.endswith("*"):
            inner = self._parse_type_text(s[:-1])
            return Pointer(inner) if inner is not None else None
        b = self._find_top_level_char(s, "[")
        if b == -1:
            return Type(s)
        if not s.endswith("]"):
            return None
        name = s[:b].strip()
        inner = s[b + 1 : -1]
        gens: list[Type] = []
        for part in self._split_top_level(inner, ","):
            t = self._parse_type_text(part)
            if t is None:
                return None
            gens.append(t)
        return Type(name, gens)

    @staticmethod
    def _find_top_level_char(text: str, needle: str) -> int:
        sq = 0
        for i, ch in enumerate(text):
            if ch == "[":
                sq += 1
            elif ch == "]":
                sq -= 1
            elif ch == needle and sq == 0:
                return i
        return -1

    @staticmethod
    def _split_top_level(text: str, sep: str) -> list[str]:
        out: list[str] = []
        sq = 0
        start = 0
        for i, ch in enumerate(text):
            if ch == "[":
                sq += 1
            elif ch == "]":
                sq -= 1
            elif ch == sep and sq == 0:
                out.append(text[start:i].strip())
                start = i + 1
        tail = text[start:].strip()
        if tail:
            out.append(tail)
        return out

    def _rewrite_types(self, value):
        if isinstance(value, Type):
            return self._resolve_type(value)
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = self._rewrite_types(item)
            return value
        if not is_dataclass(value):
            return value
        for field in fields(value):
            setattr(value, field.name, self._rewrite_types(getattr(value, field.name)))
        return value
