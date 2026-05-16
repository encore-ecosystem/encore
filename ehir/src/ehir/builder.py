from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ehir.core.block import Block
from ehir.core.derectives import (
    Derective_cimp,
    Derective_extern_fn,
    Derective_fn,
    Derective_imp,
    Derective_impl,
    Derective_struct,
    Derective_trait,
    TraitMethod,
)
from ehir.core.derectives.base import Derective
from ehir.core.instructions import (
    BinOp,
    Instruction_add,
    Instruction_and,
    Instruction_br,
    Instruction_call,
    Instruction_capprim,
    Instruction_capstruct,
    Instruction_cbr,
    Instruction_div,
    Instruction_geq,
    Instruction_grt,
    Instruction_ieq,
    Instruction_leq,
    Instruction_les,
    Instruction_match,
    Instruction_mod,
    Instruction_mul,
    Instruction_neq,
    Instruction_or,
    Instruction_ret,
    Instruction_salloc,
    Instruction_put,
    Instruction_scstruct,
    Instruction_sgetfield,
    Instruction_shl,
    Instruction_shr,
    Instruction_sub,
    Instruction_xor,
    MatchCase,
)
from ehir.core.instructions.base import Assignable, Instruction
from ehir.core.primitives import Usize_t
from ehir.core.primitives.base import Primitive
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Type
from ehir.core.variable import Parameter, TypedVariable, Variable


@dataclass
class EHIR_Module:
    id: Path
    ast: list[Derective]

    def __str__(self) -> str:
        return "\n\n".join(map(str, self.ast))


