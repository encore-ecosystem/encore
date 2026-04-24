from copy import deepcopy

from ehir.core.block import Block
from ehir.core.derectives import Derective_enum, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import EnumVariant
from ehir.core.instructions import (
    Instruction_getfield,
    Instruction_hfree,
    Instruction_load,
    Instruction_match,
    Instruction_ret,
    MatchCase,
)
from ehir.core.type import Pointer, Type
from ehir.core.variable import Parameter, TypedVariable
from ehir.simplifier.drop_helper import drop_function_name, is_box_struct, needs_drop


class AutoDropPass:
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
        existing_drop_names = {
            directive.name
            for directive in ast
            if isinstance(directive, Derective_fn)
        }

        generated: list[Derective] = []
        for directive in ast:
            if isinstance(directive, Derective_struct) and not directive.generics:
                fn_name = drop_function_name(Type(directive.name))
                if fn_name not in existing_drop_names:
                    generated.append(self._generate_struct_drop_fn(directive))
                    existing_drop_names.add(fn_name)
            elif isinstance(directive, Derective_enum) and not directive.generics:
                fn_name = drop_function_name(Type(directive.name))
                if fn_name not in existing_drop_names:
                    generated.append(self._generate_enum_drop_fn(directive))
                    existing_drop_names.add(fn_name)

        return ast + generated

    def _generate_struct_drop_fn(self, directive: Derective_struct) -> Derective_fn:
        self_type = Type(directive.name)
        self_var = TypedVariable("self", self_type)
        body = self._generate_struct_drop_body(directive, self_var)
        return Derective_fn(
            name=drop_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=[Block(name="entry", body=body)],
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_enum_drop_fn(self, directive: Derective_enum) -> Derective_fn:
        self_type = Type(directive.name)
        self_var = TypedVariable("self", self_type)
        blocks = self._generate_enum_drop_blocks(directive, self_var)
        return Derective_fn(
            name=drop_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=blocks,
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_struct_drop_body(self, directive: Derective_struct, self_var: TypedVariable):
        body = []
        if is_box_struct(directive):
            ptr_type = directive.params[0].type
            assert isinstance(ptr_type, Pointer)
            ptr_var = TypedVariable(".drop_ptr", ptr_type)
            body.append(
                Instruction_getfield(
                    var_out=ptr_var,
                    src=self_var,
                    field=TypedVariable("0", ptr_type),
                )
            )
            pointee_type = ptr_type.pointee
            if needs_drop(pointee_type, self._aggregate_names):
                value_var = TypedVariable(".drop_value", pointee_type)
                body.append(Instruction_load(var_out=value_var, var=ptr_var))
            body.append(Instruction_hfree(var=ptr_var))
        else:
            for index, field in enumerate(directive.params):
                if not needs_drop(field.type, self._aggregate_names):
                    continue
                field_var = TypedVariable(f".drop_{field.name}", deepcopy(field.type))
                body.append(
                    Instruction_getfield(
                        var_out=field_var,
                        src=self_var,
                        field=TypedVariable(str(index), deepcopy(field.type)),
                    )
                )

        body.append(Instruction_ret(TypedVariable(".drop_ret", Type("void"))))
        return body

    def _generate_enum_drop_blocks(self, directive: Derective_enum, self_var: TypedVariable) -> list[Block]:
        drop_variants = [
            (variant_index, variant)
            for variant_index, variant in enumerate(directive.variants, start=1)
            if self._variant_needs_drop(variant)
        ]
        if not drop_variants:
            return [Block(name="entry", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))])]

        entry = Block(
            name="entry",
            body=[
                Instruction_match(
                    cond_var=self_var,
                    default_case="done",
                    cases=[MatchCase(variant=variant.name, label=f"drop_{variant.name}") for _, variant in drop_variants],
                )
            ],
        )
        blocks = [entry]
        for variant_index, variant in drop_variants:
            assert variant.type is not None
            payload_ptr_type = Pointer(deepcopy(variant.type))
            payload_ptr = TypedVariable(f".drop_{variant.name}_ptr", payload_ptr_type)
            payload = TypedVariable(f".drop_{variant.name}", deepcopy(variant.type))
            blocks.append(
                Block(
                    name=f"drop_{variant.name}",
                    body=[
                        Instruction_getfield(
                            var_out=payload_ptr,
                            src=self_var,
                            field=TypedVariable(str(variant_index), payload_ptr_type),
                        ),
                        Instruction_load(var_out=payload, var=payload_ptr),
                        Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
                    ],
                )
            )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))]))
        return blocks

    def _variant_needs_drop(self, variant: EnumVariant) -> bool:
        return variant.type is not None and needs_drop(variant.type, self._aggregate_names)
