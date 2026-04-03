from ehir.core.block import Block
from ehir.core.derectives import (
    Derective_cimp,
    Derective_enum,
    Derective_fn,
    Derective_imp,
    Derective_impl,
    Derective_struct,
    Derective_trait,
    TraitMethod,
)
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, EnumVariant
from ehir.core.instructions.base import Instruction
from ehir.core.instructions.capture import (
    Instruction_ceoh,
    Instruction_ceos,
    Instruction_cpoh,
    Instruction_cpos,
    Instruction_csoh,
    Instruction_csos,
    Instruction_lceos,
    Instruction_lcpos,
    Instruction_lcsos,
    Instruction_scpoh,
    Instruction_scpos,
    Instruction_scsoh,
    Instruction_scsos,
)
from ehir.core.instructions.control_flow import (
    Instruction_br,
    Instruction_call,
    Instruction_cbr,
    Instruction_match,
    Instruction_ret,
    Instruction_switch,
    MatchCase,
)
from ehir.core.instructions.control_flow.phi import Instruction_phi, PhiPair
from ehir.core.instructions.memory import (
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_hfree,
    Instruction_pcast,
    Instruction_put,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_store,
)
from ehir.core.instructions.memory.halloc import Instruction_halloc
from ehir.core.instructions.memory.load import Instruction_load
from ehir.core.instructions.memory.salloc import Instruction_salloc
from ehir.core.instructions.operators.arithmetic import (
    Instruction_add,
    Instruction_div,
    Instruction_mod,
    Instruction_mul,
    Instruction_shl,
    Instruction_shr,
    Instruction_sub,
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
from ehir.core.primitives import Float, Float_t, Isize, Isize_t, Str, Str_t, Usize, Usize_t
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.struct import Struct
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type
from ehir.core.variable import Parameter, Variable
from ehir.frontend.builtin.parser import tokens as t
from ehir.frontend.builtin.parser.lexer import Lexer


class Parser:
    _ast: list[Derective]

    def __init__(self):
        self._lexer = Lexer()
        self._tokens = []
        self._ast = []
        self._consumed = 0

    def parse(self, source_code: str) -> list[Derective]:
        self._ast.clear()
        self._tokens = self._lexer.tokenize(source_code)
        self._consumed = 0
        # print(*self._tokens, sep="\n")
        while not self._is_at_end():
            current_token = self._lookup_curr()
            is_public = False

            if isinstance(current_token, t.PUB):
                self._safe_consume(t.PUB)
                is_public = True
                current_token = self._lookup_curr()

            if isinstance(current_token, t.FN):
                derective = self._parse_fn()
            elif isinstance(current_token, t.EXTERN):
                derective = self._parse_extern_fn()
            elif isinstance(current_token, t.TRAIT):
                derective = self._parse_trait()
            elif isinstance(current_token, t.IMPL):
                derective = self._parse_impl()
            elif isinstance(current_token, t.IMP):
                derective = self._parse_imp()
            elif isinstance(current_token, t.CIMP):
                derective = self._parse_cimp()
            elif isinstance(current_token, t.ENUM):
                derective = self._parse_enum()
            elif isinstance(current_token, t.STRUCT):
                derective = self._parse_struct()
            else:
                raise ValueError(f"Unexpected token {current_token}")

            self._mark_visibility(derective, is_public)
            self._ast.append(derective)

        return self._ast

    def _mark_visibility(self, derective: Derective, is_public: bool):
        if isinstance(derective, Derective_impl):
            setattr(derective, "is_public", True)
            return
        setattr(derective, "is_public", is_public)

    def _parse_cimp(self) -> Derective_cimp:
        self._safe_consume(t.CIMP)
        parts = [self._safe_consume(t.IDENTIFIER).string]
        while isinstance(self._lookup_curr(), t.DOUBLE_COLON):
            self._safe_consume(t.DOUBLE_COLON)
            parts.append(self._safe_consume(t.IDENTIFIER).string)

        if isinstance(self._lookup_curr(), t.SEMICOLON):
            self._safe_consume(t.SEMICOLON)

        if len(parts) < 2:
            raise ValueError("Import must have module path and symbol: imp path::to::symbol")
        return Derective_cimp(prefix=parts[:-1], symbol=parts[-1])

    def _parse_imp(self) -> Derective_imp:
        self._safe_consume(t.IMP)
        parts = [self._safe_consume(t.IDENTIFIER).string]
        while isinstance(self._lookup_curr(), t.DOUBLE_COLON):
            self._safe_consume(t.DOUBLE_COLON)
            parts.append(self._safe_consume(t.IDENTIFIER).string)

        if isinstance(self._lookup_curr(), t.SEMICOLON):
            self._safe_consume(t.SEMICOLON)

        if len(parts) < 2:
            raise ValueError("Import must have module path and symbol: imp path::to::symbol")
        return Derective_imp(prefix=parts[:-1], symbol=parts[-1])

    def _parse_trait(self) -> Derective_trait:
        self._safe_consume(t.TRAIT)
        name = self._parse_name()
        generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []
        bounds = self._parse_bounds() if isinstance(self._lookup_curr(), t.WHERE) else {}

        methods: list[TraitMethod] = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            method = self._parse_fn_decl(with_body=False)
            methods.append(
                TraitMethod(name=method.name, generics=method.generics, params=method.params, ret_type=method.ret_type)
            )
        self._safe_consume(t.RIGHT_BRACE)

        return Derective_trait(name=name, generics=generics, bounds=bounds, methods=methods)

    def _parse_impl(self) -> Derective_impl:
        self._safe_consume(t.IMPL)
        generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []
        trait_name = self._parse_name()
        trait_args = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []
        self._safe_consume(t.FOR)
        for_type = self._parse_type()
        bounds = self._parse_bounds() if isinstance(self._lookup_curr(), t.WHERE) else {}

        methods: list[Derective_fn] = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            methods.append(self._parse_fn_decl(with_body=True))
        self._safe_consume(t.RIGHT_BRACE)

        return Derective_impl(
            trait_name=trait_name,
            trait_args=trait_args,
            for_type=for_type,
            generics=generics,
            bounds=bounds,
            methods=methods,
        )

    def _parse_enum(self) -> Derective_enum:
        self._safe_consume(t.ENUM)
        name = self._safe_consume(t.IDENTIFIER).string

        generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []

        variants = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            variant_name = self._safe_consume(t.IDENTIFIER).string
            variant_type = None
            if isinstance(self._lookup_curr(), t.LEFT_PAREN):
                self._safe_consume(t.LEFT_PAREN)
                if not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
                    variant_type = self._parse_type()
                self._safe_consume(t.RIGHT_PAREN)
            variants.append(EnumVariant(name=variant_name, type=variant_type))
        self._safe_consume(t.RIGHT_BRACE)

        return Derective_enum(name=name, generics=generics, variants=variants)

    def _parse_struct(self) -> Derective_struct:
        self._safe_consume(t.STRUCT)
        name = self._safe_consume(t.IDENTIFIER).string

        generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []

        params = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            params.append(self._parse_param())
        self._safe_consume(t.RIGHT_BRACE)

        return Derective_struct(name=name, generics=generics, params=params)

    def _parse_fn(self) -> Derective_fn:
        return self._parse_fn_decl(with_body=True)

    def _parse_extern_fn(self) -> Derective_fn:
        self._safe_consume(t.EXTERN)
        return self._parse_fn_decl(with_body=False, is_extern=True)

    def _parse_fn_decl(self, with_body: bool, is_extern: bool = False) -> Derective_fn:
        self._safe_consume(t.FN)
        name = self._parse_name()
        generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []

        params = []
        self._safe_consume(t.LEFT_PAREN)
        if not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
            params.append(self._parse_param())
            while not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
                self._safe_consume(t.COMMA)
                params.append(self._parse_param())
        self._safe_consume(t.RIGHT_PAREN)

        self._safe_consume(t.ARROW)
        ret_type = self._parse_type()

        body = []
        if with_body:
            self._safe_consume(t.LEFT_BRACE)
            while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
                body.append(self._parse_block())
            self._safe_consume(t.RIGHT_BRACE)
        return Derective_fn(
            name=name,
            generics=generics,
            params=params,
            ret_type=ret_type,
            body=body,
            is_extern=is_extern,
        )

    def _parse_block(self) -> Block:
        name = self._parse_block_label()
        self._safe_consume(t.COLON)

        body: list[Instruction] = []

        while instr := self._parse_instruction():
            body.append(instr)

        return Block(name=name, body=body)

    def _parse_instruction(self) -> Instruction | None:
        curr_token = self._lookup_curr()
        if isinstance(curr_token, t.RET):
            return self._parse_ret()
        elif isinstance(curr_token, t.BR):
            return self._parse_br()
        elif isinstance(curr_token, t.CBR):
            return self._parse_cbr()
        elif isinstance(curr_token, t.MATCH):
            return self._parse_match()
        elif isinstance(curr_token, t.SWITCH):
            return self._parse_switch()
        elif isinstance(curr_token, t.PUT):
            return self._parse_put()
        elif isinstance(curr_token, t.STORE):
            return self._parse_store()
        elif isinstance(curr_token, t.HFREE):
            return self._parse_hfree()

        next_token = self._lookup_next()
        # Assign with typed / untyped variable
        if isinstance(next_token, (t.COLON, t.EQUAL)):
            return self._parse_assignable()

    def _parse_hfree(self) -> Instruction_hfree:
        self._safe_consume(t.HFREE)
        var = self._parse_variable()
        return Instruction_hfree(var=var)

    def _parse_put(self) -> Instruction_put:
        self._safe_consume(t.PUT)
        prim = self._parse_primitive()
        self._safe_consume(t.COMMA)
        var = self._parse_variable()
        return Instruction_put(var=var, primitive=prim)

    def _parse_store(self) -> Instruction_store:
        self._safe_consume(t.STORE)
        var_src = self._parse_variable()
        self._safe_consume(t.COMMA)
        var_dst = self._parse_variable()
        return Instruction_store(var_src=var_src, var_dst=var_dst)

    def _parse_br(self) -> Instruction_br:
        self._safe_consume(t.BR)
        label = self._parse_block_label()
        return Instruction_br(label)

    def _parse_cbr(self) -> Instruction_cbr:
        self._safe_consume(t.CBR)
        cond = self._parse_variable()
        self._safe_consume(t.COMMA)
        true_br = self._parse_block_label()
        self._safe_consume(t.COMMA)
        else_br = self._parse_block_label()

        return Instruction_cbr(cond_var=cond, true_br_label=true_br, else_br_label=else_br)

    def _parse_switch(self) -> Instruction_switch:
        self._safe_consume(t.SWITCH)
        cond_var = self._parse_variable()
        self._safe_consume(t.COMMA)
        default_label = self._parse_block_label()

        cases = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            val = self._parse_primitive()
            assert isinstance(val, Usize), "Switch case value must be a usize"
            self._safe_consume(t.BOLD_ARROW)
            label = self._parse_block_label()
            cases.append((val, label))
        self._safe_consume(t.RIGHT_BRACE)
        return Instruction_switch(cond_var=cond_var, default_case=default_label, cases=cases)

    def _parse_match(self) -> Instruction_match:
        self._safe_consume(t.MATCH)
        cond_var = self._parse_variable()
        self._safe_consume(t.COMMA)
        default_label = self._parse_block_label()

        cases: list[MatchCase] = []
        self._safe_consume(t.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACE):
            variant = self._safe_consume(t.IDENTIFIER).string
            payload_var = None
            if isinstance(self._lookup_curr(), t.LEFT_PAREN):
                self._safe_consume(t.LEFT_PAREN)
                payload_var = self._parse_variable()
                self._safe_consume(t.RIGHT_PAREN)
            self._safe_consume(t.BOLD_ARROW)
            label = self._parse_block_label()
            cases.append(MatchCase(variant=variant, label=label, payload_var=payload_var))
        self._safe_consume(t.RIGHT_BRACE)
        return Instruction_match(cond_var=cond_var, default_case=default_label, cases=cases)

    def _parse_ret(self) -> Instruction_ret:
        self._safe_consume(t.RET)
        var = self._parse_variable()
        return Instruction_ret(var)

    def _parse_block_label(self) -> str:
        self._safe_consume(t.DOLLAR)
        return self._safe_consume(t.IDENTIFIER).string

    def _parse_assignable(self) -> Instruction:
        var = self._parse_variable()
        self._safe_consume(t.EQUAL)

        curr_token = self._consume()
        if isinstance(curr_token, t.CPOS):
            primitive = self._parse_primitive()
            return Instruction_cpos(var_out=var, primitive=primitive)

        elif isinstance(curr_token, t.CEOH):
            enum = self._parse_enum_init()
            return Instruction_ceoh(var_out=var, enum=enum)

        elif isinstance(curr_token, t.CEOS):
            enum = self._parse_enum_init()
            return Instruction_ceos(var_out=var, enum=enum)

        elif isinstance(curr_token, t.CPOH):
            primitive = self._parse_primitive()
            return Instruction_cpoh(var_out=var, primitive=primitive)

        elif isinstance(curr_token, t.CSOS):
            struct = self._parse_struct_init()
            return Instruction_csos(var_out=var, struct=struct)

        elif isinstance(curr_token, t.CSOH):
            struct = self._parse_struct_init()
            return Instruction_csoh(var_out=var, struct=struct)

        elif isinstance(curr_token, t.SCPOS):
            primitive = self._parse_primitive()
            return Instruction_scpos(var_out=var, primitive=primitive)

        elif isinstance(curr_token, t.SCPOH):
            primitive = self._parse_primitive()
            return Instruction_scpoh(var_out=var, primitive=primitive)

        elif isinstance(curr_token, t.SCSOS):
            struct = self._parse_struct_init()
            return Instruction_scsos(var_out=var, struct=struct)

        elif isinstance(curr_token, t.SCSOH):
            struct = self._parse_struct_init()
            return Instruction_scsoh(var_out=var, struct=struct)

        elif isinstance(curr_token, t.LCPOS):
            primitive = self._parse_primitive()
            return Instruction_lcpos(var_out=var, primitive=primitive)

        elif isinstance(curr_token, t.LCEOS):
            enum = self._parse_enum_init()
            return Instruction_lceos(var_out=var, enum=enum)

        elif isinstance(curr_token, t.LCSOS):
            struct = self._parse_struct_init()
            return Instruction_lcsos(var_out=var, struct=struct)

        elif isinstance(curr_token, t.CALL) or isinstance(curr_token, t.UNSAFE):
            is_unsafe = False
            if isinstance(curr_token, t.UNSAFE):
                curr_token = self._consume()
                is_unsafe = True
            fn_name = self._parse_name()
            if isinstance(self._lookup_curr(), t.DOUBLE_COLON):
                self._safe_consume(t.DOUBLE_COLON)
                method = self._parse_name()
                fn_name = f"{fn_name}::{method}"
            generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []

            args = []
            self._safe_consume(t.LEFT_PAREN)
            if not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
                args.append(self._parse_variable())
                while not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
                    self._safe_consume(t.COMMA)
                    args.append(self._parse_variable())
            self._safe_consume(t.RIGHT_PAREN)
            return Instruction_call(var_out=var, fn_name=fn_name, generics=generics, args=args, is_unsafe=is_unsafe)

        elif isinstance(curr_token, t.ADD):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_add(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.SUB):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_sub(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.MUL):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_mul(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.DIV):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_div(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.MOD):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_mod(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.SHL):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_shl(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.SHR):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_shr(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.LES):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_les(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.LEQ):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_leq(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.GRT):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_grt(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.GEQ):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_geq(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.IEQ):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_ieq(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.NEQ):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_neq(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.AND):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_and(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.OR):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_or(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.XOR):
            lhs = self._parse_variable()
            self._safe_consume(t.COMMA)
            rhs = self._parse_variable()
            return Instruction_xor(var_out=var, lhs=lhs, rhs=rhs)

        elif isinstance(curr_token, t.PHI):
            return self._parse_phi(var)

        elif isinstance(curr_token, t.SALLOC):
            type = self._parse_type()
            return Instruction_salloc(var_out=var, type=type)

        elif isinstance(curr_token, t.HALLOC):
            type = self._parse_type()
            return Instruction_halloc(var_out=var, type=type)

        elif isinstance(curr_token, t.LOAD):
            var_src = self._parse_variable()
            return Instruction_load(var_out=var, var=var_src)

        elif isinstance(curr_token, t.PCAST):
            var_src = self._parse_variable()
            self._safe_consume(t.COMMA)
            type = self._parse_type()
            assert isinstance(type, PrimitiveType)
            return Instruction_pcast(var_out=var, var=var_src, type=type)

        elif isinstance(curr_token, t.GETPTR):
            var_src = self._parse_variable()
            return Instruction_getptr(var_out=var, var=var_src)

        elif isinstance(curr_token, t.GETFIELD):
            var_src = self._parse_variable()
            self._safe_consume(t.COMMA)
            field = self._parse_variable()
            return Instruction_getfield(var_out=var, src=var_src, field=field)

        elif isinstance(curr_token, t.GETFIELDPTR):
            var_src = self._parse_variable()
            self._safe_consume(t.COMMA)
            field = self._parse_variable()
            return Instruction_getfieldptr(var_out=var, src=var_src, field=field)

        elif isinstance(curr_token, t.SGETFIELD):
            var_src = self._parse_variable()
            self._safe_consume(t.COMMA)
            field = self._parse_variable()
            return Instruction_sgetfield(var_out=var, src=var_src, field=field)

        elif isinstance(curr_token, t.SGETFIELDPTR):
            var_src = self._parse_variable()
            self._safe_consume(t.COMMA)
            field = self._parse_variable()
            return Instruction_sgetfieldptr(var_out=var, src=var_src, field=field)

        else:
            raise ValueError(f"Unexpected token {curr_token}")

    def _parse_phi(self, var: Variable) -> Instruction_phi:
        args: list[PhiPair] = []

        def parse_phi_arg() -> PhiPair:
            var_src = self._parse_variable()
            label = self._parse_block_label()
            return PhiPair(var_src, label)

        args.append(parse_phi_arg())

        while isinstance(self._lookup_curr(), t.COMMA):
            self._safe_consume(t.COMMA)
            args.append(parse_phi_arg())

        return Instruction_phi(var_out=var, args=args)

    def _parse_struct_init(self) -> Struct:
        struct_as_type = self._parse_type()
        params = []
        self._safe_consume(t.LEFT_PAREN)
        if not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
            params.append(self._parse_variable())
            while not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
                self._safe_consume(t.COMMA)
                params.append(self._parse_variable())
        self._safe_consume(t.RIGHT_PAREN)
        return Struct(name=struct_as_type.name, generics=struct_as_type.generics, args=params)

    def _parse_enum_init(self) -> Enum:
        enum_as_type = self._parse_type()
        self._safe_consume(t.DOUBLE_COLON)
        variant = self._safe_consume(t.IDENTIFIER).string
        self._safe_consume(t.LEFT_PAREN)
        payload = None
        if not isinstance(self._lookup_curr(), t.RIGHT_PAREN):
            if isinstance(self._lookup_next(), (t.LEFT_PAREN, t.LEFT_BRACKET, t.LESS)):
                payload = self._parse_struct_init()
            else:
                payload_var = self._parse_variable()
                payload_type = payload_var.type
                payload = Struct(
                    name=payload_type.name if payload_type is not None else "_",
                    value=payload_var,
                    type=payload_type,
                )
        self._safe_consume(t.RIGHT_PAREN)
        return Enum(name=enum_as_type.name, generics=enum_as_type.generics, variant=variant, payload=payload)

    def _parse_variable(self) -> Variable:
        name = self._safe_consume(t.IDENTIFIER)
        type = None
        if isinstance(self._lookup_curr(), t.COLON):
            self._safe_consume(t.COLON)
            type = self._parse_type()
        return Variable(name.string, type)

    def _parse_param(self) -> Parameter:
        var = self._parse_variable()
        if var.type is not None:
            return Parameter(var.name, var.type)
        else:
            raise ValueError(f"Parameter {var.name} must have a type")

    def _parse_type(self) -> Type | PrimitiveType | Pointer:
        name = self._safe_consume(t.IDENTIFIER).string

        type = Type(name)
        if name == "usize":
            type = Usize_t()
        elif name == "isize":
            type = Isize_t()
        elif name == "str":
            type = Str_t()
        elif name.startswith("u") and name[1:].isdigit():
            size = int(name[1:])
            type = Usize_t(size=size)
        elif name.startswith("i") and name[1:].isdigit():
            size = int(name[1:])
            type = Isize_t(size=size)
        elif name.startswith("f") and name[1:].isdigit():
            size = int(name[1:])
            type = Float_t(size=size)

        type.generics = self._parse_generics() if isinstance(self._lookup_curr(), t.LEFT_BRACKET) else []
        if isinstance(self._lookup_curr(), t.STAR):
            self._safe_consume(t.STAR)
            type = Pointer(type)
        elif isinstance(self._lookup_curr(), t.LESS):
            # Smart pointer
            self._safe_consume(t.LESS)
            pointer_t = self._safe_consume(t.IDENTIFIER).string
            if pointer_t == "H":
                type = HeapSmartPointer(type)
            elif pointer_t == "S":
                type = StackSmartPointer(type)
            else:
                raise ValueError(f"Invalid smart pointer type: {pointer_t}")
            self._safe_consume(t.GREATER)

        return type

    def _parse_generics(self) -> list[Type]:
        generics = []

        self._safe_consume(t.LEFT_BRACKET)
        generics.append(self._parse_type())
        while not isinstance(self._lookup_curr(), t.RIGHT_BRACKET):
            self._safe_consume(t.COMMA)
            generics.append(self._parse_type())
        self._safe_consume(t.RIGHT_BRACKET)
        return generics

    def _parse_bounds(self) -> dict[str, list[str]]:
        bounds: dict[str, list[str]] = {}
        self._safe_consume(t.WHERE)
        while True:
            generic_name = self._parse_name()
            self._safe_consume(t.COLON)
            traits = [self._parse_name()]
            while isinstance(self._lookup_curr(), t.PLUS):
                self._safe_consume(t.PLUS)
                traits.append(self._parse_name())
            bounds[generic_name] = traits
            if not isinstance(self._lookup_curr(), t.COMMA):
                break
            self._safe_consume(t.COMMA)
        return bounds

    def _parse_name(self) -> str:
        token = self._consume()
        if isinstance(token, (t.IDENTIFIER, t.ADD, t.SUB, t.MUL, t.DIV, t.LES, t.LEQ, t.GRT, t.GEQ, t.IEQ, t.NEQ)):
            return token.string
        self._trace_unexpected_token(token, t.IDENTIFIER)
        raise AssertionError("Unreachable")

    def _parse_primitive(self) -> Primitive:
        sign = 1
        if isinstance(self._lookup_curr(), t.MINUS):
            self._safe_consume(t.MINUS)
            sign = -1

        curr_token = self._consume()
        if isinstance(curr_token, t.STRING):
            suffix = self._safe_consume(t.IDENTIFIER).string
            if suffix != "_str":
                raise ValueError(f"Invalid primitive suffix: {suffix}")
            return Str(val=self._unescape_string_literal(curr_token.string[1:-1]))

        if isinstance(curr_token, t.NUMBER):
            suffix = self._safe_consume(t.IDENTIFIER).string
            if suffix == "_usize":
                return Usize(val=int(curr_token.string) * sign)
            if suffix.startswith("_u"):
                size = int(suffix[2:])
                return Usize(val=int(curr_token.string) * sign, size=size)
            if suffix == "_isize":
                return Isize(val=int(curr_token.string) * sign)
            if suffix.startswith("_i"):
                size = int(suffix[2:])
                return Isize(val=int(curr_token.string) * sign, size=size)
            if suffix.startswith("_f"):
                size = int(suffix[2:])
                return Float(val=float(f"{'-' if sign < 0 else ''}{curr_token.string}"), size=size)
            raise ValueError(f"Invalid primitive suffix: {suffix}")
        raise ValueError(f"Expected primitive literal, got {curr_token}")

    def _unescape_string_literal(self, string: str) -> str:
        return bytes(string, "utf-8").decode("unicode_escape")

    def _lookup_curr(self) -> t.Token:
        return t.EOF("", 0, 0) if self._is_at_end(0) else self._tokens[self._consumed + 0]

    def _lookup_next(self) -> t.Token:
        return t.EOF("", 0, 0) if self._is_at_end(1) else self._tokens[self._consumed + 1]

    def _safe_consume(self, expected: type[t.Token]) -> t.Token:
        current_token = self._consume()
        if not isinstance(current_token, expected):
            self._trace_unexpected_token(current_token, expected)
        return current_token

    def _consume(self) -> t.Token:
        current_token = self._lookup_curr()
        self._consumed += 1
        return current_token

    def _is_at_end(self, n: int = 0) -> bool:
        return self._consumed + n >= len(self._tokens)

    def _trace_unexpected_token(self, token: t.Token, expected_t: type[t.Token]):
        raise ValueError(f"Unexpected token: {token}. Expected: {expected_t}")
