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
    Instruction_callvoid,
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
from ehir.core.type import Pointer, Reference, Type, box_pointee, is_box_type, mangle_type_name
from ehir.core.variable import Parameter, TypedVariable, Variable
from ehir.errors import EhirCompileError
from ehir.simplifier.drop_helper import collect_aggregate_names, needs_retain, retain_function_name
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
    Instruction_callvoid,
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
    _aggregate_names: set[str]
    _structs_to_add: list[Derective_struct]
    _fns: dict[str, Normalized_fn]
    _fns_to_add: list[Normalized_fn]
    _BOX_STORAGE_FIELDS = {"ptr", "owner", "0", "1"}

    def _lookup_struct(self, type_name: str) -> Derective_struct | None:
        struct_decl = self._structs.get(type_name)
        if struct_decl is not None:
            return struct_decl
        if "[" in type_name:
            base_name = type_name.split("[", 1)[0]
            return self._structs.get(base_name)
        return None

    def _box_field_target(self, owner_t: Type, field: Variable) -> tuple[Type, Derective_struct] | None:
        if field.name in self._BOX_STORAGE_FIELDS:
            return None
        pointee = self._box_pointee(owner_t)
        if pointee is None:
            return None
        decl = self._lookup_struct(pointee.name)
        if decl is None:
            return None
        if field.name.isdigit():
            index = int(field.name)
            if 0 <= index < len(decl.params):
                return pointee, decl
            return None
        if any(param.name == field.name for param in decl.params):
            return pointee, decl
        return None

    def _box_pointee(self, typ: Type) -> Type | None:
        if is_box_type(typ):
            return box_pointee(typ)
        if not typ.name.startswith("__Box_"):
            return None
        decl = self._lookup_struct(typ.name)
        if decl is None or not decl.params:
            return None
        ptr_field = decl.params[0].type
        if not isinstance(ptr_field, Pointer):
            return None
        return ptr_field.pointee

    def run(self, ast: list[Derective]) -> list[Derective]:
        self._structs = {}
        self._enum_variants = {}
        self._structs_to_add = []
        self._fns = {}
        self._fns_to_add = []
        source_structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct) and not directive.generics
        }
        source_enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum) and not directive.generics
        }
        self._aggregate_names = collect_aggregate_names(source_structs, source_enums)

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
        blocks_by_name = {block.name: block for block in fn.get_body()}
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            new_body = []
            for instr in block.get_body():
                if isinstance(instr, Instruction_match):
                    self._inject_match_payload_bindings(fn, blocks_by_name, instr)
                new = self._downgrade(instr)
                if not isinstance(instr, ControlFlow):
                    new_body.extend(new)
                else:
                    term = new.pop()
                    assert isinstance(term, ControlFlow)
                    new_body.extend(new)
                    block.term = term

            block.body = new_body

    def _inject_match_payload_bindings(
        self,
        fn: Normalized_fn,
        blocks_by_name: dict[str, TerminatedBlock],
        match_instr: Instruction_match,
    ) -> None:
        assert match_instr.cond_var.type is not None
        enum_struct = self._lookup_struct(match_instr.cond_var.type.name)
        if enum_struct is None:
            return

        payload_field_index_by_variant: dict[str, int] = {}
        for index, param in enumerate(enum_struct.params):
            if param.name == "tag":
                continue
            payload_field_index_by_variant[param.name] = index

        for case in match_instr.cases:
            if case.payload_var is None:
                continue
            field_index = payload_field_index_by_variant.get(case.variant)
            if field_index is None:
                continue

            case_block = blocks_by_name.get(case.label)
            if case_block is None:
                raise EhirCompileError(
                    f"Unknown match case label '{case.label}' in function '{fn.name}'",
                    code="EHIR2101",
                )

            field_type = enum_struct.params[field_index].type
            payload_out = TypedVariable(
                name=case.payload_var.name,
                type=case.payload_var.type or field_type,
            )
            high_level_field_index = self._high_level_enum_payload_field_index(
                match_instr.cond_var.type.name,
                case.variant,
            )
            if self._case_block_already_extracts_payload(
                case_block,
                match_instr.cond_var,
                field_index,
                high_level_field_index,
            ):
                continue

            case_block.body.insert(
                0,
                Instruction_getfield(
                    var_out=payload_out,
                    src=match_instr.cond_var,
                    field=TypedVariable(case.variant, field_type),
                ),
            )
            if needs_retain(payload_out.type, self._aggregate_names):
                case_block.body.insert(
                    1,
                    Instruction_call(
                        var_out=TypedVariable(f".retain_{payload_out.name}", Type("void")),
                        fn_name=retain_function_name(payload_out.type),
                        generics=[],
                        args=[payload_out],
                    ),
                )

    def _high_level_enum_payload_field_index(self, enum_name: str, variant_name: str) -> int | None:
        variant_names = self._enum_variants.get(enum_name)
        if variant_names is None:
            return None
        try:
            return variant_names.index(variant_name) + 1
        except ValueError:
            return None

    def _case_block_already_extracts_payload(
        self,
        case_block: TerminatedBlock,
        cond_var: Variable,
        lowered_field_index: int,
        high_level_field_index: int | None,
    ) -> bool:
        if len(case_block.body) < 1:
            return False

        field_read = case_block.body[0]
        if not isinstance(field_read, Instruction_getfield):
            return False
        if field_read.src.name != cond_var.name:
            return False
        accepted_field_names = {str(lowered_field_index)}
        if high_level_field_index is not None:
            accepted_field_names.add(str(high_level_field_index))
        return field_read.field.name in accepted_field_names

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
            params.append(Parameter(name=variant.name, type=payload_type))
        return Derective_struct(name=enum.name, generics=enum.generics, params=params)

    def _variant_payload_type(self, variant: UnitLikeVariant | TupleLikeVariant):
        if isinstance(variant, UnitLikeVariant):
            return None
        if isinstance(variant, TupleLikeVariant):
            if len(variant.types) == 0:
                return None
            return variant.types[0]
        raise EhirCompileError(f"Unknown enum variant kind: {type(variant)}", code="EHIR2103")

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

            box_target = self._box_field_target(owner_t, field)
            if box_target is not None:
                pointee, struct_decl = box_target
                payload_ptr_type = Pointer(pointee)
                payload_field_ptr = TypedVariable(
                    name=f".{instr.var_out.name}_{index}_box_payload_field_ptr",
                    type=Pointer(payload_ptr_type),
                )
                payload_ptr = TypedVariable(
                    name=f".{instr.var_out.name}_{index}_box_payload_ptr",
                    type=payload_ptr_type,
                )
                result.append(
                    Instruction_getfieldptr(
                        var_out=payload_field_ptr,
                        src=current_src,
                        field=Variable(name="0", type=payload_ptr_type),
                    )
                )
                result.append(Instruction_load(var_out=payload_ptr, var=payload_field_ptr))
                current_src = payload_ptr
                owner_t = pointee
            else:
                struct_decl = self._lookup_struct(owner_t.name)
            assert struct_decl is not None, f"Unknown struct for getfieldptr: {owner_t}"
            field_index = int(field.name) if field.name.isdigit() else None
            if field_index is not None:
                enum_variants = self._enum_variants.get(owner_t.name)
                if enum_variants is not None and field_index > 0:
                    # High-level enum field numbering is tag(0) + variant ordinal(1..N).
                    # Lowered enum layout stores only payload-carrying variants as named fields.
                    variant_ordinal = field_index - 1
                    assert variant_ordinal < len(enum_variants), (
                        f"Invalid enum variant field index {field_index} for {owner_t.name}"
                    )
                    variant_name = enum_variants[variant_ordinal]
                    payload_field_index = None
                    for idx, p in enumerate(struct_decl.params):
                        if p.name == variant_name:
                            payload_field_index = idx
                            break
                    assert payload_field_index is not None, (
                        f"Enum variant '{variant_name}' in {owner_t.name} has no payload field in lowered layout"
                    )
                    field_index = payload_field_index
            if field_index is None:
                for idx, p in enumerate(struct_decl.params):
                    if p.name == field.name:
                        field_index = idx
                        break
            assert field_index is not None, f"Unknown field {field.name} for {owner_t.name}"
            resolved_field_type = field.type or struct_decl.params[field_index].type
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
        owner_type = instr.var.type
        assert owner_type is not None

        # Mutating a value-typed variable must flow updated value back into the same SSA symbol.
        # Otherwise getfieldptr works over a temporary copy and changes are lost.
        if not isinstance(owner_type, (Pointer, Reference)):
            owner_ptr = TypedVariable(name=f".{instr.var.name}_setfield_owner_ptr", type=Pointer(owner_type))
            owner_writeback = TypedVariable(name=instr.var.name, type=owner_type)
            field_ptr = TypedVariable(
                name=f".{instr.var.name}_{final_field.name}_ptr",
                type=Pointer(final_field.type),
            )
            getfieldptr = Instruction_getfieldptr(
                var_out=field_ptr,
                src=owner_ptr,
                field=instr.field,
                field_path=list(instr.field_path),
            )
            store_value = Instruction_store(var_src=instr.value, var_dst=field_ptr)
            return [
                Instruction_salloc(var_out=owner_ptr, type=owner_type),
                Instruction_store(var_src=instr.var, var_dst=owner_ptr),
                *self._downgrade_getfieldptr(getfieldptr),
                store_value,
                Instruction_load(var_out=owner_writeback, var=owner_ptr),
            ]

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

        payload_field_index = next(i for i, param in enumerate(lowered_struct.params) if param.name == enum.variant)
        payload_field_ptr = TypedVariable(name=f".{out.name}_{enum.variant}_field_ptr", type=Pointer(payload_type))
        payload_getfieldptr = Instruction_getfieldptr(
            var_out=payload_field_ptr,
            src=out,
            field=TypedVariable(name=str(payload_field_index), type=payload_type),
        )
        payload_store = Instruction_store(var_src=payload_value, var_dst=payload_field_ptr)
        result.extend([payload_getfieldptr, payload_store])
        return result

    def _downgrade_sgetfield(self, instr: Instruction_sgetfield) -> list[Instruction]:
        assert instr.var_out.type is not None
        assert instr.src.type
        wrapped_struct = self._lookup_struct(instr.src.type.name)
        assert wrapped_struct is not None, f"Unknown wrapped struct for sgetfield: {instr.src.type.name}"
        if not wrapped_struct.params or not isinstance(wrapped_struct.params[0].type, Pointer):
            # Plain struct: static field access is equivalent to direct field access.
            return self._downgrade_getfield(
                Instruction_getfield(var_out=instr.var_out, src=instr.src, field=instr.field)
            )
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
        wrapped_struct = self._lookup_struct(instr.src.type.name)
        assert wrapped_struct is not None, f"Unknown wrapped struct for sgetfieldptr: {instr.src.type.name}"
        if not wrapped_struct.params or not isinstance(wrapped_struct.params[0].type, Pointer):
            # Plain struct: static field pointer access is equivalent to direct getfieldptr.
            return [Instruction_getfieldptr(var_out=instr.var_out, src=instr.src, field=instr.field)]
        wrapped_struct_ptr = TypedVariable(name=f".{instr.var_out.name}_sgfptr_ptr", type=wrapped_struct.params[0].type)
        getfield = Instruction_getfield(
            var_out=wrapped_struct_ptr, src=instr.src, field=TypedVariable("0", wrapped_struct.params[0].type)
        )
        getfieldptr = Instruction_getfieldptr(var_out=instr.var_out, src=wrapped_struct_ptr, field=instr.field)
        return [*self._downgrade_getfield(getfield), getfieldptr]

    def _downgrade_cbr(self, instr: Instruction_cbr) -> list[Instruction]:
        return [instr]

    def _downgrade_br(self, instr: Instruction_br) -> list[Instruction]:
        return [instr]

    def _downgrade_match(self, instr: Instruction_match) -> list[Instruction]:
        assert instr.cond_var.type is not None
        cond_src = instr.cond_var
        prelude: list[Instruction] = []
        variant_names = self._enum_variants.get(instr.cond_var.type.name)

        if variant_names is None:
            wrapped_struct = self._lookup_struct(instr.cond_var.type.name)
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
            raise EhirCompileError(
                f"Match condition must be a lowered enum, got '{instr.cond_var.type}'",
                code="EHIR2104",
            )

        tag = TypedVariable(name=f".{cond_src.name}_match_tag", type=Usize_t(8))
        get_tag = Instruction_getfield(
            var_out=tag,
            src=cond_src,
            field=TypedVariable("0", Usize_t(8)),
        )

        cases: list[tuple[Usize, str]] = []
        for case in instr.cases:
            if case.variant not in variant_names:
                raise EhirCompileError(
                    f"Unknown enum variant '{case.variant}' for '{cond_src.type.name}'",
                    code="EHIR2105",
                )
            cases.append((Usize(variant_names.index(case.variant), size=8), case.label))

        switch = Instruction_switch(cond_var=tag, default_case=instr.default_case, cases=cases)
        return [*prelude, *self._downgrade_getfield(get_tag), switch]
