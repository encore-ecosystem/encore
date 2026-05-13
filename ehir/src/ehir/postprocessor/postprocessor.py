from ehir.builder import EHIR_Module
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_extern_fn, Derective_struct
from ehir.core.instructions import (
    BinOp,
    ControlFlow,
    Instruction_add,
    Instruction_and,
    Instruction_br,
    Instruction_call,
    Instruction_capprim,
    Instruction_cbr,
    Instruction_gep,
    Instruction_geq,
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
    Instruction_mod,
    Instruction_mul,
    Instruction_neq,
    Instruction_or,
    Instruction_pcast,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_shl,
    Instruction_shr,
    Instruction_store,
    Instruction_sub,
    Instruction_switch,
    Instruction_xor,
)
from ehir.core.instructions.arithmetic import Instruction_div
from ehir.core.instructions.base import Instruction
from ehir.core.variable import TypedVariable
from ehir.postprocessor.instructions import (
    ProcessedControlFlow,
    ProcessedInstruction,
    ProcessedInstruction_add,
    ProcessedInstruction_and,
    ProcessedInstruction_br,
    ProcessedInstruction_call,
    ProcessedInstruction_cbr,
    ProcessedInstruction_div,
    ProcessedInstruction_gep,
    ProcessedInstruction_geq,
    ProcessedInstruction_getfieldptr,
    ProcessedInstruction_grt,
    ProcessedInstruction_halloc,
    ProcessedInstruction_hfree,
    ProcessedInstruction_hrealloc,
    ProcessedInstruction_ieq,
    ProcessedInstruction_leq,
    ProcessedInstruction_les,
    ProcessedInstruction_load,
    ProcessedInstruction_mod,
    ProcessedInstruction_mul,
    ProcessedInstruction_neq,
    ProcessedInstruction_or,
    ProcessedInstruction_pcast,
    ProcessedInstruction_phi,
    ProcessedInstruction_put,
    ProcessedInstruction_ret,
    ProcessedInstruction_salloc,
    ProcessedInstruction_shl,
    ProcessedInstruction_shr,
    ProcessedInstruction_store,
    ProcessedInstruction_sub,
    ProcessedInstruction_switch,
    ProcessedInstruction_xor,
)
from ehir.postprocessor.module import ProcessedModule
from ehir.postprocessor.special import ProcessedBlock
from ehir.simplifier.normalizer.norm_fn import Normalized_fn

from .derectives import (
    ProcessedDerective_extern_fn,
    ProcessedDerective_fn,
    ProcessedDerective_struct,
)


