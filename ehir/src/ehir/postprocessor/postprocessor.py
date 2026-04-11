from ehir.builder import EHIR_Module
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_struct
from ehir.core.instructions.base import Instruction
from ehir.core.instructions.capture import Instruction_lcpos
from ehir.core.instructions.control_flow import (
    Instruction_br,
    Instruction_call,
    Instruction_cbr,
    Instruction_phi,
    Instruction_ret,
    Instruction_switch,
)
from ehir.core.instructions.control_flow.base import ControlFlow
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_load,
    Instruction_pcast,
    Instruction_put,
    Instruction_salloc,
    Instruction_store,
)
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mod,
    Instruction_mul,
    Instruction_shl,
    Instruction_shr,
    Instruction_sub,
)
from ehir.core.instructions.operators.comparison import (
    Instruction_geq,
    Instruction_grt,
    Instruction_leq,
    Instruction_les,
)
from ehir.core.instructions.operators.logic import (
    Instruction_and,
    Instruction_ieq,
    Instruction_neq,
    Instruction_or,
    Instruction_xor,
)
from ehir.core.variable import TypedVariable
from ehir.postprocessor.instructions import (
    ProcessedControlFlow,
    ProcessedInstruction,
    ProcessedInstruction_add,
    ProcessedInstruction_br,
    ProcessedInstruction_call,
    ProcessedInstruction_cbr,
    ProcessedInstruction_div,
    ProcessedInstruction_grt,
    ProcessedInstruction_ieq,
    ProcessedInstruction_les,
    ProcessedInstruction_load,
    ProcessedInstruction_mul,
    ProcessedInstruction_neq,
    ProcessedInstruction_phi,
    ProcessedInstruction_put,
    ProcessedInstruction_ret,
    ProcessedInstruction_salloc,
    ProcessedInstruction_store,
    ProcessedInstruction_sub,
    ProcessedInstruction_switch,
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
        mod = ProcessedModule(id=raw_mod.id, structs=[], funcs=[])
        for derective in raw_mod.ast:
            if isinstance(derective, Normalized_fn):
                assert len(derective.generics) == 0

                mod.funcs.append(
                    ProcessedDerective_fn(
                        name=derective.name,
                        params=derective.params,
                        ret_type=derective.ret_type,
                        entry_block=self._validate_block(derective.entry_block),
                        body=[self._validate_block(b) for b in derective.body],
                        exit_block=self._validate_block(derective.exit_block),
                    )
                )

            elif isinstance(derective, Derective_struct):
                assert len(derective.generics) == 0

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
                fn_name=instr.fn_name,
                args=args,
            )

        if isinstance(instr, Instruction_lcpos):
            self._build_lcpos(instr)
        if isinstance(instr, Instruction_halloc):
            self._build_halloc(instr)
        if isinstance(instr, Instruction_add):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_add(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )
        if isinstance(instr, Instruction_sub):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_sub(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )
        if isinstance(instr, Instruction_mul):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_mul(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )
        if isinstance(instr, Instruction_div):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_div(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )

        if isinstance(instr, Instruction_or):
            self._build_or(instr)
        if isinstance(instr, Instruction_and):
            self._build_and(instr)
        if isinstance(instr, Instruction_xor):
            self._build_xor(instr)
        if isinstance(instr, Instruction_ieq):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_ieq(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )

        if isinstance(instr, Instruction_neq):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_neq(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )

        if isinstance(instr, Instruction_les):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_les(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )
        if isinstance(instr, Instruction_leq):
            self._build_leq(instr)
        if isinstance(instr, Instruction_grt):
            assert instr.var_out.type
            assert instr.lhs.type
            assert instr.rhs.type

            return ProcessedInstruction_grt(
                var_out=TypedVariable(instr.var_out.name, instr.var_out.type),
                lhs=TypedVariable(instr.lhs.name, instr.lhs.type),
                rhs=TypedVariable(instr.rhs.name, instr.rhs.type),
            )
        if isinstance(instr, Instruction_geq):
            self._build_geq(instr)

        if isinstance(instr, Instruction_mod):
            self._build_mod(instr)
        if isinstance(instr, Instruction_shl):
            self._build_shl(instr)
        if isinstance(instr, Instruction_shr):
            self._build_shr(instr)
        if isinstance(instr, Instruction_hfree):
            self._build_hfree(instr)
        if isinstance(instr, Instruction_store):
            assert instr.var_src.type
            assert instr.var_dst.type
            return ProcessedInstruction_store(
                var_src=TypedVariable(instr.var_src.name, instr.var_src.type),
                var_dst=TypedVariable(instr.var_dst.name, instr.var_dst.type),
            )
        if isinstance(instr, Instruction_pcast):
            self._build_pcast(instr)
        if isinstance(instr, Instruction_getfieldptr):
            self._build_getfieldptr(instr)
        if isinstance(instr, Instruction_getfield):
            self._build_getfield(instr)
        if isinstance(instr, Instruction_getptr):
            self._build_getptr(instr)
        if isinstance(instr, Instruction_phi):
            assert instr.var_out.type
            pairs: list[tuple[TypedVariable, str]] = []
            for pair in instr.args:
                assert pair.var.type
                pairs.append((TypedVariable(pair.var.name, pair.var.type), pair.block_label))
            return ProcessedInstruction_phi(var_out=TypedVariable(instr.var_out.name, instr.var_out.type), args=pairs)

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
