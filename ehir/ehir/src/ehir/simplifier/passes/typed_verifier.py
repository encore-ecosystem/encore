from dataclasses import dataclass

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_extern_fn, Derective_fn
from ehir.core.instructions import (
    Instruction_call,
    Instruction_callvoid,
    Instruction_cbr,
    Instruction_drop,
    Instruction_hrealloc,
    Instruction_load,
    Instruction_match,
    Instruction_pcast,
    Instruction_ret,
    Instruction_setfield,
    Instruction_store,
    Instruction_switch,
    Instruction_wraph,
    Instruction_wraps,
)
from ehir.core.instructions.base import Assignable
from ehir.core.type import Pointer, Reference, Type
from ehir.core.variable import Variable
from ehir.errors import EhirCompileError
from ehir.simplifier.base import SimplifierPass


@dataclass(frozen=True)
class _FunctionContext:
    name: str
    generic_names: set[str]
    known_functions: set[str]


class TypedVerifierPass(SimplifierPass):
    def run(self, module: EHIR_Module) -> EHIR_Module:
        known_functions = {
            directive.name for directive in module.ast if isinstance(directive, (Derective_fn, Derective_extern_fn))
        }
        for directive in module.ast:
            if isinstance(directive, Derective_fn):
                self._verify_fn(directive, known_functions)
            elif isinstance(directive, Derective_extern_fn):
                self._verify_extern_fn(directive)
        return module

    def _verify_extern_fn(self, fn: Derective_extern_fn) -> None:
        for param in fn.params:
            self._require_type(param, f"extern parameter '{fn.name}::{param.name}'")
        self._require_concrete_type(fn.ret_type, f"extern return type '{fn.name}'", set())

    def _verify_fn(self, fn: Derective_fn, known_functions: set[str]) -> None:
        context = _FunctionContext(
            name=fn.name,
            generic_names={generic.name for generic in fn.generics},
            known_functions=known_functions,
        )
        for param in fn.params:
            self._require_type(param, f"parameter '{fn.name}::{param.name}'")
            if not context.generic_names:
                self._require_concrete_type(param.type, f"parameter '{fn.name}::{param.name}'", context.generic_names)
        if not context.generic_names:
            self._require_concrete_type(fn.ret_type, f"return type '{fn.name}'", context.generic_names)
        for block in fn.body:
            for instr in block.body:
                self._verify_instruction(instr, context)

    def _verify_instruction(self, instr, context: _FunctionContext) -> None:
        if isinstance(instr, Assignable):
            self._require_type(instr.var_out, f"output of '{instr}' in '{context.name}'")
            if not context.generic_names:
                self._require_concrete_type(instr.var_out.type, f"output of '{instr}'", context.generic_names)

        if isinstance(instr, Instruction_call):
            self._verify_call_target(instr.fn_name, context)
            self._verify_no_call_generics(instr.fn_name, instr.generics, context)
            self._require_type(instr.var_out, f"call output '{instr.fn_name}' in '{context.name}'")
            for arg in instr.args:
                self._require_type(arg, f"argument '{arg.name}' of call '{instr.fn_name}' in '{context.name}'")
            return

        if isinstance(instr, Instruction_callvoid):
            self._verify_call_target(instr.fn_name, context)
            self._verify_no_call_generics(instr.fn_name, instr.generics, context)
            for arg in instr.args:
                self._require_type(arg, f"argument '{arg.name}' of callvoid '{instr.fn_name}' in '{context.name}'")
            if instr.assign_to is not None:
                self._require_type(instr.assign_to, f"callvoid assign target '{instr.assign_to.name}' in '{context.name}'")
            return

        if isinstance(instr, Instruction_ret):
            self._require_type(instr.var, f"return value in '{context.name}'")
        elif isinstance(instr, Instruction_load):
            self._require_type(instr.var, f"load source '{instr.var.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_store):
            self._require_type(instr.var_src, f"store source '{instr.var_src.name}' in '{context.name}'")
            self._require_type(instr.var_dst, f"store destination '{instr.var_dst.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_setfield):
            self._require_type(instr.var, f"setfield owner '{instr.var.name}' in '{context.name}'")
            self._require_type(instr.value, f"setfield value '{instr.value.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_hrealloc):
            self._require_type(instr.var, f"hrealloc source '{instr.var.name}' in '{context.name}'")
            self._require_type(instr.count, f"hrealloc count '{instr.count.name}' in '{context.name}'")
        elif isinstance(instr, (Instruction_wraps, Instruction_wraph)):
            self._require_type(instr.variable, f"wrap source '{instr.variable.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_pcast):
            self._require_type(instr.var, f"pcast source '{instr.var.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_cbr):
            self._require_type(instr.cond_var, f"cbr condition '{instr.cond_var.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_switch):
            self._require_type(instr.cond_var, f"switch condition '{instr.cond_var.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_match):
            self._require_type(instr.cond_var, f"match condition '{instr.cond_var.name}' in '{context.name}'")
            for case in instr.cases:
                if case.payload_var is not None:
                    self._require_type(case.payload_var, f"match payload '{case.payload_var.name}' in '{context.name}'")
        elif isinstance(instr, Instruction_drop):
            self._require_type(instr.var, f"drop value '{instr.var.name}' in '{context.name}'")

    def _verify_call_target(self, fn_name: str, context: _FunctionContext) -> None:
        if fn_name.startswith("__dyn_dispatch__"):
            return
        if context.generic_names:
            return
        if fn_name not in context.known_functions:
            raise EhirCompileError(
                f"Typed verifier found call to unknown function '{fn_name}' in '{context.name}'",
                code="EHIR1301",
            )

    def _verify_no_call_generics(self, fn_name: str, generics: list[Type], context: _FunctionContext) -> None:
        if not generics:
            return
        if context.generic_names and all(not self._contains_unbound_placeholder(generic, context.generic_names) for generic in generics):
            return
        raise EhirCompileError(
            f"Typed verifier found non-monomorphized call '{fn_name}' in '{context.name}': {generics}",
            code="EHIR1302",
        )

    def _require_type(self, var: Variable, what: str) -> None:
        if var.type is None:
            raise EhirCompileError(f"Typed verifier found unresolved type for {what}", code="EHIR1303")

    def _require_concrete_type(self, typ: Type | None, what: str, generic_names: set[str]) -> None:
        if typ is None:
            raise EhirCompileError(f"Typed verifier found unresolved type for {what}", code="EHIR1304")
        if self._contains_unbound_placeholder(typ, generic_names):
            raise EhirCompileError(f"Typed verifier found unresolved generic type for {what}: {typ}", code="EHIR1305")

    def _contains_unbound_placeholder(self, typ: Type, generic_names: set[str]) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return self._contains_unbound_placeholder(typ.pointee, generic_names)
        if not typ.generics and typ.name in {"T", "Self"}:
            return typ.name not in generic_names
        if not typ.generics and len(typ.name) == 1 and typ.name.isupper():
            return typ.name not in generic_names
        return any(self._contains_unbound_placeholder(generic, generic_names) for generic in typ.generics)
