from ehir.core.block import Block
from ehir.core.derectives import (
    Derective_cimp,
    Derective_enum,
    Derective_extern_fn,
    Derective_fn,
    Derective_imp,
    Derective_impl,
    Derective_struct,
    Derective_trait,
    Derective_typealias,
    TraitMethod,
)
from ehir.core.derectives.base import Derective
from ehir.core.enum import Enum, EnumVariant, TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import (
    Instruction_add,
    Instruction_and,
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
    Instruction_geq,
    Instruction_getfield,
    Instruction_getfieldptr,
    Instruction_getptr,
    Instruction_grt,
    Instruction_halloc,
    Instruction_hfree,
    Instruction_hrealloc,
    Instruction_ieq,
    Instruction_leq,
    Instruction_les,
    Instruction_load,
    Instruction_match,
    Instruction_mod,
    Instruction_mul,
    Instruction_neq,
    Instruction_or,
    Instruction_pcast,
    Instruction_put,
    Instruction_ret,
    Instruction_salloc,
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_sgetfield,
    Instruction_sgetfieldptr,
    Instruction_shl,
    Instruction_shr,
    Instruction_store,
    Instruction_sub,
    Instruction_switch,
    Instruction_wraph,
    Instruction_wraps,
    Instruction_xor,
    MatchCase,
)
from ehir.core.instructions.base import Instruction
from ehir.core.primitives import Char, Char_t, Float, Float_t, Isize, Isize_t, Str, Str_t, Usize, Usize_t
from ehir.core.primitives.base import Primitive, PrimitiveType
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type
from ehir.core.variable import Parameter, StructField, Variable
from ehir.frontend.builtin.parser.lexer import Lexer
from ehir.frontend.builtin.parser.tokens import Token, TokenType


