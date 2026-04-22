from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions.base import Assignable, Instruction
from ehir.core.instructions.capture import Instruction_lcpos
from ehir.core.instructions.control_flow import (
    Instruction_br,
    Instruction_call,
    Instruction_cbr,
    Instruction_ret,
    Instruction_switch,
)
from ehir.core.instructions.control_flow.base import ControlFlow
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_hfree,
    Instruction_load,
    Instruction_pcast,
    Instruction_put,
    Instruction_store,
)
from ehir.core.instructions.operators.arithmetic import (
    Instruction_sub,
)
from ehir.core.instructions.operators.logic import Instruction_and, Instruction_ieq, Instruction_neq, Instruction_or
from ehir.core.instructions.special import Instruction_cfree, Instruction_comment
from ehir.core.primitives import Usize, Usize_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, SmartPointer, Type, mangle_type_name
from ehir.core.variable import Parameter, TypedVariable, Variable
from ehir.simplifier.normalizer.norm_fn import Normalized_fn


class Cfree_Simplifier_Pass:
    _fns: dict[str, Derective_fn]
    _fns_to_add: list[Derective_fn]
    _structs: dict[str, Derective_struct]
    _structs_to_add: list[Derective_struct]

    def run(self, ast: list[Derective]):
        self._fns = {}
        self._fns_to_add = []
        self._structs = {}
        self._structs_to_add = []

        for derective in ast:
            if isinstance(derective, Derective_fn):
                self._fns[derective.name] = derective
            elif isinstance(derective, Derective_struct):
                self._structs[derective.name] = derective

        for struct in list(self._structs.values()):
            self._unwrap_smart_pointer_in_struct(struct)

        # Bootstrap mode: keep cfree lowering disabled for now.
        # We intentionally skip generating recursive cfree helper functions.

        for fn in self._fns.values():
            self._unwrap_smart_pointer_in_fn(fn)

        return self._structs_to_add + self._fns_to_add + ast

    def _unwrap_smart_pointer_in_struct(self, struct: Derective_struct):
        for param in struct.params:
            if isinstance(param.type, SmartPointer):
                self._unwrap_smart_pointer(param)

    def _unwrap_smart_pointer_in_fn(self, fn: Derective_fn):
        for param in fn.params:
            if isinstance(param.type, SmartPointer):
                self._unwrap_smart_pointer(param)

        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            new_body = []
            for instr in block.get_body():
                new_body.extend(self._unwrap_smart_pointer_in_instruction(instr))
            term = new_body.pop()
            assert isinstance(term, ControlFlow)
            block.body = new_body
            block.term = term

    def _unwrap_smart_pointer_in_instruction(self, instr: Instruction) -> list[Instruction]:
        if isinstance(instr, Assignable):
            assert instr.var_out.type
            if isinstance(instr.var_out.type, SmartPointer):
                self._unwrap_smart_pointer(instr.var_out)

        if isinstance(instr, Instruction_cfree):
            # Temporary bootstrap behavior: ignore cfree instructions.
            return []
        return [instr]

    def _is_concrete_type(self, typ: Type) -> bool:
        if isinstance(typ, SmartPointer):
            return self._is_concrete_type(typ.pointee)
        if isinstance(typ, Pointer):
            return self._is_concrete_type(typ.pointee)
        if isinstance(typ, PrimitiveType):
            return True
        if typ.generics and not all(self._is_concrete_type(generic) for generic in typ.generics):
            return False
        return typ.name in self._structs or not typ.name.isidentifier() or typ.name.startswith(("u", "i", "f"))

    def _unwrap_smart_pointer(self, var: Variable):
        assert isinstance(var.type, SmartPointer)
        if var.type.get_name() not in self._structs:
            self._generate_wrapper_struct(var.type)
        smart_struct = self._structs[var.type.get_name()]
        var.type = Type(name=smart_struct.name)

    def _generate_wrapper_struct(self, type: SmartPointer):
        struct_name = type.get_name()
        if struct_name not in self._structs:
            struct = Derective_struct(
                name=struct_name,
                generics=[],
                params=[
                    Parameter(name="ptr", type=Pointer(type.pointee)),
                    Parameter(name="ref_cnt", type=Usize_t()),
                    Parameter(name="in_reachable", type=Usize_t(1)),
                    Parameter(name="out_reachable", type=Usize_t(1)),
                    Parameter(name="out_visited", type=Usize_t(1)),
                    Parameter(name="deallocate", type=Usize_t(1)),
                ],
            )

            self._structs[struct_name] = struct
            self._structs_to_add.append(struct)

    def _generate_cfree(self, typ: SmartPointer):
        name = f"cfree_{typ.get_name()}"
        if name in self._fns:
            return self._fns[name]
        self._generate_wrapper_struct(typ)

        wrapped_name = typ.pointee.name
        if wrapped_name not in self._structs and typ.pointee.generics:
            wrapped_name = mangle_type_name(typ.pointee)
        struct_wrapped = self._structs[wrapped_name]
        struct = self._structs[typ.get_name()]

        self_param = TypedVariable(name="self", type=Type(typ.get_name()))
        mode_param = TypedVariable(name="mode", type=Usize_t())

        var_0 = TypedVariable("zero", Usize_t())
        var_1 = TypedVariable("one", Usize_t())
        var_2 = TypedVariable("two", Usize_t())
        var_3 = TypedVariable("tree", Usize_t())

        exit_var = TypedVariable(name="ok", type=Usize_t())
        exit_block = TerminatedBlock(
            name="exit",
            body=[
                Instruction_lcpos(var_out=exit_var, primitive=Usize(0)),
            ],
            term=Instruction_ret(var=exit_var),
        )

        err_var = TypedVariable(name="err", type=Usize_t())
        error_block = TerminatedBlock(
            name="error",
            body=[
                Instruction_lcpos(var_out=err_var, primitive=Usize(1)),
            ],
            term=Instruction_ret(var=err_var),
        )

        # ============
        # Pass 1
        # ============
        in_reachable_ptr = TypedVariable(
            name="in_reachable_field_ptr",
            type=Pointer(struct.params[2].type),
        )
        in_reachable_var = TypedVariable(
            name="in_reachable_field",
            type=struct.params[2].type,
        )

        pass_1_block = TerminatedBlock(
            name="pass_1",
            body=[],
            term=Instruction_cbr(cond_var=in_reachable_var, true_br_label=exit_block.name, else_br_label="pass_1v1"),
        )
        pass_1v1_block = TerminatedBlock(
            name="pass_1v1",
            body=[Instruction_put(primitive=Usize(val=1, size=1), var=in_reachable_ptr)],
            term=Instruction_br(exit_block.name),
        )

        for i, field in enumerate(struct_wrapped.params):
            if isinstance(field.type, SmartPointer):
                ref_cnt_ptr = TypedVariable(
                    name=f".{field.name}_ref_cnt_ptr", type=Pointer(struct_wrapped.params[i].type)
                )
                ref_cnt = TypedVariable(name=f".{field.name}_ref_cnt", type=struct_wrapped.params[i].type)

                pass_1v1_block.body.append(Instruction_load(var_out=ref_cnt, var=ref_cnt_ptr))

                ref_cnt_new = TypedVariable(name=f".{field.name}_ref_cnt_new", type=struct_wrapped.params[i].type)
                ref_cnt_new_ptr = TypedVariable(
                    name=f".{field.name}_ref_cnt_new_ptr", type=Pointer(struct_wrapped.params[i].type)
                )
                pass_1v1_block.body.extend(
                    [
                        Instruction_sub(var_out=ref_cnt_new, lhs=ref_cnt, rhs=var_1),
                        Instruction_getptr(var_out=ref_cnt_new_ptr, var=ref_cnt_new),
                        Instruction_store(var_src=ref_cnt_new_ptr, var_dst=ref_cnt_ptr),
                        Instruction_call(
                            var_out=TypedVariable(name=f".pass1_{field}", type=Usize_t()),
                            fn_name=f"cfree_{struct_wrapped.params[i].type.get_name()}",
                            args=[self_param, var_1],
                        ),
                    ]
                )

        # ============
        # Pass 2
        # ============
        out_reachable_ptr = TypedVariable(
            name="out_reachable_field_ptr",
            type=Pointer(struct.params[2].type),
        )
        out_reachable_var = TypedVariable(
            name="out_reachable_field",
            type=struct.params[2].type,
        )
        pass_2_block = TerminatedBlock(
            name="pass_2",
            body=[
                Instruction_getfieldptr(
                    var_out=out_reachable_ptr,
                    src=self_param,
                    field=TypedVariable(name="3", type=Usize_t(1)),
                ),
                Instruction_load(
                    var_out=out_reachable_var,
                    var=out_reachable_ptr,
                ),
            ],
            term=Instruction_cbr(cond_var=in_reachable_var, true_br_label=exit_block.name, else_br_label="pass_2v1"),
        )

        out_reachable_2_ptr = TypedVariable(name=".pass_2_out_reachable_ptr", type=Pointer(Usize_t(1)))
        out_reachable_2 = TypedVariable(name=".pass_2_out_reachable", type=Usize_t(1))
        out_visited_2_ptr = TypedVariable(name=".pass_2_out_visited_ptr", type=Pointer(Usize_t(1)))
        out_visited_2 = TypedVariable(name=".pass_2_out_visited", type=Usize_t(1))
        # out_reachable_new_ptr = TypedVariable(name=".pass_2_out_reachable_new_ptr", type=Pointer(Usize_t(1)))
        out_reachable_new = TypedVariable(name=".pass_2_out_reachable_new", type=Usize_t(1))
        ref_cnt = TypedVariable(name=".pass_2_ref_cnt", type=Usize_t())
        ref_cnt_not_zero = TypedVariable(name=".pass_2_ref_cnt_not_zero", type=Usize_t(1))
        pass_2v1_block = TerminatedBlock(
            name="pass_2v1",
            body=[
                Instruction_getfieldptr(
                    var_out=out_reachable_2_ptr,
                    src=self_param,
                    field=TypedVariable(name="3", type=Usize_t(1)),
                ),
                Instruction_load(
                    var_out=out_reachable_2,
                    var=out_reachable_2_ptr,
                ),
                Instruction_getfieldptr(
                    var_out=out_visited_2_ptr,
                    src=self_param,
                    field=TypedVariable(name="4", type=Usize_t(1)),
                ),
                Instruction_load(
                    var_out=out_visited_2,
                    var=out_visited_2_ptr,
                ),
                Instruction_getfield(
                    var_out=ref_cnt,
                    src=self_param,
                    field=TypedVariable(name="1", type=Usize_t()),
                ),
                Instruction_neq(
                    var_out=ref_cnt_not_zero,
                    lhs=ref_cnt,
                    rhs=var_0,
                ),
                Instruction_or(
                    var_out=out_reachable_new,
                    lhs=out_reachable_2,
                    rhs=ref_cnt_not_zero,
                ),
                Instruction_store(
                    var_src=out_reachable_new,
                    var_dst=out_reachable_2_ptr,
                ),
                Instruction_put(
                    primitive=Usize(val=1, size=1),
                    var=out_visited_2_ptr,
                ),
            ],
            term=Instruction_cbr(cond_var=out_reachable_new, true_br_label="pass_2v2", else_br_label="pass_2v3"),
        )

        pass_2v2_block = TerminatedBlock(
            name="pass_2v2",
            body=[],
            term=Instruction_br("pass_2v3"),
        )
        for i, field in enumerate(struct_wrapped.params):
            if isinstance(field.type, SmartPointer):
                pass_2v2_block.body.append(Instruction_comment("Not implemented logic"))

        pass_2v3_block = TerminatedBlock(
            name="pass_2v3",
            body=[],
            term=Instruction_br(exit_block.name),
        )
        for i, field in enumerate(struct_wrapped.params):
            if isinstance(field.type, SmartPointer):
                pass_2v2_block.body.append(
                    Instruction_call(
                        var_out=TypedVariable(name=f".pass2_{field}", type=Usize_t()),
                        fn_name=f"cfree_{struct_wrapped.params[i].type.get_name()}",
                        args=[self_param, var_2],
                    ),
                )

        # ============
        # Pass 3
        # ============
        deallocate_3_ptr = TypedVariable(name=".pass_3_deallocate_ptr", type=Pointer(Usize_t(1)))
        deallocate_3 = TypedVariable(name=".pass_3_deallocate", type=Usize_t(1))
        pass_3_block = TerminatedBlock(
            name="pass_3",
            body=[
                Instruction_getfieldptr(
                    var_out=deallocate_3_ptr,
                    src=self_param,
                    field=TypedVariable(name="5", type=Usize_t(1)),
                ),
                Instruction_load(
                    var_out=deallocate_3,
                    var=deallocate_3_ptr,
                ),
            ],
            term=Instruction_cbr(cond_var=deallocate_3, true_br_label=exit_block.name, else_br_label="pass_3v1"),
        )

        cond2 = TypedVariable(name=".pass_3_cond2", type=Usize_t(1))
        pass_3v1_block = TerminatedBlock(
            name="pass_3v1",
            body=[
                Instruction_put(primitive=Usize(val=1, size=1), var=deallocate_3_ptr),
            ],
            term=Instruction_cbr(cond_var=cond2, true_br_label="pass_3v2", else_br_label=exit_block.name),
        )
        for i, field in enumerate(struct_wrapped.params):
            if isinstance(field.type, SmartPointer):
                pass_3v1_block.body.append(
                    Instruction_call(
                        var_out=TypedVariable(name=f".pass3_{field}", type=Usize_t()),
                        fn_name=f"cfree_{struct_wrapped.params[i].type.get_name()}",
                        args=[self_param, var_3],
                    ),
                )
        ref_cnt = TypedVariable(name=".pass_3_ref_cnt", type=Usize_t())
        pass_3v1_block.body.append(
            Instruction_getfield(
                var_out=ref_cnt,
                src=self_param,
                field=TypedVariable(name="1", type=Usize_t()),
            )
        )
        ref_cnt_is_zero = TypedVariable(name=".pass_3_ref_cnt_is_zero", type=Usize_t(1))
        zero_1_bit = TypedVariable(".pass_3_zero_1_bit", type=Usize_t(1))
        one_1_bit = TypedVariable(".pass_3_one_1_bit", type=Usize_t(1))
        pass_3v1_block.body.extend(
            [
                Instruction_pcast(var_out=zero_1_bit, var=var_0, type=Usize_t(1)),
                Instruction_pcast(var_out=one_1_bit, var=var_1, type=Usize_t(1)),
                Instruction_ieq(var_out=ref_cnt_is_zero, lhs=ref_cnt, rhs=var_0),
            ]
        )

        inner_reach = TypedVariable(name=".pass_3_inner_reach", type=Usize_t(1))
        pass_3v1_block.body.append(
            Instruction_getfield(
                var_out=inner_reach,
                src=self_param,
                field=TypedVariable(name="2", type=Usize_t(1)),
            )
        )
        outer_reach = TypedVariable(name=".pass_3_outer_reach", type=Usize_t(1))
        pass_3v1_block.body.append(
            Instruction_getfield(
                var_out=outer_reach,
                src=self_param,
                field=TypedVariable(name="3", type=Usize_t(1)),
            )
        )
        inner_reach_is_one = TypedVariable(name=".pass_3_inner_reach_is_one", type=Usize_t(1))
        pass_3v1_block.body.append(Instruction_ieq(var_out=inner_reach_is_one, lhs=inner_reach, rhs=one_1_bit))

        outer_reach_is_zero = TypedVariable(name=".pass_3_outer_reach_is_zero", type=Usize_t(1))
        pass_3v1_block.body.append(Instruction_ieq(var_out=outer_reach_is_zero, lhs=outer_reach, rhs=zero_1_bit))

        cond1 = TypedVariable(name=".pass_3_cond1", type=Usize_t(1))
        pass_3v1_block.body.append(Instruction_and(var_out=cond1, lhs=ref_cnt_is_zero, rhs=inner_reach_is_one))

        pass_3v1_block.body.append(Instruction_and(var_out=cond2, lhs=cond1, rhs=outer_reach_is_zero))

        wrap_struct_ptr = TypedVariable(name=".pass3_wrapped_struct_ptr", type=struct.params[0].type)
        pass_3v2_block = TerminatedBlock(
            name="pass_3v2",
            body=[
                Instruction_getfield(
                    var_out=wrap_struct_ptr,
                    src=self_param,
                    field=TypedVariable(name="0", type=struct.params[0].type),
                ),
                Instruction_hfree(var=wrap_struct_ptr),
            ],
            term=Instruction_br(label=exit_block.name),
        )

        initiator_block = TerminatedBlock(
            name="initiator",
            body=[
                Instruction_call(
                    var_out=TypedVariable(name=".pass_1", type=Usize_t()),
                    fn_name=name,
                    generics=[],
                    args=[self_param, var_1],
                ),
                Instruction_call(
                    var_out=TypedVariable(name=".pass_2", type=Usize_t()),
                    fn_name=name,
                    generics=[],
                    args=[self_param, var_2],
                ),
                Instruction_call(
                    var_out=TypedVariable(name=".pass_3", type=Usize_t()),
                    fn_name=name,
                    generics=[],
                    args=[self_param, var_3],
                ),
            ],
            term=Instruction_br(label=exit_block.name),
        )
        entry_block = TerminatedBlock(
            name="entry",
            body=[
                Instruction_lcpos(var_out=var_0, primitive=Usize(0)),
                Instruction_lcpos(var_out=var_1, primitive=Usize(1)),
                Instruction_lcpos(var_out=var_2, primitive=Usize(2)),
                Instruction_lcpos(var_out=var_3, primitive=Usize(3)),
                Instruction_getfieldptr(
                    in_reachable_ptr,
                    self_param,
                    field=TypedVariable(name="2", type=Usize_t(1)),
                ),
                Instruction_load(
                    var_out=in_reachable_var,
                    var=in_reachable_ptr,
                ),
            ],
            term=Instruction_switch(
                cond_var=mode_param,
                default_case=error_block.name,
                cases=[
                    (Usize(0), initiator_block.name),
                    (Usize(1), pass_1_block.name),
                    (Usize(2), pass_2_block.name),
                    (Usize(3), pass_3_block.name),
                ],
            ),
        )

        derective = Normalized_fn.new(
            name=name,
            params=[self_param, mode_param],
            ret_type=Usize_t(),
            entry_block=entry_block,
            body=[
                initiator_block,
                pass_1_block,
                pass_1v1_block,
                pass_2_block,
                pass_2v1_block,
                pass_2v2_block,
                pass_2v3_block,
                pass_3_block,
                pass_3v1_block,
                pass_3v2_block,
                error_block,
            ],
            exit_block=exit_block,
        )
        self._fns[name] = derective
        self._fns_to_add.append(derective)
        return derective
