from collections import deque
from copy import deepcopy

from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    BinOp,
    Instruction_br,
    Instruction_call,
    Instruction_capenum,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_cenum,
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_gep,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_load,
    Instruction_match,
    Instruction_pcast,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
    Instruction_switch,
    Instruction_wraph,
    Instruction_wraps,
)
from ehir.core.instructions.base import Assignable
from ehir.core.type import Type
from ehir.core.variable import TypedVariable, Variable
from ehir.simplifier.drop_helper import collect_aggregate_names, needs_drop
from ehir.simplifier.normalizer.norm_fn import Normalized_fn

SKIPABLE = (
    Instruction_br,
    Instruction_halloc,
    Instruction_hrealloc,
    Instruction_capprim,
    Instruction_cpos,
    Instruction_salloc,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
)


class Deallocator:
    _usages: dict[str, set[str]]
    _captures: dict[str, str]
    _returned_aliases: set[str]
    _curr_block: str
    _variables: dict[str, Variable]
    _arg_names: set[str]
    _aggregate_names: set[str]
    _dealloc_name_seq: int

    def run(self, ast: list[Derective]) -> list[Derective]:
        structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct) and not directive.generics
        }
        enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum) and not directive.generics
        }
        self._aggregate_names = collect_aggregate_names(structs, enums)
        for derective in ast:
            if isinstance(derective, Normalized_fn) and not self._is_runtime_memory_fn(derective.name):
                self._place_cfree(derective)
        return ast

    def _is_runtime_memory_fn(self, name: str) -> bool:
        return (
            name.startswith("__Box_")
            or name.startswith("__drop_")
            or name.startswith("__retain_")
            or name.startswith("__cfree")
        )

    def _place_cfree(self, fn: Normalized_fn):
        self._usages = {}
        self._captures = {}
        self._returned_aliases = set()
        self._variables = {}
        self._arg_names = {param.name for param in fn.params}
        self._dealloc_name_seq = 0
        cfg: dict[str, list[str]] = {}
        predecessors: dict[str, set[str]] = {}
        observed: set[str] = set()

        name2block: dict[str, TerminatedBlock] = {}
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            name2block[block.name] = block
            cfg[block.name] = []
            predecessors[block.name] = set()

        queue: deque[TerminatedBlock] = deque([fn.entry_block])
        while queue:
            block = queue.popleft()
            self._collect_variable_usages(block)
            observed.add(block.name)

            children: list[str] = []
            if isinstance(block.term, Instruction_br):
                children.append(block.term.label)
            elif isinstance(block.term, Instruction_cbr):
                children.append(block.term.true_br_label)
                children.append(block.term.else_br_label)
            elif isinstance(block.term, Instruction_switch):
                children.append(block.term.default_case)
                for case in block.term.cases:
                    children.append(case[1])
            elif isinstance(block.term, Instruction_match):
                children.append(block.term.default_case)
                for case in block.term.cases:
                    children.append(case.label)

            for child in children:
                if child not in cfg[block.name]:
                    cfg[block.name].append(child)
                    predecessors[child].add(block.name)
                if child not in observed:
                    queue.append(name2block[child])

        dominators = self._compute_dominators(fn.entry_block.name, observed, predecessors)
        for var, block in self._captures.items():
            assert isinstance(fn.exit_block.term, Instruction_ret)
            if fn.exit_block.term.var.name == var:
                continue
            if var in self._returned_aliases:
                continue

            var_def = self._variables[var]
            if var_def.type is None:
                continue
            drop_edges = self._collect_drop_edges(
                def_block=block,
                cfg=cfg,
                dominators=dominators,
                observed=observed,
            )
            placed = False
            for src, dst in sorted(drop_edges):
                dealloc_block_name = self._next_dealloc_block_name(var)
                dealloc_block = TerminatedBlock(
                    name=dealloc_block_name,
                    body=[
                        Instruction_call(
                            var_out=TypedVariable(name=f".drop_{var}", type=Type("void")),
                            fn_name="Drop::drop",
                            generics=[deepcopy(generic) for generic in var_def.type.generics],
                            args=[TypedVariable(var_def.name, var_def.type)],
                        )
                    ],
                    term=Instruction_br(label=dst),
                )
                fn.body.append(dealloc_block)
                name2block[dealloc_block_name] = dealloc_block
                self._redirect_block_edge(name2block[src], dst, dealloc_block_name)
                placed = True

            if not placed and self._is_dominated(fn.exit_block.name, block, dominators):
                fn.exit_block.body.append(
                    Instruction_call(
                        var_out=TypedVariable(name=f".drop_{var}", type=Type("void")),
                        fn_name="Drop::drop",
                        generics=[deepcopy(generic) for generic in var_def.type.generics],
                        args=[TypedVariable(var_def.name, var_def.type)],
                    )
                )

    def _next_dealloc_block_name(self, var_name: str) -> str:
        self._dealloc_name_seq += 1
        return f".dealloc_{var_name}_{self._dealloc_name_seq}"

    def _redirect_block_edge(self, block: TerminatedBlock, src_label: str, dst_label: str) -> None:
        if isinstance(block.term, Instruction_br):
            if block.term.label == src_label:
                block.term.label = dst_label
            return

        if isinstance(block.term, Instruction_cbr):
            if block.term.true_br_label == src_label:
                block.term.true_br_label = dst_label
            elif block.term.else_br_label == src_label:
                block.term.else_br_label = dst_label
            return

        if isinstance(block.term, Instruction_switch):
            if block.term.default_case == src_label:
                block.term.default_case = dst_label
            for i in range(len(block.term.cases)):
                if block.term.cases[i][1] == src_label:
                    block.term.cases[i] = (block.term.cases[i][0], dst_label)
            return

        if isinstance(block.term, Instruction_match):
            if block.term.default_case == src_label:
                block.term.default_case = dst_label
            for i, case in enumerate(block.term.cases):
                if case.label == src_label:
                    block.term.cases[i] = type(case)(variant=case.variant, label=dst_label)

    @staticmethod
    def _compute_dominators(
        entry: str,
        observed: set[str],
        predecessors: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        all_nodes = set(observed)
        dominators: dict[str, set[str]] = {node: set(all_nodes) for node in all_nodes}
        dominators[entry] = {entry}

        changed = True
        while changed:
            changed = False
            for node in all_nodes:
                if node == entry:
                    continue

                preds = predecessors.get(node, set()) & all_nodes
                if not preds:
                    new_dom = {node}
                else:
                    pred_doms = [dominators[pred] for pred in preds]
                    new_dom = {node} | set.intersection(*pred_doms)

                if new_dom != dominators[node]:
                    dominators[node] = new_dom
                    changed = True

        return dominators

    @staticmethod
    def _is_dominated(node: str, dominator: str, dominators: dict[str, set[str]]) -> bool:
        return dominator in dominators.get(node, set())

    def _collect_drop_edges(
        self,
        def_block: str,
        cfg: dict[str, list[str]],
        dominators: dict[str, set[str]],
        observed: set[str],
    ) -> set[tuple[str, str]]:
        drop_edges: set[tuple[str, str]] = set()
        for src in observed:
            if not self._is_dominated(src, def_block, dominators):
                continue
            for dst in cfg.get(src, []):
                if not self._is_dominated(dst, def_block, dominators):
                    drop_edges.add((src, dst))
        return drop_edges

    def _add_variable_usage(self, var: Variable):
        if cached := self._variables.get(var.name):
            if cached.type is None and var.type is not None:
                self._variables[var.name] = var
            else:
                var = cached
        else:
            self._variables[var.name] = var

        if var.type is not None and needs_drop(var.type, self._aggregate_names):
            self._usages[var.name] = self._usages.get(var.name, set()) | {self._curr_block}

    def _add_variable_capture(self, var: Variable):
        if var.name.startswith("."):
            # Compiler-generated temporaries frequently alias user-owned aggregates.
            # Dropping them as independent owners causes duplicate cascades.
            return
        if cached := self._variables.get(var.name):
            if cached.type is None and var.type is not None:
                self._variables[var.name] = var
            else:
                var = cached
        else:
            self._variables[var.name] = var

        if var.name not in self._arg_names and var.type is not None and needs_drop(var.type, self._aggregate_names):
            self._captures[var.name] = self._curr_block
            self._add_variable_usage(var)

    def _collect_variable_usages(self, block: TerminatedBlock):
        self._curr_block = block.name
        for instr in [*block.body, block.term]:
            if isinstance(instr, Assignable):
                self._add_variable_capture(instr.var_out)

            if isinstance(instr, SKIPABLE):
                pass
            elif isinstance(instr, Instruction_ret):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_cbr):
                self._add_variable_usage(instr.cond_var)
            elif isinstance(instr, Instruction_match):
                self._add_variable_usage(instr.cond_var)
            elif isinstance(instr, Instruction_switch):
                self._add_variable_usage(instr.cond_var)
            elif isinstance(instr, Instruction_getptr):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_gep):
                self._add_variable_usage(instr.var)
                self._add_variable_usage(instr.offset)
            elif isinstance(instr, Instruction_hrealloc):
                self._add_variable_usage(instr.var)
                self._add_variable_usage(instr.count)
            elif isinstance(instr, Instruction_store):
                if instr.var_dst.name == ".exit_var_ptr":
                    self._returned_aliases.add(instr.var_src.name)
                self._add_variable_usage(instr.var_src)
                self._add_variable_usage(instr.var_dst)
            elif isinstance(instr, Instruction_setfield):
                self._add_variable_usage(instr.var)
                self._add_variable_usage(instr.value)
            elif isinstance(instr, Instruction_load):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_put):
                self._add_variable_usage(instr.var)
            elif isinstance(
                instr,
                (
                    Instruction_scstruct,
                    Instruction_cstruct,
                    Instruction_capstruct,
                ),
            ):
                args = [instr.struct.value] if instr.struct.value is not None else instr.struct.fields
                for arg in args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, (Instruction_cenum, Instruction_capenum)):
                for arg in instr.enum.args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, Instruction_hfree):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_pcast):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_call):
                for arg in instr.args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, (Instruction_wraps, Instruction_wraph)):
                self._add_variable_usage(instr.variable)
            elif isinstance(instr, BinOp):
                self._add_variable_usage(instr.lhs)
                self._add_variable_usage(instr.rhs)
            else:
                raise NotImplementedError(f"Variable usage not define for {instr}")
