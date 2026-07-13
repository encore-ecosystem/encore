from ehir.resolver import EHIR_TypedModule
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_fn, Derective_impl
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    ControlFlow,
    Instruction_br,
    Instruction_cbr,
    Instruction_load,
    Instruction_match,
    Instruction_ret,
    Instruction_salloc,
    Instruction_store,
    Instruction_switch,
)
from ehir.core.type import Pointer, Type
from ehir.core.variable import TypedVariable
from ehir.errors import EhirCompileError
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.normalizer.norm_fn import Normalized_fn


class NormalizerPass(SimplifierPass):
    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        new = []
        for derective in ast:
            if isinstance(derective, Derective_fn):
                self._terminate_blocks(derective)
                new.append(self._normalize_fn(derective))
            elif isinstance(derective, Derective_impl):
                normalized_methods = []
                for method in derective.methods:
                    if isinstance(method, Derective_fn):
                        self._terminate_blocks(method)
                        normalized_methods.append(self._normalize_fn(method))
                    else:
                        normalized_methods.append(method)
                derective.methods = normalized_methods
                new.append(derective)
            else:
                new.append(derective)
        return new

    def _terminate_blocks(self, derective: Derective_fn):
        new_blocks = []
        referenced_labels = self._referenced_labels(derective)
        for block_index, block in enumerate(derective.body):
            term_index = None
            for instr_index, instr in enumerate(block.body):
                if isinstance(instr, ControlFlow):
                    term_index = instr_index
                    break

            if term_index is None:
                if len(block.body) == 0:
                    if block_index + 1 >= len(derective.body):
                        if block.name not in referenced_labels:
                            continue
                        raise EhirCompileError(
                            f"Empty block has no successor: function '{derective.name}', block '{block.name}'"
                        )
                    next_block = derective.body[block_index + 1]
                    new_blocks.append(TerminatedBlock(name=block.name, body=[], term=Instruction_br(label=next_block.name)))
                    continue
                raise EhirCompileError(
                    f"Block must end with a control flow instruction: function '{derective.name}', block '{block.name}'"
                )

            block_body = block.body[:term_index]
            term = block.body[term_index]
            assert isinstance(term, ControlFlow)
            new_blocks.append(TerminatedBlock(name=block.name, body=block_body, term=term))
        derective.body = new_blocks

    def _referenced_labels(self, derective: Derective_fn) -> set[str]:
        labels: set[str] = set()
        for block in derective.body:
            for instr in block.body:
                if isinstance(instr, Instruction_br):
                    labels.add(instr.label)
                elif isinstance(instr, Instruction_cbr):
                    labels.add(instr.true_br_label)
                    labels.add(instr.else_br_label)
                elif isinstance(instr, Instruction_switch):
                    labels.add(instr.default_case)
                    labels.update(label for _, label in instr.cases)
                elif isinstance(instr, Instruction_match):
                    labels.add(instr.default_case)
                    labels.update(case.label for case in instr.cases)
        return labels

    def _normalize_fn(self, derective: Derective_fn) -> Normalized_fn:
        # Step 0: Prepare block mapping
        block_mapping: dict[str, TerminatedBlock] = {}
        num_ret = 0
        ret_block_name = None
        for block in derective.body:
            if block.name in block_mapping:
                raise EhirCompileError(f"Double definition of block {block.name}")
            assert isinstance(block, TerminatedBlock)
            block_mapping[block.name] = block
            if isinstance(block.term, Instruction_ret):
                num_ret += 1
                ret_block_name = block.name

        if "entry" not in block_mapping:
            raise EhirCompileError(f"Function '{derective.name}' must have an entry block")

        if num_ret == 1 and ret_block_name != "entry":
            assert ret_block_name
            return Normalized_fn.new(
                name=derective.name,
                params=derective.params,
                ret_type=derective.ret_type,
                entry_block=block_mapping["entry"],
                body=[block for name, block in block_mapping.items() if name not in ("entry", ret_block_name)],
                exit_block=block_mapping[ret_block_name],
            )

        if "exit" in block_mapping:
            raise EhirCompileError(f"Function '{derective.name}' has reserved block `exit`")

        if derective.ret_type.name == "void":
            for block in block_mapping.values():
                if isinstance(block.term, Instruction_ret):
                    block.term = Instruction_br(label="exit")

            exit_block = TerminatedBlock(
                name="exit",
                body=[],
                term=Instruction_ret(TypedVariable(name=".void", type=Type("void"))),
            )
            return Normalized_fn.new(
                name=derective.name,
                params=derective.params,
                ret_type=derective.ret_type,
                entry_block=block_mapping["entry"],
                body=[block for name, block in block_mapping.items() if name != "entry"],
                exit_block=exit_block,
            )

        # Step 1: Create resulting variable in entry block
        exit_var_ptr = TypedVariable(name=".exit_var_ptr", type=Pointer(derective.ret_type))
        entry_block = block_mapping["entry"]
        entry_block.body.append(
            Instruction_salloc(
                var_out=exit_var_ptr,
                type=derective.ret_type,
            )
        )

        # Step 2: Replace `ret` to `getptr` + `store` + `br exit`
        for block in block_mapping.values():
            if isinstance(block.term, Instruction_ret):
                assert block.term.var.type is not None
                store = Instruction_store(
                    var_src=block.term.var,
                    var_dst=exit_var_ptr,
                )
                block.body.append(store)
                block.term = Instruction_br(label="exit")

        # Step 3: Create and add exit block
        exit_var = TypedVariable(name=".exit_var", type=derective.ret_type)
        exit_block = TerminatedBlock(
            name="exit", body=[Instruction_load(var_out=exit_var, var=exit_var_ptr)], term=Instruction_ret(exit_var)
        )

        # Step 4: Return normalized block
        return Normalized_fn.new(
            name=derective.name,
            params=derective.params,
            ret_type=derective.ret_type,
            entry_block=entry_block,
            body=[block for name, block in block_mapping.items() if name != "entry"],
            exit_block=exit_block,
        )


Normalizer = NormalizerPass
