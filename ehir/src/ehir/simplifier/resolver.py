from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Optional

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
from ehir.core.enum import Enum, EnumVariant, TupleLikeVariant, UnitLikeVariant
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
from ehir.core.instructions.arithmetic import Instruction_div
from ehir.core.instructions.base import Assignable
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
class VariableDatabase:
    _data: dict[str, Variable] = field(default_factory=dict)

    def store_raw_as_source_of_truth(self, variable: Variable, expected_type: Type) -> Variable:
        if cached := self._data.get(variable.name):
            if cached.type != expected_type:
                raise RuntimeError(
                    f"Different type for variable {cached.name}. Cached {cached.type} but last store expect {expected_type}"
                )
            return cached
        var = Variable(variable.name, expected_type)
        self._data[var.name] = var
        return var

    def store_typ_as_source_of_truth(self, variable: TypedVariable, expected_type: Type):
        if variable.type != expected_type:
            raise RuntimeError(f"Different typed for variable {variable.name}: {variable.type} != {expected_type}")
        return self.store_raw_as_source_of_truth(variable, expected_type)

    def store(self, variable: Variable, expected_type: Type):
        if isinstance(variable, TypedVariable):
            return self.store_typ_as_source_of_truth(variable, expected_type)
        return self.store_raw_as_source_of_truth(variable, expected_type)

    def get(self, variable: Variable) -> Variable:
        if cached := self._data.get(variable.name):
            return cached

        var = deepcopy(variable)
        self._data[var.name] = var
        return var