class EHIR_Builder:
    module: EHIR_Module
    current_function: Derective_fn
    current_block: Block
    shift: int
    variables: dict[str, Variable]

    def __init__(self, module: EHIR_Module):
        self.module = module
        self.shift = 0

    def build_imp(self, prefix: list[str], symbol: str, alias: str | None = None):
        self.module.ast.append(Derective_imp(prefix=prefix, symbol=symbol, alias=alias))

    def build_cimp(self, prefix: list[str], symbol: str, alias: str | None = None):
        self.module.ast.append(Derective_cimp(prefix=prefix, symbol=symbol, alias=alias))

    def build_struct(self, name: str, generics: list[Type], params: list[Parameter]):
        self.module.ast.append(
            Derective_struct(
                name=name,
                generics=generics,
                params=params,
            )
        )

    def build_trait(
        self,
        name: str,
        generics: list[Type],
        methods: list[TraitMethod],
        bounds: dict[str, list[str]] | None = None,
    ):
        trait = Derective_trait(name=name, generics=generics, bounds=bounds or {}, methods=methods)
        self.module.ast.append(trait)
        return trait

    def build_impl(
        self,
        trait_name: str,
        trait_args: list[Type],
        for_type: Type,
        generics: list[Type],
        methods: list[Derective_fn],
    ):
        impl = Derective_impl(
            trait_name=trait_name,
            trait_args=trait_args,
            for_type=for_type,
            generics=generics,
            methods=methods,
        )
        self.module.ast.append(impl)
        return impl

    def build_fn(self, name: str, generics: list[Type], params: list[Parameter], ret_type: Type):
        fn = Derective_fn(name=name, generics=generics, params=params, body=[], ret_type=ret_type)
        self.module.ast.append(fn)
        self.current_function = fn
        self.variables = {p.name: p for p in fn.params}

    def build_extern_fn(self, name: str, params: list[Parameter], ret_type: Type):
        extern_fn = Derective_extern_fn(name=name, params=params, ret_type=ret_type)
        self.module.ast.append(extern_fn)

    def build_binop(self, op: str, lhs: Variable, rhs: Variable, name: Optional[str] = None) -> BinOp:
        instr = None
        match op:
            case "add":
                instr = Instruction_add(self._reserve_variable(name), lhs, rhs)
            case "sub":
                instr = Instruction_sub(self._reserve_variable(name), lhs, rhs)
            case "mul":
                instr = Instruction_mul(self._reserve_variable(name), lhs, rhs)
            case "div":
                instr = Instruction_div(self._reserve_variable(name), lhs, rhs)
            case "mod":
                instr = Instruction_mod(self._reserve_variable(name), lhs, rhs)
            case "shl":
                instr = Instruction_shl(self._reserve_variable(name, lhs.type), lhs, rhs)
            case "shr":
                instr = Instruction_shr(self._reserve_variable(name, lhs.type), lhs, rhs)
            case "ieq":
                instr = Instruction_ieq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case "neq":
                instr = Instruction_neq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case "and":
                instr = Instruction_and(self._reserve_variable(name, lhs.type), lhs, rhs)
            case "or":
                instr = Instruction_or(self._reserve_variable(name, lhs.type), lhs, rhs)
            case "xor":
                instr = Instruction_xor(self._reserve_variable(name, lhs.type), lhs, rhs)
            case "les":
                instr = Instruction_les(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case "leq":
                instr = Instruction_leq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case "grt":
                instr = Instruction_grt(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case "geq":
                instr = Instruction_geq(self._reserve_variable(name, Usize_t(1)), lhs, rhs)
            case _:
                raise ValueError(f"Unknown operator: {op}")

        assert instr
        self._add(instr)
        return instr

    def build_sgetfield(self, src: Variable, field: Variable, name: Optional[str] = None) -> Instruction_sgetfield:
        instr = Instruction_sgetfield(self._reserve_variable(name), src, field)
        self._add(instr)
        return instr

    def build_capprim(self, prim: Primitive, name: Optional[str] = None) -> Instruction_capprim:
        capprim = Instruction_capprim(self._reserve_variable(name, prim.type), prim)
        self._add(capprim)
        return capprim

    def build_cpos(self, prim: Primitive, name: Optional[str] = None) -> Instruction_salloc:
        # Legacy API compatibility: lower old cpos into salloc + put.
        ptr = self._reserve_variable(name, Pointer(prim.type))
        salloc = Instruction_salloc(var_out=ptr, type=prim.type)
        self._add(salloc)
        self._add(Instruction_put(primitive=prim, var=ptr))
        return salloc

    def build_capstruct(
        self, struct_name: str, args: list[Variable], name: Optional[str] = None
    ) -> Instruction_capstruct:
        struct = Struct(name=struct_name, args=args)
        capstruct = Instruction_capstruct(var_out=self._reserve_variable(name, struct.as_type()), struct=struct)
        self._add(capstruct)
        return capstruct

    def build_scstruct(
        self, struct_name: str, args: list[Variable], name: Optional[str] = None
    ) -> Instruction_scstruct:
        struct = Struct(name=struct_name, args=args)
        scstruct = Instruction_scstruct(
            var_out=self._reserve_variable(name, Type("Box", [struct.as_type()])), struct=struct
        )
        self._add(scstruct)
        return scstruct

    def build_struct_method_call(
        self,
        struct: str,
        fn_name: str,
        generics: list[Type],
        args: list[Variable],
        name: Optional[str] = None,
        is_unsafe: bool = False,
    ):
        call = Instruction_call(
            var_out=self._reserve_variable(name),
            fn_name=fn_name,
            generics=generics,
            args=args,
            is_unsafe=is_unsafe,
        )
        self._add(call)
        return call

    def build_call(
        self,
        fn_name: str,
        generics: list[Type],
        args: list[Variable],
        name: Optional[str] = None,
        is_unsafe: bool = False,
    ) -> Instruction_call:
        call = Instruction_call(
            var_out=self._reserve_variable(name),
            fn_name=fn_name,
            generics=generics,
            args=args,
            is_unsafe=is_unsafe,
        )
        self._add(call)
        return call

    def build_ret(self, var: Variable):
        self._add(Instruction_ret(var))

    def build_br(self, label: str):
        self._add(Instruction_br(label=label))

    def build_cbr(self, cond_var: Variable, true_label: str, else_label: str):
        self._add(Instruction_cbr(cond_var=cond_var, true_br_label=true_label, else_br_label=else_label))

    def build_match(self, cond_var: Variable, default_label: str, cases: list[MatchCase]):
        self._add(Instruction_match(cond_var=cond_var, default_case=default_label, cases=cases))

    def get_var(self, name: Optional[str] = None) -> Assignable:
        if name is None:
            raise ValueError
        if var := self.variables.get(name, None):
            return Assignable(var)
        raise ValueError

    def append_block(self, name: str) -> Block:
        block = Block(name, [])
        self.current_function.body.append(block)
        return block

    def position_at_end(self, block: Block):
        self.current_block = block

    def _add(self, instruction: Instruction):
        self.current_block.body.append(instruction)

    def _process_name(self, name: Optional[str]) -> str:
        if name is None:
            name = f"_{self.shift}"
            self.shift += 1
        return name

    def _reserve_variable(self, name: Optional[str] = None, type: Optional[Type] = None) -> Variable:
        name = self._process_name(name)
        var = TypedVariable(name, type) if type else Variable(name)
        self.variables[name] = var
        return var
