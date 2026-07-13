from dataclasses import replace
from pathlib import Path
from typing import Optional

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
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_setfield,
    Instruction_shl,
    Instruction_shr,
    Instruction_sub,
    Instruction_switch,
    Instruction_xor,
)
from ehir.core.instructions.base import Instruction
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type
from ehir.core.variable import Parameter
from ehir.parser import Parser

from encore.compiler.base import ParserBase
from encore.compiler.lexer import LexerToken
from encore.compiler.lexer.tokens import TokenType
from encore.compiler.parser import statements as s
from encore.compiler.types import AnySmartPointer, is_mutable_type, make_array_type, make_mutable_type, make_tuple_type
from encore.utils.diagnostics import CompileDiagnostic

TRACE_MAX_LINES_FOR_UNIT = 5
SAFE_EHIR_INSTRUCTION_TYPES = (
    Instruction_capprim,
    Instruction_capenum,
    Instruction_capstruct,
    Instruction_cpos,
    Instruction_cenum,
    Instruction_cstruct,
    Instruction_scpos,
    Instruction_scstruct,
    Instruction_add,
    Instruction_sub,
    Instruction_mul,
    Instruction_div,
    Instruction_mod,
    Instruction_shl,
    Instruction_shr,
    Instruction_les,
    Instruction_leq,
    Instruction_grt,
    Instruction_geq,
    Instruction_ieq,
    Instruction_neq,
    Instruction_and,
    Instruction_or,
    Instruction_xor,
    Instruction_setfield,
)
ALLOWED_SAFE_EHIR_INSTRUCTION_TYPES = SAFE_EHIR_INSTRUCTION_TYPES + (Instruction_call,)
FORBIDDEN_EHIR_INSTRUCTION_TYPES = (
    Instruction_ret,
    Instruction_br,
    Instruction_cbr,
    Instruction_match,
    Instruction_switch,
)