class Parser:
    _ast: list[Derective]
    _valid_attrs = {"safe", "inline"}

    def __init__(self):
        self._lexer = Lexer()
        self._tokens = []
        self._ast = []
        self._consumed = 0

    def parse(self, source_code: str) -> list[Derective]:
        self._sc = source_code
        self._ast.clear()
        self._tokens = self._lexer.tokenize(source_code)
        self._consumed = 0

        while not self._is_at_end():
            attrs = self._parse_attrs()
            current_token = self._lookup_curr()
            is_public = False

            if current_token.type == TokenType.KW_PUB:
                self._safe_consume(TokenType.KW_PUB)
                is_public = True
                current_token = self._lookup_curr()

            if current_token.type == TokenType.KW_FN:
                derective = self._parse_fn()
            elif current_token.type == TokenType.KW_EXTERN:
                derective = self._parse_extern_fn()
            elif current_token.type == TokenType.KW_TRAIT:
                derective = self._parse_trait()
            elif current_token.type == TokenType.KW_IMPL:
                derective = self._parse_impl()
            elif current_token.type == TokenType.KW_IMP:
                derective = self._parse_imp()
            elif current_token.type == TokenType.KW_ENUM:
                derective = self._parse_enum()
            elif current_token.type == TokenType.KW_STRUCT:
                derective = self._parse_struct()
            elif current_token.type == TokenType.KW_TYPE:
                derective = self._parse_typealias()
            else:
                raise ValueError(f"Unexpected token {current_token}")

            self._mark_metadata(derective, is_public, attrs)
            self._ast.append(derective)

        return self._ast

    def parse_instruction_stream(self, source_code: str) -> list[Instruction]:
        self._tokens = self._lexer.tokenize(source_code)
        self._consumed = 0
        instructions: list[Instruction] = []
        while not self._is_at_end():
            instr = self._parse_instruction()
            if instr is None:
                current = self._lookup_curr()
                raise ValueError(f"Unexpected token {current}")
            instructions.append(instr)
        return instructions

    def _mark_metadata(self, derective: Derective, is_public: bool, attrs: tuple[str, ...]):
        target = self._metadata_target_name(derective)
        self._validate_attrs(attrs, target)
        if isinstance(derective, Derective_impl):
            setattr(derective, "attrs", attrs)
            return
        setattr(derective, "is_public", is_public)
        setattr(derective, "attrs", attrs)

    def _metadata_target_name(self, derective: Derective) -> str:
        if isinstance(derective, Derective_extern_fn):
            return "extern_fn"
        if isinstance(derective, Derective_fn):
            return "fn"
        if isinstance(derective, Derective_struct):
            return "struct"
        if isinstance(derective, Derective_enum):
            return "enum"
        if isinstance(derective, Derective_typealias):
            return "typealias"
        if isinstance(derective, Derective_trait):
            return "trait"
        if isinstance(derective, Derective_impl):
            return "impl"
        return "directive"

    def _validate_attrs(self, attrs: tuple[str, ...], target: str):
        for attr in attrs:
            if attr not in self._valid_attrs:
                raise ValueError(f"Unknown attribute '{attr}'")
            if attr == "safe" and target not in {"fn", "extern_fn", "struct"}:
                raise ValueError(f"Attribute 'safe' is not valid for {target}")
            if attr == "inline" and target not in {"fn", "extern_fn"}:
                raise ValueError(f"Attribute 'inline' is not valid for {target}")

    def _parse_typealias(self) -> Derective_typealias:
        self._safe_consume(TokenType.KW_TYPE)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.EQUAL)
        target = self._parse_type()
        if self._lookup_curr() == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.SEMICOLON)
        return Derective_typealias(name=name, target=target)

    def _parse_attrs(self) -> tuple[str, ...]:
        attrs: list[str] = []
        while self._lookup_curr().type == TokenType.HASH:
            self._safe_consume(TokenType.HASH)
            attr_kw = self._safe_consume(TokenType.IDENTIFIER).value
            if attr_kw != "attr":
                raise ValueError(f"Unknown attribute directive '#{attr_kw}'")

            self._safe_consume(TokenType.LEFT_PAREN)
            if self._lookup_curr() != TokenType.RIGHT_PAREN:
                attrs.append(self._safe_consume(TokenType.IDENTIFIER).value)
                while self._lookup_curr() == TokenType.COMMA:
                    self._safe_consume(TokenType.COMMA)
                    attrs.append(self._safe_consume(TokenType.IDENTIFIER).value)
            self._safe_consume(TokenType.RIGHT_PAREN)

        return tuple(dict.fromkeys(attrs))

    def _parse_imp(self) -> Derective_imp:
        self._safe_consume(TokenType.KW_IMP)
        parts = [self._parse_import_path_segment()]
        while self._lookup_curr() == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.OP_SCOPE)
            parts.append(self._parse_import_path_segment())

        if self._lookup_curr() == TokenType.SEMICOLON:
            self._safe_consume(TokenType.SEMICOLON)

        if len(parts) < 2:
            raise ValueError("Import must have module path and symbol: imp path::to::symbol")
        return Derective_imp(prefix=parts[:-1], symbol=parts[-1])

    def _parse_trait(self) -> Derective_trait:
        self._safe_consume(TokenType.KW_TRAIT)
        name = self._parse_name()
        generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []
        bounds = self._parse_bounds() if self._lookup_curr() == TokenType.KW_WHERE else {}

        methods: list[TraitMethod] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._lookup_curr() != TokenType.RIGHT_BRACE:
            method = self._parse_fn_decl(with_body=False)
            methods.append(
                TraitMethod(name=method.name, generics=method.generics, params=method.params, ret_type=method.ret_type)
            )
        self._safe_consume(TokenType.RIGHT_BRACE)

        return Derective_trait(name=name, generics=generics, bounds=bounds, methods=methods)

    def _parse_impl(self) -> Derective_impl:
        self._safe_consume(TokenType.KW_IMPL)
        generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []
        first_type = self._parse_type()
        if self._lookup_curr() == TokenType.KW_FOR:
            trait_name = first_type.name
            trait_args = first_type.generics
            self._safe_consume(TokenType.KW_FOR)
            for_type = self._parse_type()
        else:
            trait_name = None
            trait_args = []
            for_type = first_type
        bounds = self._parse_bounds() if self._lookup_curr() == TokenType.KW_WHERE else {}

        methods: list[Derective_fn] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._lookup_curr() != TokenType.RIGHT_BRACE:
            method_attrs = self._parse_attrs()
            is_public = False
            if self._lookup_curr() == TokenType.KW_PUB:
                self._safe_consume(TokenType.KW_PUB)
                is_public = True
            methods.append(self._parse_fn_decl(with_body=True, attrs=method_attrs, is_public=is_public))
        self._safe_consume(TokenType.RIGHT_BRACE)

        return Derective_impl(
            trait_name=trait_name,
            trait_args=trait_args,
            for_type=for_type,
            generics=generics,
            bounds=bounds,
            methods=methods,
        )

    def _parse_enum(self) -> Derective_enum:
        self._safe_consume(TokenType.KW_ENUM)
        name = self._safe_consume(TokenType.IDENTIFIER).value

        generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []

        variants = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._lookup_curr() != TokenType.RIGHT_BRACE:
            variant_name = self._safe_consume(TokenType.IDENTIFIER).value

            match self._lookup_curr():
                case TokenType.LEFT_BRACKET:
                    raise NotImplementedError
                case TokenType.LEFT_PAREN:
                    self._safe_consume(TokenType.LEFT_PAREN)
                    variant_fields_types = []
                    if self._lookup_curr() != TokenType.RIGHT_PAREN:
                        variant_fields_types.append(self._parse_type())
                    while self._lookup_curr() != TokenType.RIGHT_PAREN:
                        self._safe_consume(TokenType.COMMA)
                        variant_fields_types.append(self._parse_type())
                    self._safe_consume(TokenType.RIGHT_PAREN)
                    variants.append(TupleLikeVariant(name=variant_name, types=variant_fields_types))
                case _:
                    variants.append(UnitLikeVariant(name=variant_name))

        self._safe_consume(TokenType.RIGHT_BRACE)

        return Derective_enum(name=name, generics=generics, variants=variants)

    def _parse_struct(self) -> Derective_struct:
        self._safe_consume(TokenType.KW_STRUCT)
        name = self._safe_consume(TokenType.IDENTIFIER).value

        generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []

        params = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._lookup_curr() != TokenType.RIGHT_BRACE:
            params.append(self._parse_struct_field())
        self._safe_consume(TokenType.RIGHT_BRACE)

        return Derective_struct(name=name, generics=generics, params=params)

    def _parse_fn(self) -> Derective_fn:
        return self._parse_fn_decl(with_body=True)

    def _parse_extern_fn(self) -> Derective_fn:
        self._safe_consume(TokenType.EXTERN)
        return self._parse_fn_decl(with_body=False, is_extern=True)

    def _parse_fn_decl(
        self,
        with_body: bool,
        is_extern: bool = False,
        attrs: tuple[str, ...] = (),
        is_public: bool = False,
    ) -> Derective_fn | Derective_extern_fn:
        self._safe_consume(TokenType.KW_FN)
        name = self._parse_callable_name()
        generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []

        params = []
        self._safe_consume(TokenType.LEFT_PAREN)
        if self._lookup_curr() != TokenType.RIGHT_PAREN:
            params.append(self._parse_param())
            while self._lookup_curr() != TokenType.RIGHT_PAREN:
                self._safe_consume(TokenType.COMMA)
                params.append(self._parse_param())
        self._safe_consume(TokenType.RIGHT_PAREN)

        self._safe_consume(TokenType.ARROW)
        ret_type = self._parse_type()

        body = []
        if with_body:
            self._safe_consume(TokenType.LEFT_BRACE)
            while self._lookup_curr() != TokenType.RIGHT_BRACE:
                body.append(self._parse_block())
            self._safe_consume(TokenType.RIGHT_BRACE)
        if is_extern:
            if len(generics) > 0:
                raise ValueError(f"Extern function '{name}' cannot declare generics")
            return Derective_extern_fn(
                name=name,
                params=params,
                ret_type=ret_type,
                is_public=is_public,
                attrs=attrs,
            )

        return Derective_fn(
            name=name,
            generics=generics,
            params=params,
            ret_type=ret_type,
            body=body,
            is_public=is_public,
            attrs=attrs,
        )

    def _parse_block(self) -> Block:
        name = self._parse_block_label()
        self._safe_consume(TokenType.COLON)

        body: list[Instruction] = []

        while instr := self._parse_instruction():
            body.append(instr)

        return Block(name=name, body=body)

    def _parse_instruction(self) -> Instruction | None:
        curr_token = self._lookup_curr()
        match curr_token:
            case TokenType.KW_RET:
                return self._parse_ret()
            case TokenType.KW_BR:
                return self._parse_br()
            case TokenType.KW_CBR:
                return self._parse_cbr()
            case TokenType.KW_MATCH:
                return self._parse_match()
            case TokenType.KW_SWITCH:
                return self._parse_switch()
            case TokenType.KW_PUT:
                return self._parse_put()
            case TokenType.KW_STORE:
                return self._parse_store()
            case TokenType.KW_SETFIELD:
                return self._parse_setfield()
            case TokenType.KW_HFREE:
                return self._parse_hfree()

        next_token = self._lookup_next()
        if next_token == TokenType.COLON or next_token == TokenType.EQUAL:
            return self._parse_assignable()

    def _parse_hfree(self) -> Instruction_hfree:
        self._safe_consume(TokenType.KW_HFREE)
        var = self._parse_variable()
        return Instruction_hfree(var=var)

    def _parse_put(self) -> Instruction_put:
        self._safe_consume(TokenType.KW_PUT)
        prim = self._parse_primitive()
        self._safe_consume(TokenType.COMMA)
        var = self._parse_variable()
        return Instruction_put(var=var, primitive=prim)

    def _parse_store(self) -> Instruction_store:
        self._safe_consume(TokenType.KW_STORE)
        var_src = self._parse_variable()
        self._safe_consume(TokenType.COMMA)
        var_dst = self._parse_variable()
        return Instruction_store(var_src=var_src, var_dst=var_dst)

    def _parse_setfield(self) -> Instruction_setfield:
        self._safe_consume(TokenType.KW_SETFIELD)
        var = self._parse_variable()
        self._safe_consume(TokenType.GREATER)
        field, field_path = self._parse_field_path()
        self._safe_consume(TokenType.COMMA)
        value = self._parse_variable()
        return Instruction_setfield(var=var, field=field, field_path=field_path, value=value)

    def _parse_br(self) -> Instruction_br:
        self._safe_consume(TokenType.KW_BR)
        label = self._parse_block_label()
        return Instruction_br(label)

    def _parse_cbr(self) -> Instruction_cbr:
        self._safe_consume(TokenType.KW_CBR)
        cond = self._parse_variable()
        self._safe_consume(TokenType.COMMA)
        true_br = self._parse_block_label()
        self._safe_consume(TokenType.COMMA)
        else_br = self._parse_block_label()

        return Instruction_cbr(cond_var=cond, true_br_label=true_br, else_br_label=else_br)

    def _parse_switch(self) -> Instruction_switch:
        self._safe_consume(TokenType.KW_SWITCH)
        cond_var = self._parse_variable()
        self._safe_consume(TokenType.COMMA)
        default_label = self._parse_block_label()

        cases = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._lookup_curr() != TokenType.RIGHT_BRACE:
            val = self._parse_primitive()
            self._safe_consume(TokenType.BOLD_ARROW)
            label = self._parse_block_label()
            cases.append((val, label))
        self._safe_consume(TokenType.RIGHT_BRACE)
        return Instruction_switch(cond_var=cond_var, default_case=default_label, cases=cases)

    def _parse_match(self) -> Instruction_match:
        self._safe_consume(TokenType.MATCH)
        cond_var = self._parse_variable()
        self._safe_consume(TokenType.COMMA)
        default_label = self._parse_block_label()

        cases: list[MatchCase] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while not isinstance(self._lookup_curr(), TokenType.RIGHT_BRACE):
            variant = self._safe_consume(TokenType.IDENTIFIER).string
            payload_var = None
            if isinstance(self._lookup_curr(), TokenType.LEFT_PAREN):
                self._safe_consume(TokenType.LEFT_PAREN)
                payload_var = self._parse_variable()
                self._safe_consume(TokenType.RIGHT_PAREN)
            self._safe_consume(TokenType.BOLD_ARROW)
            label = self._parse_block_label()
            cases.append(MatchCase(variant=variant, label=label, payload_var=payload_var))
        self._safe_consume(TokenType.RIGHT_BRACE)
        return Instruction_match(cond_var=cond_var, default_case=default_label, cases=cases)

    def _parse_ret(self) -> Instruction_ret:
        self._safe_consume(TokenType.KW_RET)
        var = self._parse_variable()
        return Instruction_ret(var)

    def _parse_block_label(self) -> str:
        self._safe_consume(TokenType.DOLLAR)
        return self._safe_consume(TokenType.IDENTIFIER).value

    def _parse_assignable(self) -> Instruction:
        var = self._parse_variable()
        self._safe_consume(TokenType.EQUAL)

        curr_token = self._consume()
        match curr_token:
            case TokenType.KW_CAPPRIM:
                primitive = self._parse_primitive()
                return Instruction_capprim(var_out=var, primitive=primitive)

            case TokenType.KW_CAPENUM:
                enum = self._parse_enum_init()
                return Instruction_capenum(var_out=var, enum=enum)

            case TokenType.KW_CAPSTRUCT:
                struct = self._parse_struct_init()
                return Instruction_capstruct(var_out=var, struct=struct)

            case TokenType.KW_WRAPS:
                variable = self._parse_variable()
                return Instruction_wraps(var_out=var, variable=variable)

            case TokenType.KW_WRAPH:
                variable = self._parse_variable()
                return Instruction_wraph(var_out=var, variable=variable)

            case TokenType.KW_CALL | TokenType.KW_UNSAFE:
                is_unsafe = False
                if curr_token == TokenType.KW_UNSAFE:
                    self._consume()
                    is_unsafe = True

                fn_name = self._parse_callable_name()
                generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []

                args = []
                self._safe_consume(TokenType.LEFT_PAREN)
                if self._lookup_curr() != TokenType.RIGHT_PAREN:
                    args.append(self._parse_variable())
                    while self._lookup_curr() != TokenType.RIGHT_PAREN:
                        self._safe_consume(TokenType.COMMA)
                        args.append(self._parse_variable())
                self._safe_consume(TokenType.RIGHT_PAREN)
                return Instruction_call(var_out=var, fn_name=fn_name, generics=generics, args=args, is_unsafe=is_unsafe)

            case TokenType.KW_ADD:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_add(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_SUB:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_sub(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_MUL:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_mul(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_DIV:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_div(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_MOD:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_mod(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_SHL:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_shl(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_SHR:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_shr(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_LES:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_les(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_LEQ:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_leq(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_GRT:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_grt(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_GEQ:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_geq(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_IEQ:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_ieq(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_NEQ:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_neq(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_AND:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_and(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_OR:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_or(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_XOR:
                lhs = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                rhs = self._parse_variable()
                return Instruction_xor(var_out=var, lhs=lhs, rhs=rhs)

            case TokenType.KW_SALLOC:
                type = self._parse_type()
                return Instruction_salloc(var_out=var, type=type)

            case TokenType.KW_HALLOC:
                type = self._parse_type()
                return Instruction_halloc(var_out=var, type=type)

            case TokenType.KW_HREALLOC:
                var_src = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                count = self._parse_variable()
                return Instruction_hrealloc(var_out=var, var=var_src, count=count)

            case TokenType.KW_LOAD:
                var_src = self._parse_variable()
                return Instruction_load(var_out=var, var=var_src)

            case TokenType.KW_PCAST:
                var_src = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                type = self._parse_type()
                return Instruction_pcast(var_out=var, var=var_src, type=type)

            case TokenType.KW_GETPTR:
                var_src = self._parse_variable()
                return Instruction_getptr(var_out=var, var=var_src)

            case TokenType.KW_GETFIELD:
                src = self._parse_variable()
                self._safe_consume(TokenType.GREATER)
                field, field_path = self._parse_field_path()
                return Instruction_getfield(var_out=var, src=src, field=field, field_path=field_path)

            case TokenType.KW_GETFIELDPTR:
                src = self._parse_variable()
                self._safe_consume(TokenType.GREATER)
                field, field_path = self._parse_field_path()
                return Instruction_getfieldptr(var_out=var, src=src, field=field, field_path=field_path)

            case TokenType.KW_GEP:
                var_src = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                offset = self._parse_variable()
                return Instruction_gep(var_out=var, var=var_src, offset=offset)

            case TokenType.KW_SGETFIELD:
                var_src = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                field = self._parse_variable()
                return Instruction_sgetfield(var_out=var, src=var_src, field=field)

            case TokenType.KW_SGETFIELDPTR:
                var_src = self._parse_variable()
                self._safe_consume(TokenType.COMMA)
                field = self._parse_variable()
                return Instruction_sgetfieldptr(var_out=var, src=var_src, field=field)

            case _:
                raise ValueError(f"Unexpected token {curr_token}")

    def _parse_struct_init(self) -> Struct:
        struct_as_type = self._parse_type()
        result = Struct(name=struct_as_type.name, generics=struct_as_type.generics, fields=[])

        if self._lookup_curr() != TokenType.LEFT_PAREN:
            return result

        self._safe_consume(TokenType.LEFT_PAREN)
        fields = []
        if self._lookup_curr() != TokenType.RIGHT_PAREN:
            fields.append(self._parse_variable())
        while self._lookup_curr() != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            fields.append(self._parse_variable())
        self._safe_consume(TokenType.RIGHT_PAREN)

        result.fields = fields
        return result

    def _parse_enum_init(self) -> Enum:
        enum_as_type = self._parse_type()
        self._safe_consume(TokenType.OP_SCOPE)
        variant = self._parse_name()

        args = []
        if self._lookup_curr() == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            if self._lookup_curr() != TokenType.RIGHT_PAREN:
                args.append(self._parse_variable())
            while self._lookup_curr() != TokenType.RIGHT_PAREN:
                self._safe_consume(TokenType.COMMA)
                args.append(self._parse_variable())
            self._safe_consume(TokenType.RIGHT_PAREN)
        return Enum(name=enum_as_type.name, generics=enum_as_type.generics, variant=variant, args=args)

    def _parse_variable(self) -> Variable:
        name = self._parse_name()
        type = None
        if self._lookup_curr() == TokenType.COLON:
            self._safe_consume(TokenType.COLON)
            type = self._parse_type()
        return Variable(name, type)

    def _parse_field_path(self) -> tuple[Variable, list[Variable]]:
        head = self._parse_variable()
        tail: list[Variable] = []
        while self._lookup_curr() == TokenType.GREATER:
            self._safe_consume(TokenType.GREATER)
            tail.append(self._parse_variable())
        return head, tail

    def _parse_param(self) -> Parameter:
        var = self._parse_variable()
        if var.type is not None:
            return Parameter(var.name, var.type)
        else:
            raise ValueError(f"Parameter {var.name} must have a type")

    def _parse_struct_field(self) -> StructField:
        attrs = self._parse_attrs()
        self._validate_attrs(attrs, "struct_field")

        var = self._parse_variable()
        if var.type is None:
            raise ValueError(f"Struct field {var.name} must have a type")
        return StructField(var.name, var.type, attrs=attrs)

    def _parse_type(self) -> Type | PrimitiveType | Pointer | Reference:
        # Unit type syntax in staged EHIR: `()`
        if self._lookup_curr() == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            self._safe_consume(TokenType.RIGHT_PAREN)
            return Type("void")

        if self._lookup_curr() == TokenType.AMPERSAND:
            self._safe_consume(TokenType.AMPERSAND)
            inner = self._parse_type()
            return Reference(inner)

        name = self._safe_consume(TokenType.IDENTIFIER).value

        type = Type(name)
        if name == "usize":
            type = Usize_t()
        elif name == "isize":
            type = Isize_t()
        elif name == "char":
            type = Char_t()
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

        type.generics = self._parse_generics() if self._lookup_curr() == TokenType.LEFT_BRACKET else []
        if self._lookup_curr() == TokenType.STAR:
            self._safe_consume(TokenType.STAR)
            type = Pointer(type)

        return type

    def _parse_generics(self) -> list[Type]:
        generics = []

        self._safe_consume(TokenType.LEFT_BRACKET)
        generics.append(self._parse_type())
        while self._lookup_curr() != TokenType.RIGHT_BRACKET:
            self._safe_consume(TokenType.COMMA)
            generics.append(self._parse_type())
        self._safe_consume(TokenType.RIGHT_BRACKET)
        return generics

    def _parse_bounds(self) -> dict[str, list[str]]:
        bounds: dict[str, list[str]] = {}
        self._safe_consume(TokenType.KW_WHERE)
        while True:
            generic_name = self._parse_name()
            self._safe_consume(TokenType.COLON)
            traits = [self._parse_name()]
            while isinstance(self._lookup_curr(), TokenType.PLUS):
                self._safe_consume(TokenType.PLUS)
                traits.append(self._parse_name())
            bounds[generic_name] = traits
            if not isinstance(self._lookup_curr(), TokenType.COMMA):
                break
            self._safe_consume(TokenType.COMMA)
        return bounds

    def _parse_name(self) -> str:
        return self._consume().value

    def _parse_import_path_segment(self) -> str:
        if self._lookup_curr() == TokenType.STAR:
            return self._consume().value
        return self._parse_name()

    def _parse_callable_name(self) -> str:
        name = self._parse_name()
        name += self._parse_scoped_segment_generics()

        while self._lookup_curr() == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.OP_SCOPE)
            segment = self._parse_name()
            segment += self._parse_scoped_segment_generics()
            name = f"{name}::{segment}"

        return name

    def _parse_scoped_segment_generics(self) -> str:
        if self._lookup_curr() != TokenType.LEFT_BRACKET:
            return ""

        saved = self._consumed
        generics = self._parse_generics()
        if self._lookup_curr() == TokenType.OP_SCOPE:
            joined = ", ".join(str(generic) for generic in generics)
            return f"[{joined}]"

        self._consumed = saved
        return ""

    def _parse_primitive(self) -> Primitive:
        sign = 1
        if self._lookup_curr() == TokenType.MINUS:
            self._safe_consume(TokenType.MINUS)
            sign = -1

        curr_token = self._consume()
        if curr_token == TokenType.STRING:
            if self._lookup_curr() == TokenType.IDENTIFIER and self._lookup_curr().value == "_str":
                self._consume()
            return Str(val=self._unescape_string_literal(curr_token.value[1:-1]))

        if curr_token == TokenType.CHAR:
            raw = self._unescape_string_literal(curr_token.value[1:-1])
            return Char(val=raw)

        if curr_token == TokenType.NUMBER:
            suffix = self._safe_consume(TokenType.IDENTIFIER).value
            if suffix == "_usize":
                return Usize(val=int(curr_token.value) * sign)
            if suffix.startswith("_u"):
                size = int(suffix[2:])
                return Usize(val=int(curr_token.value) * sign, size=size)
            if suffix == "_isize":
                return Isize(val=int(curr_token.value) * sign)
            if suffix.startswith("_i"):
                size = int(suffix[2:])
                return Isize(val=int(curr_token.value) * sign, size=size)
            if suffix.startswith("_f"):
                size = int(suffix[2:])
                return Float(val=float(f"{'-' if sign < 0 else ''}{curr_token.value}"), size=size)
            raise ValueError(f"Invalid primitive suffix: {suffix}")
        raise ValueError(f"Expected primitive literal, got {curr_token}")

    def _unescape_string_literal(self, string: str) -> str:
        return bytes(string, "utf-8").decode("unicode_escape")

    def _lookup_curr(self) -> Token:
        return self._eof() if self._is_at_end(0) else self._tokens[self._consumed + 0]

    def _lookup_next(self) -> Token:
        return self._eof() if self._is_at_end(1) else self._tokens[self._consumed + 1]

    def _safe_consume(self, expected: TokenType) -> Token:
        current_token = self._consume()
        if current_token.type != expected:
            self._trace_unexpected_token(current_token, expected)
        return current_token

    def _consume(self) -> Token:
        current_token = self._lookup_curr()
        self._consumed += 1
        return current_token

    def _is_at_end(self, n: int = 0) -> bool:
        return self._consumed + n >= len(self._tokens)

    def _eof(self) -> Token:
        return Token(TokenType.EOF, "", 0, 0)

    def _trace_unexpected_token(self, token: Token, expected_t: TokenType):
        raise ValueError(f"Unexpected token: {token}. Expected: {expected_t}")