class Resolver:
    fn: dict[str, Derective_fn | Derective_extern_fn]
    enums: dict[str, Derective_enum]
    structs: dict[str, Derective_struct]
    traits: dict[str, Derective_trait]
    impls: list[Derective_impl]
    variables: VariableDatabase = VariableDatabase()

    def run(self, ast: list[Derective]) -> list[Derective]:
        # 1. Collect all sources of truth (all declarations)
        self.fn = {}
        self.enums = {}
        self.structs = {}
        self.traits = {}
        self.impls = []

        for derective in ast:
            if isinstance(derective, (Derective_fn, Derective_extern_fn)):
                self.fn[derective.name] = derective
            elif isinstance(derective, Derective_enum):
                self.enums[derective.name] = derective
            elif isinstance(derective, Derective_struct):
                self.structs[derective.name] = derective
            elif isinstance(derective, Derective_trait):
                self.traits[derective.name] = self._resolve_trait(derective)
            elif isinstance(derective, Derective_impl):
                self.impls.append(self._resolve_impl(derective))

        # 2. Resolve types in functions
        for fn in list(self.fn.values()):
            if isinstance(fn, Derective_extern_fn):
                continue
            self._resolve_function_body(fn)

        raise RuntimeError("Stoppoint")

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

    def _resolve_trait(self, trait: Derective_trait) -> Derective_trait:
        return trait

    def _resolve_impl(self, impl: Derective_impl) -> Derective_impl:
        def rename_self(type: Type) -> Type:
            if type.name == "Self":
                type.name = impl.for_type.name
            for i, g in enumerate(type.generics):
                type.generics[i] = rename_self(g)
            return type

        for method in impl.methods:
            method.ret_type = rename_self(method.ret_type)

        return impl

    def _resolve_function_body(self, fn: Derective_fn):
        self.variables = VariableDatabase()

        # step 0: Collect all variables
        for i, param in enumerate(fn.params):
            fn.params[i] = self.variables.store_typ_as_source_of_truth(param, param.type)

        for block in fn.body:
            for instr in block.get_body():
                if isinstance(instr, Instruction_capprim):
                    self._resolve_capprim(instr)
                elif isinstance(instr, Instruction_capenum):
                    self._resolve_capenum(instr)
                elif isinstance(instr, Instruction_call):
                    self._resolve_call(instr)
                else:
                    raise NotImplementedError(f"Unable to resolve instruction: {instr}")

        # step 1: Check variables
        for name, val in variables.items():
            if val.type is None:
                raise TypeError(f"Type not specified for variable '{name}' in fn '{fn.name}'")

    def _resolve_capprim(self, instr: Instruction_capprim):
        expected_type = instr.primitive.type

        if isinstance(instr.var_out, TypedVariable):
            new_var_out = self.variables.store_typ_as_source_of_truth(instr.var_out, expected_type)
        else:
            new_var_out = self.variables.store_raw_as_source_of_truth(instr.var_out, expected_type)

        instr.var_out = new_var_out

    def _resolve_call(self, instr: Instruction_call):
        expected_type = None
        target_fn = None
        for res in self.impls:
            for method in res.methods:
                name = f"{res.for_type}::{method.name}"
                if name == instr.fn_name:
                    expected_type = method.ret_type
                    target_fn = method

        if expected_type is not None:
            instr.var_out = self.variables.store(instr.var_out, expected_type)
        assert target_fn

        for i, arg in enumerate(instr.args):
            expected_type = target_fn.params[i].type
            instr.args[i] = self.variables.store(arg, expected_type)

    def _resolve_capenum(self, instr: Instruction_capenum):
        if instr.enum.name not in self.enums:
            raise RuntimeError(f"Unknown enum: {instr.enum.name}")

        target_enum = self.enums[instr.enum.name]
        target_variant = None
        for variant in target_enum.variants:
            if variant.name == instr.enum.variant:
                target_variant = variant
                break
        else:
            raise RuntimeError(f"Unknown variant {instr.enum.variant} for enum {instr.enum.name}")

        target_variant: EnumVariant
        if isinstance(target_variant, UnitLikeVariant):
            raise NotImplementedError()
        elif isinstance(target_variant, TupleLikeVariant):
            for i, arg in enumerate(instr.enum.args):
                instr.enum.args[i] = self.variables.get(arg)
        else:
            raise NotImplementedError()

        curr_gens = len(instr.enum.generics)
        targ_gens = len(target_enum.generics)
        if curr_gens > targ_gens:
            raise RuntimeError(f"Too much typed generics: {instr}. Current: {curr_gens} but expected {targ_gens}")
        else:
            generic_to_arg_index_mapping: dict[str, list[int]] = {}
            for gen in target_enum.generics:
                for i, arg in enumerate(target_variant.types):
                    if arg.name != gen.name:
                        continue
                    generic_to_arg_index_mapping[gen.name] = generic_to_arg_index_mapping.get(gen.name, []) + [i]

            # Check existing generics
            for _i in range(curr_gens):
                # print(1, instr.enum.generics[i], target_enum.generics)
                raise NotImplementedError

            for i in range(curr_gens, targ_gens):
                possible_indexes_to_acquire_type = generic_to_arg_index_mapping[target_enum.generics[i].name]
                types = [instr.enum.args[index].type for index in possible_indexes_to_acquire_type]
                assert types[0]
                instr.enum.generics.append(types[0])

        instr.var_out = self.variables.store(instr.var_out, instr.enum.as_type())

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
        """
        Steps:
            1. Get corresponding enum declaration as a truth source
            2. Resolve generics if they may occure here
        """

        # 1
        enum_declaration = self.enums.get(enum.name, None)
        if enum_declaration is None:
            raise RuntimeError(f"Unable to find corresponding enum declaration: {enum.name}")

        # 2
        if enum.payload is None:
            raise NotImplementedError

        declared_payload = None
        for variant in enum_declaration.variants:
            if variant.name == enum.payload.name:
                declared_payload = variant

        if declared_payload is None:
            raise RuntimeError(f"Unable to find payload {enum.payload.name} in enum {enum.name}")

        generics_mapping: dict[str, Type] = {}
        for arg in enum.payload.fields:
            if not isinstance(arg, TypedVariable):
                raise RuntimeError(f"Found untyped argument: {arg}")

            print(52, arg.type)

        # if len(enum.payload.fields) != len(enum_declaration.)

        current_generics = enum.generics
        target_generics = enum_declaration.generics

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

            print(variant.type, enum)
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

        print([x.for_type.name for x in self.impls])

        for impl in self.impls:
            if impl.for_type.name != trait_name:
                continue
            for method in impl.methods:
                if method.name != method_name:
                    continue
                print(1, method)

        print(trait_name, method_name, self.impls[1].for_type)
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
                expected_param_type = (
                    template_owner if param.type.name == "Self" and not param.type.generics else param.type
                )
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

        if typ.name in self.structs:
            target_struct = self.structs[typ.name]
            return Type(target_struct.name, [self._canonicalize_type(generic) for generic in target_struct.generics])
        if typ.name in self.enums:
            target_enum = self.enums[typ.name]
            raise NotImplementedError
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
