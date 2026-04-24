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
    Instruction_phi,
    Instruction_pcast,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
    Instruction_switch,
)
from ehir.core.instructions.base import Assignable
from ehir.core.type import Type
from ehir.core.variable import TypedVariable, Variable
from ehir.simplifier.drop_helper import needs_drop
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

    def run(self, ast: list[Derective]) -> list[Derective]:
        self._aggregate_names = {
            directive.name for directive in ast if isinstance(directive, (Derective_struct, Derective_enum))
        }
        for derective in ast:
            if isinstance(derective, Normalized_fn) and not derective.name.startswith("__retain_"):
                self._place_cfree(derective)
        return ast

    def _place_cfree(self, fn: Normalized_fn):
        self._usages = {}
        self._captures = {}
        self._returned_aliases = set()
        self._variables = {}
        self._arg_names = {param.name for param in fn.params}
        cfg: dict[str, list[str]] = {}
        observed: set[str] = set()

        name2block: dict[str, TerminatedBlock] = {}
        for block in fn.get_body():
            assert isinstance(block, TerminatedBlock)
            name2block[block.name] = block
            cfg[block.name] = []

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
                if child not in observed:
                    queue.append(name2block[child])

        all_paths = self._find_all_paths(fn.entry_block.name, fn.exit_block.name, cfg)
        for var, block in self._captures.items():
            assert isinstance(fn.exit_block.term, Instruction_ret)
            if fn.exit_block.term.var.name == var:
                continue
            if var in self._returned_aliases:
                continue

            outer_paths = []
            inner_paths = []
            for path in all_paths:
                if any(usg in path for usg in self._usages[var]):
                    inner_paths.append(path)
                else:
                    outer_paths.append(path)

            if not inner_paths:
                continue

            shared_path = self._find_shared_path(inner_paths)
            least_shared_node = shared_path[0]
            if least_shared_node == fn.entry_block.name:
                # LLVM entry block cannot have predecessors.
                # If CFG merge-point resolution falls back to entry,
                # place cfree at function exit instead.
                least_shared_node = fn.exit_block.name

            if any(least_shared_node in pth for pth in outer_paths):
                dealloc_block = TerminatedBlock(
                    name=f".dealloc_{var}",
                    body=[],
                    term=Instruction_br(label=least_shared_node),
                )
                fn.body.append(dealloc_block)

                for path in inner_paths:
                    index = path.index(least_shared_node)
                    prev_block = path[index - 1]
                    block = name2block[prev_block]

                    if isinstance(block.term, Instruction_br):
                        block.term.label = dealloc_block.name
                    elif isinstance(block.term, Instruction_cbr):
                        if block.term.true_br_label == least_shared_node:
                            block.term.true_br_label = dealloc_block.name
                        elif block.term.else_br_label == least_shared_node:
                            block.term.else_br_label = dealloc_block.name
                    elif isinstance(block.term, Instruction_switch):
                        if block.term.default_case == least_shared_node:
                            block.term.default_case = dealloc_block.name
                        else:
                            for i in range(len(block.term.cases)):
                                if block.term.cases[i][1] == least_shared_node:
                                    block.term.cases[i] = (block.term.cases[i][0], dealloc_block.name)
                    elif isinstance(block.term, Instruction_match):
                        if block.term.default_case == least_shared_node:
                            block.term.default_case = dealloc_block.name
                        else:
                            for i, case in enumerate(block.term.cases):
                                if case.label == least_shared_node:
                                    block.term.cases[i] = type(case)(variant=case.variant, label=dealloc_block.name)

            else:
                dealloc_block = name2block[least_shared_node]

            dealloc_block.body.append(
                Instruction_call(
                    var_out=TypedVariable(name=f".drop_{var}", type=Type("void")),
                    fn_name="Drop::drop",
                    generics=[deepcopy(generic) for generic in self._variables[var].type.generics],
                    args=[TypedVariable(self._variables[var].name, self._variables[var].type)],
                )
            )

    @staticmethod
    def _find_shared_path(paths: list[list[str]]) -> list[str]:
        available_stepbacks = min(map(len, paths))
        n = 1
        for _ in range(available_stepbacks):
            if all(path[-n] == paths[0][-n] for path in paths):
                n += 1

        return paths[0][-n + 1 :]

    @staticmethod
    def _find_all_paths(start: str, finish: str, cfg: dict[str, list[str]]):
        def dfs(current: str, path: list[str], visited: set[str], all_paths: list[list[str]]):
            path.append(current)
            visited.add(current)

            if current == finish:
                all_paths.append(path.copy())
            else:
                for neighbor in cfg.get(current, []):
                    if neighbor not in visited:
                        dfs(neighbor, path, visited, all_paths)

            # (backtracking)
            path.pop()
            visited.remove(current)

        all_paths = []
        visited = set()
        dfs(start, [], visited, all_paths)
        return all_paths

    def _add_variable_usage(self, var: Variable):
        self._variables[var.name] = var

        if var.type is not None and needs_drop(var.type, self._aggregate_names):
            self._usages[var.name] = self._usages.get(var.name, set()) | {self._curr_block}

    def _add_variable_capture(self, var: Variable):
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
            elif isinstance(
                instr,
                (
                    Instruction_scstruct,
                    Instruction_cstruct,
                    Instruction_capstruct,
                    Instruction_cenum,
                    Instruction_capenum,
                ),
            ):
                if hasattr(instr, "struct"):
                    args = [instr.struct.value] if instr.struct.value is not None else instr.struct.args
                elif instr.enum.payload is not None:
                    args = (
                        [instr.enum.payload.value] if instr.enum.payload.value is not None else instr.enum.payload.args
                    )
                else:
                    args = []
                for arg in args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, Instruction_hfree):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_pcast):
                self._add_variable_usage(instr.var)
            elif isinstance(instr, Instruction_call):
                for arg in instr.args:
                    self._add_variable_usage(arg)
            elif isinstance(instr, BinOp):
                self._add_variable_usage(instr.lhs)
                self._add_variable_usage(instr.rhs)
            elif isinstance(instr, Instruction_phi):
                for arg in instr.args:
                    self._add_variable_usage(arg.var)
            else:
                raise NotImplementedError(f"Variable usage not define for {instr}")
