from typing import Optional

from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter
from ehir.format import ThemePalette, printfmt

from encore.frontend.base import ParserBase
from encore.frontend.lexer import LexerToken
from encore.frontend.lexer.tokens import TokenType
from encore.frontend.parser import statements as s

TRACE_MAX_LINES_FOR_UNIT = 5


class Parser(ParserBase[LexerToken, s.Statement]):
    def _parse(self) -> list[s.Statement]:
        while not self._is_at_end():
            self._parse_top_level()
        return self._result

    def _get_eof_token(self) -> LexerToken:
        return LexerToken(type=TokenType.EOF, value="", line=0, column=0)

    def _parse_top_level(self):
        curr_token = self._peek_curr()

        if curr_token.type == TokenType.KW_IMPL:
            return self._parse_impl()
        elif curr_token.type == TokenType.ONE_LINE_COMMENT:
            return self._parse_one_line_comment()
        elif curr_token.type == TokenType.MULTI_LINE_COMMENT:
            return self._parse_multi_line_comment()

        is_public = False
        if curr_token.type == TokenType.KW_PUB:
            self._safe_consume(TokenType.KW_PUB)
            is_public = True
            curr_token = self._peek_curr()

        match curr_token.type:
            case TokenType.KW_IMPORT:
                self._parse_import(is_public)
            case TokenType.KW_ENUM:
                self._parse_enum(is_public)
            case TokenType.KW_TRAIT:
                self._parse_trait(is_public)
            case TokenType.KW_STRUCT:
                self._parse_struct(is_public)
            case TokenType.KW_FN:
                self._parse_fn(is_public)
            case TokenType.KW_EXTERN:
                self._parse_extern(is_public)
            case _:
                raise NotImplementedError(f"{curr_token}")

    def _parse_import(self, is_pub: bool):
        self._safe_consume(TokenType.KW_IMPORT)
        imp = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE)
        self._push(s.Statement_Import(is_public=is_pub, pair=imp))

    def _parse_enum(self, is_public: bool):
        self._safe_consume(TokenType.KW_ENUM)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_possible_generics()

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
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

        body: list[s.FunctionSignature] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            body.append(self._parse_function_signature())
        self._safe_consume(TokenType.RIGHT_BRACE)
        self._push(s.Statement_Trait(is_public=is_public, name=name, generics=generics, body=body))

    def _parse_impl(self):
        self._safe_consume(TokenType.KW_IMPL)
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

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
                is_public = False
                if self._peek_curr().type == TokenType.KW_PUB:
                    self._safe_consume(TokenType.KW_PUB)
                    is_public = True

                sign = self._parse_function_signature(is_public)
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

    def _parse_fn(self, is_public: bool):
        sign = self._parse_function_signature()
        body = self._parse_block()
        self._push(
            s.Statement_FunctionDefinition(
                is_public=is_public,
                signature=sign,
                body=body,
            )
        )

    def _parse_extern(self, is_public: bool):
        self._push(self._parse_function_signature(is_public))

    def _parse_import_path(self, default_leaf_kind: s.Statement_Import.ImportKind) -> s.Statement_Import.ImportPair:
        module = self._safe_consume(TokenType.IDENTIFIER).value

        if self._is_at_end() or self._peek_curr().type != TokenType.OP_SCOPE:
            return s.Statement_Import.ImportPair(module, [], default_leaf_kind)

        self._safe_consume(TokenType.OP_SCOPE)
        if self._is_at_end():
            raise ValueError("Import path cannot end with ::")

        curr_token = self._peek_curr()
        match curr_token.type:
            case TokenType.OP_MULTIPLY:
                self._consume()
                if not self._is_at_end() and self._peek_curr().type == TokenType.OP_SCOPE:
                    raise TypeError("Wildcard '*' must be terminal in import path")
                return s.Statement_Import.ImportPair(
                    module,
                    [s.Statement_Import.ImportPair("*", [], s.Statement_Import.ImportKind.GLOB)],
                )
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
                return s.Statement_Import.ImportPair(module, mods)
            case TokenType.IDENTIFIER:
                nested = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.SYMBOL)
                return s.Statement_Import.ImportPair(module, [nested])
            case _:
                raise ValueError(f"Unexpected Token: {curr_token}")

    def _parse_struct_signature(self) -> s.StructureSignature:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
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

    def _parse_function_signature(self, is_public: bool = False) -> s.FunctionSignature:
        is_extern = False
        if self._peek_curr().type == TokenType.KW_EXTERN:
            self._safe_consume(TokenType.KW_EXTERN)
            is_extern = True

        self._safe_consume(TokenType.KW_FN)
        func_name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_possible_generics()

        params: list[Parameter] = []
        self._safe_consume(TokenType.LEFT_PAREN)
        if self._peek_curr().type != TokenType.RIGHT_PAREN:
            params.append(self._parse_param())

        while self._peek_curr().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            params.append(self._parse_param())
        self._safe_consume(TokenType.RIGHT_PAREN)

        fn_type = None
        if self._peek_curr().type == TokenType.OP_ARROW:
            self._safe_consume(TokenType.OP_ARROW)
            fn_type = self._parse_type()

        return s.FunctionSignature(
            is_public=is_public, is_extern=is_extern, name=func_name, generics=generics, params=params, type=fn_type
        )

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
                return self._parse_ret()
            case TokenType.KW_LET:
                return self._parse_let()
            case TokenType.KW_DO:
                return self._parse_do_while()
            case TokenType.KW_WHILE:
                return self._parse_while()
            case TokenType.KW_LOOP:
                return self._parse_loop()
            case TokenType.KW_IF:
                return self._parse_if_block()
            case TokenType.KW_MATCH:
                return self._parse_match()
            case TokenType.KW_UNSAFE:
                return self._parse_unsafe_block()
            case TokenType.KW_BREAK:
                return self._parse_break()
            case TokenType.KW_CONTINUE:
                return self._parse_continue()
            case TokenType.IDENTIFIER:
                target = self._parse_expression()
                match self._peek_curr().type:
                    case (
                        TokenType.OP_ASSIGN
                        | TokenType.OP_PLUS_ASSIGN
                        | TokenType.OP_MINUS_ASSIGN
                        | TokenType.OP_MULT_ASSIGN
                        | TokenType.OP_DIV_ASSIGN
                    ):
                        return self._parse_assignment(target)
                    case _:
                        return s.Statement_Expr(target)
            case _:
                raise NotImplementedError(curr_token)

    def _parse_ret(self) -> s.Statement_Ret:
        self._safe_consume(TokenType.KW_RET)
        expr = self._parse_expression()
        return s.Statement_Ret(expr=expr)

    def _parse_while(self) -> s.Statement_While:
        self._safe_consume(TokenType.KW_WHILE)
        label = self._parse_maybe_label()
        expr = self._parse_expression()
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
        expr = self._parse_expression()
        return s.Statement_DoWhile(body, expr)

    def _parse_if_block(self):
        self._safe_consume(TokenType.KW_IF)
        branches = [s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block())]

        while not self._is_at_end() and self._peek_curr().type == TokenType.KW_ELIF:
            self._safe_consume(TokenType.KW_ELIF)
            branches.append(s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block()))

        else_body = None
        if not self._is_at_end() and self._peek_curr().type == TokenType.KW_ELSE:
            self._safe_consume(TokenType.KW_ELSE)
            else_body = self._parse_block()

        return s.Statement_If(branches=branches, else_body=else_body)

    def _parse_unsafe_block(self) -> s.Statement_Unsafe:
        self._safe_consume(TokenType.KW_UNSAFE)
        body = self._parse_block()
        return s.Statement_Unsafe(body=body)

    def _parse_match(self) -> s.Statement_Match:
        self._safe_consume(TokenType.KW_MATCH)
        self._parsing_match_header = True
        expr = self._parse_expression()
        self._parsing_match_header = False
        self._safe_consume(TokenType.LEFT_BRACE)
        arms: list[s.Statement_MatchArm] = []
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            arms.append(self._parse_match_arm())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Statement_Match(expr=expr, arms=arms)

    def _parse_match_arm(self) -> s.Statement_MatchArm:
        pattern = None
        if self._peek_curr().type == TokenType.IDENTIFIER and self._peek_curr().value == "_":
            self._consume()
        else:
            pattern = self._parse_path()
        binding = None
        if self._peek_curr().type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            binding = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.RIGHT_PAREN)
        self._safe_consume(TokenType.OP_FAT_ARROW)
        body = self._parse_block()
        return s.Statement_MatchArm(pattern=pattern, binding=binding, body=body)

    def _parse_match_expression(self) -> s.Expression_Match:
        self._safe_consume(TokenType.KW_MATCH)
        self._parsing_match_header = True
        expr = self._parse_expression()
        self._parsing_match_header = False
        self._safe_consume(TokenType.LEFT_BRACE)
        arms: list[s.Expression_MatchArm] = []
        while self._peek_curr().type != TokenType.RIGHT_BRACE:
            arms.append(self._parse_match_expression_arm())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Expression_Match(expr=expr, arms=arms)

    def _parse_match_expression_arm(self) -> s.Expression_MatchArm:
        pattern = None
        if self._peek_curr().type == TokenType.IDENTIFIER and self._peek_curr().value == "_":
            self._consume()
        else:
            pattern = self._parse_path()
        binding = None
        if self._peek_curr().type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            binding = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.RIGHT_PAREN)
        self._safe_consume(TokenType.OP_FAT_ARROW)
        expr = self._parse_expression()
        return s.Expression_MatchArm(pattern=pattern, binding=binding, expr=expr)

    def _parse_expression(self) -> s.Statement_Expression:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> s.Statement_Expression:
        left = self._parse_logical_and()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_OR}:
                break
            self._consume()
            right = self._parse_logical_and()
            left = s.BinaryOperation_LogicalOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_logical_and(self) -> s.Statement_Expression:
        left = self._parse_bitwise_or()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_AND}:
                break
            self._consume()
            right = self._parse_bitwise_or()
            left = s.BinaryOperation_LogicalAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_or(self) -> s.Statement_Expression:
        left = self._parse_bitwise_xor()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_BIT_OR}:
                break
            self._consume()
            right = self._parse_bitwise_xor()
            left = s.BinaryOperation_BitwiseOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_xor(self) -> s.Statement_Expression:
        left = self._parse_bitwise_and()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_BIT_XOR}:
                break
            self._consume()
            right = self._parse_bitwise_and()
            left = s.BinaryOperation_BitwiseXor(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_and(self) -> s.Statement_Expression:
        left = self._parse_equality()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_BIT_AND}:
                break
            self._consume()
            right = self._parse_equality()
            left = s.BinaryOperation_BitwiseAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_equality(self) -> s.Statement_Expression:
        left = self._parse_relational()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_EQUAL, TokenType.OP_NOT_EQUAL}:
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
                TokenType.OP_LESS,
                TokenType.OP_GREATER,
                TokenType.OP_LESS_EQUAL,
                TokenType.OP_GREATER_EQUAL,
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
            if operator.type not in {TokenType.OP_LEFT_SHIFT, TokenType.OP_RIGHT_SHIFT}:
                break
            self._consume()
            right = self._parse_additive()
            left = s.BinaryOperation_Shift(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_additive(self) -> s.Statement_Expression:
        left = self._parse_multiplicative()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_PLUS, TokenType.OP_MINUS}:
                break
            self._consume()
            right = self._parse_multiplicative()
            left = s.BinaryOperation_Additive(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_multiplicative(self) -> s.Statement_Expression:
        left = self._parse_unary()
        while True:
            operator = self._peek_curr()
            if operator.type not in {TokenType.OP_MULTIPLY, TokenType.OP_DIVIDE, TokenType.OP_MODULO}:
                break
            self._consume()
            right = self._parse_unary()
            left = s.BinaryOperation_Multiplicative(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_unary(self) -> s.Statement_Expression:
        tok = self._peek_curr()
        if tok.type in {
            TokenType.OP_PLUS,
            TokenType.OP_MINUS,
            TokenType.OP_NOT,
            TokenType.OP_BIT_NOT,
            TokenType.OP_INCREMENT,
            TokenType.OP_DECREMENT,
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
            if token.type == TokenType.OP_TRY:
                self._consume()
                expr = s.Expression_Try(expr=expr)
                continue
            break
        return expr

    def _parse_integer_literal(self) -> s.Expression_IntegerLiteral:
        value = self._safe_consume(TokenType.INTEGER).value
        literal_type = self._parse_numeric_literal_suffix()
        if literal_type is not None and self._is_float_type_name(literal_type.name):
            return s.Expression_FloatLiteral(value, literal_type=literal_type)
        return s.Expression_IntegerLiteral(value, literal_type=literal_type)

    def _parse_float_literal(self) -> s.Expression_FloatLiteral:
        value = self._safe_consume(TokenType.FLOAT).value
        literal_type = self._parse_numeric_literal_suffix()
        if literal_type is not None and not self._is_float_type_name(literal_type.name):
            raise TypeError(f"Float literal suffix must be a float type, got {literal_type}")
        return s.Expression_FloatLiteral(value, literal_type=literal_type)

    def _parse_string_literal(self) -> s.Expression_StringLiteral:
        raw = self._safe_consume(TokenType.STRING).value
        unescape = bytes(raw[1:-1], "utf-8").decode("unicode_escape")
        return s.Expression_StringLiteral(unescape)

    def _parse_parenthesized(self) -> s.Expression_Parenthesized:
        self._safe_consume(TokenType.LEFT_PAREN)
        expr = self._parse_expression()
        self._safe_consume(TokenType.RIGHT_PAREN)
        return s.Expression_Parenthesized(expr=expr)

    def _parse_maybe_label(self) -> Optional[str]:
        label = None
        if self._peek_curr().type == TokenType.OP_LESS:
            self._safe_consume(TokenType.OP_LESS)
            self._safe_consume(TokenType.QUOTE)
            label = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.OP_GREATER)
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
            callee = s.Expression_Path([*callee.segments[:-1], replace(last_segment, generics=[])])

        args = self._parse_call_args()
        return s.Expression_Call(callee, generics, args)

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

    def _build_struct_field(self, receiver: s.Statement_Expression, field: str) -> s.Expression_StructField:
        if isinstance(receiver, s.Expression_Path):
            return s.Expression_StructField(receiver.name, field)
        if isinstance(receiver, s.Expression_StructField):
            return s.Expression_StructField(f"{receiver.name}.{receiver.field}", field)
        raise TypeError(f"Field access is supported only for paths/fields, got: {receiver}")

    def _parse_dotted_postfix(self, base: s.Statement_Expression) -> s.Statement_Expression:
        expr = base
        while not self._is_at_end() and self._peek_curr().type == TokenType.DOT:
            self._safe_consume(TokenType.DOT)
            member = self._safe_consume(TokenType.IDENTIFIER).value
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

    def _parse_path(self) -> s.Expression_Path:
        segments = [self._parse_type()]
        while self._peek_curr().type == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.OP_SCOPE)
            segments.append(self._parse_type())
        return s.Expression_Path(segments)

    def _parse_primary(self) -> s.Statement_Expression:
        curr_token = self._peek_curr()

        if curr_token.type == TokenType.INTEGER:
            return self._parse_integer_literal()
        elif curr_token.type == TokenType.FLOAT:
            return self._parse_float_literal()
        elif curr_token.type == TokenType.STRING:
            return self._parse_string_literal()

        elif curr_token.type == TokenType.LEFT_PAREN:
            return self._parse_parenthesized()

        elif curr_token.type == TokenType.KW_MATCH:
            return self._parse_match_expression()

        elif curr_token.type == TokenType.KW_IF:
            return self._parse_if_expression()

        elif curr_token.type == TokenType.KW_UNSAFE:
            return self._parse_unsafe_expression()

        elif curr_token.type == TokenType.IDENTIFIER:
            if curr_token.value in ("true", "false"):
                self._consume()
                return s.Expression_BooleanLiteral(curr_token.value == "true")
            first = self._parse_type()
            segments = [first]
            while self._peek_curr().type == TokenType.OP_SCOPE:
                self._safe_consume(TokenType.OP_SCOPE)
                segment = self._parse_type()
                segments.append(segment)
            path = s.Expression_Path(segments)

            if self._peek_curr().type == TokenType.LEFT_BRACE:
                if self._parsing_match_header:
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
        name = self._safe_consume(TokenType.IDENTIFIER).value
        typ = None
        if self._peek_curr().type == TokenType.COLON:
            self._safe_consume(TokenType.COLON)
            typ = self._parse_type()
        self._safe_consume(TokenType.OP_ASSIGN)
        expr = self._parse_expression()
        return s.Statement_Let(
            name=name,
            type=typ,
            expr=expr,
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
        return Parser._is_integer_type_name(name) or Parser._is_float_type_name(name)

    @staticmethod
    def _is_integer_type_name(name: str) -> bool:
        return name in ("usize", "isize") or (len(name) > 1 and name[0] in ("u", "i") and name[1:].isdigit())

    @staticmethod
    def _is_float_type_name(name: str) -> bool:
        return len(name) > 1 and name[0] == "f" and name[1:].isdigit()

    def _parse_possible_generics(self) -> list[Type]:
        return self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []

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
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._peek_curr().type == TokenType.LEFT_BRACKET else []
        typ = Type(name, generics)

        if self._is_smart_pointer_suffix():
            self._safe_consume(TokenType.OP_LESS)
            pointer = self._safe_consume(TokenType.IDENTIFIER).value
            if pointer not in ("H", "S"):
                raise TypeError(f"Unexpected pointer annotation: {pointer}")
            self._safe_consume(TokenType.OP_GREATER)
            if pointer == "H":
                return HeapSmartPointer(typ)
            return StackSmartPointer(typ)
        return typ

    def _parse_param(self) -> Parameter:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.COLON)
        type = self._parse_type()
        return Parameter(name, type)

    def _is_smart_pointer_suffix(self) -> bool:
        if self._peek_curr().type != TokenType.OP_LESS:
            return False
        try:
            pointer = self._peek_n(1)
            closer = self._peek_n(2)
        except ValueError:
            return False
        return (
            pointer.type == TokenType.IDENTIFIER and pointer.value in ("H", "S") and closer.type == TokenType.OP_GREATER
        )

    def _safe_consume(self, expected_token_type: TokenType) -> LexerToken:
        token = self._consume()

        if token.type != expected_token_type:
            self._trace_unexpected_token_error(token, expected_types=[expected_token_type])
            exit(1)

        return token

    def _trace_unexpected_token_error(self, token: LexerToken, expected_types: list[TokenType]):
        printfmt(
            f"  Error: Unexpected token '{token.value}' at line {token.line + 1}, column {token.column + 1}\n",
            ThemePalette.ERROR_TEXT,
        )
        if expected_types:
            printfmt(
                f"  Expected: {','.join(str(x) for x in expected_types)}\n",
                ThemePalette.ACCENT_TEXT,
            )
