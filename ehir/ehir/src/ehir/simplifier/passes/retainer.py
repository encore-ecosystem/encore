from copy import deepcopy

from ehir.resolver import EHIR_TypedModule
from ehir.core.block import TerminatedBlock
from ehir.core.derectives import Derective_enum, Derective_fn, Derective_struct
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    Instruction_br,
    Instruction_call,
    Instruction_callvoid,
    Instruction_capenum,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_cenum,
    Instruction_cstruct,
    Instruction_drop,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_load,
    Instruction_match,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_store,
    Instruction_switch,
    Instruction_wraph,
    Instruction_wraps,
)
from ehir.core.instructions.base import Assignable
from ehir.core.instructions.base import Instruction
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type
from ehir.core.variable import TypedVariable, Variable
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.drop_helper import (
    collect_aggregate_names,
    needs_retain,
    reference_storage_struct,
    retain_function_name,
)


class RetainInsertionPass(SimplifierPass):
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
        self._reference_type_names = {
            name
            for name, directive in structs.items()
            if reference_storage_struct(directive, structs) is not None
        }
        for directive in ast:
            if isinstance(directive, Derective_fn):
                self._instrument_fn(directive)
        return ast

    def _instrument_fn(self, fn: Derective_fn) -> None:
        if fn.name.startswith("__drop_") or fn.name.startswith("__retain_") or fn.name.startswith("__cfree"):
            return

        self._tmp_seq = 0
        self._fresh_owning_vars: set[str] = set()
        self._stack_slots: set[str] = set()
        self._owning_stack_slot_types: dict[str, Type] = {}
        self._initialized_stack_slots: set[str] = set()
        self._direct_return_loads: set[str] = set()
        self._direct_drop_loads: set[str] = set()
        self._return_var_to_stack_slot: dict[str, str] = {}
        self._reference_field_ptrs: set[str] = set()
        for param in fn.params:
            if isinstance(param.type, Pointer) and self._type_needs_retain(param.type.pointee):
                self._reference_field_ptrs.add(param.name)
        for block in fn.body:
            for instr in block.body:
                if isinstance(instr, Instruction_salloc):
                    self._stack_slots.add(instr.var_out.name)
                    if isinstance(instr.var_out.type, Pointer) and self._type_needs_retain(instr.var_out.type.pointee):
                        self._owning_stack_slot_types[instr.var_out.name] = instr.var_out.type.pointee
        for block in fn.body:
            instructions = self._instructions_with_term(block)
            for index, instr in enumerate(instructions[:-1]):
                next_instr = instructions[index + 1]
                if (
                    isinstance(instr, Instruction_load)
                    and isinstance(next_instr, Instruction_ret)
                    and instr.var_out.name == next_instr.var.name
                    and instr.var.name in self._owning_stack_slot_types
                ):
                    self._direct_return_loads.add(instr.var_out.name)
                    self._return_var_to_stack_slot[instr.var_out.name] = instr.var.name
                elif (
                    isinstance(instr, Instruction_load)
                    and isinstance(next_instr, Instruction_store)
                    and next_instr.var_dst.name == ".exit_var_ptr"
                    and instr.var_out.name == next_instr.var_src.name
                    and instr.var.name in self._owning_stack_slot_types
                ):
                    self._direct_return_loads.add(instr.var_out.name)
                    self._return_var_to_stack_slot[instr.var_out.name] = instr.var.name
                elif (
                    isinstance(instr, Instruction_load)
                    and isinstance(next_instr, Instruction_drop)
                    and instr.var_out.name == next_instr.var.name
                ):
                    self._direct_drop_loads.add(instr.var_out.name)
        initialized_in = self._compute_initialized_stack_slots(fn)
        arg_names = {param.name for param in fn.params}
        for block in fn.body:
            self._initialized_stack_slots = set(initialized_in.get(block.name, set()))
            new_body: list[Instruction] = []
            for instr in block.body:
                new_body.extend(self._instrument_instruction(instr, arg_names, fn.name))
            block.body = new_body

    def _instrument_instruction(self, instr: Instruction, arg_names: set[str], fn_name: str) -> list[Instruction]:
        if isinstance(instr, Instruction_ret):
            before_ret = self._drop_live_stack_slots_before_return(instr)
            return [*before_ret, instr]

        if isinstance(instr, Instruction_store):
            if self._is_owning_stack_store(instr):
                return self._instrument_owning_stack_store(instr)
            if self._is_reference_field_store(instr):
                return self._instrument_reference_field_store(instr)
            if instr.var_src.name in self._fresh_owning_vars:
                self._fresh_owning_vars.discard(instr.var_src.name)
                if instr.var_dst.name not in self._stack_slots:
                    return [instr]
            if self._is_concrete_box_store(fn_name) and self._needs_retain(instr.var_src):
                old = TypedVariable(f".old_{instr.var_dst.name}", deepcopy(instr.var_src.type))
                return [
                    Instruction_load(var_out=old, var=instr.var_dst),
                    *self._retain_calls([instr.var_src]),
                    instr,
                    Instruction_drop(var=deepcopy(old)),
                ]
            return [*self._retain_calls([instr.var_src]), instr]

        if isinstance(instr, Instruction_put):
            if instr.var.name in self._stack_slots:
                self._initialized_stack_slots.add(instr.var.name)
            return [instr]

        if isinstance(instr, Instruction_setfield):
            final_field = ([instr.field, *instr.field_path])[-1]
            if final_field.type is None or not needs_retain(final_field.type, self._aggregate_names):
                return [*self._retain_calls([instr.value]), instr]
            old = TypedVariable(f".old_{self._next_tmp()}_{instr.var.name}_{final_field.name}", deepcopy(final_field.type))
            return [
                *self._retain_calls([instr.value]),
                Instruction_getfield(
                    var_out=old,
                    src=deepcopy(instr.var),
                    field=deepcopy(instr.field),
                    field_path=deepcopy(instr.field_path or []),
                ),
                instr,
                Instruction_drop(var=old),
            ]

        if isinstance(instr, Instruction_getfieldptr):
            if isinstance(instr.var_out.type, Pointer) and self._type_needs_retain(instr.var_out.type.pointee):
                self._reference_field_ptrs.add(instr.var_out.name)
            return [instr]

        if isinstance(instr, (Instruction_load, Instruction_getfield, Instruction_sgetfield)):
            assert isinstance(instr.var_out, Variable)
            if isinstance(instr, Instruction_load) and (
                instr.var_out.name in self._direct_return_loads or instr.var_out.name in self._direct_drop_loads
            ):
                return [instr]
            return [instr, *self._retain_calls([instr.var_out])]

        if isinstance(instr, (Instruction_capstruct, Instruction_cstruct, Instruction_scstruct)):
            result = [*self._retain_calls(self._struct_args(instr.struct)), instr]
            self._mark_fresh_owning_result(instr)
            return result

        if isinstance(instr, (Instruction_capenum, Instruction_cenum)):
            result = [*self._retain_calls(self._enum_args(instr.enum)), instr]
            self._mark_fresh_owning_result(instr)
            return result

        if isinstance(instr, (Instruction_call, Instruction_callvoid)):
            result = [instr] if instr.is_unsafe else [*self._retain_calls(instr.args), instr]
            if isinstance(instr, Instruction_call):
                self._mark_fresh_owning_result(instr)
            return result

        if isinstance(instr, (Instruction_wraps, Instruction_wraph)):
            self._mark_fresh_owning_result(instr)

        return [instr]

    def _next_tmp(self) -> int:
        self._tmp_seq += 1
        return self._tmp_seq

    @staticmethod
    def _is_concrete_box_store(fn_name: str) -> bool:
        return fn_name.startswith("__Box_") and fn_name.endswith("::store")

    def _retain_calls(self, vars: list[Variable]) -> list[Instruction_call]:
        result: list[Instruction_call] = []
        for var in vars:
            if not self._needs_retain(var):
                continue
            result.append(
                Instruction_call(
                    var_out=TypedVariable(f".retain_{var.name}", Type("void")),
                    fn_name=retain_function_name(var.type),
                    generics=[],
                    args=[deepcopy(var)],
                )
            )
        return result

    def _needs_retain(self, var: Variable) -> bool:
        return var.type is not None and self._type_needs_retain(var.type)

    def _type_needs_retain(self, typ: Type) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return False
        return needs_retain(typ, self._aggregate_names) or typ.name in self._reference_type_names

    def _is_owning_stack_store(self, instr: Instruction_store) -> bool:
        if instr.var_dst.name not in self._owning_stack_slot_types:
            return False
        if instr.var_src.type is None:
            return True
        return self._type_needs_retain(instr.var_src.type)

    def _is_reference_field_store(self, instr: Instruction_store) -> bool:
        if instr.var_dst.name not in self._reference_field_ptrs:
            return False
        if not isinstance(instr.var_dst.type, Pointer):
            return False
        return self._type_needs_retain(instr.var_dst.type.pointee)

    def _drop_live_stack_slots_before_return(self, instr: Instruction_ret) -> list[Instruction]:
        returned_slot = self._return_var_to_stack_slot.get(instr.var.name)
        result: list[Instruction] = []
        for slot_name in sorted(self._initialized_stack_slots):
            if slot_name == returned_slot:
                continue
            pointee = self._owning_stack_slot_types.get(slot_name)
            if pointee is None:
                continue
            slot_var = TypedVariable(slot_name, Pointer(deepcopy(pointee)))
            value = TypedVariable(f".drop_slot_{slot_name}_{self._next_tmp()}", deepcopy(pointee))
            result.extend(
                [
                    Instruction_load(var_out=value, var=slot_var),
                    Instruction_drop(var=value),
                ]
            )
        return result

    def _instrument_owning_stack_store(self, instr: Instruction_store) -> list[Instruction]:
        was_initialized = instr.var_dst.name in self._initialized_stack_slots
        slot_type = self._owning_stack_slot_types[instr.var_dst.name]
        src = instr.var_src
        if src.type is None:
            src = TypedVariable(src.name, deepcopy(slot_type))
            instr = deepcopy(instr)
            instr.var_src = src
        is_fresh_owner = instr.var_src.name in self._fresh_owning_vars
        self._fresh_owning_vars.discard(instr.var_src.name)

        result: list[Instruction] = []
        if was_initialized:
            old = TypedVariable(f".old_{instr.var_dst.name}_{self._next_tmp()}", deepcopy(slot_type))
            result.append(Instruction_load(var_out=old, var=instr.var_dst))
        else:
            old = None

        if not is_fresh_owner:
            result.extend(self._retain_calls([src]))

        result.append(instr)
        self._initialized_stack_slots.add(instr.var_dst.name)

        if old is not None:
            result.append(Instruction_drop(var=old))
        return result

    def _instrument_reference_field_store(self, instr: Instruction_store) -> list[Instruction]:
        assert isinstance(instr.var_dst.type, Pointer)
        field_type = instr.var_dst.type.pointee
        src = instr.var_src
        if src.type is None:
            src = TypedVariable(src.name, deepcopy(field_type))
            instr = deepcopy(instr)
            instr.var_src = src

        old = TypedVariable(f".old_{instr.var_dst.name}_{self._next_tmp()}", deepcopy(field_type))
        is_fresh_owner = instr.var_src.name in self._fresh_owning_vars
        self._fresh_owning_vars.discard(instr.var_src.name)

        result: list[Instruction] = [Instruction_load(var_out=old, var=instr.var_dst)]
        if not is_fresh_owner:
            result.extend(self._retain_calls([src]))
        result.extend([instr, Instruction_drop(var=old)])
        return result

    def _mark_fresh_owning_result(self, instr: Assignable) -> None:
        if instr.var_out.type is None or not self._type_needs_retain(instr.var_out.type):
            return
        self._fresh_owning_vars.add(instr.var_out.name)

    def _compute_initialized_stack_slots(self, fn: Derective_fn) -> dict[str, set[str]]:
        block_names = [block.name for block in fn.body]
        block_by_name = {block.name: block for block in fn.body}
        successors = {name: self._successors(block_by_name[name], block_names, index) for index, name in enumerate(block_names)}
        predecessors: dict[str, set[str]] = {name: set() for name in block_names}
        for src, dsts in successors.items():
            for dst in dsts:
                if dst in predecessors:
                    predecessors[dst].add(src)

        generated = {block.name: self._initialized_slots_generated_by_block(block) for block in fn.body}
        initialized_in: dict[str, set[str]] = {name: set() for name in block_names}
        initialized_out: dict[str, set[str]] = {name: set(generated[name]) for name in block_names}

        changed = True
        while changed:
            changed = False
            for name in block_names:
                preds = predecessors[name]
                if preds:
                    incoming = set.intersection(*(initialized_out[pred] for pred in preds))
                else:
                    incoming = set()
                outgoing = incoming | generated[name]
                if incoming != initialized_in[name] or outgoing != initialized_out[name]:
                    initialized_in[name] = incoming
                    initialized_out[name] = outgoing
                    changed = True
        dominators = self._compute_dominators(block_names[0], set(block_names), predecessors)
        definition_blocks: dict[str, set[str]] = {}
        for block_name, slots in generated.items():
            for slot in slots:
                definition_blocks.setdefault(slot, set()).add(block_name)
        for block_name in block_names:
            for slot, definitions in definition_blocks.items():
                if any(definition != block_name and definition in dominators[block_name] for definition in definitions):
                    initialized_in[block_name].add(slot)
        return initialized_in

    @staticmethod
    def _compute_dominators(
        entry: str,
        block_names: set[str],
        predecessors: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        dominators: dict[str, set[str]] = {name: set(block_names) for name in block_names}
        dominators[entry] = {entry}
        changed = True
        while changed:
            changed = False
            for name in block_names:
                if name == entry:
                    continue
                preds = predecessors.get(name, set())
                if not preds:
                    next_dominators = {name}
                else:
                    next_dominators = {name} | set.intersection(*(dominators[pred] for pred in preds))
                if next_dominators != dominators[name]:
                    dominators[name] = next_dominators
                    changed = True
        return dominators

    def _initialized_slots_generated_by_block(self, block) -> set[str]:
        initialized: set[str] = set()
        for instr in block.body:
            if isinstance(instr, Instruction_put) and instr.var.name in self._stack_slots:
                initialized.add(instr.var.name)
            elif isinstance(instr, Instruction_store) and instr.var_dst.name in self._stack_slots:
                initialized.add(instr.var_dst.name)
        return initialized

    def _successors(self, block, block_names: list[str], index: int) -> list[str]:
        term = block.term if isinstance(block, TerminatedBlock) else (block.body[-1] if block.body else None)
        if term is None:
            return block_names[index + 1 : index + 2]
        if isinstance(term, Instruction_br):
            return [term.label]
        if isinstance(term, Instruction_cbr):
            return [term.true_br_label, term.else_br_label]
        if isinstance(term, Instruction_match):
            return [term.default_case, *(case.label for case in term.cases)]
        if isinstance(term, Instruction_switch):
            return [term.default_case, *(label for _, label in term.cases)]
        if isinstance(term, Instruction_ret):
            return []
        return block_names[index + 1 : index + 2]

    @staticmethod
    def _instructions_with_term(block) -> list[Instruction]:
        if isinstance(block, TerminatedBlock):
            return [*block.body, block.term]
        return list(block.body)

    @staticmethod
    def _struct_args(struct: Struct) -> list[Variable]:
        if struct.value is not None:
            return [struct.value]
        return list(struct.fields)

    @staticmethod
    def _enum_args(enum) -> list[Variable]:
        return list(enum.args)
