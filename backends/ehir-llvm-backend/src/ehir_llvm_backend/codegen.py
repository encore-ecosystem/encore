import ctypes
from collections.abc import Sequence

import llvmlite.binding as llvm
import llvmlite.ir as ir
from ehir.core.instructions.capture import Instruction_lcpos
from ehir.core.instructions.control_flow import (
    Instruction_br,
    Instruction_cbr,
    Instruction_phi,
)
from ehir.core.instructions.control_flow.phi import PhiPair
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_hfree,
    Instruction_pcast,
)
from ehir.core.instructions.memory.halloc import Instruction_halloc
from ehir.core.instructions.operators.arithmetic import (
    Instruction_div,
    Instruction_mod,
    Instruction_shl,
    Instruction_shr,
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
from ehir.core.instructions.special import Instruction_comment
from ehir.core.primitives import Float, Float_t, Isize, Isize_t, Str, Str_t, Usize, Usize_t
from ehir.core.primitives.base import Primitive
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type
from ehir.core.variable import TypedVariable
from ehir.postprocessor import ProcessedModule
from ehir.postprocessor.derectives import (
    ProcessedDerective,
    ProcessedDerective_extern_fn,
    ProcessedDerective_fn,
    ProcessedDerective_struct,
)
from ehir.postprocessor.instructions import (
    ProcessedInstruction,
    ProcessedInstruction_add,
    ProcessedInstruction_call,
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
        self.module = ir.Module()
        self.builder = ir.IRBuilder()
        self._variables: dict[str, object] = {}
        self._structs: dict[str, ir.BaseStructType] = {}
        self._blocks: dict[str, ir.Block] = {}
        self._pending_phi_incomings: list[tuple[ir.PhiInstr, Sequence[tuple[TypedVariable, str]]]] = []
        self._pointer_width_bits: int | None = None
        self._string_literal_counter = 0
        self._str_type: ir.IdentifiedStructType | None = None

    def run(self, mod: ProcessedModule) -> ir.Module:
        self._reset_state()

        for derective in mod.structs:
            self._codegen_struct_decl(derective)

        for derective in mod.structs:
            self._codegen_struct_body(derective)

        for derective in mod.funcs:
            self._codegen_fn_decl(derective)

        for derective in mod.funcs:
            if isinstance(derective, ProcessedDerective_fn):
                self._codegen_fn_body(derective)

        return self.module

    def _codegen_struct_decl(self, struct: ProcessedDerective_struct):
        if struct.name in self._structs:
            raise ValueError(f"Struct '{struct.name}' already declared")
        st = self.module.context.get_identified_type(struct.name)
        self._structs[struct.name] = st

    def _codegen_fn_decl(self, fn: ProcessedDerective_fn | ProcessedDerective_extern_fn):
        ret_type = self._build_type(fn.ret_type)
        param_types = [self._build_type(t.type) for t in fn.params]

        func_type = ir.FunctionType(ret_type, param_types)
        func = ir.Function(self.module, func_type, name=fn.name)

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
        field_types = [self._build_type(param.type) for param in struct.fields]
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
        func = [f for f in self.module.functions if f.name == fn.name][0]

        self._variables.clear()
        self._blocks.clear()
        self._pending_phi_incomings.clear()
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

        for block, ir_block in zip(fn.get_body(), ir_blocks, strict=True):
            assert block.name == ir_block.name
            self.builder.position_at_end(ir_block)
            self._build_block(block)

        self._resolve_pending_phi_incomings()

    def _build_block(self, block: ProcessedBlock):
        for instr in block.body:
            self._build_instruction(instr)
        self._build_instruction(block.term)

    def _build_instruction(self, instr: ProcessedInstruction):
        if isinstance(instr, ProcessedInstruction_salloc):
            self._build_salloc(instr)
        elif isinstance(instr, Instruction_lcpos):
            self._build_lcpos(instr)
        elif isinstance(instr, Instruction_halloc):
            self._build_halloc(instr)
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
        elif isinstance(instr, Instruction_div):
            self._build_div(instr)
        elif isinstance(instr, Instruction_or):
            self._build_or(instr)
        elif isinstance(instr, Instruction_and):
            self._build_and(instr)
        elif isinstance(instr, Instruction_xor):
            self._build_xor(instr)
        elif isinstance(instr, ProcessedInstruction_ieq):
            self._build_ieq(instr)
        elif isinstance(instr, ProcessedInstruction_neq):
            self._build_neq(instr)
        elif isinstance(instr, ProcessedInstruction_les):
            self._build_les(instr)
        elif isinstance(instr, Instruction_leq):
            self._build_leq(instr)
        elif isinstance(instr, ProcessedInstruction_grt):
            self._build_grt(instr)
        elif isinstance(instr, Instruction_geq):
            self._build_geq(instr)
        elif isinstance(instr, Instruction_mod):
            self._build_mod(instr)
        elif isinstance(instr, Instruction_shl):
            self._build_shl(instr)
        elif isinstance(instr, Instruction_shr):
            self._build_shr(instr)
        elif isinstance(instr, ProcessedInstruction_call):
            self._build_call(instr)
        elif isinstance(instr, ProcessedInstruction_ret):
            self._build_ret(instr)
        elif isinstance(instr, Instruction_br):
            self._build_br(instr)
        elif isinstance(instr, Instruction_cbr):
            self._build_cbr(instr)
        elif isinstance(instr, ProcessedInstruction_switch):
            self._build_switch(instr)
        elif isinstance(instr, Instruction_hfree):
            self._build_hfree(instr)
        elif isinstance(instr, ProcessedInstruction_store):
            self._build_store(instr)
        elif isinstance(instr, Instruction_pcast):
            self._build_pcast(instr)
        elif isinstance(instr, Instruction_getfieldptr):
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
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        assert instr.var.type is not None
        type = self._build_type(instr.var.type)
        ptr = self.builder.alloca(type, name=instr.var.name)
        self._variables[instr.var.name] = ptr

    def _build_getptr(self, instr: Instruction_getptr):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        assert instr.var.type is not None
        dst_type = self._build_type(instr.var.type)

        alloca = self.builder.alloca(dst_type, name=instr.var_out.name)
        self.builder.store(self._variables[instr.var.name], alloca)
        self._variables[instr.var_out.name] = alloca

    def _build_pcast(self, instr: Instruction_pcast):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        value = self._variables[instr.var.name]
        assert hasattr(value, "type")
        src_type = value.type

        assert instr.var.type is not None
        dst_type = self._build_type(instr.type)

        # Cast
        ## Same
        if src_type == dst_type:
            return

        result = None
        ## Int to Int
        if isinstance(src_type, ir.IntType) and isinstance(dst_type, ir.IntType):
            src_width = src_type.width
            dst_width = dst_type.width

            if src_width < dst_width:
                result = self.builder.zext(value, dst_type, name=instr.var_out.name)
            elif src_width > dst_width:
                result = self.builder.trunc(value, dst_type, name=instr.var_out.name)
            else:
                raise RuntimeError("Unreachable")

        else:
            raise NotImplementedError(f"Unsupported cast: {src_type} -> {dst_type}")

        self._variables[instr.var_out.name] = result
        return result

    def _build_store(self, instr: ProcessedInstruction_store):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        value = self._variables[instr.var_src.name]
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
            raise ValueError(f"Invalid store types: {value.type} -> {ptr.type} for {instr}")

        self.builder.store(value, ptr)

    def _build_getfieldptr(self, instr: Instruction_getfieldptr):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        base = self._variables[instr.src.name]
        assert hasattr(base, "type")
        expected_result_type = self._build_type(instr.var_out.type) if instr.var_out.type is not None else None
        if not isinstance(base.type, ir.PointerType):
            temp = self.builder.alloca(base.type)
            self.builder.store(base, temp)
            base = temp
        elif not isinstance(base.type.pointee, ir.BaseStructType):
            # Tolerate mismatched lowering paths where field access is emitted for a scalar pointer.
            self._variables[instr.var_out.name] = base
            return base

        field_index = int(instr.field.name)
        base = self._unwrap_smart_pointer_wrapper_for_gep(base, field_index, instr.var_out.name, expected_result_type)
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

    def _build_getfield(self, instr: Instruction_getfield):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        field_ptr_instr = Instruction_getfieldptr(var_out=instr.var_out, src=instr.src, field=instr.field)
        field_ptr = self._build_getfieldptr(field_ptr_instr)
        result = self.builder.load(field_ptr, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_salloc(self, instr: ProcessedInstruction_salloc):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        byte_size = self._sizeof(instr.type)
        ptr = self.builder.alloca(ir.IntType(8), size=byte_size, name=f".salloc_{instr.var_out.name}")
        target_type = self._build_type(instr.type)
        casted_ptr = self.builder.bitcast(ptr, ir.PointerType(target_type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = casted_ptr
        return casted_ptr

    def _build_halloc(self, instr: Instruction_halloc):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        byte_size = self._sizeof(instr.type)
        malloc_func = self._get_malloc_function()
        raw_ptr = self.builder.call(malloc_func, [byte_size], name=f".halloc_{instr.var_out.name}")
        target_type = self._build_type(instr.type)
        casted_ptr = self.builder.bitcast(raw_ptr, ir.PointerType(target_type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = casted_ptr
        return casted_ptr

    def _build_hfree(self, instr: Instruction_hfree):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        ptr = self._variables[instr.var.name]
        free_func = self._get_free_function()
        dst_type = free_func.args[0].type
        ptr_conv = self.builder.bitcast(typ=dst_type, val=ptr)

        self.builder.call(free_func, [ptr_conv])

    def _build_put(self, instr: ProcessedInstruction_put):
        self.builder.comment("")
        self.builder.comment(str(instr).replace("\n", "\\n"))
        constant = self._build_primitive(instr.primitive)
        self.builder.store(constant, self._variables[instr.var.name])

    def _build_lcpos(self, instr: Instruction_lcpos):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        constant = self._build_primitive(instr.primitive)
        self._variables[instr.var_out.name] = constant
        return constant

    def _build_load(self, instr: ProcessedInstruction_load):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        ptr = self._variables[instr.var.name]
        if not isinstance(ptr.type, ir.PointerType):
            # Some lowered match payload paths may already yield a concrete value.
            # Treat repeated `load` on that value as a move.
            self._variables[instr.var_out.name] = ptr
            return ptr
        value = self.builder.load(ptr, name=instr.var_out.name)
        self._variables[instr.var_out.name] = value
        return value

    def _build_add(self, instr: ProcessedInstruction_add):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.add(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_sub(self, instr: ProcessedInstruction_sub):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.sub(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_mul(self, instr: ProcessedInstruction_mul):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.mul(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_div(self, instr: Instruction_div):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.sdiv(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_mod(self, instr: Instruction_mod):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.srem(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_shl(self, instr: Instruction_shl):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.shl(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_shr(self, instr: Instruction_shr):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]

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

    def _build_or(self, instr: Instruction_or):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.or_(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_and(self, instr: Instruction_and):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.and_(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_xor(self, instr: Instruction_xor):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.xor(left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_ieq(self, instr: ProcessedInstruction_ieq):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed("==", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_neq(self, instr: ProcessedInstruction_neq):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed("!=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_les(self, instr: ProcessedInstruction_les):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed("<", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_leq(self, instr: Instruction_leq):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed("<=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_grt(self, instr: ProcessedInstruction_grt):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed(">", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_geq(self, instr: Instruction_geq):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        left = self._variables[instr.lhs.name]
        right = self._variables[instr.rhs.name]
        result = self.builder.icmp_signed(">=", left, right, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _build_call(self, instr: ProcessedInstruction_call):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        func = [f for f in self.module.functions if f.name == instr.fn_name][0]

        expected_types = list(func.function_type.args)
        if len(expected_types) != len(instr.args):
            raise ValueError(
                f"Call arg count mismatch for '{instr.fn_name}': {len(instr.args)} != {len(expected_types)}"
            )

        args = []
        for index, (expected_type, arg) in enumerate(zip(expected_types, instr.args, strict=True)):
            value = self._variables[arg.name]
            try:
                args.append(
                    self._coerce_call_arg(value=value, expected_type=expected_type, arg_name=f"{arg.name}_{index}")
                )
            except TypeError as exc:
                raise TypeError(f"Call '{instr.fn_name}' arg#{index} '{arg.name}' type mismatch: {exc}") from exc

        result = self.builder.call(func, args, name=instr.var_out.name)
        self._variables[instr.var_out.name] = result
        return result

    def _coerce_call_arg(self, value, expected_type: ir.Type, arg_name: str):
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
                return self.builder.zext(value, expected_type, name=f"{arg_name}.zext")
            if value.type.width > expected_type.width:
                return self.builder.trunc(value, expected_type, name=f"{arg_name}.trunc")
            return value

        if isinstance(value.type, ir.PointerType) and isinstance(expected_type, ir.PointerType):
            return self.builder.bitcast(value, expected_type, name=f"{arg_name}.bitcast")

        raise TypeError(
            "Type of arg mismatch: "
            f"{value.type} ({type(value.type).__name__}, name={getattr(value.type, 'name', None)}) != "
            f"{expected_type} ({type(expected_type).__name__}, name={getattr(expected_type, 'name', None)}), "
            f"value_fields={len(value.type.elements) if isinstance(value.type, ir.BaseStructType) else 'na'}, "
            f"expected_fields={len(expected_type.elements) if isinstance(expected_type, ir.BaseStructType) else 'na'}"
        )

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
        if isinstance(typ, (ir.HalfType, ir.FloatType, ir.DoubleType, ir.FP128Type)):
            return ir.Constant(typ, 0.0)
        return ir.Constant(typ, None)

    def _build_br(self, instr: Instruction_br):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        self.builder.branch(self._blocks[instr.label])

    def _build_cbr(self, instr: Instruction_cbr):
        self.builder.comment("")
        self.builder.comment(f"{instr}")
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
        self.builder.comment("")
        self.builder.comment(f"{instr}")
        value = self._variables[instr.var.name]
        self.builder.ret(value)

    def _build_phi(self, instr: ProcessedInstruction_phi):
        self.builder.comment("")
        self.builder.comment(f"{instr}")

        assert instr.var_out.type
        phi = self.builder.phi(typ=self._build_type(instr.var_out.type), name=instr.var_out.name)
        self._variables[instr.var_out.name] = phi
        self._pending_phi_incomings.append((phi, instr.args))
        return phi

    def _resolve_pending_phi_incomings(self):
        for phi, args in self._pending_phi_incomings:
            for arg in args:
                block = self._blocks[arg[1]]
                value = self._variables[arg[0].name]
                phi.add_incoming(value=value, block=block)

    def _build_type(self, type: Type) -> ir.Type:
        if isinstance(type, (HeapSmartPointer, StackSmartPointer)):
            wrapper_name = type.get_name()
            if wrapper_name not in self._structs:
                self._ensure_smart_pointer_wrapper(type)
            return self._structs[wrapper_name]

        if isinstance(type, Pointer):
            return ir.PointerType(self._build_type(type.pointee))

        if isinstance(type, Usize_t):
            return ir.IntType(bits=self._get_pointer_width_bits() if type.size is None else type.size)

        if isinstance(type, Isize_t):
            return ir.IntType(bits=self._get_pointer_width_bits() if type.size is None else type.size)

        if isinstance(type, Float_t):
            match type.size:
                case 16:
                    return ir.HalfType()
                case 32:
                    return ir.FloatType()
                case 64:
                    return ir.DoubleType()
                case 128:
                    return ir.FP128Type()
                case _:
                    raise ValueError(f"Unsupported float size: f{type.size}")

        if isinstance(type, Str_t) or type.name == "str":
            return self._get_str_type()

        if type.name not in self._structs:
            # Allow referencing external/opaque structs across refrain boundaries.
            self._structs[type.name] = self.module.context.get_identified_type(type.name)
        struct = self._structs[type.name]

        return struct

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
            bits = self._get_pointer_width_bits() if prim.type.size is None else prim.type.size
            return ir.Constant(ir.IntType(bits=bits), prim.val)
        if isinstance(prim, Isize):
            bits = self._get_pointer_width_bits() if prim.type.size is None else prim.type.size
            return ir.Constant(ir.IntType(bits=bits), prim.val)
        if isinstance(prim, Float):
            return ir.Constant(self._build_type(prim.type), prim.val)
        if isinstance(prim, Str):
            encoded = bytearray(prim.val.encode("utf-8"))
            encoded.append(0)
            array_type = ir.ArrayType(ir.IntType(8), len(encoded))
            literal_name = f".str.{self._string_literal_counter}"
            self._string_literal_counter += 1

            global_var = ir.GlobalVariable(self.module, array_type, name=literal_name)
            global_var.global_constant = True
            global_var.linkage = "internal"
            global_var.initializer = ir.Constant(array_type, encoded)

            zero = ir.Constant(ir.IntType(32), 0)
            ptr = global_var.gep((zero, zero))
            strlen = ir.Constant(ir.IntType(self._get_pointer_width_bits()), len(encoded) - 1)
            return ir.Constant(self._get_str_type(), [ptr, strlen])
        raise NotImplementedError(f"Unsupported primitive: {prim}")

    def _get_str_type(self) -> ir.IdentifiedStructType:
        if self._str_type is not None:
            return self._str_type

        str_type = self.module.context.get_identified_type("str")
        if str_type.is_opaque:
            str_type.set_body(ir.IntType(8).as_pointer(), ir.IntType(self._get_pointer_width_bits()))
        self._str_type = str_type
        return str_type

    def _get_pointer_width_bits(self) -> int:
        if self._pointer_width_bits is not None:
            return self._pointer_width_bits

        # This backend only targets the native machine, so host pointer width
        # is the correct machine-sized integer width for `usize` / `isize`.
        self._pointer_width_bits = ctypes.sizeof(ctypes.c_void_p) * 8
        return self._pointer_width_bits

    def _sizeof(self, type: Type):
        t = self._build_type(type)
        null_ptr_type = ir.PointerType(t)
        null_ptr = ir.Constant(null_ptr_type, None)
        one = ir.Constant(ir.IntType(32), 1)
        size_ptr = self.builder.gep(null_ptr, [one], name=f".sizeof_{type.name}_ptr")
        return self.builder.ptrtoint(size_ptr, ir.IntType(64), name=f".sizeof_{type.name}_")

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

    def _get_free_function(self):
        if "free" in self.module.globals:
            return self.module.globals["free"]

        free_type = ir.FunctionType(ir.VoidType(), [ir.IntType(8).as_pointer()])
        free_func = ir.Function(self.module, free_type, name="free")
        free_func.attributes.add("noinline")
        return free_func

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
