from copy import deepcopy

from ehir.core.block import Block
from ehir.core.derectives import Derective_enum, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import EnumVariant
from ehir.core.instructions import (
    Instruction_add,
    Instruction_call,
    Instruction_capprim,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_load,
    Instruction_ret,
    Instruction_store,
)
from ehir.core.primitives import Usize, Usize_t
from ehir.core.type import Pointer, Type
from ehir.core.variable import Parameter, TypedVariable
from ehir.simplifier.drop_helper import is_box_struct, needs_retain, retain_function_name


class AutoRetainPass:
    def run(self, ast: list[Derective]) -> list[Derective]:
        self._structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct) and not directive.generics
        }
        self._enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum) and not directive.generics
        }
        self._aggregate_names = set(self._structs) | set(self._enums)
        existing_names = {
            directive.name
            for directive in ast
            if isinstance(directive, Derective_fn)
        }

        generated: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_struct) and not directive.generics:
                fn_name = retain_function_name(Type(directive.name))
                if fn_name not in existing_names:
                    generated.append(self._generate_struct_retain_fn(directive))
                    existing_names.add(fn_name)
            elif isinstance(directive, Derective_enum) and not directive.generics:
                fn_name = retain_function_name(Type(directive.name))
                if fn_name not in existing_names:
                    generated.append(self._generate_enum_retain_fn(directive))
                    existing_names.add(fn_name)

        return ast + generated

    def _generate_struct_retain_fn(self, directive: Derective_struct) -> Derective_fn:
        self_type = Type(directive.name)
        self_var = TypedVariable("self", self_type)
        if is_box_struct(directive):
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

    def _generate_enum_retain_fn(self, directive: Derective_enum) -> Derective_fn:
        self_type = Type(directive.name)
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
            assert variant.type is not None
            payload_ptr_type = Pointer(deepcopy(variant.type))
            payload_ptr = TypedVariable(f".retain_{variant.name}_ptr", payload_ptr_type)
            payload = TypedVariable(f".retain_{variant.name}", deepcopy(variant.type))
            blocks.append(
                Block(
                    name=f"retain_{variant.name}",
                    body=[
                        Instruction_getfield(
                            var_out=payload_ptr,
                            src=self_var,
                            field=TypedVariable(str(variant_index), payload_ptr_type),
                        ),
                        Instruction_load(var_out=payload, var=payload_ptr),
                        Instruction_call(
                            var_out=TypedVariable(f".retain_call_{variant.name}", Type("void")),
                            fn_name=retain_function_name(variant.type),
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
        return variant.type is not None and needs_retain(variant.type, self._aggregate_names)