class Postprocessor:
    def run(self, raw_mod: EHIR_Module) -> ProcessedModule:
        self._known_type_suffixes = {
            directive.name for directive in raw_mod.ast if isinstance(directive, (Derective_struct, Derective_enum))
        } | {
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
        }
        mod = ProcessedModule(id=raw_mod.id, structs=[], funcs=[])
        for derective in raw_mod.ast:
            if isinstance(derective, Normalized_fn):
                mod.funcs.append(
                    ProcessedDerective_fn(
                        name=self._emit_symbol_name(derective.name),
                        params=derective.params,
                        ret_type=derective.ret_type,
                        entry_block=self._validate_block(derective.entry_block),
                        body=[self._validate_block(b) for b in derective.body],
                        exit_block=self._validate_block(derective.exit_block),
                    )
                )
            elif isinstance(derective, Derective_extern_fn):
                mod.funcs.append(
                    ProcessedDerective_extern_fn(
                        name=self._emit_symbol_name(derective.name),
                        params=derective.params,
                        ret_type=derective.ret_type,
                    )
                )

            elif isinstance(derective, Derective_struct):
                mod.structs.append(
                    ProcessedDerective_struct(
                        name=derective.name,
                        fields=derective.params,
                    )
                )

            else:
                raise NotImplementedError(f"Unknown derective: {derective}")
        return mod

    def _validate_block(self, block: TerminatedBlock) -> ProcessedBlock:
        return ProcessedBlock(
            name=block.name,
            body=[self._validate_instr(instr) for instr in block.body],
            term=self._validate_term(block.term),
        )

    def _validate_instr(self, instr: Instruction) -> ProcessedInstruction:
        if isinstance(instr, Instruction_salloc):
            assert instr.var_out.type
            return ProcessedInstruction_salloc(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type), type=instr.type
            )
        if isinstance(instr, Instruction_put):
            assert instr.var.type
            return ProcessedInstruction_put(
                primitive=instr.primitive, var=TypedVariable(instr.var.name, instr.var.type)
            )
        if isinstance(instr, Instruction_load):
            assert instr.var_out.type
            assert instr.var.type
            return ProcessedInstruction_load(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                var=TypedVariable(instr.var.name, instr.var.type),
            )
        if isinstance(instr, Instruction_call):
            assert instr.var_out.type
            assert len(instr.generics) == 0
            args = []
            for arg in instr.args:
                assert arg.type
                args.append(TypedVariable(arg.name, arg.type))
            return ProcessedInstruction_call(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                fn_name=self._emit_symbol_name(instr.fn_name),
                args=args,
            )

        if isinstance(instr, Instruction_capprim):
            raise AssertionError("Instruction_capprim must be downgraded before postprocessing")
        if isinstance(instr, Instruction_halloc):
            assert instr.var_out.type
            return ProcessedInstruction_halloc(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                type=instr.type,
            )
        if isinstance(instr, Instruction_hrealloc):
            assert instr.var_out.type
            assert instr.var.type
            assert instr.count.type
            return ProcessedInstruction_hrealloc(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                var=TypedVariable(instr.var.name, instr.var.type),
                count=TypedVariable(instr.count.name, instr.count.type),
            )

        if isinstance(instr, Instruction_hfree):
            assert instr.var.type
            return ProcessedInstruction_hfree(var=TypedVariable(instr.var.name, instr.var.type))
        if isinstance(instr, Instruction_store):
            assert instr.var_src.type
            assert instr.var_dst.type
            return ProcessedInstruction_store(
                var_src=TypedVariable(instr.var_src.name, instr.var_src.type),
                var_dst=TypedVariable(instr.var_dst.name, instr.var_dst.type),
            )
        if isinstance(instr, Instruction_pcast):
            assert instr.var_out.type
            assert instr.var.type
            return ProcessedInstruction_pcast(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                var=TypedVariable(instr.var.name, instr.var.type),
                type=instr.type,
            )
        if isinstance(instr, Instruction_getfieldptr):
            assert instr.var_out.type
            assert instr.src.type
            assert instr.field.type

            return ProcessedInstruction_gep(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                var=TypedVariable(instr.src.name, instr.src.type),
                offset=int(instr.field.name),
            )
        if isinstance(instr, Instruction_gep):
            assert instr.var_out.type
            assert instr.var.type
            assert instr.offset.type
            return ProcessedInstruction_gep(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                var=TypedVariable(instr.var.name, instr.var.type),
                offset=TypedVariable(instr.offset.name, instr.offset.type),
            )
        if isinstance(instr, Instruction_getptr):
            self._build_getptr(instr)
        if isinstance(instr, BinOp):
            return self._build_processed_binop(instr)
        raise NotImplementedError(instr)

    def _validate_term(self, term: ControlFlow) -> ProcessedControlFlow:
        if isinstance(term, Instruction_br):
            return ProcessedInstruction_br(label=term.label)

        if isinstance(term, Instruction_cbr):
            assert isinstance(term.cond_var, TypedVariable)
            return ProcessedInstruction_cbr(
                cond_var=term.cond_var,
                true_br_label=term.true_br_label,
                else_br_label=term.else_br_label,
            )
        if isinstance(term, Instruction_ret):
            assert term.var.type
            return ProcessedInstruction_ret(var=TypedVariable(term.var.name, term.var.type))

        if isinstance(term, Instruction_switch):
            assert term.cond_var.type
            return ProcessedInstruction_switch(
                cond_var=TypedVariable(term.cond_var.name, term.cond_var.type),
                default_case=term.default_case,
                cases=term.cases,
            )

        raise NotImplementedError(term)

    def _emit_symbol_name(self, name: str) -> str:
        if "::" not in name:
            return name

        owner_text, method_name = name.rsplit("::", 1)
        owner_name = owner_text.split("[", 1)[0]
        return f"{owner_name}__{self._emit_method_name(method_name)}"

    def _emit_method_name(self, method_name: str) -> str:
        if "__" in method_name:
            return method_name

        parts = method_name.split("_")
        if len(parts) < 2:
            return method_name

        for index in range(1, len(parts)):
            suffix = "_".join(parts[index:])
            if suffix in self._known_type_suffixes:
                prefix = "_".join(parts[:index])
                if prefix:
                    return f"{prefix}__{suffix}"
                return suffix

        return method_name

    def _build_processed_binop(self, instr: BinOp):
        assert instr.var_out.type
        assert instr.lhs.type
        assert instr.rhs.type
        result = None
        if isinstance(instr, Instruction_add):
            result = ProcessedInstruction_add

        if isinstance(instr, Instruction_sub):
            result = ProcessedInstruction_sub

        if isinstance(instr, Instruction_mul):
            result = ProcessedInstruction_mul

        if isinstance(instr, Instruction_div):
            result = ProcessedInstruction_div

        if isinstance(instr, Instruction_mod):
            result = ProcessedInstruction_mod

        if isinstance(instr, Instruction_shl):
            result = ProcessedInstruction_shl

        if isinstance(instr, Instruction_shr):
            result = ProcessedInstruction_shr

        if isinstance(instr, Instruction_or):
            result = ProcessedInstruction_or

        if isinstance(instr, Instruction_and):
            result = ProcessedInstruction_and

        if isinstance(instr, Instruction_xor):
            result = ProcessedInstruction_xor

        if isinstance(instr, Instruction_ieq):
            result = ProcessedInstruction_ieq

        if isinstance(instr, Instruction_neq):
            result = ProcessedInstruction_neq

        if isinstance(instr, Instruction_les):
            result = ProcessedInstruction_les

        if isinstance(instr, Instruction_leq):
            result = ProcessedInstruction_leq

        if isinstance(instr, Instruction_grt):
            result = ProcessedInstruction_grt

        if isinstance(instr, Instruction_geq):
            result = ProcessedInstruction_geq

        assert result
        return result(
            var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
            lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
            rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
        )
