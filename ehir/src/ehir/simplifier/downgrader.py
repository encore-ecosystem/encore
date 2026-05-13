from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    BinOp,
    ControlFlow,
    Instruction_and,
    Instruction_br,
    Instruction_call,
    Instruction_capenum,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_cenum,
    Instruction_comment,
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_gep,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_ieq,
    Instruction_load,
    Instruction_match,
    Instruction_neq,
    Instruction_or,
    Instruction_pcast,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
    Instruction_switch,
    Instruction_wraph,
    Instruction_wraps,
)
from ehir.core.instructions.base import Instruction
from ehir.core.primitives import Usize, Usize_t
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type, mangle_type_name
from ehir.core.variable import Parameter, TypedVariable, Variable
from ehir.simplifier.normalizer.norm_fn import Normalized_fn

SKIPABLE = (
    Instruction_ret,
    BinOp,
    Instruction_and,
    Instruction_or,
    Instruction_ieq,
    Instruction_neq,
    Instruction_store,
    Instruction_call,
    Instruction_switch,
    Instruction_salloc,
    Instruction_load,
    Instruction_put,
    Instruction_hfree,
    Instruction_gep,
    Instruction_pcast,
    Instruction_getptr,
    Instruction_comment,
    Instruction_halloc,
    Instruction_hrealloc,
)

ENABLE_COMMENTS: bool = True


