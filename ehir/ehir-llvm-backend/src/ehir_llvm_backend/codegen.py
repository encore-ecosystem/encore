import ctypes
import hashlib
import re
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

import llvmlite.binding as llvm
import llvmlite.ir as ir
from ehir.core.instructions import (
    Instruction_br,
    Instruction_cbr,
    Instruction_comment,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
)
from ehir.core.primitives import Float, Float_t, Isize, Isize_t, Str, Str_t, Usize, Usize_t
from ehir.core.primitives.base import Primitive
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type, mangle_type_name
from ehir.core.variable import TypedVariable
from ehir.postprocessor import EHIR_ProcessedModule
from ehir.postprocessor.derectives import (
    ProcessedDerective,
    ProcessedDerective_extern_fn,
    ProcessedDerective_fn,
    ProcessedDerective_struct,
)
from ehir.postprocessor.instructions import (
    ProcessedInstruction,
    ProcessedInstruction_add,
    ProcessedInstruction_and,
    ProcessedInstruction_br,
    ProcessedInstruction_call,
    ProcessedInstruction_callvoid,
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
from ehir.postprocessor.special import ProcessedBlock


class Codegen:
    builder: ir.IRBuilder
    module: ir.Module

    def __init__(self):
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        llvm.initialize_native_asmparser()

        self._reset_state()

    def _reset_state(self):
        self.module = ir.Module(context=ir.Context())
        self.module.triple = llvm.get_default_triple()
        self.builder = ir.IRBuilder()
        self._variables: dict[str, object] = {}
        self._structs: dict[str, ir.BaseStructType] = {}
        self._blocks: dict[str, ir.Block] = {}
        self._pending_phi_incomings: list[tuple[ir.PhiInstr, Sequence[tuple[TypedVariable, str]]]] = []
        self._block_predecessors: dict[str, set[str]] = {}
        self._generic_struct_templates: dict[str, tuple[list[str], list[Type]]] = {}
        self._pointer_width_bits: int | None = None
        self._string_literal_counter = 0
        self._str_type: ir.IdentifiedStructType | None = None
        self._enabled_functions: set[str] = set()
        self._current_fn_name: str | None = None
        self._symbol_by_canonical: dict[str, str] = {}
        self._canonical_by_symbol: dict[str, str] = {}
        self._symbol_version_salt = self._detect_symbol_version_salt()

    def _detect_symbol_version_salt(self) -> str:
        try:
            return version("ehir-llvm-backend")
        except PackageNotFoundError:
            return "0.0.0-dev"

    def _comment_instruction(self, instr: object) -> None:
        self.builder.comment("")
        self.builder.comment(str(instr).encode("unicode_escape").decode("ascii"))

    def run(self, mod: EHIR_ProcessedModule) -> ir.Module:
        self._reset_state()
        self._enabled_functions = self._collect_enabled_functions(mod.funcs)

        for derective in mod.structs:
            self._codegen_struct_decl(derective)

        for derective in mod.structs:
            self._codegen_struct_body(derective)

        for derective in mod.funcs:
            if derective.name not in self._enabled_functions:
                continue
            self._codegen_fn_decl(derective)

        for derective in mod.funcs:
            if derective.name not in self._enabled_functions:
                continue
            if isinstance(derective, ProcessedDerective_fn):
                self._codegen_fn_body(derective)

        self._emit_builtin_native_helpers()
        return self.module

    def _collect_enabled_functions(
        self, funcs: Sequence[ProcessedDerective_fn | ProcessedDerective_extern_fn]
    ) -> set[str]:
        by_name: dict[str, ProcessedDerective_fn | ProcessedDerective_extern_fn] = {fn.name: fn for fn in funcs}
        by_emitted: dict[str, ProcessedDerective_fn | ProcessedDerective_extern_fn] = {}
        for fn in funcs:
            emitted = self._emit_like_symbol_name(fn.name)
            by_emitted.setdefault(emitted, fn)
        roots = [fn.name for fn in funcs if isinstance(fn, ProcessedDerective_fn) and fn.name == "main"]
        if not roots:
            return set(by_name.keys())

        enabled: set[str] = set()
        queue = list(roots)
        for fn in funcs:
            if self._is_memory_management_function(fn.name):
                queue.append(fn.name)
        while queue:
            name = queue.pop()
            if name in enabled:
                continue
            fn = by_name.get(name) or by_emitted.get(name)
            if fn is None:
                continue
            enabled.add(name)
            if not isinstance(fn, ProcessedDerective_fn):
                continue
            for block in fn.get_body():
                for instr in block.body:
                    if isinstance(instr, (ProcessedInstruction_call, ProcessedInstruction_callvoid)):
                        if instr.fn_name.startswith("__dyn_dispatch__"):
                            payload = instr.fn_name[len("__dyn_dispatch__") :]
                            if "::" in payload:
                                trait_name, method_name = payload.rsplit("::", 1)
                                prefix = f"{trait_name}::{method_name}"
                                for candidate_name in by_name:
                                    if not candidate_name.startswith(prefix):
                                        continue
                                    tail = candidate_name[len(prefix) :]
                                    if tail and not tail.startswith("__"):
                                        continue
                                    queue.append(candidate_name)
                        queue.append(instr.fn_name)
                if isinstance(block.term, ProcessedInstruction_call):
                    if block.term.fn_name.startswith("__dyn_dispatch__"):
                        payload = block.term.fn_name[len("__dyn_dispatch__") :]
                        if "::" in payload:
                            trait_name, method_name = payload.rsplit("::", 1)
                            prefix = f"{trait_name}::{method_name}"
                            for candidate_name in by_name:
                                if not candidate_name.startswith(prefix):
                                    continue
                                tail = candidate_name[len(prefix) :]
                                if tail and not tail.startswith("__"):
                                    continue
                                queue.append(candidate_name)
                    queue.append(block.term.fn_name)
        out: set[str] = set()
        for name in enabled:
            fn = by_name.get(name) or by_emitted.get(name)
            if fn is not None:
                out.add(fn.name)
        return out

    def _is_memory_management_function(self, name: str) -> bool:
        return (
            name.startswith("__retain_")
            or name.startswith("__drop_")
            or name.startswith("__cfree")
            or name in {"encore_str_retain", "encore_str_drop"}
        )

    def _emit_like_symbol_name(self, name: str) -> str:
        if name == "main":
            return "main"
        if name in self._symbol_by_canonical:
            return self._symbol_by_canonical[name]
        if name in self._canonical_by_symbol:
            return name

        base = name.rsplit("::", 1)[-1].split("[", 1)[0]
        base = re.sub(r"[^0-9A-Za-z_]", "_", base)
        if not base or not (base[0].isalpha() or base[0] == "_"):
            base = f"fn_{base}" if base else "fn"

        digest = hashlib.blake2b(
            f"{self._symbol_version_salt}:{name}".encode("utf-8"),
            digest_size=8,
        ).hexdigest()
        symbol = f"__ehir_{base}_{digest}"
        self._symbol_by_canonical[name] = symbol
        self._canonical_by_symbol[symbol] = name
        return symbol

    def _codegen_struct_decl(self, struct: ProcessedDerective_struct):
        if struct.name in self._structs:
            raise ValueError(f"Struct '{struct.name}' already declared")
        st = self.module.context.get_identified_type(struct.name)
        self._structs[struct.name] = st
        template_field_types = [param.type for param in struct.fields]
        generic_names = [generic.name for generic in struct.generics]
        if generic_names:
            self._generic_struct_templates[struct.name] = (generic_names, template_field_types)

    def _codegen_fn_decl(self, fn: ProcessedDerective_fn | ProcessedDerective_extern_fn):
        ret_type = self._build_type(fn.ret_type)
        param_types = [self._build_type(t.type) for t in fn.params]

        func_type = ir.FunctionType(ret_type, param_types)
        emitted_name = (
            fn.name
            if isinstance(fn, ProcessedDerective_extern_fn) or fn.name == "main"
            else self._emit_like_symbol_name(fn.name)
        )
        self._symbol_by_canonical[fn.name] = emitted_name
        self._canonical_by_symbol[emitted_name] = fn.name
        func = ir.Function(self.module, func_type, name=emitted_name)

        for i, param in enumerate(func.args):
            param.name = fn.params[i].name

        return func

    def _codegen_derective(self, derective: ProcessedDerective):
        if isinstance(derective, ProcessedDerective_fn):
            self._codegen_fn_body(derective)
        elif isinstance(derective, ProcessedDerective_struct):
            self._codegen_struct_body(derective)
        else:
            raise NotImplementedError(f"Unsupported derective type: {type(derective)}")

    def _codegen_struct_body(self, struct: ProcessedDerective_struct):
        struct_type = self._structs[struct.name]
        template_field_types = [param.type for param in struct.fields]
        generic_names = [generic.name for generic in struct.generics]
        if generic_names:
            # Generic backend templates (__tuple_N/__array_N) are materialized
            # into concrete identified structs on demand in _build_type().
            self._generic_struct_templates[struct.name] = (generic_names, template_field_types)
            return

        field_types = [self._build_type(field_type) for field_type in template_field_types]
        if isinstance(struct_type, ir.IdentifiedStructType):
            if struct_type.is_opaque:
                struct_type.set_body(*field_types)
            else:
                current = tuple(struct_type.elements)  # ty:ignore[invalid-argument-type]
                target = tuple(field_types)
                if current != target:
                    raise ValueError(f"Struct '{struct.name}' body already defined with a different layout")
            return

        struct_type.elements = field_types  # ty:ignore[invalid-assignment]

    def _codegen_fn_body(self, fn: ProcessedDerective_fn):
        emitted_name = self._symbol_by_canonical.get(fn.name, fn.name)
        func = [f for f in self.module.functions if f.name == emitted_name][0]
        self._current_fn_name = fn.name

        self._variables.clear()
        self._blocks.clear()
        self._pending_phi_incomings.clear()
        self._block_predecessors = self._collect_block_predecessors(fn.get_body())
        for i, param in enumerate(func.args):
            param_name = fn.params[i].name
            self._variables[param_name] = param
            param.name = param_name

        ir_blocks = []
        for block in fn.get_body():
            assert isinstance(block, ProcessedBlock), type(block)
            ir_block = func.append_basic_block(block.name)
            ir_blocks.append(ir_block)
            self._blocks[block.name] = ir_block

        if ir_blocks:
            self.builder.position_at_end(ir_blocks[0])
            self._predeclare_stack_allocas(fn.get_body())

        for block, ir_block in zip(fn.get_body(), ir_blocks, strict=True):
            self.builder.position_at_end(ir_block)
            self._build_block(block)

        self._resolve_pending_phi_incomings()
        self._current_fn_name = None

    def _collect_block_predecessors(self, blocks: Sequence[ProcessedBlock]) -> dict[str, set[str]]:
        predecessors: dict[str, set[str]] = {}
        for block in blocks:
            predecessors[block.name] = set()

        for block in blocks:
            term = block.term
            if isinstance(term, Instruction_br):
                predecessors.setdefault(term.label, set()).add(block.name)
            elif isinstance(term, Instruction_cbr):
                predecessors.setdefault(term.true_br_label, set()).add(block.name)
                predecessors.setdefault(term.else_br_label, set()).add(block.name)
            elif isinstance(term, ProcessedInstruction_switch):
                predecessors.setdefault(term.default_case, set()).add(block.name)
                for _, case_label in term.cases:
                    predecessors.setdefault(case_label, set()).add(block.name)

        return predecessors

    def _predeclare_stack_allocas(self, blocks: Sequence[ProcessedBlock]) -> None:
        for block in blocks:
            for instr in block.body:
                if not isinstance(instr, ProcessedInstruction_salloc):
                    continue
                if instr.var_out.name in self._variables:
                    continue
                target_type = self._build_type(instr.type)
                if isinstance(target_type, ir.VoidType):
                    continue
                self._variables[instr.var_out.name] = self.builder.alloca(target_type, name=instr.var_out.name)

    def _build_block(self, block: ProcessedBlock):
        for instr in block.body:
            self._build_instruction(instr)
        self._build_instruction(block.term)

    def _build_instruction(self, instr: ProcessedInstruction):
        if isinstance(instr, ProcessedInstruction_salloc):
            self._build_salloc(instr)
        elif isinstance(instr, ProcessedInstruction_halloc):
            self._build_halloc(instr)
        elif isinstance(instr, ProcessedInstruction_hrealloc):
            self._build_hrealloc(instr)
        elif isinstance(instr, ProcessedInstruction_put):
            self._build_put(instr)
        elif isinstance(instr, ProcessedInstruction_load):
            self._build_load(instr)
        elif isinstance(instr, ProcessedInstruction_add):
            self._build_add(instr)
        elif isinstance(instr, ProcessedInstruction_sub):
            self._build_sub(instr)
        elif isinstance(instr, ProcessedInstruction_mul):
            self._build_mul(instr)
        elif isinstance(instr, ProcessedInstruction_div):
            self._build_div(instr)
        elif isinstance(instr, ProcessedInstruction_ieq):
            self._build_ieq(instr)
        elif isinstance(instr, ProcessedInstruction_neq):
            self._build_neq(instr)
        elif isinstance(instr, ProcessedInstruction_les):
            self._build_les(instr)
        elif isinstance(instr, ProcessedInstruction_leq):
            self._build_leq(instr)
        elif isinstance(instr, ProcessedInstruction_or):
            self._build_or(instr)
        elif isinstance(instr, ProcessedInstruction_and):
            self._build_and(instr)
        elif isinstance(instr, ProcessedInstruction_xor):
            self._build_xor(instr)

        elif isinstance(instr, ProcessedInstruction_grt):
            self._build_grt(instr)
        elif isinstance(instr, ProcessedInstruction_geq):
            self._build_geq(instr)
        elif isinstance(instr, ProcessedInstruction_mod):
            self._build_mod(instr)
        elif isinstance(instr, ProcessedInstruction_shl):
            self._build_shl(instr)
        elif isinstance(instr, ProcessedInstruction_shr):
            self._build_shr(instr)
        elif isinstance(instr, ProcessedInstruction_call):
            self._build_call(instr)
        elif isinstance(instr, ProcessedInstruction_callvoid):
            self._build_callvoid(instr)
        elif isinstance(instr, ProcessedInstruction_ret):
            self._build_ret(instr)
        elif isinstance(instr, (Instruction_br, ProcessedInstruction_br)):
            self._build_br(instr)
        elif isinstance(instr, (Instruction_cbr, ProcessedInstruction_cbr)):
            self._build_cbr(instr)
        elif isinstance(instr, ProcessedInstruction_switch):
            self._build_switch(instr)
        elif isinstance(instr, ProcessedInstruction_hfree):
            self._build_hfree(instr)
        elif isinstance(instr, ProcessedInstruction_store):
            self._build_store(instr)
        elif isinstance(instr, ProcessedInstruction_pcast):
            self._build_pcast(instr)
        elif isinstance(instr, ProcessedInstruction_gep):
            self._build_gep(instr)
        elif isinstance(instr, ProcessedInstruction_getfieldptr):
            self._build_getfieldptr(instr)
        elif isinstance(instr, Instruction_getfield):
            self._build_getfield(instr)
        elif isinstance(instr, Instruction_getptr):
            self._build_getptr(instr)
        elif isinstance(instr, ProcessedInstruction_phi):
            self._build_phi(instr)
        elif isinstance(instr, Instruction_comment):
            pass  # skip comment
        else:
            raise NotImplementedError(f"Unsupported instruction type: {type(instr)}")

    def _build_getptr(self, instr: Instruction_getptr):
        self._comment_instruction(instr)

        assert instr.var.type is not None
        type = self._build_type(instr.var.type)
        ptr = self.builder.alloca(type, name=instr.var.name)
        self._variables[instr.var.name] = ptr

    def _build_getptr(self, instr: Instruction_getptr):
        self._comment_instruction(instr)

        assert instr.var.type is not None
        dst_type = self._build_type(instr.var.type)

        entry_builder = self._entry_alloca_builder()
        alloca = entry_builder.alloca(dst_type, name=instr.var_out.name)
        self.builder.store(self._variables[instr.var.name], alloca)
        self._variables[instr.var_out.name] = alloca

    def _build_pcast(self, instr: ProcessedInstruction_pcast):
        self._comment_instruction(instr)

        value = self._variables[instr.var.name]
        assert hasattr(value, "type")
        src_type = value.type

        assert instr.var_out.type is not None
        dst_type = self._build_type(instr.var_out.type)
        if (
            not isinstance(instr.var_out.type, Pointer)
            and instr.var_out.type.name == "dyn"
            and len(instr.var_out.type.generics) == 1
        ):
            trait_name = instr.var_out.type.generics[0].name
            assert instr.var.type is not None
            raw_ptr = self._pack_dyn_payload(value, instr.var.type)
            vtable_ptr = self._get_dyn_vtable_ptr(trait_name, instr.var.type)
            dyn_value = ir.Constant(dst_type, ir.Undefined)
            dyn_value = self.builder.insert_value(dyn_value, raw_ptr, 0, name=f"{instr.var_out.name}.dyn_data")
            dyn_value = self.builder.insert_value(dyn_value, vtable_ptr, 1, name=f"{instr.var_out.name}.dyn_vtable")
            self._variables[instr.var_out.name] = dyn_value
            return dyn_value

        # Cast
        ## Same
        if src_type == dst_type:
            result = value

        elif isinstance(src_type, ir.IntType) and isinstance(dst_type, ir.IntType):
            src_width = src_type.width
            dst_width = dst_type.width

            if src_width < dst_width:
                if self._is_signed_integer_type(instr.var.type):
                    result = self.builder.sext(value, dst_type, name=instr.var_out.name)
                else:
                    result = self.builder.zext(value, dst_type, name=instr.var_out.name)
            elif src_width > dst_width:
                result = self.builder.trunc(value, dst_type, name=instr.var_out.name)
            else:
                result = value
        elif isinstance(src_type, ir.IntType) and isinstance(dst_type, self._float_ir_types()):
            if self._is_signed_integer_type(instr.var.type):
                result = self.builder.sitofp(value, dst_type, name=instr.var_out.name)
            else:
                result = self.builder.uitofp(value, dst_type, name=instr.var_out.name)
        elif isinstance(src_type, self._float_ir_types()) and isinstance(dst_type, ir.IntType):
            if self._is_signed_integer_type(instr.var_out.type):
                result = self.builder.fptosi(value, dst_type, name=instr.var_out.name)
            else:
                result = self.builder.fptoui(value, dst_type, name=instr.var_out.name)
        elif isinstance(src_type, self._float_ir_types()) and isinstance(dst_type, self._float_ir_types()):
            src_width = self._float_width(src_type)
            dst_width = self._float_width(dst_type)
            if src_width < dst_width:
                result = self.builder.fpext(value, dst_type, name=instr.var_out.name)
            elif src_width > dst_width:
                result = self.builder.fptrunc(value, dst_type, name=instr.var_out.name)
            else:
                result = value
        elif isinstance(src_type, ir.IntType) and isinstance(dst_type, ir.PointerType):
            result = self.builder.inttoptr(value, dst_type, name=instr.var_out.name)
        elif isinstance(src_type, ir.PointerType) and isinstance(dst_type, ir.IntType):
            result = self.builder.ptrtoint(value, dst_type, name=instr.var_out.name)
        elif isinstance(src_type, ir.PointerType) and isinstance(dst_type, ir.PointerType):
            result = self.builder.bitcast(value, dst_type, name=instr.var_out.name)

        else:
            raise NotImplementedError(
                f"Unsupported cast: {src_type} -> {dst_type}; instr={instr}; out_type={instr.var_out.type!r}; "
                f"out_type_cls={type(instr.var_out.type).__name__}; fn={self._current_fn_name or '<none>'}"
            )

        self._variables[instr.var_out.name] = result
        return result

    def _build_store(self, instr: ProcessedInstruction_store):
        self._comment_instruction(instr)
        value = self._variables.get(instr.var_src.name)
        if value is None:
            src_t = instr.var_src.type
            if src_t is not None and src_t.name == "void":
                return
            if instr.var_src.name.startswith(".drop_") or instr.var_src.name == ".drop_ret":
                return
            raise KeyError(instr.var_src.name)
        ptr = self._variables[instr.var_dst.name]

        if isinstance(ptr.type, ir.PointerType) and ptr.type.pointee == self._get_str_type():
            if value.type == ir.IntType(8).as_pointer():
                field_ptr = self.builder.gep(
                    ptr,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
                    name=f"{instr.var_dst.name}.ptr",
                )
                self.builder.store(value, field_ptr)
                return

            strlen_type = ir.IntType(self._get_pointer_width_bits())
            if value.type == strlen_type:
                field_ptr = self.builder.gep(
                    ptr,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
                    name=f"{instr.var_dst.name}.len",
                )
                self.builder.store(value, field_ptr)
                return

        if ptr.type != value.type.as_pointer():
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.IntType)
                and ptr.type.pointee.width == 8
            ):
                if isinstance(value.type, ir.BaseStructType):
                    cast_ptr = self.builder.bitcast(
                        ptr, ir.PointerType(value.type), name=f"{instr.var_dst.name}.store_struct_ptr"
                    )
                    self.builder.store(value, cast_ptr)
                    return
                cast_ptr = self.builder.bitcast(
                    ptr, ir.PointerType(value.type), name=f"{instr.var_dst.name}.store_cast_ptr"
                )
                self.builder.store(value, cast_ptr)
                return
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.PointerType)
                and isinstance(ptr.type.pointee.pointee, ir.IntType)
                and ptr.type.pointee.pointee.width == 8
                and isinstance(value.type, ir.BaseStructType)
            ):
                cast_ptr = self.builder.bitcast(
                    ptr, ir.PointerType(value.type), name=f"{instr.var_dst.name}.store_struct_ptrptr"
                )
                self.builder.store(value, cast_ptr)
                return
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.PointerType)
                and isinstance(value.type, ir.PointerType)
            ):
                value = self.builder.bitcast(value, ptr.type.pointee, name=f"{instr.var_src.name}.store_ptrcast")
                self.builder.store(value, ptr)
                return
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.BaseStructType)
                and isinstance(value.type, ir.PointerType)
                and isinstance(value.type.pointee, ir.BaseStructType)
            ):
                loaded = self.builder.load(value, name=f"{instr.var_src.name}.store_ptrload")
                self.builder.store(loaded, ptr)
                return
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.IntType)
                and isinstance(value.type, ir.IntType)
            ):
                dst_bits = ptr.type.pointee.width
                src_bits = value.type.width
                if src_bits < dst_bits:
                    value = self.builder.zext(value, ir.IntType(dst_bits), name=f"{instr.var_src.name}.store_zext")
                elif src_bits > dst_bits:
                    value = self.builder.trunc(value, ir.IntType(dst_bits), name=f"{instr.var_src.name}.store_trunc")
                self.builder.store(value, ptr)
                return
            if (
                isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.IntType)
                and isinstance(value.type, ir.PointerType)
            ):
                int_type = ptr.type.pointee
                value = self.builder.ptrtoint(value, int_type, name=f"{instr.var_src.name}.store_ptrtoint")
                self.builder.store(value, ptr)
                return
            if (
                isinstance(value.type, ir.BaseStructType)
                and isinstance(ptr.type, ir.PointerType)
                and isinstance(ptr.type.pointee, ir.BaseStructType)
                and len(value.type.elements) == len(ptr.type.pointee.elements)
            ):
                src_slot = self.builder.alloca(value.type, name=f"{instr.var_src.name}.store_cast_src")
                self.builder.store(value, src_slot)
                dst_slot = self.builder.bitcast(
                    src_slot, ir.PointerType(ptr.type.pointee), name=f"{instr.var_src.name}.store_cast_ptr"
                )
                value = self.builder.load(dst_slot, name=f"{instr.var_src.name}.store_cast_val")
            else:
                raise ValueError(f"Invalid store types: {value.type} -> {ptr.type} for {instr}")

        self.builder.store(value, ptr)

    def _build_getfieldptr(self, instr: ProcessedInstruction_getfieldptr):
        self._comment_instruction(instr)
        base = self._variables[instr.src.name]
        assert hasattr(base, "type")
        expected_result_type = self._build_type(instr.var_out.type) if instr.var_out.type is not None else None
        if not isinstance(base.type, ir.PointerType):
            entry_builder = self._entry_alloca_builder()
            temp = entry_builder.alloca(base.type)
            self.builder.store(base, temp)
            base = temp
        elif not isinstance(base.type.pointee, ir.BaseStructType):
            # Tolerate mismatched lowering paths where field access is emitted for a scalar pointer.
            self._variables[instr.var_out.name] = base
            return base

        field_index = int(instr.field.name)
        base = self._unwrap_smart_pointer_wrapper_for_gep(base, field_index, instr.var_out.name, expected_result_type)
        if isinstance(base.type, ir.PointerType) and isinstance(base.type.pointee, ir.IdentifiedStructType):
            pointee_name = getattr(base.type.pointee, "name", "")
            template_name = pointee_name.split("[", 1)[0]
            if template_name in self._generic_struct_templates and instr.var_out.type is not None:
                i8_ptr = self.builder.bitcast(
                    base, ir.IntType(8).as_pointer(), name=f"{instr.var_out.name}.tmpl_i8_base"
                )
                field_type = (
                    instr.var_out.type.pointee if isinstance(instr.var_out.type, Pointer) else instr.var_out.type
                )
                elem_size = self._sizeof(field_type)
                byte_offset = ir.Constant(ir.IntType(32), field_index * elem_size)
                field_i8_ptr = self.builder.gep(i8_ptr, [byte_offset], name=f"{instr.var_out.name}.tmpl_i8_ptr")
                result = self.builder.bitcast(
                    field_i8_ptr, self._build_type(instr.var_out.type), name=instr.var_out.name
                )
                self._variables[instr.var_out.name] = result
                return result
        if isinstance(base.type, ir.PointerType) and not isinstance(base.type.pointee, ir.BaseStructType):
            self._variables[instr.var_out.name] = base
            return base
        if isinstance(base.type, ir.PointerType) and isinstance(base.type.pointee, ir.BaseStructType):
            element_count = len(base.type.pointee.elements)
            if field_index >= element_count:
                raise ValueError(
                    f"Invalid getfieldptr index {field_index} for {base.type.pointee} with {element_count} fields: {instr}"
                )
        indices = [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_index)]

        result = self.builder.gep(base, indices, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_gep(self, instr: ProcessedInstruction_gep):
        self._comment_instruction(instr)

        base = self._variables[instr.var.name]
        if not isinstance(base.type, ir.PointerType):
            entry_builder = self._entry_alloca_builder()
            temp = entry_builder.alloca(base.type)
            self.builder.store(base, temp)
            base = temp

        if not isinstance(base.type, ir.PointerType):
            raise ValueError(f"GEP expects pointer base, got {base.type}")

        const_offset: int | None = None
        if isinstance(instr.offset, int):
            const_offset = instr.offset
            offset_value = ir.Constant(ir.IntType(32), instr.offset)
        elif isinstance(instr.offset, TypedVariable) and instr.offset.name.isdigit():
            const_offset = int(instr.offset.name)
            offset_value = ir.Constant(ir.IntType(32), const_offset)
        else:
            offset_value = self._variables[instr.offset.name]

        if isinstance(base.type.pointee, ir.BaseStructType):
            if base.type.pointee.elements is None:
                i8_ptr = self.builder.bitcast(base, ir.IntType(8).as_pointer(), name=f"{instr.var.name}.opaque_i8_ptr")
                result_i8 = self.builder.gep(i8_ptr, [offset_value], name=f"{instr.var_out.name}.opaque_gep")
                if instr.var_out.type is not None:
                    result = self.builder.bitcast(
                        result_i8, self._build_type(instr.var_out.type), name=instr.var_out.name
                    )
                else:
                    result = result_i8
                self._variables[instr.var_out.name] = result
                return result
            field_index: int | None = None
            if const_offset is not None:
                field_index = const_offset
            elif hasattr(offset_value, "constant"):
                field_index = int(offset_value.constant)

            if field_index is not None:
                element_count = len(base.type.pointee.elements)
                if field_index < 0 or field_index >= element_count:
                    raise ValueError(
                        "Invalid gep field index "
                        f"{field_index} for {base.type.pointee} with {element_count} fields: {instr}"
                    )
                indices = [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_index)]
            else:
                indices = [offset_value]
        else:
            indices = [offset_value]

        result = self.builder.gep(base, indices, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_getfield(self, instr: Instruction_getfield):
        self._comment_instruction(instr)

        field_ptr_instr = Instruction_getfieldptr(var_out=instr.var_out, src=instr.src, field=instr.field)
        field_ptr = self._build_getfieldptr(field_ptr_instr)
        result = self.builder.load(field_ptr, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_salloc(self, instr: ProcessedInstruction_salloc):
        self._comment_instruction(instr)
        if instr.var_out.name in self._variables:
            return self._variables[instr.var_out.name]
        target_type = self._build_type(instr.type)
        if isinstance(target_type, ir.VoidType):
            return None
        entry_builder = self._entry_alloca_builder()
        ptr = entry_builder.alloca(target_type, name=instr.var_out.name)
        self._variables[instr.var_out.name] = ptr
        return ptr

    def _entry_alloca_builder(self) -> ir.IRBuilder:
        current_block = self.builder.block
        if current_block is None:
            return self.builder
        entry_block = current_block.function.entry_basic_block
        builder = ir.IRBuilder(entry_block)
        if entry_block.instructions:
            builder.position_before(entry_block.instructions[0])
        else:
            builder.position_at_end(entry_block)
        return builder

    def _build_halloc(self, instr: ProcessedInstruction_halloc):
        self._comment_instruction(instr)

        byte_size = self._sizeof(instr.type)
        malloc_func = self._get_malloc_function()
        raw_ptr = self.builder.call(malloc_func, [byte_size], name=f".halloc_{instr.var_out.name}")
        target_type = self._build_type(instr.type)
        casted_ptr = self.builder.bitcast(raw_ptr, ir.PointerType(target_type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = casted_ptr
        return casted_ptr

    def _build_hrealloc(self, instr: ProcessedInstruction_hrealloc):
        self._comment_instruction(instr)

        ptr = self._variables[instr.var.name]
        count = self._variables[instr.count.name]
        assert instr.var.type is not None

        size_type = ir.IntType(self._get_pointer_width_bits())
        if count.type != size_type:
            if isinstance(count.type, ir.IntType):
                if count.type.width < size_type.width:
                    count = self.builder.zext(count, size_type, name=f".countext_{instr.count.name}")
                elif count.type.width > size_type.width:
                    count = self.builder.trunc(count, size_type, name=f".counttrunc_{instr.count.name}")
            else:
                raise TypeError(f"HREALLOC count must lower to integer, got {count.type}")

        elem_size = self._sizeof(instr.var.type.pointee)
        byte_size = self.builder.mul(count, elem_size, name=f".hrealloc_bytes_{instr.var_out.name}")
        realloc_func = self._get_realloc_function()
        raw_ptr = self.builder.bitcast(ptr, realloc_func.args[0].type, name=f".hrealloc_raw_{instr.var.name}")
        resized = self.builder.call(realloc_func, [raw_ptr, byte_size], name=f".hrealloc_{instr.var_out.name}")
        target_type = self._build_type(instr.var.type.pointee)
        casted_ptr = self.builder.bitcast(resized, ir.PointerType(target_type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = casted_ptr
        return casted_ptr

    def _build_hfree(self, instr: ProcessedInstruction_hfree):
        self._comment_instruction(instr)

        ptr = self._variables[instr.var.name]
        free_func = self._get_free_function()
        dst_type = free_func.args[0].type
        ptr_conv = self.builder.bitcast(typ=dst_type, val=ptr)

        self.builder.call(free_func, [ptr_conv])

    def _build_put(self, instr: ProcessedInstruction_put):
        self._comment_instruction(instr)
        constant = self._build_primitive(instr.primitive)
        dst = self._variables[instr.var.name]
        if (
            isinstance(dst.type, ir.PointerType)
            and isinstance(dst.type.pointee, ir.IntType)
            and isinstance(constant.type, ir.IntType)
            and constant.type != dst.type.pointee
        ):
            dst_bits = dst.type.pointee.width
            src_bits = constant.type.width
            if src_bits < dst_bits:
                constant = self.builder.zext(constant, ir.IntType(dst_bits), name=f"{instr.var.name}.put_zext")
            elif src_bits > dst_bits:
                constant = self.builder.trunc(constant, ir.IntType(dst_bits), name=f"{instr.var.name}.put_trunc")
        self.builder.store(constant, dst)

    def _build_load(self, instr: ProcessedInstruction_load):
        self._comment_instruction(instr)
        ptr = self._variables[instr.var.name]
        if not isinstance(ptr.type, ir.PointerType):
            # Some lowered match payload paths may already yield a concrete value.
            # Treat repeated `load` on that value as a move.
            self._variables[instr.var_out.name] = ptr
            return ptr
        if instr.var_out.type is not None and isinstance(ptr.type.pointee, ir.IntType) and ptr.type.pointee.width == 8:
            expected_ptr = ir.PointerType(self._build_type(instr.var_out.type))
            ptr = self.builder.bitcast(ptr, expected_ptr, name=f"{instr.var.name}.load_cast_ptr")
        value = self.builder.load(ptr, name=instr.var_out.name)
        self._variables[instr.var_out.name] = value
        return value

    def _build_add(self, instr: ProcessedInstruction_add):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_str_value(left):
            if not self._is_str_value(right):
                raise TypeError(f"Invalid add operands for str concat: {left.type} + {right.type}")
            concat_func = self._get_str_concat_function()
            result = self.builder.call(concat_func, [left, right], name=instr.var_out.name)
        elif self._is_float_value(left):
            result = self.builder.fadd(left, right, name=instr.var_out.name)
        else:
            result = self.builder.add(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_sub(self, instr: ProcessedInstruction_sub):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fsub(left, right, name=instr.var_out.name)
        else:
            result = self.builder.sub(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_mul(self, instr: ProcessedInstruction_mul):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fmul(left, right, name=instr.var_out.name)
        else:
            result = self.builder.mul(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_div(self, instr: ProcessedInstruction_div):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fdiv(left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.udiv(left, right, name=instr.var_out.name)
        else:
            result = self.builder.sdiv(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_mod(self, instr: ProcessedInstruction_mod):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.frem(left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.urem(left, right, name=instr.var_out.name)
        else:
            result = self.builder.srem(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_shl(self, instr: ProcessedInstruction_shl):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        result = self.builder.shl(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_shr(self, instr: ProcessedInstruction_shr):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)

        is_signed = True
        if instr.lhs.type is not None:
            lhs_name = instr.lhs.type.name
            if lhs_name == "usize" or lhs_name.startswith("u"):
                is_signed = False

        result = (
            self.builder.ashr(left, right, name=instr.var_out.name)
            if is_signed
            else self.builder.lshr(left, right, name=instr.var_out.name)
        )
        self._variables[instr.var_out.name] = result
        return result

    def _build_or(self, instr: ProcessedInstruction_or):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        result = self.builder.or_(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_and(self, instr: ProcessedInstruction_and):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        result = self.builder.and_(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_xor(self, instr: ProcessedInstruction_xor):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        result = self.builder.xor(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_ieq(self, instr: ProcessedInstruction_ieq):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_str_value(left):
            if not self._is_str_value(right):
                raise TypeError(f"Invalid eq operands for str compare: {left.type} == {right.type}")
            eq_fn = self._get_str_eq_function()
            result = self.builder.call(eq_fn, [left, right], name=instr.var_out.name)
        elif self._is_float_value(left):
            result = self.builder.fcmp_ordered("==", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned("==", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed("==", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_neq(self, instr: ProcessedInstruction_neq):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_str_value(left):
            if not self._is_str_value(right):
                raise TypeError(f"Invalid neq operands for str compare: {left.type} != {right.type}")
            eq_fn = self._get_str_eq_function()
            eq_result = self.builder.call(eq_fn, [left, right], name=f"{instr.var_out.name}.eq")
            result = self.builder.icmp_unsigned("==", eq_result, ir.Constant(ir.IntType(1), 0), name=instr.var_out.name)
        elif self._is_float_value(left):
            result = self.builder.fcmp_unordered("!=", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned("!=", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed("!=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_les(self, instr: ProcessedInstruction_les):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fcmp_ordered("<", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned("<", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed("<", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_leq(self, instr: ProcessedInstruction_leq):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fcmp_ordered("<=", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned("<=", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed("<=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_grt(self, instr: ProcessedInstruction_grt):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fcmp_ordered(">", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned(">", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed(">", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_geq(self, instr: ProcessedInstruction_geq):
        self._comment_instruction(instr)
        left = self._get_typed_value(instr.lhs)
        right = self._get_typed_value(instr.rhs)
        if self._is_float_value(left):
            result = self.builder.fcmp_ordered(">=", left, right, name=instr.var_out.name)
        elif self._is_unsigned_type(instr.lhs.type):
            result = self.builder.icmp_unsigned(">=", left, right, name=instr.var_out.name)
        else:
            result = self.builder.icmp_signed(">=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_call(self, instr: ProcessedInstruction_call):
        self._comment_instruction(instr)
        if instr.fn_name.startswith("__dyn_dispatch__"):
            result = self._build_dyn_dispatch_call(instr)
            self._variables[instr.var_out.name] = result
            return result
        trait_result = self._try_build_trait_op_call(instr)
        if trait_result is not None:
            self._variables[instr.var_out.name] = trait_result
            return trait_result
        func = self._get_or_declare_called_function(instr)

        expected_types = list(func.function_type.args)
        if len(expected_types) != len(instr.args):
            raise ValueError(
                f"Call arg count mismatch for '{instr.fn_name}': {len(instr.args)} != {len(expected_types)}"
            )

        args = []
        for index, (expected_type, arg) in enumerate(zip(expected_types, instr.args, strict=True)):
            value = self._get_typed_value(arg)
            try:
                args.append(
                    self._coerce_call_arg(
                        value=value,
                        expected_type=expected_type,
                        arg_name=f"{arg.name}_{index}",
                        source_type=arg.type,
                    )
                )
            except TypeError as exc:
                raise TypeError(f"Call '{instr.fn_name}' arg#{index} '{arg.name}' type mismatch: {exc}") from exc

        result = self.builder.call(func, args, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_dyn_dispatch_call(self, instr: ProcessedInstruction_call):
        payload = instr.fn_name[len("__dyn_dispatch__") :]
        if "::" not in payload:
            raise ValueError(f"Invalid dyn dispatch call name: {instr.fn_name}")
        trait_name, method_name = payload.rsplit("::", 1)
        if not instr.args:
            raise ValueError("dyn dispatch call requires receiver argument")

        recv = self._get_typed_value(instr.args[0])
        recv_ty = recv.type
        if isinstance(recv_ty, ir.PointerType) and isinstance(recv_ty.pointee, ir.BaseStructType):
            recv = self.builder.load(recv, name=f"{instr.args[0].name}.dyn_load")
            recv_ty = recv.type
        if not isinstance(recv_ty, ir.BaseStructType) or len(recv_ty.elements) != 2:
            raise TypeError(f"dyn dispatch receiver has invalid IR type: {recv_ty}")

        data_ptr = self.builder.extract_value(recv, 0, name=f"{instr.args[0].name}.dyn_data_ptr")
        vtable_ptr = self.builder.extract_value(recv, 1, name=f"{instr.args[0].name}.dyn_vtable_ptr")
        method_names = self._dyn_trait_methods(trait_name)
        if method_name not in method_names:
            raise ValueError(f"No dyn dispatch slot for {trait_name}::{method_name}")
        slot_index = 2 + method_names.index(method_name)

        callee = self._resolve_dyn_callee_from_vtable(
            trait_name=trait_name,
            method_name=method_name,
            slot_index=slot_index,
            vtable_raw_ptr=vtable_ptr,
            result_name=instr.var_out.name,
            receiver_data_ptr=data_ptr,
            args=instr.args,
        )
        return callee

    def _dyn_trait_methods(self, trait_name: str) -> list[str]:
        methods: set[str] = set()
        prefix = f"{trait_name}::"
        for fn in self.module.functions:
            canonical = self._canonical_by_symbol.get(fn.name, fn.name)
            if not canonical.startswith(prefix):
                continue
            tail = canonical[len(prefix) :]
            if not tail:
                continue
            method = tail.split("__", 1)[0]
            methods.add(method)
        return sorted(methods)

    def _collect_dyn_method_candidates(self, trait_name: str, method_name: str) -> list[ir.Function]:
        out: list[ir.Function] = []
        prefix = f"{trait_name}::{method_name}"
        for fn in self.module.functions:
            canonical = self._canonical_by_symbol.get(fn.name, fn.name)
            if not canonical.startswith(prefix):
                continue
            tail = canonical[len(prefix) :]
            if tail and not tail.startswith("__"):
                continue
            out.append(fn)
        return out

    def _find_dyn_impl_function(self, trait_name: str, method_name: str, concrete_type: Type) -> ir.Function | None:
        suffix = mangle_type_name(concrete_type)
        expected = f"{trait_name}::{method_name}__{suffix}"
        fallback = f"{trait_name}::{method_name}"
        for fn in self.module.functions:
            canonical = self._canonical_by_symbol.get(fn.name, fn.name)
            if canonical == expected:
                return fn
        for fn in self.module.functions:
            canonical = self._canonical_by_symbol.get(fn.name, fn.name)
            if canonical == fallback:
                return fn
        return None

    def _get_dyn_vtable_type(self, trait_name: str):
        vtable_name = f"__dyn_vtable_{trait_name.replace('::', '_')}"
        methods = self._dyn_trait_methods(trait_name)
        vtable_struct = self.module.context.get_identified_type(vtable_name)
        if vtable_struct.is_opaque:
            vtable_struct.set_body(*([ir.IntType(8).as_pointer()] * (2 + len(methods))))
        return vtable_struct, methods

    def _get_dyn_vtable_ptr(self, trait_name: str, concrete_type: Type):
        vtable_struct, methods = self._get_dyn_vtable_type(trait_name)
        global_name = f"{vtable_struct.name}__{mangle_type_name(concrete_type)}"
        existing = self.module.globals.get(global_name)
        if isinstance(existing, ir.GlobalVariable):
            return self.builder.bitcast(existing, ir.IntType(8).as_pointer(), name=f"{global_name}.ptr")

        retain_thunk = self._get_dyn_retain_thunk(trait_name, concrete_type)
        drop_thunk = self._get_dyn_drop_thunk(trait_name, concrete_type)
        values: list[ir.Constant] = [
            ir.Constant.bitcast(retain_thunk, ir.IntType(8).as_pointer()),
            ir.Constant.bitcast(drop_thunk, ir.IntType(8).as_pointer()),
        ]
        for method_name in methods:
            fn = self._find_dyn_impl_function(trait_name, method_name, concrete_type)
            if fn is None:
                values.append(ir.Constant(ir.IntType(8).as_pointer(), None))
            else:
                thunk = self._get_dyn_thunk(trait_name, method_name, concrete_type, fn)
                values.append(ir.Constant.bitcast(thunk, ir.IntType(8).as_pointer()))
        gv = ir.GlobalVariable(self.module, vtable_struct, name=global_name)
        gv.global_constant = True
        gv.linkage = "internal"
        gv.initializer = ir.Constant(vtable_struct, values)
        return self.builder.bitcast(gv, ir.IntType(8).as_pointer(), name=f"{global_name}.ptr")

    def _get_dyn_thunk(
        self, trait_name: str, method_name: str, concrete_type: Type, impl_fn: ir.Function
    ) -> ir.Function:
        thunk_name = f"__dyn_thunk_{trait_name.replace('::', '_')}__{method_name}__{mangle_type_name(concrete_type)}"
        existing = self.module.globals.get(thunk_name)
        if isinstance(existing, ir.Function):
            return existing

        impl_type = impl_fn.function_type
        thunk_type = ir.FunctionType(impl_type.return_type, [ir.IntType(8).as_pointer(), *impl_type.args[1:]])
        thunk = ir.Function(self.module, thunk_type, name=thunk_name)
        thunk.linkage = "internal"

        block = thunk.append_basic_block("entry")
        builder = ir.IRBuilder(block)
        typed_self_ptr = builder.bitcast(thunk.args[0], ir.PointerType(impl_type.args[0]), name="self.ptr")
        typed_self = builder.load(typed_self_ptr, name="self")
        result = builder.call(impl_fn, [typed_self, *list(thunk.args[1:])], name="call")
        if isinstance(impl_type.return_type, ir.VoidType):
            builder.ret_void()
        else:
            builder.ret(result)
        return thunk

    def _get_dyn_retain_thunk(self, trait_name: str, concrete_type: Type) -> ir.Function:
        thunk_name = f"__dyn_retain_{trait_name.replace('::', '_')}__{mangle_type_name(concrete_type)}"
        existing = self.module.globals.get(thunk_name)
        if isinstance(existing, ir.Function):
            return existing

        i8ptr = ir.IntType(8).as_pointer()
        thunk_type = ir.FunctionType(ir.VoidType(), [i8ptr])
        thunk = ir.Function(self.module, thunk_type, name=thunk_name)
        thunk.linkage = "internal"

        block = thunk.append_basic_block("entry")
        builder = ir.IRBuilder(block)
        ref_count_ptr = self._dyn_ref_count_ptr(builder, thunk.args[0], "self")
        ref_count = builder.load(ref_count_ptr, name="ref_count")
        one = ir.Constant(ref_count.type, 1)
        next_ref_count = builder.add(ref_count, one, name="next_ref_count")
        builder.store(next_ref_count, ref_count_ptr)
        builder.ret_void()
        return thunk

    def _get_dyn_drop_thunk(self, trait_name: str, concrete_type: Type) -> ir.Function:
        thunk_name = f"__dyn_drop_{trait_name.replace('::', '_')}__{mangle_type_name(concrete_type)}"
        existing = self.module.globals.get(thunk_name)
        if isinstance(existing, ir.Function):
            return existing

        i8ptr = ir.IntType(8).as_pointer()
        thunk_type = ir.FunctionType(ir.VoidType(), [i8ptr])
        thunk = ir.Function(self.module, thunk_type, name=thunk_name)
        thunk.linkage = "internal"

        block = thunk.append_basic_block("entry")
        builder = ir.IRBuilder(block)
        ref_count_ptr = self._dyn_ref_count_ptr(builder, thunk.args[0], "self")
        ref_count = builder.load(ref_count_ptr, name="ref_count")
        one = ir.Constant(ref_count.type, 1)
        should_free = builder.icmp_unsigned("<=", ref_count, one, name="should_free")

        free_block = thunk.append_basic_block("free")
        retain_block = thunk.append_basic_block("retain")
        builder.cbranch(should_free, free_block, retain_block)

        builder.position_at_end(retain_block)
        next_ref_count = builder.sub(ref_count, one, name="next_ref_count")
        builder.store(next_ref_count, ref_count_ptr)
        builder.ret_void()

        builder.position_at_end(free_block)
        typed_ptr = builder.bitcast(thunk.args[0], ir.PointerType(self._build_type(concrete_type)), name="self.ptr")
        value = builder.load(typed_ptr, name="self")
        drop_fn = self._find_function_by_canonical(f"__drop_{mangle_type_name(concrete_type)}")
        if drop_fn is not None:
            builder.call(drop_fn, [value])
        owner_ptr = self._dyn_owner_ptr(builder, thunk.args[0], "self")
        builder.call(self._get_free_function(), [owner_ptr])
        builder.ret_void()
        return thunk

    def _find_function_by_canonical(self, canonical_name: str) -> ir.Function | None:
        emitted_name = self._symbol_by_canonical.get(canonical_name, canonical_name)
        value = self.module.globals.get(emitted_name)
        if isinstance(value, ir.Function):
            return value
        value = self.module.globals.get(canonical_name)
        if isinstance(value, ir.Function):
            return value
        return None

    def _resolve_dyn_callee_from_vtable(
        self,
        *,
        trait_name: str,
        method_name: str,
        slot_index: int,
        vtable_raw_ptr,
        result_name: str,
        receiver_data_ptr,
        args: list[TypedVariable],
    ):
        vtable_struct, _ = self._get_dyn_vtable_type(trait_name)
        vtable_ptr_t = ir.PointerType(vtable_struct)
        typed_vtable_ptr = self.builder.bitcast(vtable_raw_ptr, vtable_ptr_t, name=f"{result_name}.vt_cast")
        slot_ptr = self.builder.gep(
            typed_vtable_ptr,
            [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), slot_index)],
            name=f"{result_name}.vt_slot_ptr",
        )
        fn_raw = self.builder.load(slot_ptr, name=f"{result_name}.vt_fn_raw")
        null_fn = ir.Constant(fn_raw.type, None)
        is_null = self.builder.icmp_unsigned("==", fn_raw, null_fn, name=f"{result_name}.vt_null")
        ok_block = self.builder.function.append_basic_block(f"dyn_vt_ok_{len(self.builder.function.blocks)}")
        bad_block = self.builder.function.append_basic_block(f"dyn_vt_bad_{len(self.builder.function.blocks)}")
        self.builder.cbranch(is_null, bad_block, ok_block)

        self.builder.position_at_end(bad_block)
        trap = self._get_trap_intrinsic()
        self.builder.call(trap, [])
        self.builder.unreachable()

        self.builder.position_at_end(ok_block)
        method_candidates = self._collect_dyn_method_candidates(trait_name, method_name)
        if not method_candidates:
            raise ValueError(f"No dyn dispatch candidates found for {trait_name}::{method_name}")
        sample_proto = method_candidates[0].function_type
        proto = ir.FunctionType(sample_proto.return_type, [ir.IntType(8).as_pointer(), *sample_proto.args[1:]])
        fn_ptr_t = ir.PointerType(proto)
        fn_ptr = self.builder.bitcast(fn_raw, fn_ptr_t, name=f"{result_name}.vt_fn")

        call_args = [receiver_data_ptr]
        for arg_index, expected_type in enumerate(proto.args[1:], start=1):
            arg = args[arg_index]
            value = self._get_typed_value(arg)
            call_args.append(
                self._coerce_call_arg(
                    value=value,
                    expected_type=expected_type,
                    arg_name=f"{arg.name}_{arg_index}",
                    source_type=arg.type,
                )
            )
        return self.builder.call(fn_ptr, call_args, name=f"{result_name}.dyn_call")

    def _pack_dyn_payload(self, value, source_type: Type):
        malloc_func = self._get_malloc_function()
        payload_size = self._sizeof(source_type)
        ref_size = ir.Constant(payload_size.type, self._get_pointer_width_bits() // 8)
        byte_size = self.builder.add(payload_size, ref_size, name=".dyn_alloc_size")
        owner_ptr = self.builder.call(malloc_func, [byte_size], name=".dyn_payload_owner")
        ref_count_ptr = self.builder.bitcast(
            owner_ptr,
            ir.PointerType(ir.IntType(self._get_pointer_width_bits())),
            name=".dyn_ref_count_ptr",
        )
        self.builder.store(ir.Constant(ir.IntType(self._get_pointer_width_bits()), 1), ref_count_ptr)
        raw_ptr = self.builder.gep(
            owner_ptr,
            [ir.Constant(ir.IntType(self._get_pointer_width_bits()), self._get_pointer_width_bits() // 8)],
            name=".dyn_payload_raw",
        )
        typed_ptr = self.builder.bitcast(raw_ptr, ir.PointerType(value.type), name=".dyn_payload_typed")
        self.builder.store(value, typed_ptr)
        retain_fn = self._find_function_by_canonical(f"__retain_{mangle_type_name(source_type)}")
        if retain_fn is not None:
            self.builder.call(retain_fn, [value])
        return raw_ptr

    def _dyn_owner_ptr(self, builder: ir.IRBuilder, data_ptr, name: str):
        offset = ir.Constant(ir.IntType(self._get_pointer_width_bits()), -(self._get_pointer_width_bits() // 8))
        return builder.gep(data_ptr, [offset], name=f"{name}.owner")

    def _dyn_ref_count_ptr(self, builder: ir.IRBuilder, data_ptr, name: str):
        owner_ptr = self._dyn_owner_ptr(builder, data_ptr, name)
        return builder.bitcast(
            owner_ptr,
            ir.PointerType(ir.IntType(self._get_pointer_width_bits())),
            name=f"{name}.ref_count_ptr",
        )

    def _dyn_struct_name(self, trait_name: str) -> str:
        return f"__dyn_{trait_name.replace('::', '_')}"

    def _build_callvoid(self, instr: ProcessedInstruction_callvoid):
        self._comment_instruction(instr)
        func = self._get_or_declare_called_function_void(instr)

        expected_types = list(func.function_type.args)
        if len(expected_types) != len(instr.args):
            raise ValueError(
                f"Call arg count mismatch for '{instr.fn_name}': {len(instr.args)} != {len(expected_types)}"
            )

        args = []
        for index, (expected_type, arg) in enumerate(zip(expected_types, instr.args, strict=True)):
            value = self._get_typed_value(arg)
            args.append(
                self._coerce_call_arg(
                    value=value,
                    expected_type=expected_type,
                    arg_name=f"{arg.name}_{index}",
                    source_type=arg.type,
                )
            )
        if instr.assign_to is None:
            self.builder.call(func, args)
            return
        result = self.builder.call(func, args, name=instr.assign_to.name)
        self._variables[instr.assign_to.name] = result

    def _try_build_trait_op_call(self, instr: ProcessedInstruction_call):
        if len(instr.args) != 2:
            return None
        if "::" not in instr.fn_name:
            return None
        tail = instr.fn_name.rsplit("::", 1)[-1]
        trait_name: str | None = None
        if tail == "op":
            trait_name = instr.fn_name.rsplit("::", 2)[-2]
        elif tail.endswith("__op"):
            trait_name = tail[: -len("__op")]
        if trait_name is None:
            return None
        lhs = self._get_typed_value(instr.args[0])
        rhs = self._get_typed_value(instr.args[1])

        if trait_name == "Add":
            if self._is_str_value(lhs):
                return self._build_str_concat(lhs, rhs, instr.var_out.name)
            if isinstance(lhs.type, ir.PointerType) and isinstance(rhs.type, ir.IntType):
                return self.builder.gep(lhs, [rhs], name=instr.var_out.name)
            return (
                self.builder.fadd(lhs, rhs, name=instr.var_out.name)
                if self._is_float_value(lhs)
                else self.builder.add(lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Sub":
            return (
                self.builder.fsub(lhs, rhs, name=instr.var_out.name)
                if self._is_float_value(lhs)
                else self.builder.sub(lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Mul":
            return (
                self.builder.fmul(lhs, rhs, name=instr.var_out.name)
                if self._is_float_value(lhs)
                else self.builder.mul(lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Div":
            if self._is_float_value(lhs):
                return self.builder.fdiv(lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.udiv(lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.sdiv(lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Rem":
            if self._is_float_value(lhs):
                return self.builder.frem(lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.urem(lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.srem(lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Eq":
            if self._is_str_value(lhs):
                return self._build_str_eq(lhs, rhs, instr.var_out.name)
            enum_cmp = self._try_build_enum_like_eq(lhs, rhs, instr.var_out.name, negate=False)
            if enum_cmp is not None:
                return enum_cmp
            if self._is_float_value(lhs):
                return self.builder.fcmp_ordered("==", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned("==", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed("==", lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Ne":
            if self._is_str_value(lhs):
                eq = self._build_str_eq(lhs, rhs, f"{instr.var_out.name}.eq")
                return self.builder.icmp_unsigned("==", eq, ir.Constant(ir.IntType(1), 0), name=instr.var_out.name)
            enum_cmp = self._try_build_enum_like_eq(lhs, rhs, instr.var_out.name, negate=True)
            if enum_cmp is not None:
                return enum_cmp
            if self._is_float_value(lhs):
                return self.builder.fcmp_unordered("!=", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned("!=", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed("!=", lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Lt":
            if self._is_float_value(lhs):
                return self.builder.fcmp_ordered("<", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned("<", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed("<", lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Le":
            if self._is_float_value(lhs):
                return self.builder.fcmp_ordered("<=", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned("<=", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed("<=", lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Gt":
            if self._is_float_value(lhs):
                return self.builder.fcmp_ordered(">", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned(">", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed(">", lhs, rhs, name=instr.var_out.name)
            )
        if trait_name == "Ge":
            if self._is_float_value(lhs):
                return self.builder.fcmp_ordered(">=", lhs, rhs, name=instr.var_out.name)
            return (
                self.builder.icmp_unsigned(">=", lhs, rhs, name=instr.var_out.name)
                if self._is_unsigned_type(instr.args[0].type)
                else self.builder.icmp_signed(">=", lhs, rhs, name=instr.var_out.name)
            )
        return None

    def _try_build_enum_like_eq(self, lhs, rhs, out_name: str, *, negate: bool):
        if lhs.type != rhs.type:
            return None
        if not isinstance(lhs.type, ir.BaseStructType):
            return None
        if len(lhs.type.elements) < 1:
            return None
        tag_type = lhs.type.elements[0]
        if not isinstance(tag_type, ir.IntType):
            return None

        lhs_tag = self.builder.extract_value(lhs, 0, name=f"{out_name}.lhs_tag")
        rhs_tag = self.builder.extract_value(rhs, 0, name=f"{out_name}.rhs_tag")
        op = "!=" if negate else "=="
        return self.builder.icmp_unsigned(op, lhs_tag, rhs_tag, name=out_name)

    def _build_str_eq(self, lhs, rhs, name: str):
        if not self._is_str_value(lhs) or not self._is_str_value(rhs):
            raise TypeError(f"Invalid str compare operands: {lhs.type} and {rhs.type}")
        eq_fn = self._get_str_eq_function()
        return self.builder.call(eq_fn, [lhs, rhs], name=name)

    def _build_str_concat(self, lhs, rhs, name: str):
        if not self._is_str_value(lhs) or not self._is_str_value(rhs):
            raise TypeError(f"Invalid str concat operands: {lhs.type} and {rhs.type}")
        concat_fn = self._get_str_concat_function()
        return self.builder.call(concat_fn, [lhs, rhs], name=name)

    def _get_or_declare_called_function(self, instr: ProcessedInstruction_call) -> ir.Function:
        emitted_call_name = self._symbol_by_canonical.get(instr.fn_name, instr.fn_name)
        if emitted_call_name == instr.fn_name and "::" in instr.fn_name and instr.fn_name != "main":
            emitted_call_name = self._emit_like_symbol_name(instr.fn_name)
        for fn in self.module.functions:
            if fn.name == emitted_call_name:
                return fn

        # Fallback for emitted-like call names (owner__method) that may be produced
        # by lowering while declarations are still stored under canonical names.
        alias_candidates: list[ir.Function] = []
        for fn in self.module.functions:
            if self._emit_like_symbol_name(fn.name) != emitted_call_name:
                continue
            if len(fn.function_type.args) != len(instr.args):
                continue
            matches = True
            for expected, arg in zip(fn.function_type.args, instr.args, strict=True):
                if arg.type is None:
                    matches = False
                    break
                if self._build_type(arg.type) != expected:
                    matches = False
                    break
            if matches:
                alias_candidates.append(fn)

        if len(alias_candidates) == 1:
            return alias_candidates[0]

        if instr.var_out.type is None:
            raise TypeError(f"Cannot declare function '{emitted_call_name}' without known return type")

        ret_type = self._build_type(instr.var_out.type)
        arg_types: list[ir.Type] = []
        for arg in instr.args:
            if arg.type is None:
                raise TypeError(
                    f"Cannot declare function '{emitted_call_name}' without known arg type for '{arg.name}'"
                )
            arg_types.append(self._build_type(arg.type))

        fn_type = ir.FunctionType(ret_type, arg_types)
        return ir.Function(self.module, fn_type, name=emitted_call_name)

    def _get_or_declare_called_function_void(self, instr: ProcessedInstruction_callvoid) -> ir.Function:
        emitted_call_name = self._symbol_by_canonical.get(instr.fn_name, instr.fn_name)
        if emitted_call_name == instr.fn_name and "::" in instr.fn_name and instr.fn_name != "main":
            emitted_call_name = self._emit_like_symbol_name(instr.fn_name)
        for fn in self.module.functions:
            if fn.name == emitted_call_name:
                return fn

        arg_types = [self._build_type(arg.type) for arg in instr.args]
        ret_type: ir.Type = ir.VoidType()
        if instr.assign_to is not None:
            ret_type = self._build_type(instr.assign_to.type)
        fn_type = ir.FunctionType(ret_type, arg_types)
        return ir.Function(self.module, fn_type, name=emitted_call_name)

    def _get_typed_value(self, var: TypedVariable):
        value = self._variables.get(var.name)
        if value is not None:
            return value

        if var.type is None:
            raise KeyError(var.name)

        placeholder = ir.Constant(self._build_type(var.type), ir.Undefined)
        self._variables[var.name] = placeholder
        return placeholder

    def _coerce_call_arg(self, value, expected_type: ir.Type, arg_name: str, source_type: Type | None = None):
        assert hasattr(value, "type")
        if value.type == expected_type:
            return value

        unwrapped = self._unwrap_wrapper_argument(value=value, expected_type=expected_type, arg_name=arg_name)
        if unwrapped is not None:
            return unwrapped

        wrapped = self._wrap_plain_argument(value=value, expected_type=expected_type, arg_name=arg_name)
        if wrapped is not None:
            return wrapped

        if isinstance(value.type, ir.PointerType) and value.type.pointee == expected_type:
            return self.builder.load(value, name=f"{arg_name}.load")

        if isinstance(value.type, ir.IntType) and isinstance(expected_type, ir.IntType):
            if value.type.width < expected_type.width:
                if self._is_signed_integer_type(source_type):
                    return self.builder.sext(value, expected_type, name=f"{arg_name}.sext")
                return self.builder.zext(value, expected_type, name=f"{arg_name}.zext")
            if value.type.width > expected_type.width:
                return self.builder.trunc(value, expected_type, name=f"{arg_name}.trunc")
            return value

        if isinstance(value.type, (ir.FloatType, ir.DoubleType)) and isinstance(
            expected_type, (ir.FloatType, ir.DoubleType)
        ):
            source_width = self._float_width(value.type)
            expected_width = self._float_width(expected_type)
            if source_width < expected_width:
                return self.builder.fpext(value, expected_type, name=f"{arg_name}.fpext")
            if source_width > expected_width:
                return self.builder.fptrunc(value, expected_type, name=f"{arg_name}.fptrunc")
            return value

        if (
            isinstance(value.type, ir.BaseStructType)
            and len(value.type.elements) == 1
            and value.type.elements[0] == expected_type
        ):
            return self.builder.extract_value(value, 0, name=f"{arg_name}.unwrap0")

        if isinstance(value.type, ir.BaseStructType) and isinstance(expected_type, ir.BaseStructType):
            if len(value.type.elements) == len(expected_type.elements):
                # Temporary compatibility bridge for monomorphized generic containers
                # that still share one symbol name across different T.
                src_slot = self.builder.alloca(value.type, name=f"{arg_name}.struct_cast_src")
                self.builder.store(value, src_slot)
                dst_slot = self.builder.bitcast(
                    src_slot, ir.PointerType(expected_type), name=f"{arg_name}.struct_cast_ptr"
                )
                return self.builder.load(dst_slot, name=f"{arg_name}.struct_cast_val")

        if isinstance(value.type, ir.PointerType) and isinstance(expected_type, ir.PointerType):
            return self.builder.bitcast(value, expected_type, name=f"{arg_name}.bitcast")

        raise TypeError(
            "Type of arg mismatch: "
            f"{value.type} ({type(value.type).__name__}, name={getattr(value.type, 'name', None)}) != "
            f"{expected_type} ({type(expected_type).__name__}, name={getattr(expected_type, 'name', None)}), "
            f"value_fields={len(value.type.elements) if isinstance(value.type, ir.BaseStructType) else 'na'}, "
            f"expected_fields={len(expected_type.elements) if isinstance(expected_type, ir.BaseStructType) else 'na'}"
        )

    def _is_signed_integer_type(self, typ: Type | None) -> bool:
        if typ is None:
            return False
        return (
            isinstance(typ, Isize_t)
            or typ.name == "isize"
            or (len(typ.name) > 1 and typ.name.startswith("i") and typ.name[1:].isdigit())
        )

    def _float_width(self, typ: ir.Type) -> int:
        if isinstance(typ, ir.FloatType):
            return 32
        if isinstance(typ, ir.DoubleType):
            return 64
        raise TypeError(f"Unsupported float type: {typ}")

    def _unwrap_wrapper_argument(self, value, expected_type: ir.Type, arg_name: str):
        wrapper_value = value
        if isinstance(wrapper_value.type, ir.PointerType) and isinstance(wrapper_value.type.pointee, ir.BaseStructType):
            wrapper_value = self.builder.load(wrapper_value, name=f"{arg_name}.wrapper_load")

        if not isinstance(wrapper_value.type, ir.BaseStructType):
            return None

        wrapper_name = getattr(wrapper_value.type, "name", "")
        if not (wrapper_name.endswith("_HSP") or wrapper_name.endswith("_SSP")):
            return None

        expected_name = getattr(expected_type, "name", None)
        if expected_name is None:
            return None

        inner_name = wrapper_name.removesuffix("_HSP").removesuffix("_SSP")
        if inner_name != expected_name:
            return None

        if len(wrapper_value.type.elements) < 1:
            return None
        inner_slot = wrapper_value.type.elements[0]
        if not isinstance(inner_slot, ir.PointerType):
            return None

        inner_ptr = self.builder.extract_value(wrapper_value, 0, name=f"{arg_name}.inner_ptr")
        if not isinstance(inner_ptr.type, ir.PointerType):
            return None

        pointee = inner_ptr.type.pointee
        pointee_name = getattr(pointee, "name", None)
        if pointee != expected_type and pointee_name != expected_name:
            return None

        return self.builder.load(inner_ptr, name=f"{arg_name}.inner")

    def _wrap_plain_argument(self, value, expected_type: ir.Type, arg_name: str):
        if not isinstance(expected_type, ir.BaseStructType):
            return None
        if not isinstance(value.type, ir.BaseStructType):
            return None

        wrapper_name = getattr(expected_type, "name", "")
        if not (wrapper_name.endswith("_HSP") or wrapper_name.endswith("_SSP")):
            return None

        inner_name = wrapper_name.removesuffix("_HSP").removesuffix("_SSP")
        value_name = getattr(value.type, "name", "")
        if value_name != inner_name:
            return None

        self._materialize_opaque_wrapper_struct(expected_type)
        if len(expected_type.elements) < 1:
            return None
        inner_slot = expected_type.elements[0]
        if not isinstance(inner_slot, ir.PointerType):
            return None

        inner_storage = self.builder.alloca(value.type, name=f"{arg_name}.inner_storage")
        self.builder.store(value, inner_storage)

        wrapper_storage = self.builder.alloca(expected_type, name=f"{arg_name}.wrapper_storage")
        inner_ptr_field = self.builder.gep(
            wrapper_storage,
            [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            name=f"{arg_name}.inner_ptr_field",
        )
        field_type = inner_ptr_field.type.pointee
        stored_ptr = inner_storage
        if stored_ptr.type != field_type:
            if isinstance(stored_ptr.type, ir.PointerType) and isinstance(field_type, ir.PointerType):
                stored_ptr = self.builder.bitcast(stored_ptr, field_type, name=f"{arg_name}.inner_ptr_cast")
            else:
                return None
        self.builder.store(stored_ptr, inner_ptr_field)

        for field_index in range(1, len(expected_type.elements)):
            field_ptr = self.builder.gep(
                wrapper_storage,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_index)],
                name=f"{arg_name}.meta_{field_index}",
            )
            field_type = expected_type.elements[field_index]
            self.builder.store(self._zero_of_type(field_type), field_ptr)

        return self.builder.load(wrapper_storage, name=f"{arg_name}.wrapped")

    def _zero_of_type(self, typ: ir.Type):
        if isinstance(typ, ir.IntType):
            return ir.Constant(typ, 0)
        if isinstance(typ, ir.PointerType):
            return ir.Constant(typ, None)
        if isinstance(typ, self._float_ir_types()):
            return ir.Constant(typ, 0.0)
        return ir.Constant(typ, None)

    @classmethod
    def _is_float_value(cls, value: ir.Value) -> bool:
        return isinstance(value.type, cls._float_ir_types())

    def _is_str_value(self, value: ir.Value) -> bool:
        return value.type == self._get_str_type()

    @staticmethod
    def _is_unsigned_type(typ: Type | None) -> bool:
        if typ is None:
            return False
        return isinstance(typ, Usize_t) or typ.name == "usize" or typ.name.startswith("u")

    @staticmethod
    def _float_ir_types() -> tuple[type, ...]:
        types: list[type] = [ir.HalfType, ir.FloatType, ir.DoubleType]
        fp128_type = getattr(ir, "FP128Type", None)
        if fp128_type is not None:
            types.append(fp128_type)
        return tuple(types)

    def _build_br(self, instr: Instruction_br):
        self._comment_instruction(instr)
        self.builder.branch(self._blocks[instr.label])

    def _build_cbr(self, instr: Instruction_cbr):
        self._comment_instruction(instr)
        cond_value = self._variables[instr.cond_var.name]
        self.builder.cbranch(cond_value, self._blocks[instr.true_br_label], self._blocks[instr.else_br_label])

    def _build_switch(self, instr: ProcessedInstruction_switch):
        self.builder.comment("")
        self.builder.comment("switch")
        cond_value = self._variables[instr.cond_var.name]

        blocks_mapping: dict[str, ir.Block] = {}
        for ir_block in self.builder.function.blocks:
            blocks_mapping[ir_block.name] = ir_block

        default_block = blocks_mapping[instr.default_case]
        switch = self.builder.switch(cond_value, default_block)
        for case_value, block_name in instr.cases:
            const_val = self._build_primitive(case_value)
            target_block = blocks_mapping[block_name]
            switch.add_case(const_val, target_block)

    def _build_ret(self, instr: ProcessedInstruction_ret):
        self._comment_instruction(instr)
        expected_ret_type = self.builder.function.function_type.return_type
        if isinstance(expected_ret_type, ir.VoidType):
            self.builder.ret_void()
            return

        value = self._get_typed_value(instr.var)
        if value.type != expected_ret_type:
            if (
                isinstance(value.type, ir.BaseStructType)
                and isinstance(expected_ret_type, ir.BaseStructType)
                and len(value.type.elements) == len(expected_ret_type.elements)
            ):
                src_slot = self.builder.alloca(value.type, name=f"{instr.var.name}.ret_cast_src")
                self.builder.store(value, src_slot)
                dst_slot = self.builder.bitcast(
                    src_slot, ir.PointerType(expected_ret_type), name=f"{instr.var.name}.ret_cast_ptr"
                )
                value = self.builder.load(dst_slot, name=f"{instr.var.name}.ret_cast_val")
            elif (
                isinstance(value.type, ir.BaseStructType)
                and len(value.type.elements) == 1
                and value.type.elements[0] == expected_ret_type
            ):
                value = self.builder.extract_value(value, 0, name=f"{instr.var.name}.ret_unwrap0")
        self.builder.ret(value)

    def _build_phi(self, instr: ProcessedInstruction_phi):
        self._comment_instruction(instr)

        assert instr.var_out.type
        phi = self.builder.phi(typ=self._build_type(instr.var_out.type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = phi
        self._pending_phi_incomings.append((phi, instr.args))
        return phi

    def _resolve_pending_phi_incomings(self):
        for phi, args in self._pending_phi_incomings:
            arg_by_block: dict[str, object] = {}
            for arg in args:
                arg_by_block[arg[1]] = self._variables[arg[0].name]

            parent_name = phi.parent.name
            predecessors = self._block_predecessors.get(parent_name, set())
            for pred_name in predecessors:
                value = arg_by_block.get(pred_name)
                if value is None:
                    value = ir.Constant(phi.type, ir.Undefined)
                phi.add_incoming(value=value, block=self._blocks[pred_name])

    def _build_type(self, type: Type) -> ir.Type:
        if type.name == "void":
            return ir.VoidType()

        if isinstance(type, (HeapSmartPointer, StackSmartPointer)):
            wrapper_name = type.get_name()
            if wrapper_name not in self._structs:
                self._ensure_smart_pointer_wrapper(type)
            return self._structs[wrapper_name]

        if isinstance(type, Pointer):
            return ir.PointerType(self._build_type(type.pointee))

        if type.name == "dyn" and len(type.generics) == 1:
            trait_name = type.generics[0].name
            dyn_name = self._dyn_struct_name(trait_name)
            if dyn_name not in self._structs:
                dyn_struct = self.module.context.get_identified_type(dyn_name)
                if dyn_struct.is_opaque:
                    dyn_struct.set_body(ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer())
                self._structs[dyn_name] = dyn_struct
            return self._structs[dyn_name]

        template_key = type.name.split("[", 1)[0]
        template_args = list(type.generics)
        if not template_args and "[" in type.name and type.name.endswith("]"):
            template_args = self._parse_inline_generic_args(type.name)

        if template_key in self._generic_struct_templates and template_args:
            generic_names, template_fields = self._generic_struct_templates[template_key]
            concrete_name = type.name if "[" in type.name else str(Type(template_key, template_args))
            concrete_struct = self.module.context.get_identified_type(concrete_name)
            self._structs[concrete_name] = concrete_struct
            if concrete_struct.is_opaque:
                mapping = {name: arg for name, arg in zip(generic_names, template_args, strict=False)}
                concrete_fields = [
                    self._build_type(self._substitute_generic_type(field_type, mapping))
                    for field_type in template_fields
                ]
                concrete_struct.set_body(*concrete_fields)
            return concrete_struct

        if isinstance(type, Usize_t):
            return ir.IntType(bits=self._get_pointer_width_bits() if type.size is None else type.size)
        if type.name == "usize":
            return ir.IntType(bits=self._get_pointer_width_bits())
        if type.name.startswith("u") and type.name[1:].isdigit():
            return ir.IntType(bits=int(type.name[1:]))

        if isinstance(type, Isize_t):
            return ir.IntType(bits=self._get_pointer_width_bits() if type.size is None else type.size)
        if type.name == "isize":
            return ir.IntType(bits=self._get_pointer_width_bits())
        if type.name.startswith("i") and type.name[1:].isdigit():
            return ir.IntType(bits=int(type.name[1:]))

        if isinstance(type, Float_t) or (type.name.startswith("f") and type.name[1:].isdigit()):
            size = type.size if isinstance(type, Float_t) else int(type.name[1:])
            match size:
                case 16:
                    return ir.HalfType()
                case 32:
                    return ir.FloatType()
                case 64:
                    return ir.DoubleType()
                case 128:
                    fp128_type = getattr(ir, "FP128Type", None)
                    if fp128_type is None:
                        raise ValueError("Current llvmlite build does not support f128")
                    return fp128_type()
                case _:
                    raise ValueError(f"Unsupported float size: f{size}")

        if isinstance(type, Str_t) or type.name == "str":
            return self._get_str_type()

        struct_key = type.name
        if struct_key not in self._structs and "[" in struct_key and struct_key.endswith("]"):
            base_name = struct_key.split("[", 1)[0]
            if base_name in self._structs:
                struct_key = base_name

        if struct_key not in self._structs:
            # Allow referencing external/opaque structs across refrain boundaries.
            fallback = self.module.context.get_identified_type(type.name)
            if fallback.is_opaque:
                # Fallback sized layout for unresolved aggregate types (e.g. enums not
                # materialized as structs in the current pipeline stage).
                fallback.set_body(ir.IntType(8), ir.IntType(8).as_pointer())
            self._structs[struct_key] = fallback
        struct = self._structs[struct_key]

        return struct

    def _is_generic_placeholder_name(self, name: str) -> bool:
        if name in self._structs:
            return False
        return (
            name in {"Self", "T"}
            or (len(name) == 1 and name.isupper())
            or (name.startswith("T") and name[1:].isdigit())
            or ("::" not in name and name[:1].isupper())
        )

    def _collect_generic_placeholders(self, types: list[Type]) -> list[str]:
        names: list[str] = []

        def visit(typ: Type):
            if self._is_generic_placeholder_name(typ.name) and not typ.generics and typ.name not in names:
                names.append(typ.name)
            for generic in typ.generics:
                visit(generic)
            if isinstance(typ, Pointer):
                visit(typ.pointee)

        for typ in types:
            visit(typ)
        return names

    def _substitute_generic_type(self, typ: Type, mapping: dict[str, Type]) -> Type:
        if isinstance(typ, Pointer):
            return Pointer(self._substitute_generic_type(typ.pointee, mapping))
        if not typ.generics and typ.name in mapping:
            return mapping[typ.name]
        return Type(typ.name, [self._substitute_generic_type(generic, mapping) for generic in typ.generics])

    def _parse_inline_generic_args(self, type_name: str) -> list[Type]:
        start = type_name.find("[")
        if start < 0 or not type_name.endswith("]"):
            return []
        payload = type_name[start + 1 : -1]
        items: list[str] = []
        level = 0
        token = []
        for ch in payload:
            if ch == "," and level == 0:
                part = "".join(token).strip()
                if part:
                    items.append(part)
                token = []
                continue
            if ch == "[":
                level += 1
            elif ch == "]":
                level -= 1
            token.append(ch)
        tail = "".join(token).strip()
        if tail:
            items.append(tail)
        return [Type(item) for item in items]

    def _ensure_smart_pointer_wrapper(self, smart_pointer: HeapSmartPointer | StackSmartPointer):
        wrapper_name = smart_pointer.get_name()
        wrapper_struct = self.module.context.get_identified_type(wrapper_name)
        self._structs[wrapper_name] = wrapper_struct
        if wrapper_struct.is_opaque:
            wrapper_struct.set_body(ir.PointerType(self._build_type(smart_pointer.pointee)))

    def _unwrap_smart_pointer_wrapper_for_gep(self, base, field_index: int, result_name: str, expected_result_type):
        while isinstance(base.type, ir.PointerType):
            pointee = base.type.pointee
            if not isinstance(pointee, ir.BaseStructType):
                return base
            self._materialize_opaque_wrapper_struct(pointee)
            element_count = len(pointee.elements)
            pointee_name = getattr(pointee, "name", "")

            if field_index < element_count:
                # Smart-pointer wrappers carry metadata fields after `ptr`.
                # If the requested slot type doesn't match the expected result type,
                # treat this as access into the wrapped value and unwrap first.
                if (
                    field_index != 0
                    and (pointee_name.endswith("_HSP") or pointee_name.endswith("_SSP"))
                    and element_count >= 1
                    and isinstance(pointee.elements[0], ir.PointerType)
                ):
                    direct_result_type = ir.PointerType(pointee.elements[field_index])
                    if expected_result_type is not None and str(direct_result_type) == str(expected_result_type):
                        return base
                else:
                    return base
            elif element_count != 1:
                return base

            wrapped_ptr_type = pointee.elements[0]
            if not isinstance(wrapped_ptr_type, ir.PointerType):
                return base

            ptr_field_ptr = self.builder.gep(
                base,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
                name=f"{result_name}.wrapped_ptr_ptr",
            )
            base = self.builder.load(ptr_field_ptr, name=f"{result_name}.wrapped_ptr")

        return base

    def _materialize_opaque_wrapper_struct(self, struct_type: ir.BaseStructType):
        if not isinstance(struct_type, ir.IdentifiedStructType):
            return
        if not struct_type.is_opaque:
            return
        if struct_type.name.endswith("_HSP"):
            inner_name = struct_type.name.removesuffix("_HSP")
        elif struct_type.name.endswith("_SSP"):
            inner_name = struct_type.name.removesuffix("_SSP")
        else:
            return

        if inner_name not in self._structs:
            self._structs[inner_name] = self.module.context.get_identified_type(inner_name)
        struct_type.set_body(ir.PointerType(self._structs[inner_name]))

    def _build_primitive(self, prim: Primitive) -> ir.Constant:
        if isinstance(prim, Usize):
            size = getattr(prim.type, "size", None)
            bits = self._get_pointer_width_bits() if size is None else size
            return ir.Constant(ir.IntType(bits=bits), prim.val)
        if isinstance(prim, Isize):
            size = getattr(prim.type, "size", None)
            bits = self._get_pointer_width_bits() if size is None else size
            return ir.Constant(ir.IntType(bits=bits), prim.val)
        if isinstance(prim, Float):
            return ir.Constant(self._build_type(prim.type), prim.val)
        if isinstance(prim, Str):
            encoded = bytearray(prim.val.encode("utf-8"))
            encoded.append(0)
            array_type = ir.ArrayType(ir.IntType(8), len(encoded))
            literal_type = ir.LiteralStructType(
                [
                    ir.IntType(self._get_pointer_width_bits()),
                    ir.IntType(self._get_pointer_width_bits()),
                    array_type,
                ]
            )
            literal_name = f".str.{self._string_literal_counter}"
            self._string_literal_counter += 1

            global_var = ir.GlobalVariable(self.module, literal_type, name=literal_name)
            global_var.global_constant = True
            global_var.linkage = "internal"
            global_var.initializer = ir.Constant(
                literal_type,
                [
                    ir.Constant(ir.IntType(self._get_pointer_width_bits()), 0),
                    ir.Constant(ir.IntType(self._get_pointer_width_bits()), len(encoded) - 1),
                    ir.Constant(array_type, encoded),
                ],
            )

            ptr = ir.Constant.bitcast(global_var, ir.IntType(8).as_pointer())
            return ir.Constant(self._get_str_type(), [ptr])
        raise NotImplementedError(f"Unsupported primitive: {prim}")

    def _get_str_type(self) -> ir.IdentifiedStructType:
        if self._str_type is not None:
            return self._str_type

        str_type = self.module.context.get_identified_type("str")
        if str_type.is_opaque:
            str_type.set_body(ir.IntType(8).as_pointer())
        self._str_type = str_type
        return str_type

    def _get_pointer_width_bits(self) -> int:
        if self._pointer_width_bits is not None:
            return self._pointer_width_bits

        # This backend only targets the native machine, so host pointer width
        # is the correct machine-sized integer width for `usize` / `isize`.
        self._pointer_width_bits = ctypes.sizeof(ctypes.c_void_p) * 8
        return self._pointer_width_bits

    def _sizeof(self, type: Type, builder: ir.IRBuilder | None = None):
        if builder is None:
            builder = self.builder
        t = self._build_type(type)
        null_ptr_type = ir.PointerType(t)
        null_ptr = ir.Constant(null_ptr_type, None)
        one = ir.Constant(ir.IntType(32), 1)
        size_ptr = builder.gep(null_ptr, [one], name=f".sizeof_{type.name}_ptr")
        return builder.ptrtoint(size_ptr, ir.IntType(64), name=f".sizeof_{type.name}_")

    def _get_malloc_function(self) -> ir.Function:
        if "malloc" in self.module.globals:
            return self.module.globals["malloc"]
        malloc_type = ir.FunctionType(
            ir.IntType(8).as_pointer(),
            [ir.IntType(64)],
        )

        malloc_func = ir.Function(self.module, malloc_type, name="malloc")
        malloc_func.attributes.add("noinline")
        return malloc_func

    def _get_realloc_function(self) -> ir.Function:
        if "realloc" in self.module.globals:
            return self.module.globals["realloc"]
        realloc_type = ir.FunctionType(
            ir.IntType(8).as_pointer(),
            [ir.IntType(8).as_pointer(), ir.IntType(self._get_pointer_width_bits())],
        )
        realloc_func = ir.Function(self.module, realloc_type, name="realloc")
        realloc_func.attributes.add("noinline")
        return realloc_func

    def _get_free_function(self):
        if "free" in self.module.globals:
            return self.module.globals["free"]

        free_type = ir.FunctionType(ir.VoidType(), [ir.IntType(8).as_pointer()])
        free_func = ir.Function(self.module, free_type, name="free")
        free_func.attributes.add("noinline")
        return free_func

    def _get_write_function(self):
        if "write" in self.module.globals:
            fn = self.module.globals["write"]
            if not isinstance(fn, ir.Function):
                raise TypeError("write global is not a function")
            return fn

        size_type = ir.IntType(self._get_pointer_width_bits())
        write_type = ir.FunctionType(
            size_type,
            [ir.IntType(32), ir.IntType(8).as_pointer(), size_type],
        )
        write_func = ir.Function(self.module, write_type, name="write")
        write_func.attributes.add("noinline")
        return write_func

    def _get_str_concat_function(self) -> ir.Function:
        if "encore_str_concat" in self.module.globals:
            fn = self.module.globals["encore_str_concat"]
            if not isinstance(fn, ir.Function):
                raise TypeError("encore_str_concat global is not a function")
            return fn

        str_type = self._get_str_type()
        fn_type = ir.FunctionType(str_type, [str_type, str_type])
        fn = ir.Function(self.module, fn_type, name="encore_str_concat")
        fn.attributes.add("noinline")
        return fn

    def _emit_builtin_native_helpers(self) -> None:
        self._emit_dyn_memory_helpers()

    def _emit_dyn_memory_helpers(self) -> None:
        for fn in list(self.module.functions):
            canonical = self._canonical_by_symbol.get(fn.name, fn.name)
            if canonical.startswith("__retain_dyn_"):
                self._emit_dyn_memory_helper(fn, slot_index=0)
            elif canonical.startswith("__drop_dyn_"):
                self._emit_dyn_memory_helper(fn, slot_index=1)

    def _emit_dyn_memory_helper(self, fn: ir.Function, *, slot_index: int) -> None:
        if len(fn.blocks) > 0:
            return
        if len(fn.function_type.args) != 1:
            raise TypeError(f"{fn.name} has incompatible dyn memory helper signature")

        block = fn.append_basic_block("entry")
        builder = ir.IRBuilder(block)
        dyn_value = fn.args[0]
        data_ptr = builder.extract_value(dyn_value, 0, name="data")
        vtable_ptr = builder.extract_value(dyn_value, 1, name="vtable")

        i8ptr = ir.IntType(8).as_pointer()
        slot_ptr_type = ir.PointerType(i8ptr)
        slots = builder.bitcast(vtable_ptr, slot_ptr_type, name="slots")
        slot_ptr = builder.gep(
            slots,
            [ir.Constant(ir.IntType(self._get_pointer_width_bits()), slot_index)],
            name="slot.ptr",
        )
        fn_raw = builder.load(slot_ptr, name="slot")
        helper_type = ir.FunctionType(ir.VoidType(), [i8ptr])
        helper_ptr = builder.bitcast(fn_raw, ir.PointerType(helper_type), name="helper")
        builder.call(helper_ptr, [data_ptr])
        builder.ret_void()

    def _native_declaration(self, name: str) -> ir.Function | None:
        value = self.module.globals.get(name)
        if value is None:
            return None
        if not isinstance(value, ir.Function):
            raise TypeError(f"{name} global is not a function")
        if len(value.blocks) > 0:
            return None
        return value

    def _emit_builtin_str_concat(self) -> None:
        fn = self._native_declaration("encore_str_concat")
        if fn is None:
            return
        str_type = self._get_str_type()
        expected_type = ir.FunctionType(str_type, [str_type, str_type])
        if str(fn.function_type) != str(expected_type):
            raise TypeError(f"encore_str_concat has incompatible type: {fn.function_type}")

        fn.linkage = "internal"
        lhs, rhs = fn.args
        lhs.name = "lhs"
        rhs.name = "rhs"
        block = fn.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        lhs_ptr = builder.extract_value(lhs, 0, name="lhs_ptr")
        lhs_len = builder.extract_value(lhs, 1, name="lhs_len")
        rhs_ptr = builder.extract_value(rhs, 0, name="rhs_ptr")
        rhs_len = builder.extract_value(rhs, 1, name="rhs_len")
        total_len = builder.add(lhs_len, rhs_len, name="total_len")

        one_len = ir.Constant(total_len.type, 1)
        malloc_len = builder.add(total_len, one_len, name="malloc_len")
        malloc_size = self._coerce_int_width(builder, malloc_len, 64, "malloc_size")
        out_ptr = builder.call(self._get_malloc_function(), [malloc_size], name="out_ptr")
        memcpy = self._get_memcpy_function()
        copy_len_type = memcpy.function_type.args[2]
        lhs_copy_len = self._coerce_int_width(builder, lhs_len, copy_len_type.width, "lhs_copy_len")
        rhs_copy_len = self._coerce_int_width(builder, rhs_len, copy_len_type.width, "rhs_copy_len")
        offset = self._coerce_int_width(builder, lhs_len, self._get_pointer_width_bits(), "rhs_offset")
        rhs_dst = builder.gep(out_ptr, [offset], name="rhs_dst")

        builder.call(memcpy, [out_ptr, lhs_ptr, lhs_copy_len])
        builder.call(memcpy, [rhs_dst, rhs_ptr, rhs_copy_len])
        nul_ptr = builder.gep(
            out_ptr,
            [self._coerce_int_width(builder, total_len, self._get_pointer_width_bits(), "nul_offset")],
            name="nul_ptr",
        )
        builder.store(ir.Constant(ir.IntType(8), 0), nul_ptr)

        owner_size = ir.Constant(ir.IntType(64), max(8, self._get_pointer_width_bits() // 8))
        owner_raw = builder.call(self._get_malloc_function(), [owner_size], name="owner_raw")
        owner_usize_ptr = builder.bitcast(
            owner_raw, ir.PointerType(ir.IntType(self._get_pointer_width_bits())), name="owner_ref_ptr"
        )
        builder.store(ir.Constant(ir.IntType(self._get_pointer_width_bits()), 1), owner_usize_ptr)

        out = ir.Constant(str_type, ir.Undefined)
        out = builder.insert_value(out, out_ptr, 0, name="out_with_ptr")
        out = builder.insert_value(out, total_len, 1, name="out_with_len")
        out = builder.insert_value(out, owner_raw, 2, name="out")
        builder.ret(out)

    def _emit_builtin_io_write(self) -> None:
        fn = self._native_declaration("encore_io_write")
        if fn is None:
            return
        str_type = self._get_str_type()
        expected_type = ir.FunctionType(ir.IntType(32), [ir.IntType(32), str_type])
        if str(fn.function_type) != str(expected_type):
            raise TypeError(f"encore_io_write has incompatible type: {fn.function_type}")

        fn.linkage = "internal"
        fd, value = fn.args
        fd.name = "fd"
        value.name = "value"
        block = fn.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        ptr = builder.extract_value(value, 0, name="ptr")
        length = builder.extract_value(value, 1, name="len")
        write = self._get_write_function()
        write_len_type = write.function_type.args[2]
        write_len = self._coerce_int_width(builder, length, write_len_type.width, "write_len")
        written = builder.call(write, [fd, ptr, write_len], name="written")
        ret = self._coerce_int_width(builder, written, 32, "ret")
        builder.ret(ret)

    @staticmethod
    def _coerce_int_width(builder: ir.IRBuilder, value, width: int, name: str):
        if not isinstance(value.type, ir.IntType):
            raise TypeError(f"Expected integer value for {name}, got {value.type}")
        if value.type.width == width:
            return value
        target = ir.IntType(width)
        if value.type.width < width:
            return builder.zext(value, target, name=name)
        return builder.trunc(value, target, name=name)

    def _get_str_eq_function(self) -> ir.Function:
        if "encore_str_eq" in self.module.globals:
            fn = self.module.globals["encore_str_eq"]
            if not isinstance(fn, ir.Function):
                raise TypeError("encore_str_eq global is not a function")
            return fn

        str_type = self._get_str_type()
        fn_type = ir.FunctionType(ir.IntType(1), [str_type, str_type])
        fn = ir.Function(self.module, fn_type, name="encore_str_eq")
        fn.attributes.add("noinline")
        return fn

    def _get_trap_intrinsic(self) -> ir.Function:
        name = "llvm.trap"
        if name in self.module.globals:
            fn = self.module.globals[name]
            if not isinstance(fn, ir.Function):
                raise TypeError("llvm.trap global is not a function")
            return fn
        fn = ir.Function(self.module, ir.FunctionType(ir.VoidType(), []), name=name)
        return fn

    def _initialize_memory(self, ptr, elem_type, size):
        memset_func = self._get_memset_function()
        byte_ptr = self.builder.bitcast(ptr, ir.IntType(8).as_pointer())
        zero = ir.Constant(ir.IntType(8), 0)
        self.builder.call(memset_func, [byte_ptr, zero, size])

    def _get_memset_function(self):
        if "memset" in self.module.globals:
            return self.module.globals["memset"]

        memset_type = ir.FunctionType(
            ir.IntType(8).as_pointer(),
            [
                ir.IntType(8).as_pointer(),
                ir.IntType(32),
                ir.IntType(64),
            ],
        )

        memset_func = ir.Function(self.module, memset_type, name="memset")
        memset_func.attributes.add("noinline")
        return memset_func

    def _get_memcpy_function(self):
        if "memcpy" in self.module.globals:
            fn = self.module.globals["memcpy"]
            if not isinstance(fn, ir.Function):
                raise TypeError("memcpy global is not a function")
            return fn

        size_type = ir.IntType(self._get_pointer_width_bits())
        memcpy_type = ir.FunctionType(
            ir.IntType(8).as_pointer(),
            [
                ir.IntType(8).as_pointer(),
                ir.IntType(8).as_pointer(),
                size_type,
            ],
        )

        memcpy_func = ir.Function(self.module, memcpy_type, name="memcpy")
        memcpy_func.attributes.add("noinline")
        return memcpy_func
