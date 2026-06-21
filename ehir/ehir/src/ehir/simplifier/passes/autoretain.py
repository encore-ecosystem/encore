from copy import deepcopy
from dataclasses import fields, is_dataclass

from ehir.resolver import EHIR_TypedModule
from ehir.core.block import Block
from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import EnumVariant, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    Instruction_add,
    Instruction_call,
    Instruction_callvoid,
    Instruction_capprim,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_load,
    Instruction_ret,
    Instruction_store,
)
from ehir.core.primitives import Usize, Usize_t
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.type import Pointer, Reference, Type, mangle_type_name
from ehir.core.variable import Parameter, StructField, TypedVariable
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.drop_helper import (
    collect_aggregate_names,
    is_box_struct,
    is_dyn_type,
    needs_retain,
    reference_storage_struct,
    retain_function_name,
)


class AutoRetainPass(SimplifierPass):
    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        self._structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct)
        }
        self._enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum)
        }
        self._aggregate_names = collect_aggregate_names(self._structs, self._enums)
        existing_names = {
            directive.name
            for directive in ast
            if isinstance(directive, Derective_fn)
        }

        generated: list[Derective] = []
        uses_str = self._uses_type(ast, Type("str"))
        if uses_str and "encore_str_retain" not in existing_names:
            generated.append(
                Derective_extern_fn(
                    name="encore_str_retain",
                    params=[Parameter("value", Type("str"))],
                    ret_type=Type("void"),
                )
            )
            existing_names.add("encore_str_retain")
        str_retain_name = retain_function_name(Type("str"))
        if uses_str and str_retain_name not in existing_names:
            generated.append(self._generate_str_retain_fn())
            existing_names.add(str_retain_name)

        for dyn_type in self._collect_dyn_types(ast):
            fn_name = retain_function_name(dyn_type)
            if fn_name in existing_names:
                continue
            generated.append(
                Derective_extern_fn(
                    name=fn_name,
                    params=[Parameter("self", dyn_type)],
                    ret_type=Type("void"),
                )
            )
            existing_names.add(fn_name)

        for directive in ast:
            if (
                isinstance(directive, Derective_struct)
                and not directive.generics
                and needs_retain(Type(directive.name), self._aggregate_names)
            ):
                fn_name = retain_function_name(Type(directive.name))
                if fn_name not in existing_names:
                    generated.append(self._generate_struct_retain_fn(directive))
                    existing_names.add(fn_name)
            elif (
                isinstance(directive, Derective_enum)
                and not directive.generics
                and needs_retain(Type(directive.name), self._aggregate_names)
            ):
                fn_name = retain_function_name(Type(directive.name))
                if fn_name not in existing_names:
                    generated.append(self._generate_enum_retain_fn(directive))
                    existing_names.add(fn_name)

        for concrete_type in self._collect_concrete_reference_storage_types(ast):
            fn_name = retain_function_name(concrete_type)
            if fn_name in existing_names:
                continue
            concrete_struct, concrete_storage = self._concrete_reference_storage_structs(concrete_type)
            if concrete_struct is None or concrete_storage is None:
                continue
            generated.append(
                self._generate_reference_storage_retain_fn(concrete_type, concrete_struct, concrete_storage)
            )
            existing_names.add(fn_name)

        for concrete_type in self._collect_concrete_generic_aggregate_types(ast):
            fn_name = retain_function_name(concrete_type)
            if fn_name in existing_names:
                continue
            if concrete_type.name in self._structs:
                concrete_struct = self._concrete_generic_struct(concrete_type)
                if concrete_struct is not None:
                    generated.append(self._generate_struct_retain_fn(concrete_struct, self_type=concrete_type))
                    existing_names.add(fn_name)
            elif concrete_type.name in self._enums:
                concrete_enum = self._concrete_generic_enum(concrete_type)
                if concrete_enum is not None:
                    generated.append(self._generate_enum_retain_fn(concrete_enum, self_type=concrete_type))
                    existing_names.add(fn_name)

        return ast + generated

    def _generate_str_retain_fn(self) -> Derective_fn:
        self_type = Type("str")
        self_var = TypedVariable("self", self_type)
        return Derective_fn(
            name=retain_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=[
                Block(
                    name="entry",
                    body=[
                        Instruction_callvoid(
                            fn_name="encore_str_retain",
                            generics=[],
                            args=[deepcopy(self_var)],
                        ),
                        Instruction_ret(TypedVariable(".retain_ret", Type("void"))),
                    ],
                )
            ],
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_struct_retain_fn(self, directive: Derective_struct, self_type: Type | None = None) -> Derective_fn:
        self_type = deepcopy(self_type) if self_type is not None else Type(directive.name)
        self_var = TypedVariable("self", self_type)
        reference_storage = reference_storage_struct(directive, self._structs)
        if reference_storage is not None:
            body = self._generate_reference_storage_retain_body(directive, reference_storage, self_var)
        elif is_box_struct(directive):
            body = self._generate_box_retain_body(directive, self_var)
        else:
            body = self._generate_struct_retain_body(directive, self_var)
        return Derective_fn(
            name=retain_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=[Block(name="entry", body=body)],
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_reference_storage_retain_fn(
        self,
        self_type: Type,
        directive: Derective_struct,
        storage: Derective_struct,
    ) -> Derective_fn:
        self_var = TypedVariable("self", self_type)
        return Derective_fn(
            name=retain_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=[
                Block(name="entry", body=self._generate_reference_storage_retain_body(directive, storage, self_var))
            ],
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_enum_retain_fn(self, directive: Derective_enum, self_type: Type | None = None) -> Derective_fn:
        self_type = deepcopy(self_type) if self_type is not None else Type(directive.name)
        self_var = TypedVariable("self", self_type)
        blocks = self._generate_enum_retain_blocks(directive, self_var)
        return Derective_fn(
            name=retain_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=blocks,
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_box_retain_body(self, directive: Derective_struct, self_var: TypedVariable):
        owner_ptr_type = directive.params[1].type
        assert isinstance(owner_ptr_type, Pointer)

        owner_ptr = TypedVariable(".retain_owner_ptr", owner_ptr_type)
        ref_count_ptr = TypedVariable(".retain_ref_count_ptr", Pointer(Usize_t()))
        ref_count = TypedVariable(".retain_ref_count", Usize_t())
        one = TypedVariable(".retain_one", Usize_t())
        next_ref_count = TypedVariable(".retain_next_ref_count", Usize_t())

        return [
            Instruction_getfield(var_out=owner_ptr, src=self_var, field=TypedVariable("1", owner_ptr_type)),
            Instruction_getfieldptr(
                var_out=ref_count_ptr,
                src=owner_ptr,
                field=TypedVariable("1", Usize_t()),
            ),
            Instruction_load(var_out=ref_count, var=ref_count_ptr),
            Instruction_capprim(var_out=one, primitive=Usize(1)),
            Instruction_add(var_out=next_ref_count, lhs=ref_count, rhs=one),
            Instruction_store(var_src=next_ref_count, var_dst=ref_count_ptr),
            Instruction_ret(TypedVariable(".retain_ret", Type("void"))),
        ]

    def _generate_reference_storage_retain_body(
        self,
        directive: Derective_struct,
        storage: Derective_struct,
        self_var: TypedVariable,
    ):
        storage_ptr_type = directive.params[0].type
        assert isinstance(storage_ptr_type, Pointer)

        storage_ptr = TypedVariable(".retain_storage_ptr", storage_ptr_type)
        ref_count_ptr = TypedVariable(".retain_ref_count_ptr", Pointer(Usize_t()))
        ref_count = TypedVariable(".retain_ref_count", Usize_t())
        one = TypedVariable(".retain_one", Usize_t())
        next_ref_count = TypedVariable(".retain_next_ref_count", Usize_t())

        return [
            Instruction_getfield(var_out=storage_ptr, src=self_var, field=TypedVariable("0", storage_ptr_type)),
            Instruction_getfieldptr(
                var_out=ref_count_ptr,
                src=storage_ptr,
                field=TypedVariable("0", storage.params[0].type),
            ),
            Instruction_load(var_out=ref_count, var=ref_count_ptr),
            Instruction_capprim(var_out=one, primitive=Usize(1)),
            Instruction_add(var_out=next_ref_count, lhs=ref_count, rhs=one),
            Instruction_store(var_src=next_ref_count, var_dst=ref_count_ptr),
            Instruction_ret(TypedVariable(".retain_ret", Type("void"))),
        ]

    def _generate_struct_retain_body(self, directive: Derective_struct, self_var: TypedVariable):
        body = []
        for index, field in enumerate(directive.params):
            if not needs_retain(field.type, self._aggregate_names):
                continue
            field_var = TypedVariable(f".retain_{field.name}", deepcopy(field.type))
            body.append(
                Instruction_getfield(
                    var_out=field_var,
                    src=self_var,
                    field=TypedVariable(str(index), deepcopy(field.type)),
                )
            )
            body.append(
                Instruction_call(
                    var_out=TypedVariable(f".retain_call_{field.name}", Type("void")),
                    fn_name=retain_function_name(field.type),
                    generics=[],
                    args=[deepcopy(field_var)],
                )
            )
        body.append(Instruction_ret(TypedVariable(".retain_ret", Type("void"))))
        return body

    def _generate_enum_retain_blocks(self, directive: Derective_enum, self_var: TypedVariable) -> list[Block]:
        retain_variants = [
            (variant_index, variant)
            for variant_index, variant in enumerate(directive.variants, start=1)
            if self._variant_needs_retain(variant)
        ]
        if not retain_variants:
            return [Block(name="entry", body=[Instruction_ret(TypedVariable(".retain_ret", Type("void")))])]

        entry = Block(
            name="entry",
            body=[],
        )
        # Reuse the same lowered shape as autodrop: tag-switch later in the pipeline.
        from ehir.core.instructions import Instruction_match, MatchCase

        entry.body.append(
            Instruction_match(
                cond_var=self_var,
                default_case="done",
                cases=[MatchCase(variant=variant.name, label=f"retain_{variant.name}") for _, variant in retain_variants],
            )
        )
        blocks = [entry]
        for variant_index, variant in retain_variants:
            payload_type = self._variant_payload_type(variant)
            assert payload_type is not None
            payload = TypedVariable(f".retain_{variant.name}", deepcopy(payload_type))
            blocks.append(
                Block(
                    name=f"retain_{variant.name}",
                    body=[
                        Instruction_getfield(
                            var_out=payload,
                            src=self_var,
                            field=TypedVariable(str(variant_index), deepcopy(payload_type)),
                        ),
                        Instruction_call(
                            var_out=TypedVariable(f".retain_call_{variant.name}", Type("void")),
                            fn_name=retain_function_name(payload_type),
                            generics=[],
                            args=[deepcopy(payload)],
                        ),
                        Instruction_ret(TypedVariable(".retain_ret", Type("void"))),
                    ],
                )
            )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".retain_ret", Type("void")))]))
        return blocks

    def _variant_needs_retain(self, variant: EnumVariant) -> bool:
        payload_type = self._variant_payload_type(variant)
        return payload_type is not None and needs_retain(payload_type, self._aggregate_names)

    def _collect_concrete_reference_storage_types(self, ast: list[Derective]) -> list[Type]:
        reference_storage_names = {
            name
            for name, directive in self._structs.items()
            if directive.generics and reference_storage_struct(directive, self._structs) is not None
        }
        observed: dict[str, Type] = {}
        for item in self._walk(ast):
            if isinstance(item, Type):
                self._collect_concrete_reference_storage_type(item, reference_storage_names, observed)
        return list(observed.values())

    def _collect_concrete_reference_storage_type(
        self,
        typ: Type,
        reference_storage_names: set[str],
        out: dict[str, Type],
    ) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_concrete_reference_storage_type(typ.pointee, reference_storage_names, out)
            return
        for generic in typ.generics:
            self._collect_concrete_reference_storage_type(generic, reference_storage_names, out)
        if typ.name not in reference_storage_names or not typ.generics:
            return
        if self._is_placeholder_type(typ):
            return
        out[mangle_type_name(typ)] = deepcopy(typ)

    def _collect_concrete_generic_aggregate_types(self, ast: list[Derective]) -> list[Type]:
        generic_names = {
            name
            for name, directive in {**self._structs, **self._enums}.items()
            if getattr(directive, "generics", None)
        }
        observed: dict[str, Type] = {}
        for item in self._walk(ast):
            if isinstance(item, Type):
                self._collect_concrete_generic_aggregate_type(item, generic_names, observed)
        return list(observed.values())

    def _collect_dyn_types(self, ast: list[Derective]) -> list[Type]:
        observed: dict[str, Type] = {}
        for item in self._walk(ast):
            if not isinstance(item, Type):
                continue
            self._collect_dyn_type(item, observed)
        return list(observed.values())

    def _collect_dyn_type(self, typ: Type, out: dict[str, Type]) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_dyn_type(typ.pointee, out)
            return
        for generic in typ.generics:
            self._collect_dyn_type(generic, out)
        if is_dyn_type(typ) and not self._is_placeholder_type(typ):
            out[mangle_type_name(typ)] = deepcopy(typ)

    def _collect_concrete_generic_aggregate_type(
        self,
        typ: Type,
        generic_names: set[str],
        out: dict[str, Type],
    ) -> None:
        if isinstance(typ, (Pointer, Reference)):
            self._collect_concrete_generic_aggregate_type(typ.pointee, generic_names, out)
            return
        for generic in typ.generics:
            self._collect_concrete_generic_aggregate_type(generic, generic_names, out)
        if typ.name not in generic_names or not typ.generics:
            return
        if self._is_placeholder_type(typ):
            return
        out[mangle_type_name(typ)] = deepcopy(typ)

    def _concrete_generic_struct(self, concrete_type: Type) -> Derective_struct | None:
        template = self._structs.get(concrete_type.name)
        if template is None or not template.generics:
            return None
        mapping = {
            generic.name: concrete
            for generic, concrete in zip(template.generics, concrete_type.generics, strict=False)
        }
        return self._materialize_struct(template, mapping)

    def _concrete_generic_enum(self, concrete_type: Type) -> Derective_enum | None:
        template = self._enums.get(concrete_type.name)
        if template is None or not template.generics:
            return None
        mapping = {
            generic.name: concrete
            for generic, concrete in zip(template.generics, concrete_type.generics, strict=False)
        }
        return Derective_enum(
            name=template.name,
            generics=[],
            variants=[self._replace_enum_variant_types(variant, mapping) for variant in template.variants],
            is_public=template.is_public,
            attrs=template.attrs,
        )

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
                types=[self._replace_type(typ, mapping) for typ in variant.types],
            )
        raise TypeError(f"Unknown enum variant kind: {type(variant)}")

    def _concrete_reference_storage_structs(
        self,
        concrete_type: Type,
    ) -> tuple[Derective_struct | None, Derective_struct | None]:
        template = self._structs.get(concrete_type.name)
        if template is None or not template.generics:
            return None, None
        storage_template = reference_storage_struct(template, self._structs)
        if storage_template is None:
            return None, None
        mapping = {
            generic.name: concrete
            for generic, concrete in zip(template.generics, concrete_type.generics, strict=False)
        }
        concrete_struct = self._materialize_struct(template, mapping)
        concrete_storage = self._materialize_struct(storage_template, mapping)
        return concrete_struct, concrete_storage

    def _materialize_struct(self, template: Derective_struct, mapping: dict[str, Type]) -> Derective_struct:
        return Derective_struct(
            name=template.name,
            generics=[],
            params=[
                StructField(field.name, self._replace_type(field.type, mapping), attrs=getattr(field, "attrs", ()))
                for field in template.params
            ],
            is_public=template.is_public,
            attrs=template.attrs,
        )

    def _replace_type(self, typ: Type, mapping: dict[str, Type]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._replace_type(typ.pointee, mapping))
        if isinstance(typ, Reference):
            return Reference(self._replace_type(typ.pointee, mapping))
        if not typ.generics and typ.name in mapping:
            return deepcopy(mapping[typ.name])
        if isinstance(typ, PrimitiveType):
            return deepcopy(typ)
        return Type(typ.name, [self._replace_type(generic, mapping) for generic in typ.generics])

    def _uses_type(self, ast: list[Derective], needle: Type) -> bool:
        return any(isinstance(item, Type) and item.name == needle.name and item.generics == needle.generics for item in self._walk(ast))

    def _is_placeholder_type(self, typ: Type) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return self._is_placeholder_type(typ.pointee)
        if not typ.generics and (
            typ.name in {"Self", "T"} or (len(typ.name) == 1 and typ.name.isupper()) or (typ.name.startswith("T") and typ.name[1:].isdigit())
        ):
            return True
        return any(self._is_placeholder_type(generic) for generic in typ.generics)

    def _walk(self, value):
        if value is None or isinstance(value, (str, int, float, bool, Primitive)):
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

    def _variant_payload_type(self, variant: EnumVariant) -> Type | None:
        if isinstance(variant, UnitLikeVariant):
            return None
        if isinstance(variant, TupleLikeVariant):
            if len(variant.types) == 0:
                return None
            return variant.types[0]
        raise TypeError(f"Unknown enum variant kind: {type(variant)}")
