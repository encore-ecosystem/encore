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
from ehir.core.enum import Enum
from ehir.core.instructions import (
    BinOp,
    Instruction_add,
    Instruction_br,
    Instruction_call,
    Instruction_capenum,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_cenum,
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_gep,
    Instruction_geq,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_grt,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_ieq,
    Instruction_leq,
    Instruction_les,
    Instruction_load,
    Instruction_match,
    Instruction_mul,
    Instruction_neq,
    Instruction_pcast,
    Instruction_phi,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
    Instruction_sub,
    Instruction_switch,
)
from ehir.core.instructions.base import Assignable
from ehir.core.instructions.arithmetic import Instruction_div
from ehir.core.primitives import Char_t, Float_t, Isize_t, Str_t, Usize_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Type, box_pointee, is_box_type
from ehir.core.variable import Parameter, TypedVariable, Variable

_BOOLEAN_INSTRUCTS = (
    # Comparison
    Instruction_les,
    Instruction_grt,
    Instruction_leq,
    Instruction_geq,
    Instruction_ieq,  # todo:
    Instruction_neq,  # why it is logic?
)

@dataclass
class _ImplMethodRef:
    trait_name: str | None
    method_name: str
    trait_args: list[Type]
    for_type: Type
    impl_generics: list[Type]
    fn_name: str


