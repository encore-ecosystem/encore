from copy import deepcopy

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_call, Instruction_callvoid
from ehir.core.type import Reference, Type
from ehir.core.variable import Variable
from ehir.simplifier.base import SimplifierPass


class InstanceCallLoweringPass(SimplifierPass):
    def run(self, module: EHIR_Module) -> EHIR_Module:
        module.ast = self._run_ast(module.ast)
        return module

    def _run_ast(self, ast: list[Derective]) -> list[Derective]:
        for directive in ast:
            if not isinstance(directive, Derective_fn):
                continue
            vars_by_name = {param.name: deepcopy(param.type) for param in directive.params}
            for block in directive.body:
                for instr in block.body:
                    self._lower_call(instr, vars_by_name)
                    self._learn_var_types(instr, vars_by_name)
        return ast

    def _lower_call(self, instr, vars_by_name: dict[str, Type]) -> None:
        if not isinstance(instr, (Instruction_call, Instruction_callvoid)):
            return
        if "::" not in instr.fn_name:
            return
        owner_text, method_name = instr.fn_name.rsplit("::", 1)
        owner_type = vars_by_name.get(owner_text)
        if owner_type is None:
            return

        receiver = Variable(name=owner_text, type=deepcopy(owner_type))
        owner_base = owner_type.pointee if isinstance(owner_type, Reference) else owner_type
        if owner_base.generics:
            generic_owner = Type(owner_base.name, [Type("T") for _ in owner_base.generics])
            instr.fn_name = f"{generic_owner}::{method_name}"
        else:
            instr.fn_name = f"{owner_base}::{method_name}"
        instr.args = [receiver, *instr.args]
        if isinstance(instr, Instruction_callvoid):
            instr.assign_to = Variable(name=owner_text, type=deepcopy(owner_type))

    def _learn_var_types(self, instr, vars_by_name: dict[str, Type]) -> None:
        if isinstance(instr, Instruction_call):
            if instr.var_out.type is not None:
                vars_by_name[instr.var_out.name] = deepcopy(instr.var_out.type)
            return
        if isinstance(instr, Instruction_callvoid):
            if instr.assign_to is not None and instr.assign_to.type is not None:
                vars_by_name[instr.assign_to.name] = deepcopy(instr.assign_to.type)
            return
        out = getattr(instr, "var_out", None)
        if isinstance(out, Variable) and out.type is not None:
            vars_by_name[out.name] = deepcopy(out.type)
