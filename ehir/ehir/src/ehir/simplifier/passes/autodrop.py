from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass

from ehir.resolver import EHIR_TypedModule
from ehir.core.block import Block
from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import EnumVariant, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    Instruction_add,
    Instruction_and,
    Instruction_br,
    Instruction_capprim,
    Instruction_cbr,
    Instruction_call,
    Instruction_callvoid,
    Instruction_drop,
    Instruction_gep,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_hfree,
    Instruction_ieq,
    Instruction_les,
    Instruction_load,
    Instruction_match,
    Instruction_neq,
    Instruction_pcast,
    Instruction_ret,
    Instruction_salloc,
    Instruction_store,
    Instruction_sub,
    MatchCase,
)
from ehir.core.primitives import Str, Usize, Usize_t
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.type import Pointer, Reference, Type, mangle_type_name
from ehir.core.variable import Parameter, StructField, TypedVariable
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.drop_helper import (
    collect_aggregate_names,
    drop_function_name,
    is_box_struct,
    is_dyn_type,
    needs_drop,
    reference_storage_struct,
)


@dataclass(frozen=True)
class _ChildEdge:
    field_index: int
    field_name: str
    field_type: Type
    child_type: Type
    variant_index: int | None = None
    variant_name: str | None = None


class AutoDropPass(SimplifierPass):
    def __init__(self, trace_cfree: bool = False):
        self._trace_cfree = trace_cfree

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
        existing_drop_names = {
            directive.name
            for directive in ast
            if isinstance(directive, Derective_fn)
        }

        generated: list[Derective] = []
        uses_str = self._uses_type(ast, Type("str"))
        str_drop_name = drop_function_name(Type("str"))
        if uses_str and "encore_str_drop" not in existing_drop_names:
            generated.append(
                Derective_extern_fn(
                    name="encore_str_drop",
                    params=[Parameter("value", Type("str"))],
                    ret_type=Type("void"),
                )
            )
            existing_drop_names.add("encore_str_drop")
        if uses_str and str_drop_name not in existing_drop_names:
            generated.append(self._generate_str_drop_fn())
            existing_drop_names.add(str_drop_name)

        for dyn_type in self._collect_dyn_types(ast):
            fn_name = drop_function_name(dyn_type)
            if fn_name in existing_drop_names:
                continue
            generated.append(
                Derective_extern_fn(
                    name=fn_name,
                    params=[Parameter("self", dyn_type)],
                    ret_type=Type("void"),
                )
            )
            existing_drop_names.add(fn_name)

        for directive in ast:
            if (
                isinstance(directive, Derective_struct)
                and not directive.generics
                and needs_drop(Type(directive.name), self._aggregate_names)
            ):
                fn_name = drop_function_name(Type(directive.name))
                if fn_name not in existing_drop_names:
                    generated.append(self._generate_struct_drop_fn(directive))
                    existing_drop_names.add(fn_name)
            elif (
                isinstance(directive, Derective_enum)
                and not directive.generics
                and needs_drop(Type(directive.name), self._aggregate_names)
            ):
                fn_name = drop_function_name(Type(directive.name))
                if fn_name not in existing_drop_names:
                    generated.append(self._generate_enum_drop_fn(directive))
                    existing_drop_names.add(fn_name)

        for concrete_type in self._collect_concrete_reference_storage_types(ast):
            fn_name = drop_function_name(concrete_type)
            if fn_name in existing_drop_names:
                continue
            concrete_struct, concrete_storage = self._concrete_reference_storage_structs(concrete_type)
            if concrete_struct is None or concrete_storage is None:
                continue
            generated.append(self._generate_reference_storage_drop_fn(concrete_type, concrete_struct, concrete_storage))
            existing_drop_names.add(fn_name)

        for concrete_type in self._collect_concrete_generic_aggregate_types(ast):
            fn_name = drop_function_name(concrete_type)
            if fn_name in existing_drop_names:
                continue
            if concrete_type.name in self._structs:
                concrete_struct = self._concrete_generic_struct(concrete_type)
                if concrete_struct is not None:
                    generated.append(self._generate_struct_drop_fn(concrete_struct, self_type=concrete_type))
                    existing_drop_names.add(fn_name)
            elif concrete_type.name in self._enums:
                concrete_enum = self._concrete_generic_enum(concrete_type)
                if concrete_enum is not None:
                    generated.append(self._generate_enum_drop_fn(concrete_enum, self_type=concrete_type))
                    existing_drop_names.add(fn_name)

        for directive in ast:
            if isinstance(directive, Derective_struct) and not directive.generics and is_box_struct(directive):
                for fn in self._generate_box_cfree_fns(directive):
                    if fn.name not in existing_drop_names:
                        generated.append(fn)
                        existing_drop_names.add(fn.name)

        return ast + generated

    def _generate_str_drop_fn(self) -> Derective_fn:
        self_type = Type("str")
        self_var = TypedVariable("self", self_type)
        return Derective_fn(
            name=drop_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=[
                Block(
                    name="entry",
                    body=[
                        Instruction_callvoid(
                            fn_name="encore_str_drop",
                            generics=[],
                            args=[deepcopy(self_var)],
                        ),
                        Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
                    ],
                )
            ],
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_struct_drop_fn(self, directive: Derective_struct, self_type: Type | None = None) -> Derective_fn:
        self_type = deepcopy(self_type) if self_type is not None else Type(directive.name)
        self_var = TypedVariable("self", self_type)
        reference_storage = reference_storage_struct(directive, self._structs)
        if reference_storage is not None:
            blocks = self._generate_reference_storage_drop_blocks(directive, reference_storage, self_var)
        elif is_box_struct(directive):
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

    def _generate_reference_storage_drop_fn(
        self,
        self_type: Type,
        directive: Derective_struct,
        storage: Derective_struct,
    ) -> Derective_fn:
        self_var = TypedVariable("self", self_type)
        return Derective_fn(
            name=drop_function_name(self_type),
            generics=[],
            params=[Parameter("self", self_type)],
            body=self._generate_reference_storage_drop_blocks(directive, storage, self_var),
            ret_type=Type("void"),
            attrs=("safe",),
        )

    def _generate_reference_storage_drop_blocks(
        self,
        directive: Derective_struct,
        storage: Derective_struct,
        self_var: TypedVariable,
    ) -> list[Block]:
        storage_ptr_type = directive.params[0].type
        assert isinstance(storage_ptr_type, Pointer)
        ptr_type = storage.params[1].type
        assert isinstance(ptr_type, Pointer)
        elem_type = ptr_type.pointee

        storage_ptr = TypedVariable(".drop_storage_ptr", storage_ptr_type)
        ref_count_ptr = TypedVariable(".drop_ref_count_ptr", Pointer(Usize_t()))
        ref_count = TypedVariable(".drop_ref_count", Usize_t())
        one = TypedVariable(".drop_one", Usize_t())
        next_ref_count = TypedVariable(".drop_next_ref_count", Usize_t())
        zero = TypedVariable(".drop_zero", Usize_t())
        is_zero = TypedVariable(".drop_is_zero", Type("u1"))

        entry = Block(
            name="entry",
            body=[
                Instruction_getfield(var_out=storage_ptr, src=self_var, field=TypedVariable("0", storage_ptr_type)),
                Instruction_getfieldptr(
                    var_out=ref_count_ptr,
                    src=storage_ptr,
                    field=TypedVariable("0", storage.params[0].type),
                ),
                Instruction_load(var_out=ref_count, var=ref_count_ptr),
                Instruction_capprim(var_out=one, primitive=Usize(1)),
                Instruction_sub(var_out=next_ref_count, lhs=ref_count, rhs=one),
                Instruction_store(var_src=next_ref_count, var_dst=ref_count_ptr),
                Instruction_capprim(var_out=zero, primitive=Usize(0)),
                Instruction_ieq(var_out=is_zero, lhs=next_ref_count, rhs=zero),
                Instruction_cbr(cond_var=is_zero, true_br_label="release", else_br_label="done"),
            ],
        )

        data_ptr = TypedVariable(".drop_data_ptr", ptr_type)
        release_body = [
            Instruction_getfield(var_out=data_ptr, src=storage_ptr, field=TypedVariable("1", ptr_type)),
        ]
        if needs_drop(elem_type, self._aggregate_names):
            len_var = TypedVariable(".drop_len", Usize_t())
            idx_ptr = TypedVariable(".drop_idx_ptr", Pointer(Usize_t()))
            idx_zero = TypedVariable(".drop_idx_zero", Usize_t())
            release_body.extend(
                [
                    Instruction_getfield(var_out=len_var, src=storage_ptr, field=TypedVariable("2", Usize_t())),
                    Instruction_salloc(var_out=idx_ptr, type=Usize_t()),
                    Instruction_capprim(var_out=idx_zero, primitive=Usize(0)),
                    Instruction_store(var_src=idx_zero, var_dst=idx_ptr),
                    Instruction_br("drop_elements"),
                ]
            )
            idx = TypedVariable(".drop_idx", Usize_t())
            keep_going = TypedVariable(".drop_keep_going", Type("u1"))
            elem_ptr = TypedVariable(".drop_elem_ptr", Pointer(elem_type))
            elem = TypedVariable(".drop_elem", elem_type)
            elem_one = TypedVariable(".drop_elem_one", Usize_t())
            next_idx = TypedVariable(".drop_next_idx", Usize_t())
            loop = Block(
                name="drop_elements",
                body=[
                    Instruction_load(var_out=idx, var=idx_ptr),
                    Instruction_les(var_out=keep_going, lhs=idx, rhs=len_var),
                    Instruction_cbr(cond_var=keep_going, true_br_label="drop_element", else_br_label="free_storage"),
                ],
            )
            drop_element = Block(
                name="drop_element",
                body=[
                    Instruction_gep(var_out=elem_ptr, var=data_ptr, offset=idx),
                    Instruction_load(var_out=elem, var=elem_ptr),
                    Instruction_drop(var=elem),
                    Instruction_capprim(var_out=elem_one, primitive=Usize(1)),
                    Instruction_add(var_out=next_idx, lhs=idx, rhs=elem_one),
                    Instruction_store(var_src=next_idx, var_dst=idx_ptr),
                    Instruction_br("drop_elements"),
                ],
            )
            return [
                entry,
                Block(name="release", body=release_body),
                loop,
                drop_element,
                Block(
                    name="free_storage",
                    body=[
                        Instruction_hfree(var=data_ptr),
                        Instruction_hfree(var=storage_ptr),
                        Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
                    ],
                ),
                Block(name="done", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))]),
            ]

        release_body.extend(
            [
                Instruction_hfree(var=data_ptr),
                Instruction_hfree(var=storage_ptr),
                Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
            ]
        )
        return [
            entry,
            Block(name="release", body=release_body),
            Block(name="done", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))]),
        ]

    def _generate_enum_drop_fn(self, directive: Derective_enum, self_type: Type | None = None) -> Derective_fn:
        self_type = deepcopy(self_type) if self_type is not None else Type(directive.name)
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
                body.append(
                    Instruction_call(
                        var_out=TypedVariable(f".drop_call_{field.name}", Type("void")),
                        fn_name=drop_function_name(field.type),
                        generics=[],
                        args=[deepcopy(field_var)],
                    )
                )

        body.append(Instruction_ret(TypedVariable(".drop_ret", Type("void"))))
        return body

    def _generate_box_drop_blocks(self, directive: Derective_struct, self_var: TypedVariable) -> list[Block]:
        return [
            Block(
                name="entry",
                body=[
                    Instruction_call(
                        var_out=TypedVariable(".drop_cfree", Type("void")),
                        fn_name=self._cfree_name(Type(directive.name)),
                        generics=[],
                        args=[deepcopy(self_var)],
                    ),
                    Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
                ],
            )
        ]

    def _generate_box_cfree_fns(self, directive: Derective_struct) -> list[Derective_fn]:
        ptr_type = directive.params[0].type
        assert isinstance(ptr_type, Pointer)
        box_type = Type(directive.name)
        edges = self._child_edges(ptr_type.pointee)
        return [
            self._generate_cfree_initiator_fn(directive, box_type),
            self._generate_cfree_pass0_fn(directive, box_type, edges),
            self._generate_cfree_pass1_fn(directive, box_type, edges),
            self._generate_cfree_mark_outer_fn(directive, box_type, edges),
            self._generate_cfree_pass2_fn(directive, box_type, edges),
            self._generate_cfree_pass3_fn(directive, box_type, edges),
        ]

    def _generate_cfree_initiator_fn(self, directive: Derective_struct, box_type: Type) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        owner_ptr_type = directive.params[1].type
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree")
        self._emit_ref_count_add(entry_body, owner_ptr, -1, ".cfree_root")
        entry_body.extend(
            [
                Instruction_call(
                    var_out=TypedVariable(".cfree_pass0_ret", Type("void")),
                    fn_name=self._cfree_pass_name(box_type, 0),
                    generics=[],
                    args=[deepcopy(self_var)],
                ),
                Instruction_call(
                    var_out=TypedVariable(".cfree_pass1_ret", Type("void")),
                    fn_name=self._cfree_pass_name(box_type, 1),
                    generics=[],
                    args=[deepcopy(self_var)],
                ),
                Instruction_call(
                    var_out=TypedVariable(".cfree_pass2_ret", Type("void")),
                    fn_name=self._cfree_pass_name(box_type, 2),
                    generics=[],
                    args=[deepcopy(self_var)],
                ),
            ]
        )
        root_candidate = self._emit_free_candidate(entry_body, owner_ptr, ".cfree_root_candidate")
        entry_body.append(
            Instruction_cbr(
                cond_var=root_candidate,
                true_br_label="break_root",
                else_br_label="sweep",
            )
        )

        break_root_body: list = []
        zero = self._emit_usize_const(break_root_body, 0, ".cfree_root_pending_zero")
        root_ref_ptr = self._emit_owner_field_ptr(break_root_body, owner_ptr, 1, Usize_t(), ".cfree_root_pending")
        break_root_body.extend(
            [
                Instruction_store(var_src=zero, var_dst=root_ref_ptr),
                Instruction_br(label="sweep"),
            ]
        )

        sweep_body: list = [
            Instruction_call(
                var_out=TypedVariable(".cfree_pass3_ret", Type("void")),
                fn_name=self._cfree_pass_name(box_type, 3),
                generics=[],
                args=[deepcopy(self_var)],
            ),
            Instruction_ret(TypedVariable(".cfree_ret", Type("void"))),
        ]
        return self._cfree_fn(
            self._cfree_name(box_type),
            box_type,
            [
                Block(name="entry", body=entry_body),
                Block(name="break_root", body=break_root_body),
                Block(name="sweep", body=sweep_body),
            ],
        )

    def _generate_cfree_mark_outer_fn(
        self,
        directive: Derective_struct,
        box_type: Type,
        edges: list[_ChildEdge],
    ) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree_outer")
        outer_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 3, Usize_t(1), ".cfree_outer")
        outer = TypedVariable(".cfree_outer", Usize_t(1))
        entry_body.extend(
            [
                Instruction_load(var_out=outer, var=outer_ptr),
                Instruction_cbr(cond_var=outer, true_br_label="done", else_br_label="visit"),
            ]
        )

        visit_body: list = []
        true_var = self._emit_bool_const(visit_body, True, ".cfree_outer_true")
        visit_body.append(Instruction_store(var_src=true_var, var_dst=outer_ptr))
        value = self._emit_box_value(visit_body, self_var, ptr_type, ".cfree_outer_value")

        blocks = [Block(name="entry", body=entry_body)]
        blocks.extend(
            self._edge_chain_blocks(
                start_name="visit",
                start_body=visit_body,
                value_var=value,
                edges=edges,
                op=lambda body, child, prefix: self._emit_mark_outer_child(body, child, prefix),
                final=Instruction_br(label="done"),
                prefix=".cfree_outer",
            )
        )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".cfree_outer_ret", Type("void")))]))
        return self._cfree_fn(self._cfree_mark_outer_name(box_type), box_type, blocks)

    def _generate_cfree_pass0_fn(
        self,
        directive: Derective_struct,
        box_type: Type,
        edges: list[_ChildEdge],
    ) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree0")
        inner_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 2, Usize_t(1), ".cfree0_inner")
        inner = TypedVariable(".cfree0_inner", Usize_t(1))
        entry_body.extend(
            [
                Instruction_load(var_out=inner, var=inner_ptr),
                Instruction_cbr(cond_var=inner, true_br_label="done", else_br_label="visit"),
            ]
        )

        visit_body: list = []
        true_var = self._emit_bool_const(visit_body, True, ".cfree0_true")
        visit_body.append(Instruction_store(var_src=true_var, var_dst=inner_ptr))
        value = self._emit_box_value(visit_body, self_var, ptr_type, ".cfree0_value")

        blocks = [Block(name="entry", body=entry_body)]
        blocks.extend(
            self._edge_chain_blocks(
                start_name="visit",
                start_body=visit_body,
                value_var=value,
                edges=edges,
                op=lambda body, child, prefix: self._emit_pass0_child(body, child, prefix),
                final=Instruction_br(label="done"),
                prefix=".cfree0",
            )
        )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".cfree0_ret", Type("void")))]))
        return self._cfree_fn(self._cfree_pass_name(box_type, 0), box_type, blocks)

    def _generate_cfree_pass1_fn(
        self,
        directive: Derective_struct,
        box_type: Type,
        edges: list[_ChildEdge],
    ) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree1")
        visited_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 4, Usize_t(1), ".cfree1_visited")
        visited = TypedVariable(".cfree1_visited", Usize_t(1))
        entry_body.extend(
            [
                Instruction_load(var_out=visited, var=visited_ptr),
                Instruction_cbr(cond_var=visited, true_br_label="done", else_br_label="visit"),
            ]
        )

        visit_body: list = []
        ref_count = self._emit_ref_count_load(visit_body, owner_ptr, ".cfree1")
        zero = self._emit_usize_const(visit_body, 0, ".cfree1_zero")
        has_outer_count = TypedVariable(".cfree1_has_outer_count", Usize_t(1))
        true_var = self._emit_bool_const(visit_body, True, ".cfree1_true")
        visit_body.extend(
            [
                Instruction_neq(var_out=has_outer_count, lhs=ref_count, rhs=zero),
                Instruction_store(var_src=true_var, var_dst=visited_ptr),
                Instruction_cbr(cond_var=has_outer_count, true_br_label="mark_outer", else_br_label="scan"),
            ]
        )

        mark_outer_body: list = [
            Instruction_call(
                var_out=TypedVariable(".cfree1_mark_outer_ret", Type("void")),
                fn_name=self._cfree_mark_outer_name(box_type),
                generics=[],
                args=[deepcopy(self_var)],
            ),
            Instruction_br(label="scan"),
        ]

        value_scan_body: list = []
        value_scan = self._emit_box_value(value_scan_body, self_var, ptr_type, ".cfree1_scan_value")
        scan_blocks = self._edge_chain_blocks(
            start_name="scan",
            start_body=value_scan_body,
            value_var=value_scan,
            edges=edges,
            op=lambda body, child, prefix: self._emit_pass_call(body, child, 1, prefix),
            final=Instruction_br(label="done"),
            prefix=".cfree1_scan",
        )

        blocks = [
            Block(name="entry", body=entry_body),
            Block(name="visit", body=visit_body),
            Block(name="mark_outer", body=mark_outer_body),
        ]
        blocks.extend(scan_blocks)
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".cfree1_ret", Type("void")))]))
        return self._cfree_fn(self._cfree_pass_name(box_type, 1), box_type, blocks)

    def _generate_cfree_pass2_fn(
        self,
        directive: Derective_struct,
        box_type: Type,
        edges: list[_ChildEdge],
    ) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree2")
        inner_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 2, Usize_t(1), ".cfree2_inner")
        inner = TypedVariable(".cfree2_inner", Usize_t(1))
        deal_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 5, Usize_t(1), ".cfree2_deal")
        deal = TypedVariable(".cfree2_deal", Usize_t(1))
        entry_body.extend(
            [
                Instruction_load(var_out=inner, var=inner_ptr),
                Instruction_cbr(cond_var=inner, true_br_label="check_deal", else_br_label="done"),
            ]
        )
        check_deal_body: list = [
            Instruction_load(var_out=deal, var=deal_ptr),
            Instruction_cbr(cond_var=deal, true_br_label="done", else_br_label="visit"),
        ]

        visit_body: list = []
        true_var = self._emit_bool_const(visit_body, True, ".cfree2_true")
        visit_body.append(Instruction_store(var_src=true_var, var_dst=deal_ptr))
        self_candidate = self._emit_free_candidate(visit_body, owner_ptr, ".cfree2_self_candidate")
        value = self._emit_box_value(visit_body, self_var, ptr_type, ".cfree2_value")

        blocks = [Block(name="entry", body=entry_body), Block(name="check_deal", body=check_deal_body)]
        blocks.extend(
            self._edge_chain_blocks(
                start_name="visit",
                start_body=visit_body,
                value_var=value,
                edges=edges,
                op=lambda body, child, prefix: self._emit_count_free_edge(body, child, self_candidate, prefix),
                final=Instruction_br(label="done"),
                prefix=".cfree2_count",
            )
        )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".cfree2_ret", Type("void")))]))
        return self._cfree_fn(self._cfree_pass_name(box_type, 2), box_type, blocks)

    def _generate_cfree_pass3_fn(
        self,
        directive: Derective_struct,
        box_type: Type,
        edges: list[_ChildEdge],
    ) -> Derective_fn:
        self_var = TypedVariable("self", box_type)
        ptr_type = directive.params[0].type
        owner_ptr_type = directive.params[1].type
        assert isinstance(ptr_type, Pointer)
        assert isinstance(owner_ptr_type, Pointer)

        entry_body: list = []
        owner_ptr = self._emit_owner_ptr(entry_body, self_var, owner_ptr_type, ".cfree3")
        inner_ptr = self._emit_owner_field_ptr(entry_body, owner_ptr, 2, Usize_t(1), ".cfree3_inner")
        inner = TypedVariable(".cfree3_inner", Usize_t(1))
        entry_body.extend(
            [
                Instruction_load(var_out=inner, var=inner_ptr),
                Instruction_cbr(cond_var=inner, true_br_label="decide", else_br_label="maybe_finalize"),
            ]
        )

        maybe_finalize_body: list = []
        alive = self._emit_candidate_alive(maybe_finalize_body, owner_ptr, ".cfree3_finalize_alive")
        active_ptr = self._emit_owner_field_ptr(maybe_finalize_body, owner_ptr, 4, Usize_t(1), ".cfree3_finalize_active")
        active = TypedVariable(".cfree3_finalize_active", Usize_t(1))
        finalize_false = self._emit_bool_const(maybe_finalize_body, False, ".cfree3_finalize_false")
        inactive = TypedVariable(".cfree3_finalize_inactive", Usize_t(1))
        can_check_pending = TypedVariable(".cfree3_finalize_can_check_pending", Usize_t(1))
        maybe_finalize_body.extend(
            [
                Instruction_load(var_out=active, var=active_ptr),
                Instruction_ieq(var_out=inactive, lhs=active, rhs=finalize_false),
                Instruction_and(var_out=can_check_pending, lhs=alive, rhs=inactive),
                Instruction_cbr(cond_var=can_check_pending, true_br_label="finalize_pending", else_br_label="done"),
            ]
        )

        finalize_pending_body: list = []
        finalize_pending = self._emit_ref_count_load(finalize_pending_body, owner_ptr, ".cfree3_finalize_pending")
        finalize_zero = self._emit_usize_const(finalize_pending_body, 0, ".cfree3_finalize_zero")
        finalize_pending_zero = TypedVariable(".cfree3_finalize_pending_zero", Usize_t(1))
        finalize_pending_body.extend(
            [
                Instruction_ieq(var_out=finalize_pending_zero, lhs=finalize_pending, rhs=finalize_zero),
                Instruction_cbr(cond_var=finalize_pending_zero, true_br_label="free", else_br_label="done"),
            ]
        )

        decide_body: list = []
        candidate = self._emit_free_candidate(decide_body, owner_ptr, ".cfree3_candidate")
        decide_body.append(Instruction_cbr(cond_var=candidate, true_br_label="free_visit", else_br_label="survive"))

        free_visit_body: list = []
        false_var = self._emit_bool_const(free_visit_body, False, ".cfree3_free_false")
        true_var = self._emit_bool_const(free_visit_body, True, ".cfree3_free_true")
        active_ptr = self._emit_owner_field_ptr(free_visit_body, owner_ptr, 4, Usize_t(1), ".cfree3_free_active")
        free_visit_body.append(Instruction_store(var_src=false_var, var_dst=inner_ptr))
        free_visit_body.append(Instruction_store(var_src=true_var, var_dst=active_ptr))
        value = self._emit_box_value(free_visit_body, self_var, ptr_type, ".cfree3_free_value")

        blocks = [
            Block(name="entry", body=entry_body),
            Block(name="maybe_finalize", body=maybe_finalize_body),
            Block(name="finalize_pending", body=finalize_pending_body),
            Block(name="decide", body=decide_body),
        ]
        blocks.extend(
            self._edge_chain_blocks(
                start_name="free_visit",
                start_body=free_visit_body,
                value_var=value,
                edges=edges,
                op=lambda body, child, prefix: self._emit_sweep_child_from_free(body, child, prefix),
                final=Instruction_br(label="finish_free_candidate"),
                prefix=".cfree3_free",
            )
        )

        finish_free_body: list = []
        finish_false = self._emit_bool_const(finish_free_body, False, ".cfree3_finish_false")
        finish_active_ptr = self._emit_owner_field_ptr(finish_free_body, owner_ptr, 4, Usize_t(1), ".cfree3_finish_active")
        finish_free_body.append(Instruction_store(var_src=finish_false, var_dst=finish_active_ptr))
        pending = self._emit_ref_count_load(finish_free_body, owner_ptr, ".cfree3_finish_pending")
        zero = self._emit_usize_const(finish_free_body, 0, ".cfree3_finish_zero")
        pending_zero = TypedVariable(".cfree3_finish_pending_zero", Usize_t(1))
        finish_free_body.extend(
            [
                Instruction_ieq(var_out=pending_zero, lhs=pending, rhs=zero),
                Instruction_cbr(cond_var=pending_zero, true_br_label="free", else_br_label="done"),
            ]
        )

        free_body: list = []
        kind_ptr = self._emit_owner_field_ptr(free_body, owner_ptr, 0, Usize_t(8), ".cfree3_kind")
        kind = TypedVariable(".cfree3_kind", Usize_t(8))
        heap_kind = self._emit_u8_const(free_body, 0, ".cfree3_heap_kind")
        is_heap = TypedVariable(".cfree3_is_heap", Usize_t(1))
        free_body.extend(
            [
                Instruction_load(var_out=kind, var=kind_ptr),
                Instruction_ieq(var_out=is_heap, lhs=kind, rhs=heap_kind),
                Instruction_cbr(cond_var=is_heap, true_br_label="free_heap", else_br_label="free_owner"),
            ]
        )

        free_heap_body: list = []
        ptr = self._emit_box_ptr(free_heap_body, self_var, ptr_type, ".cfree3_free")
        if self._trace_cfree:
            fd = TypedVariable(".cfree3_trace_heap_fd", Type("i32"))
            free_heap_body.append(Instruction_capprim(var_out=fd, primitive=Usize(2, size=32)))
            self._emit_cfree_trace_payload_writes(
                free_heap_body,
                box_type_name=self_var.type.name,
                ptr_type=ptr_type,
                ptr_var=ptr,
                fd=fd,
                prefix=".cfree3_trace_heap",
            )
        free_heap_body.extend([Instruction_hfree(var=ptr), Instruction_br(label="free_owner")])

        free_owner_body: list = []
        if self._trace_cfree:
            msg = self._emit_debug_message(
                free_owner_body,
                f"[cfree] free owner header of {self_var.type.name}\n",
                ".cfree3_trace_owner",
            )
            fd = TypedVariable(".cfree3_trace_owner_fd", Type("i32"))
            free_owner_body.append(Instruction_capprim(var_out=fd, primitive=Usize(2, size=32)))
            free_owner_body.append(
                Instruction_call(
                    var_out=TypedVariable(".cfree3_trace_owner_out", Type("i32")),
                    fn_name="encore_io_write",
                    generics=[],
                    args=[fd, msg],
                )
            )
        free_owner_body.extend(
            [
                Instruction_hfree(var=owner_ptr),
                Instruction_br(label="done"),
            ]
        )

        survive_body: list = []
        survive_false = self._emit_bool_const(survive_body, False, ".cfree3_survive_false")
        for index, name in ((2, "inner"), (3, "outer"), (4, "visited"), (5, "deal")):
            field_ptr = self._emit_owner_field_ptr(survive_body, owner_ptr, index, Usize_t(1), f".cfree3_survive_{name}")
            survive_body.append(Instruction_store(var_src=survive_false, var_dst=field_ptr))
        survive_value = self._emit_box_value(survive_body, self_var, ptr_type, ".cfree3_survive_value")

        blocks.extend(
            [
                Block(name="finish_free_candidate", body=finish_free_body),
                Block(name="free", body=free_body),
                Block(name="free_heap", body=free_heap_body),
                Block(name="free_owner", body=free_owner_body),
            ]
        )
        blocks.extend(
            self._edge_chain_blocks(
                start_name="survive",
                start_body=survive_body,
                value_var=survive_value,
                edges=edges,
                op=lambda body, child, prefix: self._emit_sweep_child_from_survivor(body, child, prefix),
                final=Instruction_br(label="done"),
                prefix=".cfree3_survive",
            )
        )

        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".cfree3_ret", Type("void")))]))
        return self._cfree_fn(self._cfree_pass_name(box_type, 3), box_type, blocks)

    def _edge_chain_blocks(
        self,
        *,
        start_name: str,
        start_body: list,
        value_var: TypedVariable,
        edges: list[_ChildEdge],
        op,
        final,
        prefix: str,
    ) -> list[Block]:
        blocks: list[Block] = []
        current_name = start_name
        current_body = start_body
        for index, edge in enumerate(edges):
            field_var = TypedVariable(f"{prefix}_{index}_{edge.field_name}", deepcopy(edge.field_type))
            current_body.append(
                Instruction_getfield(
                    var_out=field_var,
                    src=value_var,
                    field=TypedVariable(str(edge.field_index), deepcopy(edge.field_type)),
                )
            )
            if edge.variant_index is None:
                op(current_body, field_var, f"{prefix}_{index}")
                continue

            some_label = f"{current_name}_{edge.field_name}_some"
            next_label = f"{current_name}_{edge.field_name}_next"
            current_body.append(
                Instruction_match(
                    cond_var=field_var,
                    default_case=next_label,
                    cases=[MatchCase(variant=edge.variant_name or "Some", label=some_label)],
                )
            )
            blocks.append(Block(name=current_name, body=current_body))

            child = TypedVariable(f"{prefix}_{index}_{edge.field_name}_child", deepcopy(edge.child_type))
            some_body: list = [
                Instruction_getfield(
                    var_out=child,
                    src=field_var,
                    field=TypedVariable(str(edge.variant_index), deepcopy(edge.child_type)),
                )
            ]
            op(some_body, child, f"{prefix}_{index}_some")
            some_body.append(Instruction_br(label=next_label))
            blocks.append(Block(name=some_label, body=some_body))

            current_name = next_label
            current_body = []

        current_body.append(final)
        blocks.append(Block(name=current_name, body=current_body))
        return blocks

    def _emit_debug_message(self, body: list, text: str, name: str) -> TypedVariable:
        msg = TypedVariable(name, Type("str"))
        body.append(Instruction_capprim(var_out=msg, primitive=Str(text)))
        return msg

    def _emit_trace_write(self, body: list, fd: TypedVariable, text: TypedVariable, name: str) -> None:
        body.append(
            Instruction_call(
                var_out=TypedVariable(name, Type("i32")),
                fn_name="encore_io_write",
                generics=[],
                args=[fd, text],
            )
        )

    def _emit_cfree_trace_payload_writes(
        self,
        body: list,
        *,
        box_type_name: str,
        ptr_type: Pointer,
        ptr_var: TypedVariable,
        fd: TypedVariable,
        prefix: str,
    ) -> None:
        base = self._emit_debug_message(body, f"[cfree] free heap payload of {box_type_name}", f"{prefix}_base")
        pointee = ptr_type.pointee
        struct_decl = self._structs.get(pointee.name)
        if struct_decl is None:
            msg = self._emit_debug_message(body, f"[cfree] free heap payload of {box_type_name}\n", prefix)
            self._emit_trace_write(body, fd, msg, f"{prefix}_out")
            return

        id_index = None
        for idx, field in enumerate(struct_decl.params):
            if field.name == "id" and field.type.name == "str":
                id_index = idx
                break
        if id_index is None:
            msg = self._emit_debug_message(body, f"[cfree] free heap payload of {box_type_name}\n", prefix)
            self._emit_trace_write(body, fd, msg, f"{prefix}_out")
            return

        payload = TypedVariable(f"{prefix}_payload", deepcopy(pointee))
        id_value = TypedVariable(f"{prefix}_id", Type("str"))
        sep = self._emit_debug_message(body, " id=", f"{prefix}_sep")
        body.append(Instruction_load(var_out=payload, var=ptr_var))
        body.append(
            Instruction_getfield(
                var_out=id_value,
                src=payload,
                field=TypedVariable(str(id_index), Type("str")),
            )
        )
        nl = self._emit_debug_message(body, "\n", f"{prefix}_nl")
        self._emit_trace_write(body, fd, base, f"{prefix}_base_out")
        self._emit_trace_write(body, fd, sep, f"{prefix}_sep_out")
        self._emit_trace_write(body, fd, id_value, f"{prefix}_id_out")
        self._emit_trace_write(body, fd, nl, f"{prefix}_nl_out")

    def _emit_pass0_child(self, body: list, child: TypedVariable, prefix: str) -> None:
        self._emit_ref_count_add_for_box(body, child, -1, prefix)
        self._emit_pass_call(body, child, 0, prefix)

    def _emit_mark_outer_child(self, body: list, child: TypedVariable, prefix: str) -> None:
        assert child.type is not None
        body.append(
            Instruction_call(
                var_out=TypedVariable(f"{prefix}_mark_outer_ret", Type("void")),
                fn_name=self._cfree_mark_outer_name(child.type),
                generics=[],
                args=[deepcopy(child)],
            )
        )

    def _emit_count_free_edge(
        self,
        body: list,
        child: TypedVariable,
        self_candidate: TypedVariable,
        prefix: str,
    ) -> None:
        owner_ptr_type = self._box_owner_ptr_type(child.type)
        child_owner = self._emit_owner_ptr(body, child, owner_ptr_type, f"{prefix}_owner")
        child_candidate = self._emit_free_candidate(body, child_owner, f"{prefix}_candidate")
        edge_counts = TypedVariable(f"{prefix}_edge_counts", Usize_t(1))
        body.append(Instruction_and(var_out=edge_counts, lhs=self_candidate, rhs=child_candidate))
        delta = self._emit_bool_to_usize(body, edge_counts, f"{prefix}_delta")
        self._emit_ref_count_add_delta(body, child_owner, delta, prefix, subtract=False)
        self._emit_pass_call(body, child, 2, prefix)

    def _emit_sweep_child_from_free(self, body: list, child: TypedVariable, prefix: str) -> None:
        owner_ptr_type = self._box_owner_ptr_type(child.type)
        child_owner = self._emit_owner_ptr(body, child, owner_ptr_type, f"{prefix}_owner")
        child_candidate = self._emit_candidate_alive(body, child_owner, f"{prefix}_candidate")
        self._emit_ref_count_sub_if_pending(body, child_owner, child_candidate, prefix)
        self._emit_pass_call(body, child, 3, prefix)

    def _emit_sweep_child_from_survivor(self, body: list, child: TypedVariable, prefix: str) -> None:
        self._emit_ref_count_add_for_box(body, child, 1, prefix)
        self._emit_pass_call(body, child, 3, prefix)

    def _emit_pass1_propagate_child(self, body: list, child: TypedVariable, prefix: str) -> None:
        owner_ptr_type = self._box_owner_ptr_type(child.type)
        owner_ptr = self._emit_owner_ptr(body, child, owner_ptr_type, f"{prefix}_owner")
        outer_ptr = self._emit_owner_field_ptr(body, owner_ptr, 3, Usize_t(1), f"{prefix}_outer")
        true_var = self._emit_bool_const(body, True, f"{prefix}_true")
        body.append(Instruction_store(var_src=true_var, var_dst=outer_ptr))
        self._emit_pass_call(body, child, 1, prefix)

    def _emit_cleanup_child(self, body: list, child: TypedVariable, prefix: str) -> None:
        assert child.type is not None
        body.append(
            Instruction_call(
                var_out=TypedVariable(f"{prefix}_cleanup_ret", Type("void")),
                fn_name=self._cfree_cleanup_name(child.type),
                generics=[],
                args=[deepcopy(child)],
            )
        )

    def _emit_pass_call(self, body: list, child: TypedVariable, pass_index: int, prefix: str) -> None:
        assert child.type is not None
        body.append(
            Instruction_call(
                var_out=TypedVariable(f"{prefix}_pass{pass_index}_ret", Type("void")),
                fn_name=self._cfree_pass_name(child.type, pass_index),
                generics=[],
                args=[deepcopy(child)],
            )
        )

    def _emit_ref_count_add_for_box(self, body: list, box_var: TypedVariable, delta: int, prefix: str) -> None:
        owner_ptr_type = self._box_owner_ptr_type(box_var.type)
        owner_ptr = self._emit_owner_ptr(body, box_var, owner_ptr_type, f"{prefix}_owner")
        self._emit_ref_count_add(body, owner_ptr, delta, prefix)

    def _emit_ref_count_add(self, body: list, owner_ptr: TypedVariable, delta: int, prefix: str) -> None:
        ref_ptr = self._emit_owner_field_ptr(body, owner_ptr, 1, Usize_t(), f"{prefix}_ref")
        ref_count = TypedVariable(f"{prefix}_ref_count", Usize_t())
        one = self._emit_usize_const(body, 1, f"{prefix}_one")
        next_count = TypedVariable(f"{prefix}_next_ref_count", Usize_t())
        body.append(Instruction_load(var_out=ref_count, var=ref_ptr))
        if delta < 0:
            body.append(Instruction_sub(var_out=next_count, lhs=ref_count, rhs=one))
        else:
            body.append(Instruction_add(var_out=next_count, lhs=ref_count, rhs=one))
        body.append(Instruction_store(var_src=next_count, var_dst=ref_ptr))

    def _emit_ref_count_add_delta(
        self,
        body: list,
        owner_ptr: TypedVariable,
        delta: TypedVariable,
        prefix: str,
        *,
        subtract: bool,
    ) -> None:
        ref_ptr = self._emit_owner_field_ptr(body, owner_ptr, 1, Usize_t(), f"{prefix}_ref")
        ref_count = TypedVariable(f"{prefix}_ref_count", Usize_t())
        next_count = TypedVariable(f"{prefix}_next_ref_count", Usize_t())
        body.append(Instruction_load(var_out=ref_count, var=ref_ptr))
        if subtract:
            body.append(Instruction_sub(var_out=next_count, lhs=ref_count, rhs=delta))
        else:
            body.append(Instruction_add(var_out=next_count, lhs=ref_count, rhs=delta))
        body.append(Instruction_store(var_src=next_count, var_dst=ref_ptr))

    def _emit_ref_count_sub_if_pending(
        self,
        body: list,
        owner_ptr: TypedVariable,
        should_subtract: TypedVariable,
        prefix: str,
    ) -> None:
        ref_ptr = self._emit_owner_field_ptr(body, owner_ptr, 1, Usize_t(), f"{prefix}_ref")
        ref_count = TypedVariable(f"{prefix}_ref_count", Usize_t())
        zero = self._emit_usize_const(body, 0, f"{prefix}_zero")
        has_pending = TypedVariable(f"{prefix}_has_pending", Usize_t(1))
        do_subtract = TypedVariable(f"{prefix}_do_subtract", Usize_t(1))
        delta = TypedVariable(f"{prefix}_delta", Usize_t())
        next_count = TypedVariable(f"{prefix}_next_ref_count", Usize_t())
        body.extend(
            [
                Instruction_load(var_out=ref_count, var=ref_ptr),
                Instruction_neq(var_out=has_pending, lhs=ref_count, rhs=zero),
                Instruction_and(var_out=do_subtract, lhs=should_subtract, rhs=has_pending),
                Instruction_pcast(var_out=delta, var=do_subtract, type=Usize_t()),
                Instruction_sub(var_out=next_count, lhs=ref_count, rhs=delta),
                Instruction_store(var_src=next_count, var_dst=ref_ptr),
            ]
        )

    def _emit_ref_count_load(self, body: list, owner_ptr: TypedVariable, prefix: str) -> TypedVariable:
        ref_ptr = self._emit_owner_field_ptr(body, owner_ptr, 1, Usize_t(), f"{prefix}_ref")
        ref_count = TypedVariable(f"{prefix}_ref_count", Usize_t())
        body.append(Instruction_load(var_out=ref_count, var=ref_ptr))
        return ref_count

    def _emit_free_candidate(self, body: list, owner_ptr: TypedVariable, prefix: str) -> TypedVariable:
        inner_ptr = self._emit_owner_field_ptr(body, owner_ptr, 2, Usize_t(1), f"{prefix}_inner")
        outer_ptr = self._emit_owner_field_ptr(body, owner_ptr, 3, Usize_t(1), f"{prefix}_outer")
        inner = TypedVariable(f"{prefix}_inner", Usize_t(1))
        outer = TypedVariable(f"{prefix}_outer", Usize_t(1))
        false_var = self._emit_bool_const(body, False, f"{prefix}_false")
        not_outer = TypedVariable(f"{prefix}_not_outer", Usize_t(1))
        candidate = TypedVariable(prefix, Usize_t(1))
        body.extend(
            [
                Instruction_load(var_out=inner, var=inner_ptr),
                Instruction_load(var_out=outer, var=outer_ptr),
                Instruction_ieq(var_out=not_outer, lhs=outer, rhs=false_var),
                Instruction_and(var_out=candidate, lhs=inner, rhs=not_outer),
            ]
        )
        return candidate

    def _emit_candidate_alive(self, body: list, owner_ptr: TypedVariable, prefix: str) -> TypedVariable:
        outer_ptr = self._emit_owner_field_ptr(body, owner_ptr, 3, Usize_t(1), f"{prefix}_outer")
        deal_ptr = self._emit_owner_field_ptr(body, owner_ptr, 5, Usize_t(1), f"{prefix}_deal")
        outer = TypedVariable(f"{prefix}_outer", Usize_t(1))
        deal = TypedVariable(f"{prefix}_deal", Usize_t(1))
        false_var = self._emit_bool_const(body, False, f"{prefix}_false")
        not_outer = TypedVariable(f"{prefix}_not_outer", Usize_t(1))
        alive = TypedVariable(prefix, Usize_t(1))
        body.extend(
            [
                Instruction_load(var_out=outer, var=outer_ptr),
                Instruction_load(var_out=deal, var=deal_ptr),
                Instruction_ieq(var_out=not_outer, lhs=outer, rhs=false_var),
                Instruction_and(var_out=alive, lhs=deal, rhs=not_outer),
            ]
        )
        return alive

    def _emit_bool_to_usize(self, body: list, value: TypedVariable, prefix: str) -> TypedVariable:
        out = TypedVariable(prefix, Usize_t())
        body.append(Instruction_pcast(var_out=out, var=value, type=Usize_t()))
        return out

    def _emit_box_value(
        self,
        body: list,
        box_var: TypedVariable,
        ptr_type: Pointer,
        prefix: str,
    ) -> TypedVariable:
        ptr = self._emit_box_ptr(body, box_var, ptr_type, prefix)
        value = TypedVariable(prefix, deepcopy(ptr_type.pointee))
        body.append(Instruction_load(var_out=value, var=ptr))
        return value

    def _emit_box_ptr(
        self,
        body: list,
        box_var: TypedVariable,
        ptr_type: Pointer,
        prefix: str,
    ) -> TypedVariable:
        ptr = TypedVariable(f"{prefix}_ptr", deepcopy(ptr_type))
        body.append(Instruction_getfield(var_out=ptr, src=box_var, field=TypedVariable("0", deepcopy(ptr_type))))
        return ptr

    def _emit_owner_ptr(
        self,
        body: list,
        box_var: TypedVariable,
        owner_ptr_type: Pointer,
        prefix: str,
    ) -> TypedVariable:
        owner_ptr = TypedVariable(f"{prefix}_owner_ptr", deepcopy(owner_ptr_type))
        body.append(Instruction_getfield(var_out=owner_ptr, src=box_var, field=TypedVariable("1", deepcopy(owner_ptr_type))))
        return owner_ptr

    def _emit_owner_field_ptr(
        self,
        body: list,
        owner_ptr: TypedVariable,
        field_index: int,
        field_type: Type,
        prefix: str,
    ) -> TypedVariable:
        field_ptr = TypedVariable(f"{prefix}_ptr", Pointer(deepcopy(field_type)))
        body.append(
            Instruction_getfieldptr(
                var_out=field_ptr,
                src=owner_ptr,
                field=TypedVariable(str(field_index), deepcopy(field_type)),
            )
        )
        return field_ptr

    def _emit_bool_const(self, body: list, value: bool, prefix: str) -> TypedVariable:
        var = TypedVariable(prefix, Usize_t(1))
        body.append(Instruction_capprim(var_out=var, primitive=Usize(1 if value else 0, size=1)))
        return var

    def _emit_usize_const(self, body: list, value: int, prefix: str) -> TypedVariable:
        var = TypedVariable(prefix, Usize_t())
        body.append(Instruction_capprim(var_out=var, primitive=Usize(value)))
        return var

    def _emit_u8_const(self, body: list, value: int, prefix: str) -> TypedVariable:
        var = TypedVariable(prefix, Usize_t(8))
        body.append(Instruction_capprim(var_out=var, primitive=Usize(value, size=8)))
        return var

    def _child_edges(self, typ: Type) -> list[_ChildEdge]:
        struct = self._structs.get(typ.name)
        if struct is None:
            return []
        result: list[_ChildEdge] = []
        for index, field in enumerate(struct.params):
            if self._is_concrete_box_type(field.type):
                result.append(
                    _ChildEdge(
                        field_index=index,
                        field_name=field.name,
                        field_type=deepcopy(field.type),
                        child_type=deepcopy(field.type),
                    )
                )
                continue
            enum = self._enums.get(field.type.name)
            if enum is None:
                continue
            for variant_index, variant in enumerate(enum.variants, start=1):
                payload_type = self._variant_payload_type(variant)
                if payload_type is None or not self._is_concrete_box_type(payload_type):
                    continue
                result.append(
                    _ChildEdge(
                        field_index=index,
                        field_name=field.name,
                        field_type=deepcopy(field.type),
                        child_type=deepcopy(payload_type),
                        variant_index=variant_index,
                        variant_name=variant.name,
                    )
                )
        return result

    def _is_concrete_box_type(self, typ: Type | None) -> bool:
        return typ is not None and typ.name in self._structs and is_box_struct(self._structs[typ.name])

    def _box_owner_ptr_type(self, box_type: Type | None) -> Pointer:
        assert box_type is not None
        struct = self._structs[box_type.name]
        owner_type = struct.params[1].type
        assert isinstance(owner_type, Pointer)
        return deepcopy(owner_type)

    def _cfree_fn(
        self,
        name: str,
        box_type: Type,
        blocks: list[Block],
        ret_type: Type | None = None,
    ) -> Derective_fn:
        return Derective_fn(
            name=name,
            generics=[],
            params=[Parameter("self", deepcopy(box_type))],
            body=blocks,
            ret_type=ret_type or Type("void"),
            attrs=("safe",),
        )

    def _cfree_name(self, box_type: Type) -> str:
        return f"__cfree_{box_type.name}"

    def _cfree_pass_name(self, box_type: Type, pass_index: int) -> str:
        return f"__cfree_pass{pass_index}_{box_type.name}"

    def _cfree_mark_outer_name(self, box_type: Type) -> str:
        return f"__cfree_mark_outer_{box_type.name}"

    def _cfree_cleanup_name(self, box_type: Type) -> str:
        return f"__cfree_cleanup_{box_type.name}"

    def _generate_enum_drop_blocks(self, directive: Derective_enum, self_var: TypedVariable) -> list[Block]:
        drop_variants = [
            (variant_index, variant)
            for variant_index, variant in enumerate(directive.variants, start=1)
            if self._variant_payload_type(variant) is not None
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
            payload = TypedVariable(f".drop_{variant.name}", deepcopy(payload_type))
            body = [
                Instruction_getfield(
                    var_out=payload,
                    src=self_var,
                    field=TypedVariable(str(variant_index), deepcopy(payload_type)),
                )
            ]
            if needs_drop(payload_type, self._aggregate_names):
                body.append(
                    Instruction_call(
                        var_out=TypedVariable(f".drop_call_{variant.name}", Type("void")),
                        fn_name=drop_function_name(payload_type),
                        generics=[],
                        args=[deepcopy(payload)],
                    )
                )
            body.extend(
                [
                    Instruction_ret(TypedVariable(".drop_ret", Type("void"))),
                ]
            )
            blocks.append(
                Block(
                    name=f"drop_{variant.name}",
                    body=body,
                )
            )
        blocks.append(Block(name="done", body=[Instruction_ret(TypedVariable(".drop_ret", Type("void")))]))
        return blocks

    def _variant_needs_drop(self, variant: EnumVariant) -> bool:
        payload_type = self._variant_payload_type(variant)
        return payload_type is not None and needs_drop(payload_type, self._aggregate_names)

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
        return self._materialize_struct(template, mapping), self._materialize_struct(storage_template, mapping)

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
        return any(
            isinstance(item, Type) and item.name == needle.name and item.generics == needle.generics
            for item in self._walk(ast)
        )

    def _is_placeholder_type(self, typ: Type) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return self._is_placeholder_type(typ.pointee)
        if not typ.generics and (
            typ.name in {"Self", "T"}
            or (len(typ.name) == 1 and typ.name.isupper())
            or (typ.name.startswith("T") and typ.name[1:].isdigit())
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
