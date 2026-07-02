from collections import deque
from copy import deepcopy

from ehir.resolver import EHIR_TypedModule
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    BinOp,
    Instruction_br,
    Instruction_call,
    Instruction_callvoid,
    Instruction_capenum,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_cenum,
    Instruction_cpos,
    Instruction_cstruct,
    Instruction_drop,
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
from ehir.core.type import Pointer, Type
from ehir.core.variable import TypedVariable, Variable
from ehir.errors import EhirCompileError
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.drop_helper import collect_aggregate_names, needs_drop
from ehir.simplifier.normalizer.norm_fn import Normalized_fn

SKIPABLE = (
    Instruction_br,
    Instruction_halloc,
    Instruction_hrealloc,
    Instruction_capprim,
    Instruction_cpos,
    Instruction_salloc,
)


class DeallocatorPass(SimplifierPass):
    _usages: dict[str, set[str]]
    _captures: dict[str, str]
    _returned_alias_blocks: dict[str, set[str]]
    _curr_block: str
    _variables: dict[str, Variable]
    _arg_names: set[str]
    _aggregate_names: set[str]
    _dealloc_name_seq: int
    _fresh_owning_vars: set[str]
    _owning_stack_slots: dict[str, Type]
    _stack_slot_defs: dict[str, str]
    _stack_slot_usages: dict[str, set[str]]
    _returned_stack_slot_blocks: dict[str, set[str]]
    _loaded_from_stack_slot: dict[str, str]
    _explicitly_dropped_stack_slots: dict[str, set[str]]
    _needs_drop_cache: dict[str, bool]

    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        structs = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_struct)
        }
        enums = {
            directive.name: directive
            for directive in ast
            if isinstance(directive, Derective_enum)
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

    def _needs_drop_type(self, typ: Type) -> bool:
        key = str(typ)
        cached = self._needs_drop_cache.get(key)
        if cached is not None:
            return cached
        value = needs_drop(typ, self._aggregate_names)
        self._needs_drop_cache[key] = value
        return value

    def _place_cfree(self, fn: Normalized_fn):
        self._validate_manual_drop(fn)
        self._usages = {}
        self._captures = {}
        self._returned_alias_blocks = {}
        self._variables = {}
        self._arg_names = {param.name for param in fn.params}
        self._dealloc_name_seq = 0
        self._fresh_owning_vars = set()
        self._owning_stack_slots = {}
        self._stack_slot_defs = {}
        self._stack_slot_usages = {}
        self._returned_stack_slot_blocks = {}
        self._loaded_from_stack_slot = {}
        self._explicitly_dropped_stack_slots = {}
        self._needs_drop_cache = {}
        cfg: dict[str, list[str]] = {}
        predecessors: dict[str, set[str]] = {}
        observed: set[str] = set()
        block_order: list[str] = []

        name2block: dict[str, TerminatedBlock] = {}
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            name2block[block.name] = block
            cfg[block.name] = []
            predecessors[block.name] = set()

        queue: deque[TerminatedBlock] = deque([fn.entry_block])
        while queue:
            block = queue.popleft()
            observed.add(block.name)
            block_order.append(block.name)

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

        entry_initialized = {
            param.name
            for param in fn.params
            if param.type is not None and self._needs_drop_type(param.type)
        }
        initialized_in = self._compute_definitely_initialized(
            fn=fn,
            name2block=name2block,
            block_order=block_order,
            predecessors=predecessors,
            observed=observed,
            entry_initialized=entry_initialized,
        )
        self._insert_drop_before_reassign(
            fn=fn,
            name2block=name2block,
            block_order=block_order,
            initialized_in=initialized_in,
        )

        for param in fn.params:
            if param.type is None or not self._needs_drop_type(param.type):
                continue
            self._variables[param.name] = TypedVariable(param.name, param.type)
            self._captures[param.name] = fn.entry_block.name
            self._usages[param.name] = {fn.entry_block.name}

        for block_name in block_order:
            self._collect_variable_usages(name2block[block_name], set(initialized_in[block_name]))

        dominators = self._compute_dominators(fn.entry_block.name, observed, predecessors)
        edge_heads: dict[tuple[str, str], str] = {}
        for var, block in reversed(list(self._captures.items())):
            assert isinstance(fn.exit_block.term, Instruction_ret)
            if fn.exit_block.term.var.name == var:
                continue
            var_def = self._variables[var]
            if var_def.type is None:
                continue
            drop_edges = self._collect_drop_edges(
                def_block=block,
                cfg=cfg,
                dominators=dominators,
                observed=observed,
                usage_blocks=self._usages.get(var, set()),
                returned_blocks=self._returned_alias_blocks.get(var, set()),
            )
            placed = False
            for src, dst in sorted(drop_edges):
                dealloc_block_name = self._next_dealloc_block_name(var)
                edge_key = (src, dst)
                current_head = edge_heads.get(edge_key, dst)
                dealloc_block = TerminatedBlock(
                    name=dealloc_block_name,
                    body=[Instruction_drop(var=TypedVariable(var_def.name, var_def.type))],
                    term=Instruction_br(label=current_head),
                )
                fn.body.append(dealloc_block)
                name2block[dealloc_block_name] = dealloc_block
                self._redirect_block_edge(name2block[src], current_head, dealloc_block_name)
                edge_heads[edge_key] = dealloc_block_name
                placed = True

            if (
                not placed
                and not self._returned_alias_blocks.get(var)
                and self._is_dominated(fn.exit_block.name, block, dominators)
            ):
                fn.exit_block.body.append(Instruction_drop(var=TypedVariable(var_def.name, var_def.type)))

        self._place_stack_slot_drops(
            fn=fn,
            name2block=name2block,
            cfg=cfg,
            dominators=dominators,
            observed=observed,
            edge_heads=edge_heads,
        )

    def _compute_definitely_initialized(
        self,
        fn: Normalized_fn,
        name2block: dict[str, TerminatedBlock],
        block_order: list[str],
        predecessors: dict[str, set[str]],
        observed: set[str],
        entry_initialized: set[str],
    ) -> dict[str, set[str]]:
        candidate_vars = set(entry_initialized)
        gen: dict[str, set[str]] = {}

        for block_name in block_order:
            block = name2block[block_name]
            gen_block: set[str] = set()
            for instr in block.body:
                if not isinstance(instr, Assignable):
                    continue
                if instr.var_out.type is not None and self._needs_drop_type(instr.var_out.type):
                    gen_block.add(instr.var_out.name)
            gen[block_name] = gen_block
            candidate_vars |= gen_block

        initialized_in: dict[str, set[str]] = {}
        initialized_out: dict[str, set[str]] = {}
        entry = fn.entry_block.name
        for block_name in observed:
            if block_name == entry:
                initialized_in[block_name] = set(entry_initialized)
            else:
                initialized_in[block_name] = set(candidate_vars)
            initialized_out[block_name] = self._transfer_initialized(name2block[block_name], initialized_in[block_name])

        changed = True
        while changed:
            changed = False
            for block_name in block_order:
                if block_name == entry:
                    in_set = set(entry_initialized)
                else:
                    preds = predecessors.get(block_name, set()) & observed
                    if not preds:
                        in_set = set()
                    else:
                        pred_sets = [initialized_out[pred] for pred in preds]
                        in_set = set.intersection(*pred_sets) if pred_sets else set()
                out_set = self._transfer_initialized(name2block[block_name], in_set)
                if in_set != initialized_in[block_name] or out_set != initialized_out[block_name]:
                    initialized_in[block_name] = in_set
                    initialized_out[block_name] = out_set
                    changed = True

        return initialized_in

    def _transfer_initialized(self, block: TerminatedBlock, in_set: set[str]) -> set[str]:
        initialized = set(in_set)
        fresh_owning_vars: set[str] = set()
        for instr in block.body:
            if isinstance(instr, Instruction_drop):
                initialized.discard(instr.var.name)
                fresh_owning_vars.discard(instr.var.name)
                continue
            if isinstance(instr, Instruction_store) and instr.var_src.name in fresh_owning_vars:
                initialized.discard(instr.var_src.name)
                fresh_owning_vars.discard(instr.var_src.name)
            if not isinstance(instr, Assignable):
                continue
            if instr.var_out.type is not None and self._needs_drop_type(instr.var_out.type):
                initialized.add(instr.var_out.name)
                if self._is_fresh_owning_result(instr):
                    fresh_owning_vars.add(instr.var_out.name)
        return initialized

    def _insert_drop_before_reassign(
        self,
        fn: Normalized_fn,
        name2block: dict[str, TerminatedBlock],
        block_order: list[str],
        initialized_in: dict[str, set[str]],
    ) -> None:
        # Types are already fully resolved at this stage and treated as immutable
        # metadata inside this pass. Re-copying them on every assignment dominates
        # compile time for large modules.
        var_types: dict[str, Type] = {param.name: param.type for param in fn.params if param.type is not None}
        for block_name in block_order:
            block = name2block[block_name]
            initialized = set(initialized_in[block_name])
            new_body = []
            for instr in block.body:
                if isinstance(instr, Instruction_drop):
                    initialized.discard(instr.var.name)
                    new_body.append(instr)
                    continue
                if isinstance(instr, Instruction_store) and instr.var_src.name in self._fresh_owning_vars:
                    initialized.discard(instr.var_src.name)
                    self._fresh_owning_vars.discard(instr.var_src.name)
                if isinstance(instr, Assignable):
                    current_type = instr.var_out.type if instr.var_out.type is not None else var_types.get(instr.var_out.name)
                    if (
                        instr.var_out.name in initialized
                        and instr.var_out.name not in self._arg_names
                        and current_type is not None
                        and self._needs_drop_type(current_type)
                    ):
                        new_body.append(Instruction_drop(var=TypedVariable(instr.var_out.name, current_type)))
                    if current_type is not None and self._needs_drop_type(current_type):
                        initialized.add(instr.var_out.name)
                        var_types[instr.var_out.name] = current_type
                        if self._is_fresh_owning_result(instr):
                            self._fresh_owning_vars.add(instr.var_out.name)
                new_body.append(instr)
            block.body = new_body

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
                    # `dst_label` is an intermediate deallocation block. Match payload
                    # binding must stay with the original arm body, otherwise the
                    # downgrader injects a second payload extraction into the
                    # deallocation block and creates competing SSA definitions.
                    block.term.cases[i] = type(case)(
                        variant=case.variant,
                        label=dst_label,
                        payload_var=None,
                    )

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
        usage_blocks: set[str],
        returned_blocks: set[str] | None = None,
    ) -> set[tuple[str, str]]:
        returned_blocks = returned_blocks or set()
        dominated_region = {
            block
            for block in observed
            if self._is_dominated(block, def_block, dominators)
        }
        live_region = self._compute_live_region(
            cfg=cfg,
            dominated_region=dominated_region,
            usage_blocks=usage_blocks,
        )
        drop_edges: set[tuple[str, str]] = set()
        for src in dominated_region:
            if src not in live_region:
                continue
            if src in returned_blocks:
                continue
            for dst in cfg.get(src, []):
                if dst == def_block and src != def_block:
                    drop_edges.add((src, dst))
                elif dst not in live_region:
                    drop_edges.add((src, dst))
        return drop_edges

    @staticmethod
    def _compute_live_region(
        cfg: dict[str, list[str]],
        dominated_region: set[str],
        usage_blocks: set[str],
    ) -> set[str]:
        predecessors: dict[str, set[str]] = {block: set() for block in dominated_region}
        for src, dsts in cfg.items():
            if src not in dominated_region:
                continue
            for dst in dsts:
                if dst in dominated_region:
                    predecessors.setdefault(dst, set()).add(src)

        live_region: set[str] = set()
        worklist: deque[str] = deque(block for block in usage_blocks if block in dominated_region)
        while worklist:
            block = worklist.popleft()
            if block in live_region:
                continue
            live_region.add(block)
            worklist.extend(predecessors.get(block, set()) - live_region)
        return live_region

    def _place_stack_slot_drops(
        self,
        *,
        fn: Normalized_fn,
        name2block: dict[str, TerminatedBlock],
        cfg: dict[str, list[str]],
        dominators: dict[str, set[str]],
        observed: set[str],
        edge_heads: dict[tuple[str, str], str],
    ) -> None:
        for slot, def_block in sorted(self._stack_slot_defs.items()):
            slot_type = self._owning_stack_slots.get(slot)
            if slot_type is None:
                continue
            usage_blocks = self._stack_slot_usages.get(slot, set())
            if not usage_blocks:
                continue
            drop_edges = self._collect_drop_edges(
                def_block=def_block,
                cfg=cfg,
                dominators=dominators,
                observed=observed,
                usage_blocks=usage_blocks,
                returned_blocks=self._returned_stack_slot_blocks.get(slot, set()),
            )
            for src, dst in sorted(drop_edges):
                if src in self._explicitly_dropped_stack_slots.get(slot, set()):
                    continue
                edge_key = (src, dst)
                current_head = edge_heads.get(edge_key, dst)
                drop_block_name = self._next_dealloc_block_name(f"slot_{slot}")
                value = TypedVariable(f".drop_slot_{slot}_{self._dealloc_name_seq}", slot_type)
                drop_block = TerminatedBlock(
                    name=drop_block_name,
                    body=[
                        Instruction_load(var_out=value, var=TypedVariable(slot, Pointer(slot_type))),
                        Instruction_drop(var=value),
                    ],
                    term=Instruction_br(label=current_head),
                )
                fn.body.append(drop_block)
                name2block[drop_block_name] = drop_block
                self._redirect_block_edge(name2block[src], current_head, drop_block_name)
                edge_heads[edge_key] = drop_block_name

    def _add_variable_usage(self, var: Variable):
        if cached := self._variables.get(var.name):
            if cached.type is None and var.type is not None:
                self._variables[var.name] = var
            else:
                var = cached
        else:
            self._variables[var.name] = var

        if var.type is not None and self._needs_drop_type(var.type):
            self._usages[var.name] = self._usages.get(var.name, set()) | {self._curr_block}

    def _add_stack_slot_usage(self, slot: str) -> None:
        if slot in self._owning_stack_slots:
            self._stack_slot_usages.setdefault(slot, set()).add(self._curr_block)

    def _add_variable_capture(self, var: Variable):
        if cached := self._variables.get(var.name):
            if cached.type is None and var.type is not None:
                self._variables[var.name] = var
            else:
                var = cached
        else:
            self._variables[var.name] = var

        if var.type is not None and self._needs_drop_type(var.type):
            self._captures[var.name] = self._curr_block
            self._add_variable_usage(var)

    def _collect_variable_usages(self, block: TerminatedBlock, initialized: set[str]):
        self._curr_block = block.name
        fresh_owning_vars: set[str] = set()
        for instr in [*block.body, block.term]:
            if (
                isinstance(instr, Instruction_salloc)
                and isinstance(instr.var_out.type, Pointer)
                and self._needs_drop_type(instr.var_out.type.pointee)
            ):
                self._owning_stack_slots[instr.var_out.name] = instr.var_out.type.pointee
                self._stack_slot_defs[instr.var_out.name] = self._curr_block
            if isinstance(instr, Assignable):
                self._add_variable_capture(instr.var_out)
                if instr.var_out.type is not None and self._needs_drop_type(instr.var_out.type):
                    initialized.add(instr.var_out.name)
                    if self._is_fresh_owning_result(instr):
                        fresh_owning_vars.add(instr.var_out.name)

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
                    self._returned_alias_blocks.setdefault(instr.var_src.name, set()).add(self._curr_block)
                    if slot := self._loaded_from_stack_slot.get(instr.var_src.name):
                        self._returned_stack_slot_blocks.setdefault(slot, set()).add(self._curr_block)
                self._add_stack_slot_usage(instr.var_dst.name)
                if instr.var_src.name in fresh_owning_vars:
                    self._captures.pop(instr.var_src.name, None)
                    initialized.discard(instr.var_src.name)
                    fresh_owning_vars.discard(instr.var_src.name)
                else:
                    self._add_variable_usage(instr.var_src)
                self._add_variable_usage(instr.var_dst)
            elif isinstance(instr, Instruction_setfield):
                self._add_variable_usage(instr.var)
                self._add_variable_usage(instr.value)
            elif isinstance(instr, Instruction_load):
                self._add_stack_slot_usage(instr.var.name)
                if instr.var.name in self._owning_stack_slots:
                    self._loaded_from_stack_slot[instr.var_out.name] = instr.var.name
                    if instr.var_out.name.startswith(".drop_slot_"):
                        self._explicitly_dropped_stack_slots.setdefault(instr.var.name, set()).add(self._curr_block)
                self._add_variable_usage(instr.var)
            elif isinstance(instr, (Instruction_getfield, Instruction_getfieldptr)):
                self._add_variable_usage(instr.src)
            elif isinstance(instr, (Instruction_sgetfield, Instruction_sgetfieldptr)):
                self._add_variable_usage(instr.src)
            elif isinstance(instr, Instruction_put):
                self._add_stack_slot_usage(instr.var.name)
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
            elif isinstance(instr, Instruction_drop):
                self._add_variable_usage(instr.var)
                self._captures.pop(instr.var.name, None)
                initialized.discard(instr.var.name)
                fresh_owning_vars.discard(instr.var.name)
            elif isinstance(instr, Instruction_pcast):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, (Instruction_call, Instruction_callvoid)):
                for arg in instr.args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, (Instruction_wraps, Instruction_wraph)):
                self._add_variable_usage(instr.variable)
            elif isinstance(instr, BinOp):
                self._add_variable_usage(instr.lhs)
                self._add_variable_usage(instr.rhs)
            else:
                raise NotImplementedError(f"Variable usage not define for {instr}")

    def _is_fresh_owning_result(self, instr: Assignable) -> bool:
        if instr.var_out.type is None or not needs_drop(instr.var_out.type, self._aggregate_names):
            return False
        return isinstance(
            instr,
            (
                Instruction_call,
                Instruction_capstruct,
                Instruction_cstruct,
                Instruction_scstruct,
                Instruction_capenum,
                Instruction_cenum,
                Instruction_wraps,
                Instruction_wraph,
            ),
        )

    def _validate_manual_drop(self, fn: Normalized_fn) -> None:
        arg_names = {param.name for param in fn.params}
        name2block = {block.name: block for block in fn.get_body()}
        cfg: dict[str, list[str]] = {name: [] for name in name2block}
        predecessors: dict[str, set[str]] = {name: set() for name in name2block}
        observed: set[str] = set()

        queue: deque[TerminatedBlock] = deque([fn.entry_block])
        while queue:
            block = queue.popleft()
            observed.add(block.name)
            children: list[str] = []
            if isinstance(block.term, Instruction_br):
                children.append(block.term.label)
            elif isinstance(block.term, Instruction_cbr):
                children.extend([block.term.true_br_label, block.term.else_br_label])
            elif isinstance(block.term, Instruction_switch):
                children.append(block.term.default_case)
                children.extend(label for _, label in block.term.cases)
            elif isinstance(block.term, Instruction_match):
                children.append(block.term.default_case)
                children.extend(case.label for case in block.term.cases)
            for child in children:
                if child not in cfg[block.name]:
                    cfg[block.name].append(child)
                    predecessors[child].add(block.name)
                if child not in observed:
                    queue.append(name2block[child])

        in_dropped: dict[str, set[str]] = {name: set() for name in observed}
        out_dropped: dict[str, set[str]] = {name: set() for name in observed}
        worklist: deque[str] = deque([fn.entry_block.name])

        while worklist:
            block_name = worklist.popleft()
            block = name2block[block_name]
            if block_name == fn.entry_block.name:
                merged = set()
            else:
                preds = predecessors.get(block_name, set()) & observed
                merged = set()
                for pred in preds:
                    merged |= out_dropped[pred]
            in_dropped[block_name] = merged

            dropped = set(merged)
            for instr in block.body:
                if isinstance(instr, Instruction_drop):
                    if instr.var.name in arg_names:
                        raise EhirCompileError(
                            f"Manual drop for function parameter '{instr.var.name}' is forbidden", code="EHIR3001"
                        )
                    if instr.var.name in dropped:
                        raise EhirCompileError(f"Double drop of '{instr.var.name}' in fn '{fn.name}'", code="EHIR3002")
                    dropped.add(instr.var.name)
                    continue
                for used in self._used_vars(instr):
                    if used.name in dropped:
                        raise EhirCompileError(
                            f"Use-after-drop of '{used.name}' in fn '{fn.name}'", code="EHIR3003"
                        )
                if isinstance(instr, Assignable):
                    dropped.discard(instr.var_out.name)

            for used in self._used_vars(block.term):
                if used.name in dropped:
                    raise EhirCompileError(f"Use-after-drop of '{used.name}' in fn '{fn.name}'", code="EHIR3003")

            if dropped != out_dropped[block_name]:
                out_dropped[block_name] = dropped
                for succ in cfg.get(block_name, []):
                    worklist.append(succ)

    def _used_vars(self, instr) -> list[Variable]:
        if isinstance(instr, Instruction_ret):
            return [instr.var]
        if isinstance(instr, Instruction_cbr):
            return [instr.cond_var]
        if isinstance(instr, Instruction_match):
            return [instr.cond_var]
        if isinstance(instr, Instruction_switch):
            return [instr.cond_var]
        if isinstance(instr, Instruction_getptr):
            return [instr.var]
        if isinstance(instr, Instruction_gep):
            return [instr.var, instr.offset]
        if isinstance(instr, Instruction_hrealloc):
            return [instr.var, instr.count]
        if isinstance(instr, Instruction_store):
            return [instr.var_src, instr.var_dst]
        if isinstance(instr, Instruction_setfield):
            return [instr.var, instr.value]
        if isinstance(instr, Instruction_load):
            return [instr.var]
        if isinstance(instr, (Instruction_getfield, Instruction_getfieldptr)):
            return [instr.src]
        if isinstance(instr, (Instruction_sgetfield, Instruction_sgetfieldptr)):
            return [instr.src]
        if isinstance(instr, Instruction_put):
            return [instr.var]
        if isinstance(instr, (Instruction_scstruct, Instruction_cstruct, Instruction_capstruct)):
            return [instr.struct.value] if instr.struct.value is not None else list(instr.struct.fields)
        if isinstance(instr, (Instruction_cenum, Instruction_capenum)):
            return list(instr.enum.args)
        if isinstance(instr, Instruction_hfree):
            return [instr.var]
        if isinstance(instr, Instruction_drop):
            return [instr.var]
        if isinstance(instr, Instruction_pcast):
            return [instr.var]
        if isinstance(instr, (Instruction_call, Instruction_callvoid)):
            return list(instr.args)
        if isinstance(instr, (Instruction_wraps, Instruction_wraph)):
            return [instr.variable]
        if isinstance(instr, BinOp):
            return [instr.lhs, instr.rhs]
        return []


Deallocator = DeallocatorPass