class EncoreParser(ParserBase[LexerToken, s.Statement]):
    _module_id: Path | None = None
    _source_text: str = ""

    def parse(
        self,
        source: list[LexerToken],
        *,
        module_id: Path | None = None,
        source_text: str | None = None,
    ) -> list[s.Statement]:
        self._module_id = module_id
        self._source_text = source_text or ""
        self._ehir_parser = Parser()
        return super().parse(source)

    def _parse(self) -> list[s.Statement]:
        self._parsing_match_header = False
        self._parsing_control_flow_header = False
        self._parsing_with_binding_expr = False
        while not self._is_at_end():
            self._parse_top_level()
        return self._result

    def _get_eof_token(self) -> LexerToken:
        return LexerToken(type=TokenType.EOF, value="", line=0, column=0)

    def _source_line_at(self, line: int) -> str | None:
        if not self._source_text:
            return None
        rows = self._source_text.splitlines()
        if 0 <= line < len(rows):
            return rows[line]
        return None

    def _attach_span(self, node: object, token: LexerToken):
        if getattr(node, "line", None) is None:
            node.line = token.line
        if getattr(node, "column", None) is None:
            node.column = token.column
        if getattr(node, "span_length", None) is None:
            node.span_length = max(len(token.value), 1)
        if getattr(node, "source_line", None) is None:
            node.source_line = self._source_line_at(token.line)
        if getattr(node, "module_id", None) is None:
            node.module_id = self._module_id
        return node

    def _parse_top_level(self):
        attrs, cfgs = self._parse_metadata_directives()
        curr_token = self._peek_curr()
        result_start = len(self._result)

        if curr_token.type == TokenType.KW_IMPL:
            if attrs:
                raise TypeError("Function attributes are only allowed on fn/extern fn")
            impl = self._parse_impl()
            self._attach_span(impl, curr_token)
            self._push(impl)
            return

        is_public = False
        if curr_token.type == TokenType.KW_PUB:
            self._safe_consume(TokenType.KW_PUB)
            is_public = True
            curr_token = self._peek_curr()

        if attrs and curr_token.type not in (TokenType.KW_FN, TokenType.KW_EXTERN):
            raise TypeError("Function attributes are only allowed on fn/extern fn")

        match curr_token.type:
            case TokenType.KW_IMPORT:
                self._parse_import(is_public)
            case TokenType.KW_ENUM:
                self._parse_enum(is_public)
            case TokenType.KW_TRAIT:
                self._parse_trait(is_public)
            case TokenType.KW_STRUCT:
                self._push(self._parse_struct(is_public))
            case TokenType.KW_LET:
                self._push(self._parse_global_let(is_public))
            case TokenType.KW_FN:
                self._parse_fn(is_public, attrs)
            case TokenType.KW_EXTERN:
                self._parse_extern(is_public, attrs)
            case _:
                raise NotImplementedError(f"{curr_token}")

        for statement in self._result[result_start:]:
            self._attach_span(statement, curr_token)

    def _parse_global_let(self, is_public: bool) -> s.Statement_Global:
        let_stmt = self._parse_let()
        if let_stmt.is_mut:
            raise TypeError("Global 'let' can not be mutable")
        return s.Statement_Global(
            is_public=is_public,
            name=let_stmt.name,
            type=let_stmt.type,
            expr=let_stmt.expr,
        )

    def _parse_import(self, is_pub: bool):
        self._safe_consume(TokenType.KW_IMPORT)
        imp = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE)
        self._push(s.Statement_Import(is_public=is_pub, pair=imp))

    def _parse_enum(self, is_public: bool):
        self._safe_consume(TokenType.KW_ENUM)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generic_params()

        body = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            body.append(self._parse_struct_signature())
            if self._peek_curr().type == TokenType.COMMA:
                self._safe_consume(TokenType.COMMA)
                if self._peek_curr().type == TokenType.RIGHT_BRACE:
                    break
        self._safe_consume(TokenType.RIGHT_BRACE)

        self._push(
            s.Statement_EnumDefinition(
                is_public=is_public,
                name=name,
                generics=generics,
                body=body,
            )
        )

    def _parse_trait(self, is_public: bool):
        self._safe_consume(TokenType.KW_TRAIT)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generic_params()
        bases = self._parse_trait_bases()

        body: list[s.FunctionSignature] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            attrs, cfgs = self._parse_metadata_directives()
            method = self._parse_function_signature(attrs=attrs)
            body.append(method)
        self._safe_consume(TokenType.RIGHT_BRACE)
        self._push(s.Statement_Trait(is_public=is_public, name=name, generics=generics, body=body, bases=bases))

    def _parse_impl(self):
        self._safe_consume(TokenType.KW_IMPL)
        generics = self._parse_generic_params()

        trait_name = None
        trait_args: list[Type] = []
        if self._peek_curr().type != TokenType.KW_FOR:
            trait_name = self._safe_consume(TokenType.IDENTIFIER).value
            trait_args = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
        self._safe_consume(TokenType.KW_FOR)
        struct = self._parse_type()

        body: list[s.Statement_FunctionDefinition] = []
        if self._peek_curr().type == TokenType.LEFT_BRACE:
            self._safe_consume(TokenType.LEFT_BRACE)
            while self._peek_curr().type != TokenType.RIGHT_BRACE:
                attrs, cfgs = self._parse_metadata_directives()
                is_public = False
                if self._peek_curr().type == TokenType.KW_PUB:
                    self._safe_consume(TokenType.KW_PUB)
                    is_public = True

                sign = self._parse_function_signature(is_public, attrs=attrs)
                fn_body = self._parse_block()
                body.append(
                    s.Statement_FunctionDefinition(
                        is_public=is_public,
                        signature=sign,
                        body=fn_body,
                    )
                )
            self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Statement_Impl(
            is_public=False,
            generics=generics,
            trait_name=trait_name,
            trait_args=trait_args,
            struct=struct,
            body=body,
        )

    def _parse_struct(self, is_public: bool) -> s.Statement_StructureDefinition:
        self._safe_consume(TokenType.KW_STRUCT)
        signature = self._parse_struct_signature()
        return s.Statement_StructureDefinition(is_public=is_public, signature=signature)

    def _parse_fn(self, is_public: bool, attrs: list[str]):
        sign = self._parse_function_signature(is_public, attrs=attrs)
        body = self._parse_block()
        self._push(
            s.Statement_FunctionDefinition(
                is_public=is_public,
                signature=sign,
                body=body,
            )
        )

    def _parse_extern(self, is_public: bool, attrs: list[str]):
        self._push(self._parse_function_signature(is_public, attrs=attrs))

    def _parse_import_path(self, default_leaf_kind: s.Statement_Import.ImportKind) -> s.Statement_Import.ImportPair:
        module = self._safe_consume(TokenType.IDENTIFIER).value

        if self._is_at_end() or self._peek_curr().type != TokenType.SCOPE:
            return s.Statement_Import.ImportPair(
                module, [], default_leaf_kind, alias=self._parse_possible_import_alias()
            )

        self._safe_consume(TokenType.SCOPE)
        if self._is_at_end():
            raise ValueError("Import path cannot end with ::")

        curr_token = self._peek_curr()
        match curr_token.type:
            case TokenType.ASTERISK:
                self._consume()
                if not self._is_at_end() and self._peek_curr().type == TokenType.SCOPE:
                    raise TypeError("Wildcard '*' must be terminal in import path")
                pair = s.Statement_Import.ImportPair(
                    module,
                    [s.Statement_Import.ImportPair("*", [], s.Statement_Import.ImportKind.GLOB)],
                )
                pair.alias = self._parse_possible_import_alias()
                if pair.alias is not None:
                    raise TypeError("Wildcard import cannot have alias")
                return pair
            case TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)
                mods: list[s.Statement_Import.ImportPair] = []
                if self._peek_curr().type != TokenType.RIGHT_BRACE:
                    mods.append(self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE))
                    while self._peek_curr().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._peek_curr().type == TokenType.RIGHT_BRACE:
                            break
                        mods.append(self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE))
                self._safe_consume(TokenType.RIGHT_BRACE)
                return s.Statement_Import.ImportPair(module, mods, alias=self._parse_possible_import_alias())
            case TokenType.IDENTIFIER:
                nested = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.SYMBOL)
                return s.Statement_Import.ImportPair(module, [nested], alias=self._parse_possible_import_alias())
            case _:
                raise ValueError(f"Unexpected Token: {curr_token}")

    def _parse_possible_import_alias(self) -> str | None:
        if self._peek_curr().type != TokenType.KW_AS:
            return None
        self._safe_consume(TokenType.KW_AS)
        return self._safe_consume(TokenType.IDENTIFIER).value

    def _parse_struct_signature(self) -> s.StructureSignature:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generic_params()
        match self._peek_curr().type:
            case TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)
                fields: list[Parameter] = []
                while self._peek_curr().type != TokenType.RIGHT_BRACE:
                    fields.append(self._parse_param())
                    if self._peek_curr().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._peek_curr().type == TokenType.RIGHT_BRACE:
                            break
                self._safe_consume(TokenType.RIGHT_BRACE)
                return s.CLikeStructureDefinition(name=name, generics=generics, fields=fields)
            case TokenType.LEFT_PAREN:
                self._safe_consume(TokenType.LEFT_PAREN)
                fields: list[Type] = []
                while self._peek_curr().type != TokenType.RIGHT_PAREN:
                    fields.append(self._parse_type())
                    if self._peek_curr().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._peek_curr().type == TokenType.RIGHT_PAREN:
                            break
                self._safe_consume(TokenType.RIGHT_PAREN)
                return s.TupleStructureDefinition(name=name, generics=generics, fields=fields)
            case _:
                return s.UnitStructureDefinition(name=name, generics=generics)

    def _parse_function_signature(
        self, is_public: bool = False, *, attrs: list[str] | None = None
    ) -> s.FunctionSignature:
        attrs_list = list(attrs) if attrs is not None else []

        is_extern = False
        if self._peek_curr().type == TokenType.KW_EXTERN:
            self._safe_consume(TokenType.KW_EXTERN)
            is_extern = True

        self._safe_consume(TokenType.KW_FN)
        func_name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generic_params()

        params: list[Parameter] = []
        self._safe_consume(TokenType.LEFT_PAREN)
        if self._peek_curr().type != TokenType.RIGHT_PAREN:
            params.append(self._parse_param())

        while self._peek_curr().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            params.append(self._parse_param())
        self._safe_consume(TokenType.RIGHT_PAREN)

        fn_type = None
        if self._peek_curr().type == TokenType.ARROW:
            self._safe_consume(TokenType.ARROW)
            fn_type = self._parse_type()

        return s.FunctionSignature(
            is_public=is_public,
            attrs=attrs_list,
            is_extern=is_extern,
            name=func_name,
            generics=generics,
            params=params,
            type=fn_type,
        )

    def _parse_function_attrs(self) -> list[str]:
        attrs, cfgs = self._parse_metadata_directives()
        if cfgs:
            raise TypeError("#cfg(...) is only valid for declarations")
        return attrs

    def _parse_metadata_directives(self) -> tuple[list[str], list[str]]:
        attrs: list[str] = []
        cfgs: list[str] = []
        while self._peek_curr().type == TokenType.HASH:
            self._safe_consume(TokenType.HASH)
            directive = self._safe_consume(TokenType.IDENTIFIER).value
            if directive == "attr":
                attrs.extend(self._parse_attr_args())
                continue
            if directive == "cfg":
                cfgs.append(self._parse_cfg_args())
                continue
            raise TypeError(f"Unsupported attribute directive '#{directive}', expected '#attr(...)' or '#cfg(...)'")

        return attrs, cfgs

    def _parse_attr_args(self) -> list[str]:
        attrs: list[str] = []
        self._safe_consume(TokenType.LEFT_PAREN)
        attrs.append(self._safe_consume(TokenType.IDENTIFIER).value)
        while self._peek_curr().type == TokenType.COMMA:
            self._safe_consume(TokenType.COMMA)
            attrs.append(self._safe_consume(TokenType.IDENTIFIER).value)
        self._safe_consume(TokenType.RIGHT_PAREN)
        return attrs

    def _parse_cfg_args(self) -> str:
        self._safe_consume(TokenType.LEFT_PAREN)
        depth = 1
        parts: list[str] = []
        while depth > 0:
            if self._is_at_end():
                raise TypeError("Unclosed #cfg(...)")
            token = self._consume()
            if token.type == TokenType.LEFT_PAREN:
                depth += 1
            elif token.type == TokenType.RIGHT_PAREN:
                depth -= 1
                if depth == 0:
                    break
            parts.append(token.value)
        return "".join(parts)

    def _parse_block(self) -> s.Block:
        self._safe_consume(TokenType.LEFT_BRACE)
        statements: list[s.Statement_InnerLevel] = []
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            statements.append(self._parse_inner_level())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Block(statements)

    def _parse_inner_level(self) -> s.Statement_InnerLevel:
        curr_token = self._peek_curr()

        match curr_token.type:
            case TokenType.KW_RET:
                statement = self._parse_ret()
            case TokenType.KW_LET:
                statement = self._parse_let()
            case TokenType.KW_DO:
                statement = self._parse_do_while()
            case TokenType.KW_WITH:
                statement = self._parse_with()
            case TokenType.KW_FOR:
                statement = self._parse_for()
            case TokenType.KW_WHILE:
                statement = self._parse_while()
            case TokenType.KW_LOOP:
                statement = self._parse_loop()
            case TokenType.KW_IF:
                statement = self._parse_if_block()
            case TokenType.KW_MATCH:
                statement = self._parse_match()
            case TokenType.KW_UNSAFE:
                if self._peek_next().type == TokenType.KW_EHIR:
                    statement = self._parse_ehir_block(is_unsafe=True)
                else:
                    statement = self._parse_unsafe_block()
            case TokenType.KW_EHIR:
                statement = self._parse_ehir_block(is_unsafe=False)
            case TokenType.KW_BREAK:
                statement = self._parse_break()
            case TokenType.KW_CONTINUE:
                statement = self._parse_continue()
            case _:
                if not self._starts_statement_expression(curr_token.type):
                    raise NotImplementedError(curr_token)
                target = self._parse_expression()
                match self._peek_curr().type:
                    case (
                        TokenType.ASSIGN
                        | TokenType.PLUS_EQUAL
                        | TokenType.MINUS_EQUAL
                        | TokenType.ASTERISK_EQUAL
                        | TokenType.POWER_EQUAL
                        | TokenType.SLASH_EQUAL
                        | TokenType.PERCENT_EQUAL
                        | TokenType.AMPERSAND_EQUAL
                        | TokenType.PIPE_EQUAL
                        | TokenType.CARET_EQUAL
                        | TokenType.LEFT_SHIFT_EQUAL
                        | TokenType.RIGHT_SHIFT_EQUAL
                    ):
                        statement = self._parse_assignment(target)
                    case _:
                        statement = s.Statement_Expr(target)
        return self._attach_span(statement, curr_token)

    def _starts_statement_expression(self, token_type: TokenType) -> bool:
        return token_type in {
            TokenType.IDENTIFIER,
            TokenType.INTEGER,
            TokenType.FLOAT,
            TokenType.BOOLEAN,
            TokenType.STRING,
            TokenType.LEFT_PAREN,
            TokenType.LEFT_BRACKET,
            TokenType.LEFT_BRACE,
            TokenType.KW_MATCH,
            TokenType.KW_IF,
            TokenType.KW_UNSAFE,
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.BANG,
            TokenType.TILDE,
            TokenType.INCREMENT,
            TokenType.DECREMENT,
        }

    def _parse_ret(self) -> s.Statement_Ret:
        self._safe_consume(TokenType.KW_RET)
        expr = self._parse_expression()
        return s.Statement_Ret(expr=expr)

    def _parse_while(self) -> s.Statement_While:
        self._safe_consume(TokenType.KW_WHILE)
        label = self._parse_maybe_label()
        self._parsing_control_flow_header = True
        expr = self._parse_expression()
        self._parsing_control_flow_header = False
        body = self._parse_block()
        return s.Statement_While(label, expr, body)

    def _parse_loop(self) -> s.Statement_Loop:
        self._safe_consume(TokenType.KW_LOOP)
        label = self._parse_maybe_label()
        body = self._parse_block()
        return s.Statement_Loop(label, body)

    def _parse_break(self):
        self._safe_consume(TokenType.KW_BREAK)
        label = self._parse_maybe_label()
        return s.Statement_Break(label)

    def _parse_continue(self):
        self._safe_consume(TokenType.KW_CONTINUE)
        label = self._parse_maybe_label()
        return s.Statement_Continue(label)

    def _parse_do_while(self) -> s.Statement_DoWhile:
        self._safe_consume(TokenType.KW_DO)
        body = self._parse_block()
        self._safe_consume(TokenType.KW_WHILE)
        self._parsing_control_flow_header = True
        expr = self._parse_expression()
        self._parsing_control_flow_header = False
        return s.Statement_DoWhile(body, expr)

    def _parse_for(self) -> s.Statement_For:
        self._safe_consume(TokenType.KW_FOR)
        label = self._parse_maybe_label()
        item_name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.KW_IN)
        self._parsing_control_flow_header = True
        iterable_expr = self._parse_expression()
        self._parsing_control_flow_header = False
        body = self._parse_block()
        return s.Statement_For(label=label, name=item_name, iterable=iterable_expr, body=body)

    def _parse_with(self) -> s.Statement_With:
        self._safe_consume(TokenType.KW_WITH)
        self._parsing_with_binding_expr = True
        expr = self._parse_expression()
        self._parsing_with_binding_expr = False
        self._safe_consume(TokenType.KW_AS)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        body = self._parse_block()
        return s.Statement_With(expr=expr, name=name, body=body)

    def _parse_if_block(self):
        branches, else_body = self._parse_if_common(
            branch_factory=s.Statement_IfBranch,
            body_parser=self._parse_block,
            require_else=False,
        )
        return s.Statement_If(branches=branches, else_body=else_body)

    def _parse_if_expression(self) -> s.Expression_If:
        branches, else_body = self._parse_if_common(
            branch_factory=s.Expression_IfBranch,
            body_parser=self._parse_expression_block,
            require_else=True,
        )
        assert else_body is not None
        return s.Expression_If(branches=branches, else_body=else_body)

    def _parse_if_common(self, *, branch_factory, body_parser, require_else: bool):
        self._safe_consume(TokenType.KW_IF)
        self._parsing_control_flow_header = True
        first_expr = self._parse_expression()
        self._parsing_control_flow_header = False
        branches = [branch_factory(expr=first_expr, body=body_parser())]

        while not self._is_at_end() and self._peek_curr().type == TokenType.KW_ELIF:
            self._safe_consume(TokenType.KW_ELIF)
            self._parsing_control_flow_header = True
            branch_expr = self._parse_expression()
            self._parsing_control_flow_header = False
            branches.append(branch_factory(expr=branch_expr, body=body_parser()))

        else_body = None
        if not self._is_at_end() and self._peek_curr().type == TokenType.KW_ELSE:
            self._safe_consume(TokenType.KW_ELSE)
            else_body = body_parser()
        elif require_else:
            raise TypeError("If expression must have an else branch")

        return branches, else_body

    def _parse_unsafe_block(self) -> s.Statement_Unsafe:
        self._safe_consume(TokenType.KW_UNSAFE)
        body = self._parse_block()
        return s.Statement_Unsafe(body=body)

    def _parse_ehir_block(self, is_unsafe: bool) -> s.Statement_EHIR:
        if is_unsafe:
            self._safe_consume(TokenType.KW_UNSAFE)
        self._safe_consume(TokenType.KW_EHIR)
        self._safe_consume(TokenType.LEFT_BRACE)

        body_tokens: list[LexerToken] = []
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            body_tokens.append(self._consume())
        self._safe_consume(TokenType.RIGHT_BRACE)

        body_source = " ".join(token.value for token in body_tokens)
        instructions = self._ehir_parser.parse_instruction_stream(body_source) if body_source.strip() else []
        self._validate_ehir_instructions(instructions, is_unsafe=is_unsafe)
        return s.Statement_EHIR(instructions=instructions, is_unsafe=is_unsafe)

    def _validate_ehir_instructions(self, instructions: list[Instruction], *, is_unsafe: bool):
        for instruction in instructions:
            if isinstance(instruction, FORBIDDEN_EHIR_INSTRUCTION_TYPES):
                raise TypeError(f"EHIR block does not support control-flow instruction '{instruction}'")
            if not is_unsafe:
                if isinstance(instruction, Instruction_call) and instruction.is_unsafe:
                    raise TypeError("Unsafe EHIR call requires `unsafe ehir { ... }`")
                if not isinstance(instruction, ALLOWED_SAFE_EHIR_INSTRUCTION_TYPES):
                    raise TypeError(
                        f"Unsafe EHIR instruction '{type(instruction).__name__}' requires `unsafe ehir {{ ... }}`"
                    )

    def _parse_match(self) -> s.Statement_Match:
        expr, arms = self._parse_match_common(self._parse_statement_match_arm)
        return s.Statement_Match(expr=expr, arms=arms)

    def _parse_match_expression(self) -> s.Expression_Match:
        expr, arms = self._parse_match_common(self._parse_expression_match_arm)
        return s.Expression_Match(expr=expr, arms=arms)

    def _parse_match_common(self, arm_parser):
        self._safe_consume(TokenType.KW_MATCH)
        self._parsing_match_header = True
        expr = self._parse_expression()
        self._parsing_match_header = False
        self._safe_consume(TokenType.LEFT_BRACE)
        arms = []
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            arms.append(arm_parser())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return expr, arms

    def _parse_statement_match_arm(self) -> s.Statement_MatchArm:
        pattern, binding, body = self._parse_match_arm_common(self._parse_statement_match_body)
        return s.Statement_MatchArm(pattern=pattern, binding=binding, body=body)

    def _parse_expression_match_arm(self) -> s.Expression_MatchArm:
        pattern, binding, expr = self._parse_match_arm_common(self._parse_expression)
        return s.Expression_MatchArm(pattern=pattern, binding=binding, expr=expr)

    def _parse_match_arm_common(self, body_parser):
        pattern = self._parse_match_pattern()
        binding = None
        if self._peek_curr().type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            binding = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.RIGHT_PAREN)
        self._safe_consume(TokenType.FAT_ARROW)
        return pattern, binding, body_parser()

    def _parse_match_pattern(self):
        pattern = None
        curr_token = self._peek_curr()
        if curr_token.type == TokenType.IDENTIFIER and curr_token.value == "_":
            self._consume()
        elif curr_token.type == TokenType.MINUS:
            self._consume()
            if self._peek_curr().type == TokenType.INTEGER:
                pattern = self._parse_integer_literal()
                pattern.value = f"-{pattern.value}"
            elif self._peek_curr().type == TokenType.FLOAT:
                pattern = self._parse_float_literal()
                pattern.value = f"-{pattern.value}"
            else:
                raise TypeError("Match pattern '-' must be followed by numeric literal")
        elif curr_token.type == TokenType.STRING:
            pattern = self._parse_string_literal()
        elif curr_token.type == TokenType.INTEGER:
            pattern = self._parse_integer_literal()
        elif curr_token.type == TokenType.FLOAT:
            pattern = self._parse_float_literal()
        elif curr_token.type == TokenType.BOOLEAN:
            self._consume()
            pattern = self._attach_span(s.Expression_BooleanLiteral(curr_token.value == "true"), curr_token)
        else:
            pattern = self._parse_path()
        return pattern

    def _parse_statement_match_body(self):
        if self._peek_curr().type == TokenType.LEFT_BRACE:
            return self._parse_block()
        return self._parse_expression()

    def _parse_expression(self) -> s.Statement_Expression:
        return self._parse_range()

    def _parse_range(self) -> s.Statement_Expression:
        left = self._parse_logical_or()
        token = self._peek_curr()
        if token.type not in {TokenType.DOT_DOT, TokenType.DOT_DOT_EQUAL}:
            return left
        self._consume()
        right = self._parse_logical_or()
        return s.Expression_Range(start=left, end=right, inclusive=(token.type == TokenType.DOT_DOT_EQUAL))

    def _parse_logical_or(self) -> s.Statement_Expression:
        left = self._parse_logical_and()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.PIPE_PIPE}:
                break
            self._consume()
            right = self._parse_logical_and()
            left = s.BinaryOperation_LogicalOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_logical_and(self) -> s.Statement_Expression:
        left = self._parse_bitwise_or()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.AND_AND}:
                break
            self._consume()
            right = self._parse_bitwise_or()
            left = s.BinaryOperation_LogicalAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_or(self) -> s.Statement_Expression:
        left = self._parse_bitwise_xor()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.PIPE}:
                break
            self._consume()
            right = self._parse_bitwise_xor()
            left = s.BinaryOperation_BitwiseOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_xor(self) -> s.Statement_Expression:
        left = self._parse_bitwise_and()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.CARET}:
                break
            self._consume()
            right = self._parse_bitwise_and()
            left = s.BinaryOperation_BitwiseXor(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_and(self) -> s.Statement_Expression:
        left = self._parse_equality()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.AMPERSAND}:
                break
            self._consume()
            right = self._parse_equality()
            left = s.BinaryOperation_BitwiseAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_equality(self) -> s.Statement_Expression:
        left = self._parse_relational()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL}:
                break
            self._consume()
            right = self._parse_relational()
            left = s.BinaryOperation_Equality(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_relational(self) -> s.Statement_Expression:
        left = self._parse_shift()
        while True:
            operator = self._peek_curr()
            if operator.type not in {
                TokenType.LESS,
                TokenType.GREATER,
                TokenType.LESS_EQUAL,
                TokenType.GREATER_EQUAL,
            }:
                break
            self._consume()
            right = self._parse_shift()
            left = s.BinaryOperation_Relational(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_shift(self) -> s.Statement_Expression:
        left = self._parse_additive()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.LEFT_SHIFT, TokenType.RIGHT_SHIFT}:
                break
            self._consume()
            right = self._parse_additive()
            left = s.BinaryOperation_Shift(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_additive(self) -> s.Statement_Expression:
        left = self._parse_multiplicative()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.PLUS, TokenType.MINUS}:
                break
            self._consume()
            right = self._parse_multiplicative()
            left = s.BinaryOperation_Additive(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_multiplicative(self) -> s.Statement_Expression:
        left = self._parse_power()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.ASTERISK, TokenType.SLASH, TokenType.PERCENT}:
                break
            self._consume()
            right = self._parse_power()
            left = s.BinaryOperation_Multiplicative(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_power(self) -> s.Statement_Expression:
        left = self._parse_cast()
        operator = self._peek_curr()
        if operator.type != TokenType.POWER:
            return left
        self._consume()
        right = self._parse_power()
        return s.BinaryOperation_Power(lhs=left, operator=operator.value, rhs=right)

    def _parse_cast(self) -> s.Statement_Expression:
        expr = self._parse_unary()
        while self._peek_curr().type == TokenType.KW_AS and not self._parsing_with_binding_expr:
            self._safe_consume(TokenType.KW_AS)
            target = self._parse_type()
            expr = s.Expression_Cast(expr=expr, target=target)
        return expr

    def _parse_unary(self) -> s.Statement_Expression:
        tok = self._peek_curr()
        if tok.type in {
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.BANG,
            TokenType.TILDE,
            TokenType.INCREMENT,
            TokenType.DECREMENT,
        }:
            operator = tok
            self._consume()

            expr = self._parse_unary()
            return s.Expression_UnaryOperation(operator=operator.value, expr=expr)

        return self._parse_postfix()

    def _parse_postfix(self) -> s.Statement_Expression:
        expr = self._parse_primary()
        while not self._is_at_end():
            token = self._peek_curr()
            if token.type == TokenType.LEFT_PAREN:
                if not isinstance(expr, s.Expression_Path):
                    raise TypeError(f"Call target must be a path expression, got: {expr}")
                expr = self._parse_call(expr)
                continue
            if token.type == TokenType.DOT:
                expr = self._parse_dotted_postfix(expr)
                continue
            if token.type == TokenType.LEFT_BRACKET:
                expr = self._parse_index_postfix(expr)
                continue
            if token.type == TokenType.QUESTION:
                self._consume()
                expr = s.Expression_Try(expr=expr)
                continue
            break
        return expr

    def _parse_integer_literal(self) -> s.Expression_IntegerLiteral | s.Expression_FloatLiteral:
        token = self._safe_consume(TokenType.INTEGER)
        value = token.value
        literal_type = self._parse_numeric_literal_suffix()
        if literal_type is not None and self._is_float_type_name(literal_type.name):
            return self._attach_span(s.Expression_FloatLiteral(value, literal_type=literal_type), token)
        return self._attach_span(s.Expression_IntegerLiteral(value, literal_type=literal_type), token)

    def _parse_float_literal(self) -> s.Expression_FloatLiteral:
        token = self._safe_consume(TokenType.FLOAT)
        value = token.value
        literal_type = self._parse_numeric_literal_suffix()
        if literal_type is not None and not self._is_float_type_name(literal_type.name):
            raise TypeError(f"Float literal suffix must be a float type, got {literal_type}")
        return self._attach_span(s.Expression_FloatLiteral(value, literal_type=literal_type), token)

    def _parse_string_literal(self) -> s.Expression_StringLiteral:
        token = self._safe_consume(TokenType.STRING)
        raw = token.value
        return self._attach_span(s.Expression_StringLiteral(self._unescape_string_literal(raw[1:-1])), token)

    def _unescape_string_literal(self, raw: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(raw):
                out.append("\\")
                break
            nxt = raw[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "x":
                hex_digits = raw[i + 2 : i + 4]
                if len(hex_digits) == 2 and all(c in "0123456789abcdefABCDEF" for c in hex_digits):
                    out.append(chr(int(hex_digits, 16)))
                    i += 4
                    continue
                out.append("\\")
                out.append("x")
            elif nxt == "u":
                if i + 2 < len(raw) and raw[i + 2] == "{":
                    end = raw.find("}", i + 3)
                    if end != -1:
                        codepoint_digits = raw[i + 3 : end]
                        if codepoint_digits and all(c in "0123456789abcdefABCDEF" for c in codepoint_digits):
                            codepoint = int(codepoint_digits, 16)
                            out.append(chr(codepoint))
                            i = end + 1
                            continue
                out.append("\\")
                out.append("u")
            elif nxt == "\\":
                out.append("\\")
            elif nxt == '"':
                out.append('"')
            else:
                # Keep unknown escapes verbatim.
                out.append("\\")
                out.append(nxt)
            i += 2
        return "".join(out)

    def _parse_parenthesized_or_tuple(self) -> s.Statement_Expression:
        self._safe_consume(TokenType.LEFT_PAREN)

        if self._peek_curr().type == TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.RIGHT_PAREN)
            return s.Expression_TupleLiteral(items=[])

        first = self._parse_expression()
        if self._peek_curr().type != TokenType.COMMA:
            self._safe_consume(TokenType.RIGHT_PAREN)
            return s.Expression_Parenthesized(expr=first)

        items = [first]
        while self._peek_curr().type == TokenType.COMMA:
            self._safe_consume(TokenType.COMMA)
            if self._peek_curr().type == TokenType.RIGHT_PAREN:
                break
            items.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_PAREN)
        return s.Expression_TupleLiteral(items=items)

    def _parse_array_literal(self) -> s.Statement_Expression:
        self._safe_consume(TokenType.LEFT_BRACKET)
        if self._peek_curr().type == TokenType.RIGHT_BRACKET:
            self._safe_consume(TokenType.RIGHT_BRACKET)
            return s.Expression_ArrayLiteral(items=[])

        first = self._parse_expression()
        if self._peek_curr().type == TokenType.SEMICOLON:
            self._safe_consume(TokenType.SEMICOLON)
            size = int(self._safe_consume(TokenType.INTEGER).value)
            self._safe_consume(TokenType.RIGHT_BRACKET)
            return s.Expression_ArrayRepeat(value=first, size=size)

        items = [first]
        while self._peek_curr().type == TokenType.COMMA:
            self._safe_consume(TokenType.COMMA)
            if self._peek_curr().type == TokenType.RIGHT_BRACKET:
                break
            items.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_BRACKET)
        return s.Expression_ArrayLiteral(items=items)

    def _parse_maybe_label(self) -> Optional[str]:
        label = None
        if self._peek_curr().type == TokenType.LESS:
            self._safe_consume(TokenType.LESS)
            self._safe_consume(TokenType.QUOTE)
            label = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.GREATER)
        return label

    def _parse_expression_block(self) -> s.Statement_Expression:
        self._safe_consume(TokenType.LEFT_BRACE)
        body: list[s.Statement_InnerLevel] = []
        while self._starts_expression_block_statement():
            body.append(self._parse_inner_level())

        expr = self._parse_expression()
        self._safe_consume(TokenType.RIGHT_BRACE)
        if not body:
            return expr
        return s.Expression_Block(body=body, expr=expr)

    def _starts_expression_block_statement(self) -> bool:
        token_type = self._peek_curr().type

        if token_type in {
            TokenType.KW_LET,
            TokenType.KW_RET,
            TokenType.KW_WHILE,
            TokenType.KW_WITH,
            TokenType.KW_LOOP,
            TokenType.KW_DO,
            TokenType.KW_EHIR,
            TokenType.KW_BREAK,
            TokenType.KW_CONTINUE,
        }:
            return True

        if token_type == TokenType.KW_UNSAFE and self._peek_next().type == TokenType.KW_EHIR:
            return True

        # `if` / `match` / `unsafe` are valid expressions in tail position.
        # Prefer treating them as the final expression of the block unless the
        # language later gains explicit statement delimiters for this context.
        if token_type in {
            TokenType.KW_IF,
            TokenType.KW_MATCH,
            TokenType.KW_UNSAFE,
            TokenType.RIGHT_BRACE,
            TokenType.EOF,
        }:
            return False

        if token_type != TokenType.IDENTIFIER:
            return False

        return self._starts_assignment_statement()

    def _starts_assignment_statement(self) -> bool:
        index = 0
        if self._peek_n(index).type != TokenType.IDENTIFIER:
            return False

        while True:
            index += 1

            if self._peek_n(index).type == TokenType.LEFT_BRACKET:
                depth = 1
                index += 1
                while depth > 0:
                    token_type = self._peek_n(index).type
                    if token_type == TokenType.LEFT_BRACKET:
                        depth += 1
                    elif token_type == TokenType.RIGHT_BRACKET:
                        depth -= 1
                    elif token_type == TokenType.EOF:
                        return False
                    index += 1

            next_type = self._peek_n(index).type
            if next_type == TokenType.SCOPE:
                index += 1
                if self._peek_n(index).type != TokenType.IDENTIFIER:
                    return False
                continue

            if next_type == TokenType.DOT:
                index += 1
                if self._peek_n(index).type != TokenType.IDENTIFIER:
                    return False
                continue

            break

        return self._peek_n(index).type in {
            TokenType.ASSIGN,
            TokenType.PLUS_EQUAL,
            TokenType.MINUS_EQUAL,
            TokenType.ASTERISK_EQUAL,
            TokenType.POWER_EQUAL,
            TokenType.SLASH_EQUAL,
            TokenType.PERCENT_EQUAL,
            TokenType.AMPERSAND_EQUAL,
            TokenType.PIPE_EQUAL,
            TokenType.CARET_EQUAL,
            TokenType.LEFT_SHIFT_EQUAL,
            TokenType.RIGHT_SHIFT_EQUAL,
        }

    def _parse_struct_initialization(self, struct: Type) -> s.Expression_StructInitialization:
        self._safe_consume(TokenType.LEFT_BRACE)
        args = []
        if self._peek_curr().type != TokenType.RIGHT_BRACE:
            args.append(self._parse_expression())

        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            self._safe_consume(TokenType.COMMA)
            args.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Expression_StructInitialization(struct, args)

    def _parse_struct_field(self, variable: str) -> s.Expression_StructField:
        self._safe_consume(TokenType.DOT)
        field = self._safe_consume(TokenType.IDENTIFIER).value
        return s.Expression_StructField(variable, field)

    def _parse_call(self, callee: s.Expression_Path) -> s.Expression_Call:
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

        # `foo[T](...)` is parsed by `_parse_path()` as the last path segment carrying generics.
        # Normalize that into call generics so function lookup still uses plain `foo`.
        last_segment = callee.segments[-1]
        if last_segment.generics:
            if generics:
                raise TypeError("Function call generics must be specified only once")
            generics = list(last_segment.generics)
            normalized_callee = s.Expression_Path([*callee.segments[:-1], replace(last_segment, generics=[])])
            normalized_callee.line = callee.line
            normalized_callee.column = callee.column
            normalized_callee.span_length = callee.span_length
            normalized_callee.source_line = callee.source_line
            normalized_callee.module_id = callee.module_id
            callee = normalized_callee

        args = self._parse_call_args()
        call = s.Expression_Call(callee, generics, args)
        if callee.line is not None:
            call.line = callee.line
            call.column = callee.column
            call.span_length = callee.span_length
            call.source_line = callee.source_line
            call.module_id = callee.module_id
        return call

    def _parse_unsafe_expression(self) -> s.Expression_Unsafe:
        self._safe_consume(TokenType.KW_UNSAFE)
        body = self._parse_block()
        return s.Expression_Unsafe(body=body)

    def _parse_call_args(self) -> list[s.Statement_Expression]:
        self._safe_consume(TokenType.LEFT_PAREN)
        args: list[s.Statement_Expression] = []
        if self._peek_curr().type != TokenType.RIGHT_PAREN:
            args.append(self._parse_expression())
        while self._peek_curr().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            args.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_PAREN)
        return args

    def _build_struct_field(self, receiver: s.Statement_Expression, field: str) -> s.Statement_Expression:
        if isinstance(receiver, s.Expression_Path):
            return s.Expression_StructField(receiver.name, field)
        if isinstance(receiver, s.Expression_StructField):
            return s.Expression_StructField(f"{receiver.name}.{receiver.field}", field)
        return s.Expression_FieldAccess(receiver=receiver, field=field)

    def _parse_dotted_postfix(self, base: s.Statement_Expression) -> s.Statement_Expression:
        expr = base
        while not self._is_at_end() and self._peek_curr().type == TokenType.DOT:
            self._safe_consume(TokenType.DOT)
            member_token = self._peek_curr()
            if member_token.type not in (TokenType.IDENTIFIER, TokenType.INTEGER):
                raise TypeError(f"Expected field/method after '.', got: {member_token}")
            self._consume()
            member = member_token.value
            member_generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

            if not self._is_at_end() and self._peek_curr().type == TokenType.LEFT_PAREN:
                expr = s.Expression_MethodCall(
                    receiver=expr,
                    method=member,
                    generics=member_generics,
                    args=self._parse_call_args(),
                )
                continue

            if member_generics:
                raise TypeError(f"Field '{member}' cannot have generic arguments")
            expr = self._build_struct_field(expr, member)
        return expr

    def _parse_index_postfix(self, base: s.Statement_Expression) -> s.Statement_Expression:
        expr = base
        while not self._is_at_end() and self._peek_curr().type == TokenType.LEFT_BRACKET:
            self._safe_consume(TokenType.LEFT_BRACKET)
            index = self._parse_expression()
            self._safe_consume(TokenType.RIGHT_BRACKET)
            expr = s.Expression_Index(base=expr, index=index)
        return expr

    def _parse_path(self) -> s.Expression_Path:
        token = self._peek_curr()
        segments = [self._parse_path_segment()]
        while self._peek_curr().type == TokenType.SCOPE:
            self._safe_consume(TokenType.SCOPE)
            segments.append(self._parse_path_segment())
        return self._attach_span(s.Expression_Path(segments), token)

    def _parse_expression_path_segment(self) -> Type:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._should_parse_expression_path_generics() else []
        typ = Type(name, generics)
        if self._is_smart_pointer_suffix():
            self._safe_consume(TokenType.LESS)
            pointer = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.GREATER)
            return HeapSmartPointer(typ) if pointer == "H" else StackSmartPointer(typ)
        return typ

    def _should_parse_expression_path_generics(self) -> bool:
        if self._peek_curr().type != TokenType.LEFT_BRACKET:
            return False

        depth = 0
        index = 0
        while True:
            token_type = self._peek_n(index).type
            if token_type == TokenType.EOF:
                return False
            if token_type == TokenType.LEFT_BRACKET:
                depth += 1
            elif token_type == TokenType.RIGHT_BRACKET:
                depth -= 1
                if depth == 0:
                    after = self._peek_n(index + 1).type
                    return after in {TokenType.SCOPE, TokenType.LEFT_PAREN, TokenType.LEFT_BRACE, TokenType.LESS}
            index += 1

    def _parse_primary(self) -> s.Statement_Expression:
        curr_token = self._peek_curr()

        if curr_token.type == TokenType.INTEGER:
            return self._parse_integer_literal()
        elif curr_token.type == TokenType.FLOAT:
            return self._parse_float_literal()
        elif curr_token.type == TokenType.BOOLEAN:
            self._consume()
            return self._attach_span(s.Expression_BooleanLiteral(curr_token.value == "true"), curr_token)
        elif curr_token.type == TokenType.STRING:
            return self._parse_string_literal()

        elif curr_token.type == TokenType.LEFT_PAREN:
            return self._parse_parenthesized_or_tuple()

        elif curr_token.type == TokenType.LEFT_BRACKET:
            return self._parse_array_literal()

        elif curr_token.type == TokenType.LEFT_BRACE:
            return self._parse_expression_block()

        elif curr_token.type == TokenType.KW_MATCH:
            return self._parse_match_expression()

        elif curr_token.type == TokenType.KW_IF:
            return self._parse_if_expression()

        elif curr_token.type == TokenType.KW_UNSAFE:
            return self._parse_unsafe_expression()

        elif curr_token.type == TokenType.IDENTIFIER:
            first = self._parse_expression_path_segment()
            segments = [first]
            while self._peek_curr().type == TokenType.SCOPE:
                self._safe_consume(TokenType.SCOPE)
                segment = self._parse_expression_path_segment()
                segments.append(segment)
            path = self._attach_span(s.Expression_Path(segments), curr_token)

            if self._peek_curr().type == TokenType.LEFT_BRACE:
                if self._parsing_match_header or self._parsing_control_flow_header:
                    return path
                return self._parse_struct_initialization(first)
            return path

        raise TypeError(f"Unable to parse primary expression, got: {curr_token}")

    def _parse_assignment(self, target: s.Statement_Expression) -> s.Statement_Assignment:
        curr_token = self._peek_curr()
        self._consume()
        expr = self._parse_expression()
        return s.Statement_Assignment(target=target, expr=expr, operator=curr_token.value)

    def _parse_let(self) -> s.Statement_Let:
        self._safe_consume(TokenType.KW_LET)
        is_mut = False
        if self._peek_curr().type == TokenType.KW_MUT:
            self._safe_consume(TokenType.KW_MUT)
            is_mut = True
        name_token = self._safe_consume(TokenType.IDENTIFIER)
        name = name_token.value
        typ = None
        if self._peek_curr().type == TokenType.COLON:
            self._safe_consume(TokenType.COLON)
            typ = self._parse_type()
        self._safe_consume(TokenType.ASSIGN)
        expr = self._parse_expression()
        return self._attach_span(
            s.Statement_Let(
                name=name,
                type=typ,
                expr=expr,
                is_mut=is_mut,
            ),
            name_token,
        )

    def _parse_numeric_literal_suffix(self) -> Type | None:
        if self._is_at_end():
            return None
        token = self._peek_curr()
        if token.type != TokenType.IDENTIFIER or not token.value.startswith("_"):
            return None

        suffix_name = token.value.removeprefix("_")
        if not self._is_numeric_type_name(suffix_name):
            return None

        self._consume()
        return Type(suffix_name)

    @staticmethod
    def _is_numeric_type_name(name: str) -> bool:
        return EncoreParser._is_integer_type_name(name) or EncoreParser._is_float_type_name(name)

    @staticmethod
    def _is_integer_type_name(name: str) -> bool:
        return name in ("usize", "isize") or (len(name) > 1 and name[0] in ("u", "i") and name[1:].isdigit())

    @staticmethod
    def _is_float_type_name(name: str) -> bool:
        return len(name) > 1 and name[0] == "f" and name[1:].isdigit()

    def _parse_possible_generics(self) -> list[Type]:
        return self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

    def _parse_generic_params(self) -> list[Type]:
        return self._parse_generic_param_list() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

    def _parse_generic_param_list(self) -> list[Type]:
        generics: list[Type] = []
        self._safe_consume(TokenType.LEFT_BRACKET)
        generics.append(self._parse_generic_param())
        while self._peek_curr().type != TokenType.RIGHT_BRACKET:
            self._safe_consume(TokenType.COMMA)
            generics.append(self._parse_generic_param())
        self._safe_consume(TokenType.RIGHT_BRACKET)
        return generics

    def _parse_generic_param(self) -> s.GenericParam:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        bounds: list[Type] = []
        if self._peek_curr().type == TokenType.COLON:
            self._safe_consume(TokenType.COLON)
            bounds.append(self._parse_trait_bound())
            while self._peek_curr().type == TokenType.PLUS:
                self._safe_consume(TokenType.PLUS)
                bounds.append(self._parse_trait_bound())
        return s.GenericParam(name=name, generics=[], bounds=bounds)

    def _parse_trait_bound(self) -> Type:
        bound = self._parse_type()
        if isinstance(bound, (Pointer, HeapSmartPointer, StackSmartPointer)) or isinstance(bound, AnySmartPointer):
            raise TypeError(f"Trait bounds must be trait types, got {bound}")
        if is_mutable_type(bound):
            raise TypeError(f"Trait bounds can not be mutable, got {bound}")
        return bound

    def _parse_generics_args(self) -> list[Type]:
        generics: list[Type] = []
        if self._peek_curr().type == TokenType.LEFT_BRACKET:
            self._safe_consume(TokenType.LEFT_BRACKET)
            generics.append(self._parse_type())
            while self._peek_curr().type != TokenType.RIGHT_BRACKET:
                self._safe_consume(TokenType.COMMA)
                generics.append(self._parse_type())
            self._safe_consume(TokenType.RIGHT_BRACKET)
        return generics

    def _parse_type(self) -> Type:
        is_mut = False
        is_prefix_ref = False
        if self._peek_curr().type == TokenType.KW_MUT:
            self._safe_consume(TokenType.KW_MUT)
            is_mut = True

        if self._peek_curr().type == TokenType.AMPERSAND:
            self._safe_consume(TokenType.AMPERSAND)
            is_prefix_ref = True

        typ = self._parse_type_base()

        while self._peek_curr().type == TokenType.ASTERISK:
            self._safe_consume(TokenType.ASTERISK)
            typ = Pointer(typ)

        if self._is_smart_pointer_suffix():
            self._safe_consume(TokenType.LESS)
            pointer = self._safe_consume(TokenType.IDENTIFIER).value
            if pointer not in ("H", "S"):
                raise TypeError(f"Unexpected pointer annotation: {pointer}")
            self._safe_consume(TokenType.GREATER)
            if pointer == "H":
                typ = HeapSmartPointer(typ)
            else:
                typ = StackSmartPointer(typ)
        elif self._peek_curr().type == TokenType.AMPERSAND:
            self._safe_consume(TokenType.AMPERSAND)
            typ = AnySmartPointer(typ)

        if is_prefix_ref:
            if isinstance(typ, AnySmartPointer):
                raise TypeError(f"Unexpected duplicate reference annotation in type '{typ}'")
            typ = AnySmartPointer(typ)

        return make_mutable_type(typ) if is_mut else typ

    def _parse_type_base(self) -> Type:
        if self._peek_curr().type == TokenType.KW_DYN:
            self._safe_consume(TokenType.KW_DYN)
            trait_name = self._safe_consume(TokenType.IDENTIFIER).value
            while self._peek_curr().type == TokenType.SCOPE:
                self._safe_consume(TokenType.SCOPE)
                trait_name += f"::{self._safe_consume(TokenType.IDENTIFIER).value}"
            generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
            return Type("dyn", [Type(trait_name, generics)])

        if self._peek_curr().type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            if self._peek_curr().type == TokenType.RIGHT_PAREN:
                self._safe_consume(TokenType.RIGHT_PAREN)
                return make_tuple_type([])

            first = self._parse_type()
            if self._peek_curr().type != TokenType.COMMA:
                self._safe_consume(TokenType.RIGHT_PAREN)
                return first

            items = [first]
            while self._peek_curr().type == TokenType.COMMA:
                self._safe_consume(TokenType.COMMA)
                if self._peek_curr().type == TokenType.RIGHT_PAREN:
                    break
                items.append(self._parse_type())
            self._safe_consume(TokenType.RIGHT_PAREN)
            return make_tuple_type(items)

        if self._peek_curr().type == TokenType.LEFT_BRACKET:
            self._safe_consume(TokenType.LEFT_BRACKET)
            item_type = self._parse_type()
            self._safe_consume(TokenType.SEMICOLON)
            size = int(self._safe_consume(TokenType.INTEGER).value)
            self._safe_consume(TokenType.RIGHT_BRACKET)
            return make_array_type(item_type, size)

        name = self._safe_consume(TokenType.IDENTIFIER).value
        while self._peek_curr().type == TokenType.SCOPE:
            self._safe_consume(TokenType.SCOPE)
            name += f"::{self._safe_consume(TokenType.IDENTIFIER).value}"
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
        return Type(name, generics)

    def _parse_path_segment(self) -> Type:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
        typ = Type(name, generics)
        if self._is_smart_pointer_suffix():
            self._safe_consume(TokenType.LESS)
            pointer = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.GREATER)
            return HeapSmartPointer(typ) if pointer == "H" else StackSmartPointer(typ)
        return typ

    def _parse_param(self) -> Parameter:
        if self._peek_curr().type == TokenType.KW_MUT:
            self._safe_consume(TokenType.KW_MUT)
            if self._peek_curr().type != TokenType.IDENTIFIER or self._peek_curr().value != "self":
                raise TypeError("Only `self` may use prefix `mut` before the parameter name. Use `name: mut T`.")
            self._safe_consume(TokenType.IDENTIFIER)
            if self._peek_curr().type == TokenType.COLON:
                self._safe_consume(TokenType.COLON)
                return Parameter("self", make_mutable_type(self._parse_type()))
            return Parameter("self", make_mutable_type(Type("Self")))

        if self._peek_curr().type == TokenType.IDENTIFIER and self._peek_curr().value == "self":
            self._safe_consume(TokenType.IDENTIFIER)
            if self._peek_curr().type == TokenType.COLON:
                self._safe_consume(TokenType.COLON)
                return Parameter("self", self._parse_type())
            return Parameter("self", Type("Self"))

        name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.COLON)
        type = self._parse_type()
        return Parameter(name, type)

    def _parse_trait_bases(self) -> list[Type]:
        bases: list[Type] = []
        if self._peek_curr().type != TokenType.LESS:
            return bases

        self._safe_consume(TokenType.LESS)
        while self._peek_curr().type != TokenType.LEFT_BRACE:
            bases.append(self._parse_type())
            if self._peek_curr().type != TokenType.COMMA:
                break
            self._safe_consume(TokenType.COMMA)
        return bases

    def _is_smart_pointer_suffix(self) -> bool:
        if self._peek_curr().type != TokenType.LESS:
            return False
        try:
            pointer = self._peek_n(1)
            closer = self._peek_n(2)
        except ValueError:
            return False
        return pointer.type == TokenType.IDENTIFIER and pointer.value in ("H", "S") and closer.type == TokenType.GREATER

    def _safe_consume(self, expected_token_type: TokenType) -> LexerToken:
        token = self._consume()

        if token.type != expected_token_type:
            source_line = None
            if self._source_text:
                rows = self._source_text.splitlines()
                if 0 <= token.line < len(rows):
                    source_line = rows[token.line]
            raise CompileDiagnostic(
                message=(f"Unexpected token '{token.value}' ({token.type}). Expected: {expected_token_type}"),
                stage="parse",
                module_id=self._module_id,
                line=token.line,
                column=token.column,
                source_line=source_line,
            )

        return token