class Resolver:
    fn: dict[str, Derective_fn | Derective_extern_fn]
    enums: dict[str, Derective_enum]
    structs: dict[str, Derective_struct]
    traits: dict[str, Derective_trait]
    impls: list[Derective_impl]
    impl_method_refs: list[_ImplMethodRef]
    concrete_struct_origins: dict[str, tuple[str, list[Type]]]
    concrete_enum_origins: dict[str, tuple[str, list[Type]]]
    fn_owner_types: dict[str, Type]
    type_aliases: dict[str, Type]

    def run(self, ast: list[Derective]) -> list[Derective]:
        self.fn = {}
        self.enums = {}
        self.structs = {}
        self.traits = {}
        self.impls = []
        self.impl_method_refs = []
        self.concrete_struct_origins = {}
        self.concrete_enum_origins = {}
        self.fn_owner_types = {}
        self.type_aliases = {}
        base_function_names: set[str] = set()

        for derective in ast:
            if isinstance(derective, (Derective_fn, Derective_extern_fn)):
                self.fn[derective.name] = derective
                base_function_names.add(derective.name)
            elif isinstance(derective, Derective_enum):
                self.enums[derective.name] = derective
            elif isinstance(derective, Derective_struct):
                self.structs[derective.name] = derective
            elif isinstance(derective, Derective_trait):
                self.traits[derective.name] = derective
            elif isinstance(derective, Derective_typealias):
                self.type_aliases[derective.name] = deepcopy(derective.target)
            elif isinstance(derective, Derective_impl):
                self.impls.append(derective)

        self._rebuild_concrete_origins()

        for impl in self.impls:
            self._register_impl(impl)

        for struct in list(self.structs.values()):
            self._rewrite_types(struct.params, {})

        for enum in list(self.enums.values()):
            self._rewrite_types(enum.variants, {})

        for fn in list(self.fn.values()):
            if isinstance(fn, Derective_extern_fn):
                continue
            self._resolve(fn)

        base_enum_ast_names = {x.name for x in ast if isinstance(x, Derective_enum)}
        base_struct_ast_names = {x.name for x in ast if isinstance(x, Derective_struct)}
        new_enums = [e for e in self.enums if e not in base_enum_ast_names]
        new_structs = [s for s in self.structs if s not in base_struct_ast_names]
        new_functions = [
            f
            for f in self.fn
            if f not in base_function_names and not getattr(self.fn[f], "generics", [])
        ]
        new_ast = []

        for derective in new_enums:
            new_ast.append(self.enums[derective])
        for derective in new_structs:
            new_ast.append(self.structs[derective])
        for derective in new_functions:
            new_ast.append(self.fn[derective])

        for derective in ast[::-1]:
            if isinstance(derective, Derective_typealias):
                continue
            new_ast.append(derective)

        return new_ast

    def _rebuild_concrete_origins(self):
        known_types: list[Type] = []
        for name, struct in self.structs.items():
            if struct.generics:
                continue
            known_types.append(Type(name))
        for name, enum in self.enums.items():
            if enum.generics:
                continue
            known_types.append(Type(name))

        primitive_names = [
            "u1",
            "u8",
            "u16",
            "u32",
            "u64",
            "usize",
            "i8",
            "i16",
            "i32",
            "i64",
            "isize",
            "f32",
            "f64",
            "char",
            "str",
            "void",
        ]
        known_types.extend(Type(name) for name in primitive_names)

        mangled_to_type = {self._mangle_type_name(typ): typ for typ in known_types}

        for name, struct in list(self.structs.items()):
            if struct.generics:
                continue
            for base_name, base_struct in self.structs.items():
                if not base_struct.generics or len(base_struct.generics) != 1:
                    continue
                prefix = f"{base_name}_"
                if not name.startswith(prefix):
                    continue
                suffix = name[len(prefix) :]
                generic = mangled_to_type.get(suffix)
                if generic is None:
                    continue
                self.concrete_struct_origins[name] = (base_name, [deepcopy(generic)])
                break

    def _register_impl(self, impl: Derective_impl):
        merged_generics = deepcopy(impl.generics)
        impl_generic_names = {generic.name for generic in merged_generics}
        for method in impl.methods:
            method_fn = deepcopy(method)
            for generic in method_fn.generics:
                if generic.name in impl_generic_names:
                    continue
                merged_generics.append(generic)
                impl_generic_names.add(generic.name)
            method_fn.generics = deepcopy(merged_generics)

            if impl.trait_name is None:
                method_fn.name = f"{impl.for_type}::{method_fn.name}"
            else:
                for_type_suffix = self._mangle_type_name(impl.for_type)
                if impl.trait_args:
                    trait_args_suffix = "_".join(self._mangle_type_name(arg) for arg in impl.trait_args)
                else:
                    trait_args_suffix = "noargs"
                base_name = f"impl_{impl.trait_name}_{for_type_suffix}_{trait_args_suffix}_{method_fn.name}"
                unique_name = base_name
                suffix = 0
                while unique_name in self.fn:
                    suffix += 1
                    unique_name = f"{base_name}_{suffix}"
                method_fn.name = unique_name

            self.fn[method_fn.name] = method_fn
            self.fn_owner_types[method_fn.name] = deepcopy(impl.for_type)
            if impl.trait_name is not None:
                self.impl_method_refs.append(
                    _ImplMethodRef(
                        trait_name=impl.trait_name,
                        method_name=method.name,
                        trait_args=deepcopy(impl.trait_args),
                        for_type=impl.for_type,
                        impl_generics=deepcopy(merged_generics),
                        fn_name=method_fn.name,
                    )
                )

    @staticmethod
    def _mangle_type_name(typ: Type) -> str:
        value = str(typ)
        mangled = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
        return mangled or "type"

    def _resolve(self, fn: Derective_fn):
        variables: dict[str, Variable] = {}
        temp_rename_counters: dict[str, int] = {}

        def is_ephemeral_name(name: str) -> bool:
            return (
                name.startswith("ret_arg_")
                or name.startswith("expr_arg_")
                or name.startswith("expr_")
                or name.startswith("match_scrutinee_")
                or name.startswith("if_cond_")
                or name.startswith("if_cond_lhs_")
                or name.startswith("if_cond_rhs_")
            )

        def add_variable(var: Variable) -> Variable:
            if var.type is not None:
                var.type = self._resolve_type(var.type)

            if var.name not in variables:
                variables[var.name] = var
                return var

            old_var = variables[var.name]
            if old_var.type and var.type:
                if old_var.type != var.type:
                    if self._types_compatible(old_var.type, var.type):
                        if self._type_specificity(var.type) > self._type_specificity(old_var.type):
                            old_var.type = var.type
                        return old_var
                    if is_ephemeral_name(var.name):
                        counter = temp_rename_counters.get(var.name, 0)
                        new_name = var.name
                        while new_name in variables:
                            counter += 1
                            new_name = f"{var.name}__{counter}"
                        temp_rename_counters[var.name] = counter
                        var.name = new_name
                        variables[new_name] = var
                        return var
                    raise TypeError(f"Type mismatch for variable '{var.name}': {old_var.type} != {var.type}")
                return old_var
            elif old_var.type:
                return old_var
            else:
                old_var.type = var.type
                return old_var

        def resolve_call(instr: Instruction_call):
            instr.args = [add_variable(arg) for arg in instr.args]
            if instr.fn_name == "op" and any(
                arg.type is None or not self._is_concrete_type(arg.type) for arg in instr.args
            ):
                instr.var_out = add_variable(instr.var_out)
                return
            resolved_inherent = self._resolve_inherent_method_call(instr.fn_name, instr.args)
            if resolved_inherent is not None:
                fn_name, inferred_generics = resolved_inherent
                instr.fn_name = fn_name
                if not instr.generics:
                    instr.generics = inferred_generics
            resolved_impl = self._resolve_impl_method_call(instr.fn_name, instr.args)
            if resolved_impl is not None:
                fn_name, inferred_generics = resolved_impl
                instr.fn_name = fn_name
                if not instr.generics:
                    instr.generics = inferred_generics

            if instr.fn_name == "op" and any(
                arg.type is None or not self._is_concrete_type(arg.type) for arg in instr.args
            ):
                instr.var_out = add_variable(instr.var_out)
                return

            if instr.fn_name not in self.fn:
                if "::" not in instr.fn_name:
                    same_basename = [name for name in self.fn if name.rsplit("::", 1)[-1] == instr.fn_name]
                    if len(same_basename) == 1:
                        instr.fn_name = same_basename[0]
                    elif len(same_basename) > 1:
                        by_arity = [
                            name for name in same_basename if len(getattr(self.fn[name], "params", [])) == len(instr.args)
                        ]
                        if len(by_arity) == 1:
                            instr.fn_name = by_arity[0]

                    if instr.fn_name not in self.fn and instr.args and instr.args[0].type is not None:
                        inferred_call = self._resolve_inherent_method_call(
                            f"{instr.args[0].type}::{instr.fn_name}", instr.args
                        )
                        if inferred_call is not None:
                            inferred_name, inferred_generics = inferred_call
                            instr.fn_name = inferred_name
                            if not instr.generics:
                                instr.generics = inferred_generics

                if instr.fn_name not in self.fn:
                    debug_trait_name = instr.fn_name.rsplit("::", 1)[0] if "::" in instr.fn_name else ""
                    if (
                        len(instr.args) == 1
                        and instr.args[0].type is not None
                        and instr.fn_name.endswith("::fmt")
                        and debug_trait_name.rsplit("::", 1)[-1] == "Debug"
                    ):
                        runtime_fmt_map = {
                            "u1": "__ehir_rt_fmt_bool",
                            "u8": "__ehir_rt_fmt_u8",
                            "u16": "__ehir_rt_fmt_u16",
                            "u32": "__ehir_rt_fmt_u32",
                            "u64": "__ehir_rt_fmt_u64",
                            "usize": "__ehir_rt_fmt_usize",
                            "i8": "__ehir_rt_fmt_i8",
                            "i16": "__ehir_rt_fmt_i16",
                            "i32": "__ehir_rt_fmt_i32",
                            "i64": "__ehir_rt_fmt_i64",
                            "isize": "__ehir_rt_fmt_isize",
                            "f32": "__ehir_rt_fmt_f32",
                            "f64": "__ehir_rt_fmt_f64",
                        }
                        fmt_rt_fn = runtime_fmt_map.get(instr.args[0].type.name)
                        if fmt_rt_fn is not None and fmt_rt_fn in self.fn:
                            instr.fn_name = fmt_rt_fn
                            instr.is_unsafe = True

                if instr.fn_name not in self.fn:
                    if "::" in instr.fn_name:
                        owner_text, method_name = instr.fn_name.rsplit("::", 1)
                        owner_type = self._parse_type_text(owner_text)
                        if owner_type is not None:
                            resolved_owner = self._resolve_type(owner_type)
                            resolved_name = f"{resolved_owner}::{method_name}"
                            if resolved_name in self.fn:
                                instr.fn_name = resolved_name
                            elif instr.args and instr.args[0].type is not None:
                                inferred_call = self._resolve_inherent_method_call(
                                    f"{instr.args[0].type}::{method_name}", instr.args
                                )
                                if inferred_call is not None:
                                    inferred_name, inferred_generics = inferred_call
                                    instr.fn_name = inferred_name
                                    if not instr.generics:
                                        instr.generics = inferred_generics
                        if instr.fn_name not in self.fn:
                            same_basename = [name for name in self.fn if name.rsplit("::", 1)[-1] == method_name]
                            if len(same_basename) == 1:
                                instr.fn_name = same_basename[0]
                        if instr.fn_name not in self.fn:
                            path_parts = instr.fn_name.split("::")
                            for idx in range(1, len(path_parts) - 1):
                                suffix = "::".join(path_parts[idx:])
                                suffix_matches = [name for name in self.fn if name.endswith(suffix)]
                                if len(suffix_matches) == 1:
                                    instr.fn_name = suffix_matches[0]
                                    break

                if instr.fn_name not in self.fn:
                    if "::" in instr.fn_name:
                        # Generic trait calls (e.g. Debug::fmt(T) inside generic fn)
                        # are resolved after monomorphization when arg types become concrete.
                        has_unresolved_generic_arg = any(
                            arg.type is None or not self._is_concrete_type(arg.type) for arg in instr.args
                        )
                        if has_unresolved_generic_arg:
                            instr.var_out = add_variable(instr.var_out)
                            return

                        trait_name, method_name = instr.fn_name.rsplit("::", 1)
                        candidates = [
                            f"{ref.trait_name}[{', '.join(str(arg) for arg in ref.trait_args)}] for {ref.for_type}::{ref.method_name}"
                            for ref in self.impl_method_refs
                            if (
                                ref.method_name == method_name
                                and (
                                    ref.trait_name == trait_name
                                    or ref.trait_name.rsplit("::", 1)[-1] == trait_name.rsplit("::", 1)[-1]
                                )
                            )
                        ]
                        arg_types = [str(arg.type) if arg.type is not None else "?" for arg in instr.args]
                        raise TypeError(
                            f"Unknown function '{instr.fn_name}' for args {arg_types} in '{fn.name}'. "
                            f"Impl candidates: {candidates}"
                        )
                    arg_types = [str(arg.type) if arg.type is not None else "?" for arg in instr.args]
                    basename = instr.fn_name.rsplit("::", 1)[-1]
                    candidates = [name for name in self.fn if name.rsplit("::", 1)[-1] == basename]
                    raise TypeError(
                        f"Unknown function '{instr.fn_name}' in '{fn.name}' for args {arg_types}. "
                        f"Candidates: {candidates}"
                    )
            target_fn = self.fn[instr.fn_name]
            if isinstance(target_fn, Derective_extern_fn):
                if not instr.is_unsafe and "safe" not in getattr(target_fn, "attrs", ()):
                    raise TypeError(f"Extern function '{instr.fn_name}' requires unsafe call")
                if len(instr.args) != len(target_fn.params):
                    raise TypeError(
                        f"Argument count mismatch for extern function '{instr.fn_name}': "
                        f"{len(instr.args)} != {len(target_fn.params)}"
                    )
                for arg, param in zip(instr.args, target_fn.params, strict=True):
                    assert param.type is not None
                    expected_arg_type = self._resolve_type(deepcopy(param.type))
                    if arg.type is not None and arg.type != expected_arg_type:
                        raise TypeError(
                            f"Type mismatch for argument '{arg.name}' of extern function "
                            f"'{instr.fn_name}': {arg.type} != {expected_arg_type}"
                        )
                    arg.type = expected_arg_type
                expected_type = self._resolve_type(deepcopy(target_fn.ret_type))
                if instr.var_out.type and instr.var_out.type != expected_type:
                    raise TypeError(
                        f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                    )
                instr.var_out.type = expected_type
                instr.var_out = add_variable(instr.var_out)
                return
            if target_fn.generics:
                instr.generics = [self._resolve_type(generic) for generic in instr.generics]
                if len(instr.generics) != len(target_fn.generics):
                    raise TypeError(
                        f"Generic count mismatch for function '{instr.fn_name}': "
                        f"{len(instr.generics)} != {len(target_fn.generics)}"
                    )
                generic_mapping = {formal.name: actual for formal, actual in zip(target_fn.generics, instr.generics)}
                if not all(self._is_concrete_type(generic) for generic in instr.generics):
                    if len(instr.args) != len(target_fn.params):
                        raise TypeError(
                            f"Argument count mismatch for function '{instr.fn_name}': "
                            f"{len(instr.args)} != {len(target_fn.params)}"
                        )
                    for arg, param in zip(instr.args, target_fn.params, strict=True):
                        expected_arg_type = self._replace_type(deepcopy(param.type), generic_mapping)
                        expected_arg_type = self._resolve_type(expected_arg_type)
                        if arg.type is not None and arg.type != expected_arg_type:
                            raise TypeError(
                                f"Type mismatch for argument '{arg.name}' of function "
                                f"'{instr.fn_name}': {arg.type} != {expected_arg_type}"
                            )
                        arg.type = expected_arg_type

                    expected_type = self._replace_type(deepcopy(target_fn.ret_type), generic_mapping)
                    expected_type = self._resolve_type(expected_type)
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}' in fn '{fn.name}': "
                            f"{instr.var_out.type} != {expected_type}. Instr: {instr}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                    return
                concrete_name = target_fn.get_conrete_name(instr.generics)
                if concrete_name not in self.fn:
                    target_fn = self._concrete_fn(target_fn, instr.generics)
                instr.generics.clear()
                instr.fn_name = concrete_name
                target_fn = self.fn[concrete_name]
            inferred_mapping = self._infer_call_type_mapping(target_fn, instr.args, instr.var_out.type)
            expected_template = deepcopy(target_fn.ret_type)
            if inferred_mapping:
                expected_template = self._replace_type(expected_template, inferred_mapping)
            expected_type = self._resolve_type(expected_template)
            if instr.var_out.type and instr.var_out.type != expected_type:
                if instr.fn_name == "op":
                    expected_type = instr.var_out.type
                else:
                    arg_types = [str(arg.type) if arg.type is not None else "?" for arg in instr.args]
                    raise TypeError(
                        f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type} "
                        f"(in={fn.name}, call={instr.fn_name}, decl={target_fn.name}, ret_template={target_fn.ret_type}, "
                        f"ret_after_replace={expected_template}, mapping={inferred_mapping}, args={arg_types})"
                    )
            instr.var_out.type = expected_type
            instr.var_out = add_variable(instr.var_out)

        block_map = {block.name: block for block in fn.body}

        def inject_match_payload_binding(instr: Instruction_match):
            assert instr.cond_var.type is not None
            cond_type = instr.cond_var.type
            wrapper_ptr_type: Pointer | None = None
            enum_variant_payloads: dict[str, Type | None] = {}
            wrapped_struct = self.structs.get(cond_type.name)
            wrapped_params = self._get_struct_params(cond_type.name, cond_type.generics) if wrapped_struct else []
            is_wrapper_struct = (
                bool(wrapped_params) and wrapped_params[0].name == "ptr" and isinstance(wrapped_params[0].type, Pointer)
            )

            if is_wrapper_struct:
                wrapper_ptr_type = wrapped_params[0].type
                inner_type = wrapper_ptr_type.pointee
                if inner_type.name not in self.enums:
                    return
                enum_variant_payloads = {
                    variant.name: variant.type
                    for variant in self._get_enum_variants(inner_type.name, inner_type.generics)
                }
            elif cond_type.name in self.enums:
                enum_variant_payloads = {
                    variant.name: variant.type
                    for variant in self._get_enum_variants(cond_type.name, cond_type.generics)
                }
            else:
                return
            injected_labels: set[str] = set()
            for case in instr.cases:
                if case.payload_var is None:
                    continue
                if case.label in injected_labels:
                    raise TypeError(f"Payload-binding match target block '{case.label}' is reused")
                injected_labels.add(case.label)

                payload_type = enum_variant_payloads.get(case.variant)
                if case.variant not in enum_variant_payloads:
                    continue
                if payload_type is None:
                    raise TypeError(f"Enum variant '{case.variant}' does not carry payload")

                payload_var = case.payload_var
                if payload_var.name == "_":
                    # Wildcard payload binding must not materialize a real SSA variable.
                    case.payload_var = None
                    continue
                payload_var.type = payload_type
                payload_var = add_variable(payload_var)
                case.payload_var = payload_var

                target_block = block_map.get(case.label)
                if target_block is None:
                    raise TypeError(f"Unknown match target block '{case.label}'")

                payload_src = instr.cond_var
                if wrapper_ptr_type is not None:
                    wrapped_ptr = TypedVariable(
                        name=f"..{payload_var.name}_{case.label}_match_ptr", type=wrapper_ptr_type
                    )
                    wrapped_value = TypedVariable(
                        name=f".{payload_var.name}_{case.label}_match_value", type=wrapper_ptr_type.pointee
                    )
                    target_block.body.insert(
                        0,
                        Instruction_load(var_out=wrapped_value, var=wrapped_ptr),
                    )
                    target_block.body.insert(
                        0,
                        Instruction_getfield(
                            var_out=wrapped_ptr,
                            src=instr.cond_var,
                            field=TypedVariable("0", wrapper_ptr_type),
                        ),
                    )
                    payload_src = wrapped_value

                payload_ptr = TypedVariable(
                    name=f".{payload_var.name}_{case.label}_match_ptr", type=Pointer(payload_type)
                )
                target_block.body.insert(
                    0,
                    Instruction_load(var_out=payload_var, var=payload_ptr),
                )
                target_block.body.insert(
                    0,
                    Instruction_getfield(
                        var_out=payload_ptr,
                        src=payload_src,
                        field=TypedVariable(case.variant, Pointer(payload_type)),
                    ),
                )

        # step 0: Collect all variables
        for param in fn.params:
            if param.type is not None:
                param.type = self._resolve_type(param.type)
            add_variable(param)

        for block in fn.body:
            for instr in block.body:
                if isinstance(instr, Instruction_match):
                    instr.cond_var = add_variable(instr.cond_var)
                    if instr.cond_var.type is not None:
                        instr.cond_var.type = self._resolve_type(instr.cond_var.type)
                        inject_match_payload_binding(instr)

        for block in fn.body:
            for instr_id, instr in enumerate(block.body):
                if isinstance(instr, Assignable) and instr.var_out.type is not None:
                    instr.var_out.type = self._resolve_type(instr.var_out.type)

                if isinstance(instr, (Instruction_cpos, Instruction_scpos)):
                    if isinstance(instr, Instruction_cpos):
                        pointer_t = Pointer
                    else:
                        pointer_t = lambda inner: Type("Box", [inner])
                    expected_type = pointer_t(instr.primitive.type)
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}' in fn '{fn.name}': "
                            f"{instr.var_out.type} != {expected_type}. Instr: {instr}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_cenum):
                    instr.enum = self._resolve_enum(instr.enum)
                    expected_type = Pointer(instr.enum.as_type())

                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}' in fn '{fn.name}': "
                            f"{instr.var_out.type} != {expected_type}. Instr: {instr}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                    self._resolve_enum_payload(instr.enum)
                    if instr.enum.payload is not None:
                        if instr.enum.payload.value is None:
                            for arg in instr.enum.payload.args:
                                add_variable(arg)
                        else:
                            instr.enum.payload.value = add_variable(instr.enum.payload.value)

                elif isinstance(instr, (Instruction_cstruct, Instruction_scstruct)):
                    instr.struct = self._resolve_struct(instr.struct)
                    if isinstance(instr, Instruction_cstruct):
                        pointer_t = Pointer
                    else:
                        pointer_t = lambda inner: Type("Box", [inner])
                    expected_type = pointer_t(instr.struct.as_type())
                    if instr.var_out.type and not self._types_compatible(instr.var_out.type, expected_type):
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                    struct_params = self._get_struct_params(instr.struct.name, instr.struct.generics)
                    for i, arg in enumerate(instr.struct.args):
                        expected_type = struct_params[i].type

                        if arg.type is not None:
                            arg.type = self._resolve_type(arg.type)
                        if arg.type is not None and arg.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for argument {i} of struct '{instr.struct.name}': {arg.type} != {expected_type}"
                            )
                        arg.type = expected_type
                        add_variable(arg)

                elif isinstance(instr, Instruction_capprim):
                    expected_type = instr.primitive.type

                    if instr.var_out.type and not self._types_compatible(instr.var_out.type, expected_type):
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_capenum):
                    instr.enum = self._resolve_enum(instr.enum)
                    expected_type = instr.enum.as_type()

                    if instr.var_out.type and not self._types_compatible(instr.var_out.type, expected_type):
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                    self._resolve_enum_payload(instr.enum)
                    if instr.enum.payload is not None:
                        if instr.enum.payload.value is None:
                            for arg in instr.enum.payload.args:
                                add_variable(arg)
                        else:
                            instr.enum.payload.value = add_variable(instr.enum.payload.value)

                elif isinstance(instr, Instruction_capstruct):
                    instr.struct = self._resolve_struct(instr.struct)
                    expected_type = instr.struct.as_type()

                    if instr.var_out.type and not self._types_compatible(instr.var_out.type, expected_type):
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                    struct_params = self._get_struct_params(instr.struct.name, instr.struct.generics)
                    for i, arg in enumerate(instr.struct.args):
                        expected_type = struct_params[i].type

                        if arg.type is not None:
                            arg.type = self._resolve_type(arg.type)
                        if arg.type is not None and arg.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for argument {i} of struct '{instr.struct.name}': {arg.type} != {expected_type}"
                            )
                        arg.type = expected_type
                        add_variable(arg)

                elif isinstance(
                    instr,
                    (
                        Instruction_getfield,
                        Instruction_getfieldptr,
                        Instruction_sgetfield,
                        Instruction_sgetfieldptr,
                        Instruction_setfield,
                    ),
                ):
                    src = instr.src if hasattr(instr, "src") else instr.var
                    src = add_variable(src)
                    assert src.type
                    src.type = self._resolve_type(src.type)
                    if hasattr(instr, "src"):
                        instr.src = src
                    else:
                        instr.var = src

                    if isinstance(src.type, PrimitiveType):
                        raise TypeError(f"Cannot access field of primitive type '{src.type}'")

                    field_segments = [instr.field, *getattr(instr, "field_path", [])]
                    current_type = src.type
                    resolved_segments: list[Variable] = []
                    for field_segment in field_segments:
                        composite_type = current_type.pointee if isinstance(current_type, Pointer) else current_type
                        if isinstance(composite_type, PrimitiveType):
                            raise TypeError(f"Cannot access field of primitive type '{composite_type}'")

                        resolved_params = self._get_composite_params(composite_type.name, composite_type.generics)
                        for i, param in enumerate(resolved_params):
                            if param.name == field_segment.name or str(i) == field_segment.name:
                                if field_segment.type and field_segment.type != param.type:
                                    raise TypeError(
                                        f"Type mismatch for field '{field_segment.name}' in struct '{composite_type.name}': {field_segment.type} != {param.type}"
                                    )
                                field_segment.type = param.type
                                field_segment.name = str(i)
                                resolved_segments.append(field_segment)
                                current_type = param.type
                                break
                        else:
                            raise TypeError(f"Unknown field '{field_segment.name}' in struct '{composite_type.name}'")

                    instr.field = resolved_segments[0]
                    if hasattr(instr, "field_path"):
                        instr.field_path = resolved_segments[1:]

                    if isinstance(instr, Instruction_setfield):
                        instr.value = add_variable(instr.value)
                        expected_type = current_type
                        if instr.value.type and not self._types_compatible(instr.value.type, expected_type):
                            raise TypeError(
                                f"Type mismatch for variable '{instr.value.name}': {instr.value.type} != {expected_type}"
                            )
                        instr.value.type = expected_type
                        instr.value = add_variable(instr.value)
                    else:
                        expected_type = (
                            current_type
                            if isinstance(instr, (Instruction_getfield, Instruction_sgetfield))
                            else Pointer(current_type)
                        )
                        if instr.var_out.type and not self._types_compatible(instr.var_out.type, expected_type):
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                            )
                        instr.var_out.type = expected_type
                        instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_ret):
                    fn.ret_type = self._resolve_type(fn.ret_type)
                    expected_type = fn.ret_type
                    instr.var = add_variable(instr.var)
                    if instr.var.type and not self._types_compatible(instr.var.type, expected_type):
                        raise TypeError(f"Type mismatch for return value: {instr.var.type} != {expected_type}")
                    instr.var.type = expected_type

                elif isinstance(instr, BinOp):
                    instr.lhs = add_variable(instr.lhs)
                    instr.rhs = add_variable(instr.rhs)

                    lhs_t = instr.lhs.type
                    rhs_t = instr.rhs.type
                    expected_t = None
                    if lhs_t and rhs_t:
                        if lhs_t != rhs_t:
                            raise TypeError(
                                f"Type mismatch for binop operands in '{fn.name}': {lhs_t} != {rhs_t}. Instr: {instr}"
                            )
                        expected_t = Usize_t(size=1) if isinstance(instr, _BOOLEAN_INSTRUCTS) else lhs_t
                        if instr.var_out.type and instr.var_out.type != expected_t:
                            raise TypeError(f"Type mismatch for binop: {instr.var_out.type} != {expected_t}")
                        instr.var_out.type = expected_t

                    elif lhs_t is not None or rhs_t is not None:
                        expected_t = lhs_t if lhs_t is not None else rhs_t
                        assert expected_t is not None

                        instr.lhs = add_variable(TypedVariable(instr.lhs.name, expected_t))
                        instr.rhs = add_variable(TypedVariable(instr.rhs.name, expected_t))

                        if isinstance(instr, _BOOLEAN_INSTRUCTS):
                            expected_t = Usize_t(size=1)

                        if instr.var_out.type and instr.var_out.type != expected_t:
                            raise TypeError(f"Type mismatch for binop: {instr.var_out.type} != {expected_t}")
                        instr.var_out.type = expected_t
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_call):
                    resolve_call(instr)

                elif isinstance(instr, Instruction_phi):
                    if _t := instr.var_out.type:
                        expected_type = _t
                    else:
                        for arg in instr.args:
                            if _t := arg.var.type:
                                expected_type = _t
                                break
                        else:
                            raise TypeError(f"Unable to determine expected type for phi instruction: {instr}")

                    if instr.var_out.type and instr.var_out.type != expected_type:
                        if self._types_compatible(instr.var_out.type, expected_type):
                            instr.var_out.type = expected_type
                        else:
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                            )
                    else:
                        instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                    for arg in instr.args:
                        if arg.var.type and arg.var.type != expected_type:
                            if not self._types_compatible(arg.var.type, expected_type):
                                raise TypeError(
                                    f"Type mismatch for arg '{arg.var.name}': {arg.var.type} != {expected_type}"
                                )
                        arg.var.type = expected_type
                        arg.var = add_variable(arg.var)

                elif isinstance(instr, Instruction_br):
                    pass
                elif isinstance(instr, Instruction_cbr):
                    instr.cond_var = add_variable(instr.cond_var)
                elif isinstance(instr, Instruction_switch):
                    instr.cond_var = add_variable(instr.cond_var)
                elif isinstance(instr, Instruction_match):
                    instr.cond_var = add_variable(instr.cond_var)
                    assert instr.cond_var.type is not None
                    instr.cond_var.type = self._resolve_type(instr.cond_var.type)
                    if instr.cond_var.type.name not in self.enums:
                        raise TypeError(f"Match condition must be an enum, got '{instr.cond_var.type}'")

                    known_variants = {
                        variant.name
                        for variant in self._get_enum_variants(instr.cond_var.type.name, instr.cond_var.type.generics)
                    }
                    seen_variants: set[str] = set()
                    for case in instr.cases:
                        if case.variant not in known_variants:
                            raise TypeError(
                                f"Unknown match variant '{case.variant}' for enum '{instr.cond_var.type.name}'"
                            )
                        if case.variant in seen_variants:
                            raise TypeError(f"Duplicate match variant '{case.variant}'")
                        seen_variants.add(case.variant)
                        expected_payload_type = next(
                            variant.type
                            for variant in self._get_enum_variants(instr.cond_var.type.name, instr.cond_var.type.generics)
                            if variant.name == case.variant
                        )
                        if case.payload_var is not None:
                            if case.payload_var.type is None:
                                case.payload_var.type = expected_payload_type
                                case.payload_var = add_variable(case.payload_var)
                            elif case.payload_var.type != expected_payload_type:
                                raise TypeError(f"Type mismatch for match payload variable '{case.payload_var.name}'")
                elif isinstance(instr, Instruction_salloc):
                    instr.type = self._resolve_type(instr.type)
                    expected_type = Pointer(instr.type)
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                elif isinstance(instr, Instruction_halloc):
                    instr.type = self._resolve_type(instr.type)
                    expected_type = Pointer(instr.type)
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                elif isinstance(instr, Instruction_hrealloc):
                    instr.var = add_variable(instr.var)
                    instr.count = add_variable(instr.count)
                    if instr.var.type is not None:
                        instr.var.type = self._resolve_type(instr.var.type)
                        if not isinstance(instr.var.type, Pointer):
                            raise TypeError(f"HREALLOC expects pointer source, got {instr.var.type}")
                    if instr.count.type is not None:
                        instr.count.type = self._resolve_type(instr.count.type)
                        if not (
                            isinstance(instr.count.type, PrimitiveType)
                            and (
                                instr.count.type.name in {"usize", "isize"}
                                or instr.count.type.name.startswith("u")
                                or instr.count.type.name.startswith("i")
                            )
                        ):
                            raise TypeError(f"HREALLOC count must be integer, got {instr.count.type}")
                    expected_type = instr.var.type if instr.var.type is not None else None
                    if instr.var_out.type is not None:
                        instr.var_out.type = self._resolve_type(instr.var_out.type)
                    elif expected_type is not None:
                        instr.var_out.type = expected_type
                    if instr.var_out.type is None:
                        raise TypeError(f"Unable to infer type for HREALLOC result '{instr.var_out.name}'")
                    if not isinstance(instr.var_out.type, Pointer):
                        raise TypeError(f"HREALLOC result must be pointer, got {instr.var_out.type}")
                    if expected_type is not None and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out = add_variable(instr.var_out)
                elif isinstance(instr, Instruction_put):
                    expected_type = Pointer(instr.primitive.type)
                    if instr.var.type and instr.var.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var.name}': {instr.var.type} != {expected_type}"
                        )
                    instr.var.type = expected_type
                    instr.var = add_variable(instr.var)
                elif isinstance(instr, Instruction_load):
                    instr.var = add_variable(instr.var)
                    if instr.var.type is not None:
                        assert isinstance(instr.var.type, Pointer)
                        expected_type = instr.var.type.pointee
                        if instr.var_out.type is not None and instr.var_out.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                            )
                        instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)
                elif isinstance(instr, Instruction_gep):
                    instr.var = add_variable(instr.var)
                    instr.offset = add_variable(instr.offset)
                    if instr.var.type is not None:
                        instr.var.type = self._resolve_type(instr.var.type)
                        if not isinstance(instr.var.type, Pointer):
                            raise TypeError(f"GEP expects pointer source, got {instr.var.type}")
                    if instr.offset.type is not None:
                        instr.offset.type = self._resolve_type(instr.offset.type)
                        if not (
                            isinstance(instr.offset.type, PrimitiveType)
                            and (
                                instr.offset.type.name in {"usize", "isize"}
                                or instr.offset.type.name.startswith("u")
                                or instr.offset.type.name.startswith("i")
                            )
                        ):
                            raise TypeError(f"GEP offset must be integer, got {instr.offset.type}")
                    expected_type = instr.var.type if instr.var.type is not None else None
                    if instr.var_out.type is not None:
                        instr.var_out.type = self._resolve_type(instr.var_out.type)
                    elif expected_type is not None:
                        instr.var_out.type = expected_type
                    if instr.var_out.type is None:
                        raise TypeError(f"Unable to infer type for GEP result '{instr.var_out.name}'")
                    if not isinstance(instr.var_out.type, Pointer):
                        raise TypeError(f"GEP result must be pointer, got {instr.var_out.type}")
                    instr.var_out = add_variable(instr.var_out)
                elif isinstance(instr, Instruction_store):
                    instr.var_src = add_variable(instr.var_src)
                    instr.var_dst = add_variable(instr.var_dst)
                    if instr.var_dst.type is not None:
                        assert isinstance(instr.var_dst.type, Pointer)
                        expected_type = instr.var_dst.type.pointee
                        if instr.var_src.type is not None and instr.var_src.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var_src.name}': {instr.var_src.type} != {expected_type}"
                            )
                        instr.var_src.type = expected_type
                        instr.var_src = add_variable(instr.var_src)
                elif isinstance(instr, Instruction_hfree):
                    instr.var = add_variable(instr.var)
                elif isinstance(instr, Instruction_pcast):
                    instr.var = add_variable(instr.var)
                    instr.type = self._resolve_type(instr.type)

                    expected_type = instr.type
                    if instr.var_out.type is not None:
                        if instr.var_out.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                            )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_getptr):
                    instr.var = add_variable(instr.var)
                    if instr.var.type is not None:
                        expected_type = Pointer(instr.var.type)

                        if instr.var_out.type and instr.var.type != expected_type:
                            raise TypeError(
                                f"Type mismatch for variable '{instr.var.name}': {instr.var.type} != {expected_type}"
                            )
                        instr.var_out.type = expected_type

                    instr.var_out = add_variable(instr.var_out)
                else:
                    raise ValueError(f"Unexpected instruction: {instr}")

        # step 1: Check variables
        for name, val in variables.items():
            if val.type is None:
                raise TypeError(f"Type not specified for variable '{name}' in fn '{fn.name}'")

    def _concrete_fn(self, fn: Derective_fn, types: list[Type]) -> "Derective_fn":
        assert len(fn.generics) == len(types)
        generic_mapping = {a.name: b for a, b in zip(fn.generics, types)}

        base = deepcopy(fn)
        self._rewrite_types(base, generic_mapping)
        base.generics.clear()
        base.name = base.get_conrete_name(types)
        self.fn[base.name] = base
        if fn.name in self.fn_owner_types:
            self.fn_owner_types[base.name] = self._replace_type(deepcopy(self.fn_owner_types[fn.name]), generic_mapping)
        self._resolve(base)

        return base

    def _concrete_struct(self, struct: Derective_struct, types: list[Type]) -> Derective_struct:
        assert len(struct.generics) == len(types)
        generic_mapping = {a.name: b for a, b in zip(struct.generics, types)}
        concrete_name = struct.get_conrete_name(types)
        if concrete_name in self.structs:
            return self.structs[concrete_name]

        base = deepcopy(struct)
        base.generics.clear()
        base.name = concrete_name
        self.structs[base.name] = base
        self.concrete_struct_origins[base.name] = (struct.name, deepcopy(types))
        self._rewrite_types(base, generic_mapping)
        return base

    def _concrete_enum(self, enum: Derective_enum, types: list[Type]) -> Derective_enum:
        assert len(enum.generics) == len(types)
        generic_mapping = {a.name: b for a, b in zip(enum.generics, types)}
        concrete_name = enum.get_conrete_name(types)
        if concrete_name in self.enums:
            return self.enums[concrete_name]

        base = deepcopy(enum)
        base.generics.clear()
        base.name = concrete_name
        self.enums[base.name] = base
        self.concrete_enum_origins[base.name] = (enum.name, deepcopy(types))
        self._rewrite_types(base, generic_mapping)
        return base

    def _resolve_struct(self, struct):
        self._rewrite_types(struct, {})
        target_struct = self.structs.get(struct.name)
        if target_struct is None or not target_struct.generics:
            return struct
        if len(target_struct.generics) != len(struct.generics):
            return struct
        if not all(self._is_concrete_type(generic) for generic in struct.generics):
            return struct

        concrete_name = target_struct.get_conrete_name(struct.generics)
        if concrete_name not in self.structs:
            self._concrete_struct(target_struct, struct.generics)

        struct.name = concrete_name
        struct.generics.clear()
        return struct

    def _resolve_enum(self, enum: Enum) -> Enum:
        self._rewrite_types(enum, {})
        target_enum = self.enums.get(enum.name)
        if target_enum is None or not target_enum.generics:
            return enum
        if len(target_enum.generics) != len(enum.generics):
            return enum
        if not all(self._is_concrete_type(generic) for generic in enum.generics):
            return enum

        concrete_name = target_enum.get_conrete_name(enum.generics)
        if concrete_name not in self.enums:
            self._concrete_enum(target_enum, enum.generics)

        enum.name = concrete_name
        enum.generics.clear()
        return enum

    def _get_struct_params(self, struct_name: str, generics: list[Type]):
        struct = self.structs[struct_name]
        if not struct.generics:
            return struct.params

        if len(struct.generics) != len(generics):
            return struct.params

        params = deepcopy(struct.params)
        self._rewrite_types(params, {a.name: b for a, b in zip(struct.generics, generics)})
        return params

    def _get_enum_variants(self, enum_name: str, generics: list[Type]):
        enum = self.enums[enum_name]
        if not enum.generics:
            return enum.variants

        variants = deepcopy(enum.variants)
        self._rewrite_types(variants, {a.name: b for a, b in zip(enum.generics, generics)})
        return variants

    def _get_composite_params(self, type_name: str, generics: list[Type]) -> list[Parameter]:
        if type_name in self.structs:
            return self._get_struct_params(type_name, generics)
        if type_name in self.enums:
            params: list[Parameter] = [Parameter(name="tag", type=Usize_t(8))]
            for variant in self._get_enum_variants(type_name, generics):
                if variant.type is None:
                    continue
                params.append(Parameter(name=variant.name, type=Pointer(variant.type)))
            return params
        raise TypeError(f"Unknown composite type '{type_name}'")

    def _resolve_enum_payload(self, enum: Enum):
        variants = self._get_enum_variants(enum.name, enum.generics)
        for variant_index, variant in enumerate(variants):
            if variant.name != enum.variant:
                continue

            if enum.payload is None:
                if variant.type is not None:
                    raise TypeError(f"Enum variant '{enum.variant}' expects payload")
                return

            if variant.type is None:
                raise TypeError(f"Enum variant '{enum.variant}' must not have payload")

            if enum.payload.value is None:
                enum.payload = self._resolve_struct(enum.payload)
            else:
                if enum.payload.value.type is not None:
                    enum.payload.value.type = self._resolve_type(enum.payload.value.type)
                if enum.payload.value.type is None:
                    enum.payload.value.type = variant.type
                enum.payload.type = enum.payload.value.type

            payload_type = enum.payload.as_type()

            if payload_type != variant.type:
                raise TypeError(f"Type mismatch for enum variant '{enum.variant}': {payload_type} != {variant.type}")

            if enum.payload.value is None:
                struct_params = self._get_struct_params(enum.payload.name, enum.payload.generics)
                for i, arg in enumerate(enum.payload.args):
                    expected_type = struct_params[i].type
                    if arg.type is not None:
                        arg.type = self._resolve_type(arg.type)
                    if arg.type is not None and arg.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for argument {i} of struct '{enum.payload.name}': {arg.type} != {expected_type}"
                        )
                    arg.type = expected_type
            else:
                enum.payload.type = variant.type
                enum.payload.value.type = variant.type
            return

        raise TypeError(f"Unknown enum variant '{enum.variant}' in '{enum.name}'")

    def _resolve_impl_method_call(self, fn_name: str, args: list[Variable]) -> tuple[str, list[Type]] | None:
        if "::" not in fn_name or not args:
            return None

        trait_name, method_name = fn_name.rsplit("::", 1)
        recv = args[0]
        if recv.type is None:
            return None
        recv_type = self._canonicalize_type(recv.type)
        recv_type_variants = [recv_type]
        if is_box_type(recv_type):
            recv_type_variants.append(box_pointee(recv_type))

        for ref in self.impl_method_refs:
            if ref.method_name != method_name:
                continue
            if not (
                ref.trait_name == trait_name or ref.trait_name.rsplit("::", 1)[-1] == trait_name.rsplit("::", 1)[-1]
            ):
                continue
            generic_names = {generic.name for generic in ref.impl_generics}
            mapping: dict[str, Type] | None = None
            for recv_candidate in recv_type_variants:
                candidate_mapping: dict[str, Type] = {}
                if self._match_type_template(ref.for_type, recv_candidate, generic_names, candidate_mapping):
                    mapping = candidate_mapping
                    break
            if mapping is None:
                continue

            if ref.trait_args:
                if len(args) - 1 < len(ref.trait_args):
                    continue
                trait_arg_match = True
                for template_arg, arg in zip(ref.trait_args, args[1 : 1 + len(ref.trait_args)], strict=True):
                    if arg.type is None or not self._match_type_template(
                        template_arg, self._canonicalize_type(arg.type), generic_names, mapping
                    ):
                        trait_arg_match = False
                        break
                if not trait_arg_match:
                    continue

            target_fn = self.fn[ref.fn_name]
            if len(target_fn.params) != len(args):
                continue
            params_match = True
            for param, arg in zip(target_fn.params, args, strict=True):
                if arg.type is None or not self._match_type_template(
                    param.type, self._canonicalize_type(arg.type), generic_names, mapping
                ):
                    params_match = False
                    break
            if not params_match:
                continue
            concrete_generics: list[Type] = []
            for generic in target_fn.generics:
                if generic.name not in mapping:
                    break
                concrete_generics.append(mapping[generic.name])
            else:
                return ref.fn_name, concrete_generics

        return None

    def _infer_call_type_mapping(
        self, target_fn: Derective_fn, args: list[Variable], out_type: Type | None
    ) -> dict[str, Type]:
        mapping: dict[str, Type] = {}
        generic_names = {generic.name for generic in getattr(target_fn, "generics", [])}

        if "::" in target_fn.name:
            owner_text = target_fn.name.rsplit("::", 1)[0]
            owner_type = self._parse_type_text(owner_text)
            if owner_type is not None:
                generic_names |= {generic.name for generic in owner_type.generics if not generic.generics}
            if owner_type is not None and args and args[0].type is not None:
                self._match_type_template(owner_type, args[0].type, generic_names, mapping)

        for param, arg in zip(target_fn.params, args, strict=False):
            if arg.type is None:
                continue
            self._match_type_template(param.type, arg.type, generic_names, mapping)

        if out_type is not None:
            self._match_type_template(target_fn.ret_type, out_type, generic_names, mapping)

        return mapping

    def _resolve_inherent_method_call(self, fn_name: str, args: list[Variable]) -> tuple[str, list[Type]] | None:
        if "::" not in fn_name:
            return None

        owner_text, method_name = fn_name.rsplit("::", 1)
        actual_owner = self._parse_type_text(owner_text)
        if actual_owner is None:
            return None
        actual_owner = self._canonicalize_type(actual_owner)

        for candidate_name, target_fn in self.fn.items():
            if "::" not in candidate_name or candidate_name.rsplit("::", 1)[-1] != method_name:
                continue

            template_owner = self._parse_type_text(candidate_name.rsplit("::", 1)[0])
            if template_owner is None:
                continue
            template_owner = self._canonicalize_type(template_owner)

            generic_names = {generic.name for generic in getattr(target_fn, "generics", [])}
            generic_names |= {generic.name for generic in template_owner.generics if not generic.generics}
            mapping: dict[str, Type] = {}
            if not self._match_type_template(template_owner, actual_owner, generic_names, mapping):
                continue
            for generic_name in list(mapping.keys()):
                bound = mapping[generic_name]
                if not bound.generics and bound.name in generic_names:
                    del mapping[generic_name]

            if len(target_fn.params) != len(args):
                continue

            params_match = True
            for index, (param, arg) in enumerate(zip(target_fn.params, args, strict=True)):
                if index == 0:
                    # Receiver compatibility is already checked via owner matching.
                    continue
                if arg.type is None:
                    continue
                expected_param_type = template_owner if param.type.name == "Self" and not param.type.generics else param.type
                if not self._match_type_template(expected_param_type, arg.type, generic_names, mapping):
                    params_match = False
                    break
            if not params_match:
                continue

            concrete_generics: list[Type] = []
            for generic in target_fn.generics:
                bound = mapping.get(generic.name)
                if bound is None:
                    break
                concrete_generics.append(bound)
            else:
                return target_fn.name, concrete_generics

        return None

    def _match_type_template(
        self,
        template: Type,
        actual: Type,
        generic_names: set[str],
        mapping: dict[str, Type],
    ) -> bool:
        template = self._canonicalize_type(template)
        actual = self._canonicalize_type(actual)
        if isinstance(template, Pointer):
            return isinstance(actual, Pointer) and self._match_type_template(
                template.pointee, actual.pointee, generic_names, mapping
            )

        if not template.generics and template.name in generic_names:
            bound = mapping.get(template.name)
            if bound is None:
                mapping[template.name] = actual
                return True
            return bound == actual

        if template.name != actual.name or len(template.generics) != len(actual.generics):
            return False

        for expected, observed in zip(template.generics, actual.generics):
            if not self._match_type_template(expected, observed, generic_names, mapping):
                return False
        return True

    def _canonicalize_type(self, typ: Type) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._canonicalize_type(typ.pointee))

        if typ.name in self.concrete_struct_origins:
            base_name, generics = self.concrete_struct_origins[typ.name]
            return Type(base_name, [self._canonicalize_type(generic) for generic in generics])
        if typ.name in self.concrete_enum_origins:
            base_name, generics = self.concrete_enum_origins[typ.name]
            return Type(base_name, [self._canonicalize_type(generic) for generic in generics])

        base = deepcopy(typ)
        base.generics = [self._canonicalize_type(generic) for generic in typ.generics]
        return base

    def _types_compatible(self, lhs: Type, rhs: Type) -> bool:
        lhs_c = self._canonicalize_type(lhs)
        rhs_c = self._canonicalize_type(rhs)
        if lhs_c == rhs_c:
            return True
        generic_names = self._collect_placeholder_type_names(lhs_c) | self._collect_placeholder_type_names(rhs_c)
        if not generic_names:
            return False
        return self._match_type_template(lhs_c, rhs_c, generic_names, {}) or self._match_type_template(
            rhs_c, lhs_c, generic_names, {}
        )

    def _type_specificity(self, typ: Type) -> int:
        return -len(self._collect_placeholder_type_names(self._canonicalize_type(typ)))

    def _collect_placeholder_type_names(self, typ: Type) -> set[str]:
        names: set[str] = set()
        stack: list[Type] = [typ]
        while stack:
            current = stack.pop()
            if isinstance(current, Pointer):
                stack.append(current.pointee)
                continue
            stack.extend(current.generics)
            if (
                not current.generics
                and current.name not in self.structs
                and current.name not in self.enums
                and current.name not in self.concrete_struct_origins
                and current.name not in self.concrete_enum_origins
                and not isinstance(current, PrimitiveType)
                and current.name != "void"
            ):
                names.add(current.name)
        return names

    def _parse_type_text(self, text: str) -> Type | None:
        raw = text.strip()
        if not raw:
            return None

        if raw.endswith("*"):
            pointee = self._parse_type_text(raw[:-1])
            return Pointer(pointee) if pointee is not None else None

        bracket_index = self._find_top_level_char(raw, "[")
        if bracket_index == -1:
            return Type(raw)
        if not raw.endswith("]"):
            return None

        name = raw[:bracket_index].strip()
        inner = raw[bracket_index + 1 : -1]
        generics: list[Type] = []
        for part in self._split_top_level(inner, ","):
            generic = self._parse_type_text(part)
            if generic is None:
                return None
            generics.append(generic)
        return Type(name, generics)

    @staticmethod
    def _find_top_level_char(text: str, needle: str) -> int:
        depth_square = 0
        depth_angle = 0
        for index, char in enumerate(text):
            if char == needle and depth_square == 0 and depth_angle == 0:
                return index
            if char == "[":
                depth_square += 1
            elif char == "]":
                depth_square -= 1
            elif char == "<":
                depth_angle += 1
            elif char == ">":
                depth_angle -= 1
        return -1

    @staticmethod
    def _split_top_level(text: str, separator: str) -> list[str]:
        parts: list[str] = []
        start = 0
        depth_square = 0
        depth_angle = 0

        for index, char in enumerate(text):
            if char == "[":
                depth_square += 1
            elif char == "]":
                depth_square -= 1
            elif char == "<":
                depth_angle += 1
            elif char == ">":
                depth_angle -= 1
            elif char == separator and depth_square == 0 and depth_angle == 0:
                parts.append(text[start:index].strip())
                start = index + 1

        tail = text[start:].strip()
        if tail:
            parts.append(tail)
        return parts

    def _resolve_type(self, typ: Type) -> Type:
        return self._replace_type(typ, {})

    def _replace_type(self, typ: Type, generic_mapping: dict[str, Type]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type(typ.pointee, generic_mapping))
        if isinstance(typ, PrimitiveType):
            return deepcopy(typ)

        if not typ.generics and typ.name in generic_mapping:
            return deepcopy(generic_mapping[typ.name])

        if not typ.generics and typ.name in self.type_aliases:
            return self._replace_type(deepcopy(self.type_aliases[typ.name]), generic_mapping)

        if typ.name == "usize":
            return Usize_t()
        if typ.name == "isize":
            return Isize_t()
        if typ.name == "bool":
            return Usize_t(1)
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

        resolved = deepcopy(typ)
        resolved.generics = [self._replace_type(generic, generic_mapping) for generic in typ.generics]

        target_struct = self.structs.get(resolved.name)
        if (
            target_struct is not None
            and target_struct.generics
            and len(target_struct.generics) == len(resolved.generics)
            and all(self._is_concrete_type(generic) for generic in resolved.generics)
        ):
            concrete_name = target_struct.get_conrete_name(resolved.generics)
            if concrete_name not in self.structs:
                self._concrete_struct(target_struct, resolved.generics)
            return Type(concrete_name)

        target_enum = self.enums.get(resolved.name)
        if (
            target_enum is not None
            and target_enum.generics
            and len(target_enum.generics) == len(resolved.generics)
            and all(self._is_concrete_type(generic) for generic in resolved.generics)
        ):
            concrete_name = target_enum.get_conrete_name(resolved.generics)
            if concrete_name not in self.enums:
                self._concrete_enum(target_enum, resolved.generics)
            return Type(concrete_name)

        return resolved

    def _is_concrete_type(self, typ: Type) -> bool:
        if isinstance(typ, Pointer):
            return self._is_concrete_type(typ.pointee)

        if isinstance(typ, PrimitiveType):
            return True

        if typ.generics and not all(self._is_concrete_type(generic) for generic in typ.generics):
            return False

        return (
            typ.name in self.structs
            or typ.name in self.enums
            or not typ.name.isidentifier()
            or typ.name.startswith("u")
        )

    def _rewrite_types(self, value, generic_mapping: dict[str, Type]):
        if isinstance(value, Type):
            return self._replace_type(value, generic_mapping)

        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = self._rewrite_types(item, generic_mapping)
            return value

        if not is_dataclass(value):
            return value

        for field in fields(value):
            setattr(value, field.name, self._rewrite_types(getattr(value, field.name), generic_mapping))
        return value
