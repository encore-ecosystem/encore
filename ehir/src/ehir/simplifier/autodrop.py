from copy import deepcopy

from ehir.core.block import Block
from ehir.core.derectives import Derective_enum, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import EnumVariant, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    Instruction_br,
    Instruction_capprim,
    Instruction_cbr,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_hfree,
    Instruction_ieq,
    Instruction_load,
    Instruction_match,
    Instruction_ret,
    Instruction_store,
    Instruction_sub,
    MatchCase,
)
from ehir.core.primitives import Usize, Usize_t
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
        if is_box_struct(directive):
            blocks = self._generate_box_drop_blocks(directive, self_var)
        else:
            body = self._generate_struct_drop_body(directive, self_var)
            blocks = [Block(name="entry", body=body)]
        return Derective_fn(
            name=drop_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=blocks,
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

    def _generate_box_drop_blocks(self, directive: Derective_struct, self_var: TypedVariable) -> list[Block]:
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        owner_ptr = TypedVariable(".drop_owner_ptr", owner_ptr_type)
        ref_count_ptr = TypedVariable(".drop_ref_count_ptr", Pointer(Usize_t()))
        ref_count = TypedVariable(".drop_ref_count", Usize_t())
        one = TypedVariable(".drop_one", Usize_t())
        next_ref_count = TypedVariable(".drop_next_ref_count", Usize_t())
        is_last = TypedVariable(".drop_is_last", Usize_t(1))

        entry = Block(
            name="entry",
            body=[
                Instruction_getfield(var_out=owner_ptr, src=self_var, field=TypedVariable("1", owner_ptr_type)),
                Instruction_getfieldptr(
                    var_out=ref_count_ptr,
                    src=owner_ptr,
                    field=TypedVariable("1", Usize_t()),
                ),
                Instruction_load(var_out=ref_count, var=ref_count_ptr),
                Instruction_capprim(var_out=one, primitive=Usize(1)),
                Instruction_sub(var_out=next_ref_count, lhs=ref_count, rhs=one),
                Instruction_store(var_src=next_ref_count, var_dst=ref_count_ptr),
                Instruction_ieq(var_out=is_last, lhs=ref_count, rhs=one),
                Instruction_cbr(cond_var=is_last, true_br_label="cleanup", else_br_label="done"),
            ],
        )

        kind_ptr = TypedVariable(".drop_kind_ptr", Pointer(Usize_t(8)))
        kind = TypedVariable(".drop_kind", Usize_t(8))
        heap_kind = TypedVariable(".drop_heap_kind", Usize_t(8))
        is_heap = TypedVariable(".drop_is_heap", Usize_t(1))
        cleanup = Block(
            name="cleanup",
            body=[
                Instruction_getfieldptr(
                    var_out=kind_ptr,
                    src=owner_ptr,
                    field=TypedVariable("0", Usize_t(8)),
                ),
                Instruction_load(var_out=kind, var=kind_ptr),
                Instruction_capprim(var_out=heap_kind, primitive=Usize(0, size=8)),
                Instruction_ieq(var_out=is_heap, lhs=kind, rhs=heap_kind),
                Instruction_cbr(cond_var=is_heap, true_br_label="cleanup_heap", else_br_label="cleanup_non_heap"),
            ],
        )

        cleanup_heap_body = []
        ptr_var = TypedVariable(".drop_ptr", ptr_type)
        cleanup_heap_body.append(
            Instruction_getfield(var_out=ptr_var, src=self_var, field=TypedVariable("0", ptr_type))
        )
        pointee_type = ptr_type.pointee
        if needs_drop(pointee_type, self._aggregate_names):
            value_var = TypedVariable(".drop_value", pointee_type)
            cleanup_heap_body.append(Instruction_load(var_out=value_var, var=ptr_var))
        cleanup_heap_body.extend([Instruction_hfree(var=ptr_var), Instruction_hfree(var=owner_ptr), Instruction_ret(TypedVariable(".drop_ret", Type("void")))])
        cleanup_heap = Block(name="cleanup_heap", body=cleanup_heap_body)

        cleanup_non_heap = Block(
            name="cleanup_non_heap",
            body=[
                Instruction_hfree(var=owner_ptr),
                Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
            ],
        )

        done = Block(name="done", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))])
        return [entry, cleanup, cleanup_heap, cleanup_non_heap, done]

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
            payload_type = self._variant_payload_type(variant)
            assert payload_type is not None
            payload_ptr_type = Pointer(deepcopy(payload_type))
            payload_ptr = TypedVariable(f".drop_{variant.name}_ptr", payload_ptr_type)
            payload = TypedVariable(f".drop_{variant.name}", deepcopy(payload_type))
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
        payload_type = self._variant_payload_type(variant)
        return payload_type is not None and needs_drop(payload_type, self._aggregate_names)

    def _variant_payload_type(self, variant: EnumVariant) -> Type | None:
        if isinstance(variant, UnitLikeVariant):
            return None
        if isinstance(variant, TupleLikeVariant):
            if len(variant.types) == 0:
                return None
            return variant.types[0]
        raise TypeError(f"Unknown enum variant kind: {type(variant)}")
