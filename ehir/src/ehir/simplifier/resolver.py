from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass

from ehir.core.derectives import (
    Derective_enum,
    Derective_extern_fn,
    Derective_fn,
    Derective_impl,
    Derective_struct,
    Derective_trait,
)
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum
from ehir.core.instructions.base import Assignable
from ehir.core.instructions.capture import (
    Instruction_ceoh,
    Instruction_ceos,
    Instruction_cpoh,
    Instruction_csoh,
    Instruction_csos,
    Instruction_lceos,
    Instruction_lcpos,
    Instruction_lcsos,
    Instruction_scpoh,
    Instruction_scpos,
    Instruction_scsoh,
    Instruction_scsos,
)
from ehir.core.instructions.capture.cpos import Instruction_cpos
from ehir.core.instructions.control_flow import (
    Instruction_br,
    Instruction_call,
    Instruction_cbr,
    Instruction_match,
    Instruction_phi,
    Instruction_ret,
    Instruction_switch,
)
from ehir.core.instructions.memory import (
    Instruction_gep,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_pcast,
    Instruction_put,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
)
from ehir.core.instructions.memory.load import Instruction_load
from ehir.core.instructions.memory.salloc import Instruction_salloc
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mul,
    Instruction_sub,
)
from ehir.core.instructions.operators.base import BinOp
from ehir.core.instructions.operators.comparison import (
    Instruction_geq,
    Instruction_grt,
    Instruction_leq,
    Instruction_les,
)
from ehir.core.instructions.operators.logic import (
    Instruction_ieq,
    Instruction_neq,
)
from ehir.core.primitives import Float_t, Isize_t, Str_t, Usize_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type
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
    trait_name: str
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

    def run(self, ast: list[Derective]) -> list[Derective]:
        self.fn = {}
        self.enums = {}
        self.structs = {}
        self.traits = {}
        self.impls = []
        self.impl_method_refs = []
        self.concrete_struct_origins = {}
        self.concrete_enum_origins = {}
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
            elif isinstance(derective, Derective_impl):
                self.impls.append(derective)

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

        # drop generics
        base_enum_names = {x.name for x in self.enums.values() if x.generics}
        base_struct_names = {x.name for x in self.structs.values() if x.generics}
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
            if isinstance(derective, (Derective_trait, Derective_impl)):
                continue
            if isinstance(derective, Derective_enum) and derective.name in base_enum_names:
                continue
            if isinstance(derective, Derective_struct) and derective.name in base_struct_names:
                continue
            if isinstance(derective, Derective_fn) and derective.generics:
                continue
            new_ast.append(derective)

        return new_ast

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

            if method_fn.name in self.fn:
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

        def add_variable(var: Variable) -> Variable:
            if var.type is not None:
                var.type = self._resolve_type(var.type)

            if var.name not in variables:
                variables[var.name] = var
                return var

            old_var = variables[var.name]
            if old_var.type and var.type:
                if old_var.type != var.type:
                    raise TypeError(f"Type mismatch for variable '{var.name}': {old_var.type} != {var.type}")
                return old_var
            elif old_var.type:
                return old_var
            else:
                old_var.type = var.type
                return old_var

        def resolve_call(instr: Instruction_call):
            instr.args = [add_variable(arg) for arg in instr.args]
            resolved_impl = self._resolve_impl_method_call(instr.fn_name, instr.args)
            if resolved_impl is not None:
                fn_name, inferred_generics = resolved_impl
                instr.fn_name = fn_name
                if not instr.generics:
                    instr.generics = inferred_generics

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

                    trait_name, method_name = instr.fn_name.split("::", 1)
                    candidates = [
                        f"{ref.trait_name}[{', '.join(str(arg) for arg in ref.trait_args)}] for {ref.for_type}::{ref.method_name}"
                        for ref in self.impl_method_refs
                        if ref.trait_name == trait_name and ref.method_name == method_name
                    ]
                    arg_types = [str(arg.type) if arg.type is not None else "?" for arg in instr.args]
                    raise TypeError(
                        f"Unknown function '{instr.fn_name}' for args {arg_types}. "
                        f"Impl candidates: {candidates}"
                    )
                raise TypeError(f"Unknown function '{instr.fn_name}'")
            target_fn = self.fn[instr.fn_name]
            if isinstance(target_fn, Derective_extern_fn):
                if not instr.is_unsafe:
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
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
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
            expected_type = self._resolve_type(deepcopy(target_fn.ret_type))
            if instr.var_out.type and instr.var_out.type != expected_type:
                raise TypeError(
                    f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
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
            elif cond_type.name.endswith("_HSP") or cond_type.name.endswith("_SSP"):
                inner_name = cond_type.name.removesuffix("_HSP").removesuffix("_SSP")
                inner_type = Type(name=inner_name)
                wrapper_ptr_type = Pointer(inner_type)
                if inner_name not in self.enums:
                    return
                enum_variant_payloads = {
                    variant.name: variant.type for variant in self._get_enum_variants(inner_name, inner_type.generics)
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
                    assert instr.cond_var.type is not None
                    instr.cond_var.type = self._resolve_type(instr.cond_var.type)
                    inject_match_payload_binding(instr)

        for block in fn.body:
            for instr_id, instr in enumerate(block.body):
                if isinstance(instr, Assignable) and instr.var_out.type is not None:
                    instr.var_out.type = self._resolve_type(instr.var_out.type)

                if isinstance(instr, (Instruction_cpos, Instruction_cpoh, Instruction_scpos, Instruction_scpoh)):
                    if isinstance(instr, (Instruction_cpos, Instruction_cpoh)):
                        pointer_t = Pointer
                    elif isinstance(instr, Instruction_scpos):
                        pointer_t = StackSmartPointer
                    else:
                        pointer_t = HeapSmartPointer
                    expected_type = pointer_t(instr.primitive.type)
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, (Instruction_ceoh, Instruction_ceos)):
                    instr.enum = self._resolve_enum(instr.enum)
                    if isinstance(instr, Instruction_ceoh):
                        expected_type = Pointer(instr.enum.as_type())
                    else:
                        expected_type = Pointer(instr.enum.as_type())

                    if instr.var_out.type and instr.var_out.type != expected_type:
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

                elif isinstance(instr, (Instruction_csos, Instruction_csoh, Instruction_scsos, Instruction_scsoh)):
                    instr.struct = self._resolve_struct(instr.struct)
                    if isinstance(instr, (Instruction_csos, Instruction_csoh)):
                        pointer_t = Pointer
                    elif isinstance(instr, Instruction_scsos):
                        pointer_t = StackSmartPointer
                    else:
                        pointer_t = HeapSmartPointer
                    expected_type = pointer_t(instr.struct.as_type())
                    if instr.var_out.type and instr.var_out.type != expected_type:
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

                elif isinstance(instr, Instruction_lcpos):
                    expected_type = instr.primitive.type

                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_lceos):
                    instr.enum = self._resolve_enum(instr.enum)
                    expected_type = instr.enum.as_type()

                    if instr.var_out.type and instr.var_out.type != expected_type:
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

                elif isinstance(instr, Instruction_lcsos):
                    instr.struct = self._resolve_struct(instr.struct)
                    expected_type = instr.struct.as_type()

                    if instr.var_out.type and instr.var_out.type != expected_type:
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
                    (Instruction_getfield, Instruction_getfieldptr, Instruction_sgetfield, Instruction_sgetfieldptr),
                ):
                    instr.src = add_variable(instr.src)
                    assert instr.src.type
                    instr.src.type = self._resolve_type(instr.src.type)

                    if isinstance(instr.src.type, PrimitiveType):
                        raise TypeError(f"Cannot access field of primitive type '{instr.src.type}'")

                    resolved_params = self._get_composite_params(instr.src.type.name, instr.src.type.generics)
                    for i, param in enumerate(resolved_params):
                        if param.name == instr.field.name or str(i) == instr.field.name:
                            if instr.field.type and instr.field.type != param.type:
                                raise TypeError(
                                    f"Type mismatch for field '{instr.field.name}' in struct '{instr.src.type.name}': {instr.field.type} != {param.type}"
                                )
                            instr.field.type = param.type
                            instr.field.name = str(i)
                            break
                    else:
                        raise TypeError(f"Unknown field '{instr.field.name}' in struct '{instr.src.type.name}'")

                    expected_type = (
                        instr.field.type
                        if isinstance(instr, (Instruction_getfield, Instruction_sgetfield))
                        else Pointer(instr.field.type)
                    )
                    if instr.var_out.type and instr.var_out.type != expected_type:
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                elif isinstance(instr, Instruction_ret):
                    fn.ret_type = self._resolve_type(fn.ret_type)
                    expected_type = fn.ret_type
                    instr.var = add_variable(instr.var)
                    if instr.var.type and instr.var.type != expected_type:
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
                            raise TypeError(f"Type mismatch for binop operands: {lhs_t} != {rhs_t}")
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
                            expected_t = Usize_t(size=1)  # aka bool

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
                        raise TypeError(
                            f"Type mismatch for variable '{instr.var_out.name}': {instr.var_out.type} != {expected_type}"
                        )
                    instr.var_out.type = expected_type
                    instr.var_out = add_variable(instr.var_out)

                    for arg in instr.args:
                        if arg.var.type and arg.var.type != expected_type:
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
                        if case.payload_var is not None and case.payload_var.type != next(
                            variant.type
                            for variant in self._get_enum_variants(
                                instr.cond_var.type.name, instr.cond_var.type.generics
                            )
                            if variant.name == case.variant
                        ):
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
                raise TypeError(f"Type not specified for variable '{name}'")

    def _concrete_fn(self, fn: Derective_fn, types: list[Type]) -> "Derective_fn":
        assert len(fn.generics) == len(types)
        generic_mapping = {a.name: b for a, b in zip(fn.generics, types)}

        base = deepcopy(fn)
        self._rewrite_types(base, generic_mapping)
        base.generics.clear()
        base.name = base.get_conrete_name(types)
        self.fn[base.name] = base
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

        def unwrap_receiver_type(typ: Type) -> Type:
            if isinstance(typ, (HeapSmartPointer, StackSmartPointer)):
                return typ.pointee
            return typ

        trait_name, method_name = fn_name.split("::", 1)
        recv = args[0]
        if recv.type is None:
            return None
        recv_type = unwrap_receiver_type(recv.type)

        for ref in self.impl_method_refs:
            if ref.trait_name != trait_name or ref.method_name != method_name:
                continue
            generic_names = {generic.name for generic in ref.impl_generics}
            mapping: dict[str, Type] = {}
            if not self._match_type_template(ref.for_type, recv_type, generic_names, mapping):
                continue

            if ref.trait_args:
                if len(args) - 1 < len(ref.trait_args):
                    continue
                trait_arg_match = True
                for template_arg, arg in zip(ref.trait_args, args[1 : 1 + len(ref.trait_args)], strict=True):
                    if arg.type is None or not self._match_type_template(
                        template_arg, unwrap_receiver_type(arg.type), generic_names, mapping
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
                    param.type, unwrap_receiver_type(arg.type), generic_names, mapping
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
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._canonicalize_type(typ.pointee))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._canonicalize_type(typ.pointee))
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

    def _resolve_type(self, typ: Type) -> Type:
        return self._replace_type(typ, {})

    def _replace_type(self, typ: Type, generic_mapping: dict[str, Type]) -> Type:
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._replace_type(typ.pointee, generic_mapping))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._replace_type(typ.pointee, generic_mapping))
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type(typ.pointee, generic_mapping))
        if isinstance(typ, PrimitiveType):
            return deepcopy(typ)

        if not typ.generics and typ.name in generic_mapping:
            return deepcopy(generic_mapping[typ.name])

        if typ.name == "usize":
            return Usize_t()
        if typ.name == "isize":
            return Isize_t()
        if typ.name == "bool":
            return Usize_t(1)
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
        if isinstance(typ, (HeapSmartPointer, StackSmartPointer, Pointer)):
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