class Downgrader:
    _structs: dict[str, Derective_struct]
    _enum_variants: dict[str, list[str]]
    _structs_to_add: list[Derective_struct]
    _fns: dict[str, Normalized_fn]
    _fns_to_add: list[Normalized_fn]

    def run(self, ast: list[Derective]) -> list[Derective]:
        self._structs = {}
        self._enum_variants = {}
        self._structs_to_add = []
        self._fns = {}
        self._fns_to_add = []

        rewritten_ast: list[Derective] = []
        for derective in ast:
            if isinstance(derective, Derective_enum):
                self._enum_variants[derective.name] = [variant.name for variant in derective.variants]
                lowered = self._lower_enum_derective(derective)
                self._structs[lowered.name] = lowered
                rewritten_ast.append(lowered)
            else:
                if isinstance(derective, Derective_struct):
                    self._structs[derective.name] = derective
                rewritten_ast.append(derective)

        for derective in rewritten_ast:
            if isinstance(derective, Normalized_fn):
                self._fns[derective.name] = derective

        for derective in rewritten_ast:
            if isinstance(derective, Normalized_fn):
                self._downgrade_function(derective)

        ast[:] = rewritten_ast + self._structs_to_add + self._fns_to_add
        return ast

    def _downgrade_function(self, fn: Normalized_fn):
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            new_body = []
            for instr in block.get_body():
                new = self._downgrade(instr)
                if not isinstance(instr, ControlFlow):
                    new_body.extend(new)
                else:
                    term = new.pop()
                    assert isinstance(term, ControlFlow)
                    new_body.extend(new)
                    block.term = term

            block.body = new_body

    def _downgrade(self, instr: Instruction) -> list[Instruction]:
        if isinstance(instr, Instruction_cpos):
            return self._downgrade_cpos(instr)
        elif isinstance(instr, Instruction_cenum):
            return self._downgrade_cenum(instr)
        elif isinstance(instr, Instruction_cstruct):
            return self._downgrade_cstruct(instr)
        elif isinstance(instr, Instruction_scpos):
            return self._downgrade_scpos(instr)
        elif isinstance(instr, Instruction_scstruct):
            return self._downgrade_scstruct(instr)
        elif isinstance(instr, Instruction_capprim):
            return self._downgrade_capprim(instr)
        elif isinstance(instr, Instruction_capenum):
            return self._downgrade_capenum(instr)
        elif isinstance(instr, Instruction_capstruct):
            return self._downgrade_capstruct(instr)
        elif isinstance(instr, Instruction_getfield):
            return self._downgrade_getfield(instr)
        elif isinstance(instr, Instruction_getfieldptr):
            return self._downgrade_getfieldptr(instr)
        elif isinstance(instr, Instruction_sgetfield):
            return self._downgrade_sgetfield(instr)
        elif isinstance(instr, Instruction_sgetfieldptr):
            return self._downgrade_sgetfieldptr(instr)
        elif isinstance(instr, Instruction_setfield):
            return self._downgrade_setfield(instr)
        elif isinstance(instr, (Instruction_wraps, Instruction_wraph)):
            return self._downgrade_wrap(instr)
        elif isinstance(instr, Instruction_cbr):
            return self._downgrade_cbr(instr)
        elif isinstance(instr, Instruction_match):
            return self._downgrade_match(instr)
        elif isinstance(instr, Instruction_br):
            return self._downgrade_br(instr)
        elif isinstance(instr, SKIPABLE):
            return [instr]
        else:
            raise NotImplementedError(f"Downgrading instruction for {type(instr)}:{instr} not implemented")

    def _downgrade_wrap(self, instr: Instruction_wraps | Instruction_wraph) -> list[Instruction]:
        assert instr.variable.type is not None
        assert instr.var_out.type is not None
        if isinstance(instr, Instruction_wraph):
            assert instr.var_out.type is not None
            return [
                Instruction_call(
                    var_out=instr.var_out,
                    fn_name=f"{instr.var_out.type}::wrap",
                    generics=[],
                    args=[instr.variable],
                )
            ]

        temp_ptr = TypedVariable(name=f".{instr.var_out.name}_wrap_ptr", type=Pointer(instr.variable.type))
        return [
            Instruction_salloc(var_out=temp_ptr, type=instr.variable.type),
            Instruction_store(var_src=instr.variable, var_dst=temp_ptr),
            Instruction_call(
                var_out=instr.var_out,
                fn_name=f"{instr.var_out.type}::from_stack_raw",
                generics=[],
                args=[temp_ptr],
            ),
        ]

    def _lower_enum_derective(self, enum: Derective_enum) -> Derective_struct:
        params = [Parameter(name="tag", type=Usize_t(8))]
        for variant in enum.variants:
            payload_type = self._variant_payload_type(variant)
            if payload_type is None:
                continue
            params.append(Parameter(name=variant.name, type=Pointer(payload_type)))
        return Derective_struct(name=enum.name, generics=enum.generics, params=params)

    def _variant_payload_type(self, variant: UnitLikeVariant | TupleLikeVariant):
        if isinstance(variant, UnitLikeVariant):
            return None
        if isinstance(variant, TupleLikeVariant):
            if len(variant.types) == 0:
                return None
            return variant.types[0]
        raise TypeError(f"Unknown enum variant kind: {type(variant)}")

    def _downgrade_cpos(self, instr: Instruction_cpos) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert isinstance(instr.var_out.type, Pointer)

        salloc = Instruction_salloc(
            var_out=instr.var_out,
            type=instr.var_out.type.pointee,
        )
        put = Instruction_put(
            primitive=instr.primitive,
            var=instr.var_out,
        )
        return [
            salloc,
            put,
        ]

    def _downgrade_cenum(self, instr: Instruction_cenum) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert isinstance(instr.var_out.type, Pointer)
        return self._downgrade_enum_capture(instr.var_out, instr.enum, on_heap=False)

    def _downgrade_cstruct(self, instr: Instruction_cstruct) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert isinstance(instr.var_out.type, Pointer)

        salloc = Instruction_salloc(
            var_out=instr.var_out,
            type=instr.struct.as_type(),
        )
        downgrades = [salloc]
        for i, arg in enumerate(instr.struct.fields):
            assert arg.type
            field_arg = TypedVariable(name=f".{instr.var_out.name}.{arg.name}", type=Pointer(arg.type))
            field_ptr = Instruction_getfieldptr(
                var_out=field_arg, src=instr.var_out, field=TypedVariable(name=str(i), type=arg.type)
            )

            store = Instruction_store(
                var_src=arg,
                var_dst=field_arg,
            )
            downgrades.append(field_ptr)
            downgrades.append(store)

        return downgrades

    def _downgrade_scpos(self, instr: Instruction_scpos) -> list[Instruction]:
        raise NotImplementedError

    def _downgrade_scstruct(self, instr: Instruction_scstruct) -> list[Instruction]:
        ptr = TypedVariable(name=f".{instr.var_out.name}_wrapped_ptr", type=Pointer(instr.struct.as_type()))
        ptr_init = Instruction_cstruct(ptr, instr.struct)

        wrapper_name = mangle_type_name(Type("Box", [instr.struct.as_type()]))
        if wrapper_name not in self._structs:
            wrapper_struct = Derective_struct(
                name=wrapper_name,
                generics=[],
                params=[Parameter(name="ptr", type=ptr.type)],
            )
            self._structs[wrapper_name] = wrapper_struct
            self._structs_to_add.append(wrapper_struct)

        wrapped = Struct(name=wrapper_name, args=[ptr])
        instr.var_out.type = wrapped.as_type()
        res = Instruction_capstruct(instr.var_out, wrapped)

        return [
            *self._downgrade_cstruct(ptr_init),
            *self._downgrade_capstruct(res),
        ]

    def _downgrade_capprim(self, instr: Instruction_capprim) -> list[Instruction]:
        assert instr.var_out.type is not None
        out_ptr = TypedVariable(name=f".{instr.var_out.name}_ptr", type=Pointer(instr.var_out.type))
        cpos = Instruction_cpos(
            var_out=out_ptr,
            primitive=instr.primitive,
        )
        load = Instruction_load(var_out=instr.var_out, var=out_ptr)
        return [
            *self._downgrade_cpos(cpos),
            load,
        ]

    def _downgrade_capenum(self, instr: Instruction_capenum) -> list[Instruction]:
        assert instr.var_out.type is not None
        out_ptr = TypedVariable(name=f".{instr.var_out.name}_ptr", type=Pointer(instr.var_out.type))
        ceos = Instruction_cenum(var_out=out_ptr, enum=instr.enum)
        load = Instruction_load(var_out=instr.var_out, var=out_ptr)
        return [
            *self._downgrade_cenum(ceos),
            load,
        ]

    def _downgrade_capstruct(self, instr: Instruction_capstruct) -> list[Instruction]:
        assert instr.var_out.type is not None
        out_ptr = TypedVariable(name=f".{instr.var_out.name}_ptr", type=Pointer(instr.var_out.type))
        csos = Instruction_cstruct(var_out=out_ptr, struct=instr.struct)
        load = Instruction_load(var_out=instr.var_out, var=out_ptr)
        return [
            *self._downgrade_cstruct(csos),
            load,
        ]

    def _downgrade_getfield(self, instr: Instruction_getfield) -> list[Instruction]:
        assert instr.var_out.type is not None
        out_ptr = TypedVariable(name=f".{instr.var_out.name}_ptr", type=Pointer(instr.var_out.type))
        getfieldptr = Instruction_getfieldptr(
            var_out=out_ptr,
            src=instr.src,
            field=instr.field,
            field_path=list(instr.field_path),
        )
        load = Instruction_load(var_out=instr.var_out, var=out_ptr)
        return [
            *self._downgrade_getfieldptr(getfieldptr),
            load,
        ]

    def _downgrade_getfieldptr(self, instr: Instruction_getfieldptr) -> list[Instruction]:
        field_segments = [instr.field, *instr.field_path]
        result: list[Instruction] = []
        current_src = instr.src
        for index, field in enumerate(field_segments):
            is_last = index == len(field_segments) - 1
            owner_t = current_src.type
            assert owner_t is not None
            if isinstance(owner_t, (Pointer, Reference)):
                owner_t = owner_t.pointee
            struct_decl = self._structs.get(owner_t.name)
            assert struct_decl is not None, f"Unknown struct for getfieldptr: {owner_t}"
            field_index = int(field.name) if field.name.isdigit() else None
            if field_index is None:
                for idx, p in enumerate(struct_decl.params):
                    if p.name == field.name:
                        field_index = idx
                        break
            assert field_index is not None, f"Unknown field {field.name} for {owner_t.name}"
            resolved_field_type = struct_decl.params[field_index].type
            if field.type is None:
                field.type = resolved_field_type
            var_out = (
                instr.var_out
                if is_last
                else TypedVariable(name=f".{instr.var_out.name}_{index}_ptr", type=Pointer(resolved_field_type))
            )
            lowered = Instruction_getfieldptr(
                var_out=var_out,
                src=current_src,
                field=Variable(name=str(field_index), type=field.type),
            )
            result.append(lowered)
            current_src = var_out
        return result

    def _downgrade_setfield(self, instr: Instruction_setfield) -> list[Instruction]:
        assert instr.field.type is not None
        final_field = ([instr.field, *instr.field_path])[-1]
        assert final_field.type is not None
        field_ptr = TypedVariable(name=f".{instr.var.name}_{final_field.name}_ptr", type=Pointer(final_field.type))
        getfieldptr = Instruction_getfieldptr(
            var_out=field_ptr,
            src=instr.var,
            field=instr.field,
            field_path=list(instr.field_path),
        )
        store = Instruction_store(var_src=instr.value, var_dst=field_ptr)
        return [*self._downgrade_getfieldptr(getfieldptr), store]

    def _downgrade_enum_capture(self, out: TypedVariable, enum: Enum, on_heap: bool) -> list[Instruction]:
        assert out.type is not None
        assert isinstance(out.type, Pointer)

        lowered_enum_name = out.type.pointee.name
        lowered_struct = self._structs[lowered_enum_name]
        tag_value = self._enum_variants[lowered_enum_name].index(enum.variant)
        tag_var = TypedVariable(name=f".{out.name}_tag", type=Usize_t(8))
        tag_init = Instruction_capprim(var_out=tag_var, primitive=Usize(tag_value, size=8))

        alloc: Instruction
        if on_heap:
            alloc = Instruction_halloc(var_out=out, type=out.type.pointee)
        else:
            alloc = Instruction_salloc(var_out=out, type=out.type.pointee)

        tag_ptr = TypedVariable(name=f".{out.name}_tag_ptr", type=Pointer(Usize_t(8)))
        tag_field_ptr = Instruction_getfieldptr(
            var_out=tag_ptr, src=out, field=TypedVariable(name="0", type=Usize_t(8))
        )
        tag_store = Instruction_store(var_src=tag_var, var_dst=tag_ptr)

        result: list[Instruction] = [alloc, *self._downgrade_capprim(tag_init), tag_field_ptr, tag_store]

        if len(enum.args) == 0:
            return result

        payload_value = enum.args[0]
        assert payload_value.type is not None
        payload_type = payload_value.type
        payload_ptr = TypedVariable(name=f".{out.name}_{enum.variant}_payload", type=Pointer(payload_type))
        # Enum layout stores payload as a pointer field; payload must outlive this frame.
        result.append(Instruction_halloc(var_out=payload_ptr, type=payload_type))
        result.append(Instruction_store(var_src=payload_value, var_dst=payload_ptr))

        payload_field_index = next(i for i, param in enumerate(lowered_struct.params) if param.name == enum.variant)
        payload_field_ptr = TypedVariable(name=f".{out.name}_{enum.variant}_field_ptr", type=Pointer(payload_ptr.type))
        payload_getfieldptr = Instruction_getfieldptr(
            var_out=payload_field_ptr,
            src=out,
            field=TypedVariable(name=str(payload_field_index), type=payload_ptr.type),
        )
        payload_store = Instruction_store(var_src=payload_ptr, var_dst=payload_field_ptr)
        result.extend([payload_getfieldptr, payload_store])
        return result

    def _downgrade_sgetfield(self, instr: Instruction_sgetfield) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert instr.src.type
        wrapped_struct = self._structs[instr.src.type.name]
        wrapped_struct_ptr = TypedVariable(name=f".{instr.var_out.name}_sgf_ptr", type=wrapped_struct.params[0].type)
        getfield1 = Instruction_getfield(
            var_out=wrapped_struct_ptr, src=instr.src, field=TypedVariable("0", wrapped_struct.params[0].type)
        )
        getfield2 = Instruction_getfield(var_out=instr.var_out, src=wrapped_struct_ptr, field=instr.field)
        return [
            *self._downgrade_getfield(getfield1),
            *self._downgrade_getfield(getfield2),
        ]

    def _downgrade_sgetfieldptr(self, instr: Instruction_sgetfieldptr) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert instr.src.type
        wrapped_struct = self._structs[instr.src.type.name]
        wrapped_struct_ptr = TypedVariable(name=f".{instr.var_out.name}_sgfptr_ptr", type=wrapped_struct.params[0].type)
        getfield = Instruction_getfield(
            var_out=wrapped_struct_ptr, src=instr.src, field=TypedVariable("0", wrapped_struct.params[0].type)
        )
        getfieldptr = Instruction_getfieldptr(var_out=instr.var_out, src=wrapped_struct_ptr, field=instr.field)
        return [*self._downgrade_getfield(getfield), getfieldptr]

    def _downgrade_cbr(self, instr: Instruction_cbr) -> list[Instruction]:
        assert instr.cond_var.type is not None
        assert isinstance(instr.cond_var.type, Usize_t)

        switch = Instruction_switch(
            cond_var=instr.cond_var,
            default_case=instr.else_br_label,
            cases=[(Usize(1, size=instr.cond_var.type.size), instr.true_br_label)],
        )
        return [switch]

    def _downgrade_br(self, instr: Instruction_br) -> list[Instruction]:
        zero_ptr = TypedVariable(name=".br_zero_ptr", type=Pointer(Usize_t(1)))
        zero = TypedVariable(name=".br_zero", type=Usize_t(1))
        cpos = Instruction_cpos(var_out=zero_ptr, primitive=Usize(0, size=1))
        load = Instruction_load(
            var_out=zero,
            var=zero_ptr,
        )
        switch = Instruction_switch(
            cond_var=zero,
            default_case=instr.label,
            cases=[],
        )
        return [*self._downgrade_cpos(cpos), load, switch]

    def _downgrade_match(self, instr: Instruction_match) -> list[Instruction]:
        assert instr.cond_var.type is not None
        cond_src = instr.cond_var
        prelude: list[Instruction] = []
        variant_names = self._enum_variants.get(instr.cond_var.type.name)

        if variant_names is None:
            wrapped_struct = self._structs.get(instr.cond_var.type.name)
            if (
                wrapped_struct is not None
                and wrapped_struct.params
                and isinstance(wrapped_struct.params[0].type, Pointer)
            ):
                inner_ptr_type = wrapped_struct.params[0].type
                inner_type = inner_ptr_type.pointee
                variant_names = self._enum_variants.get(inner_type.name)
                if variant_names is not None:
                    enum_ptr = TypedVariable(name=f".{instr.cond_var.name}_match_enum_ptr", type=inner_ptr_type)
                    enum_value = TypedVariable(name=f".{instr.cond_var.name}_match_enum", type=inner_type)
                    field0 = TypedVariable(name="0", type=inner_ptr_type)
                    prelude.extend(
                        self._downgrade_getfield(
                            Instruction_getfield(var_out=enum_ptr, src=instr.cond_var, field=field0)
                        )
                    )
                    prelude.append(Instruction_load(var_out=enum_value, var=enum_ptr))
                    cond_src = enum_value

        if variant_names is None:
            if instr.cond_var.type.name == "Option" or instr.cond_var.type.name.startswith("Option_"):
                variant_names = ["Some", "None"]

        if variant_names is None:
            raise TypeError(f"Match condition must be a lowered enum, got '{instr.cond_var.type}'")

        tag = TypedVariable(name=f".{cond_src.name}_match_tag", type=Usize_t(8))
        get_tag = Instruction_getfield(
            var_out=tag,
            src=cond_src,
            field=TypedVariable("0", Usize_t(8)),
        )

        cases: list[tuple[Usize, str]] = []
        for case in instr.cases:
            if case.variant not in variant_names:
                raise TypeError(f"Unknown enum variant '{case.variant}' for '{cond_src.type.name}'")
            cases.append((Usize(variant_names.index(case.variant), size=8), case.label))

        switch = Instruction_switch(cond_var=tag, default_case=instr.default_case, cases=cases)
        return [*prelude, *self._downgrade_getfield(get_tag), switch]
