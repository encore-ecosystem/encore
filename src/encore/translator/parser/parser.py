from encore.translator.lexer import Token
from encore.translator.lexer.tokens import TokenType
from encore.translator.parser import statements as s


class Parser:
    def parse(self, tokens: list[Token]) -> list[s.Statement]:
        self.tokens = tokens
        self.current_index = 0

        statements: list[s.Statement] = []
        while not self._is_at_end():
            statements.append(self._parse_top_level())
        return statements

    def _parse_top_level(self) -> s.Statement_TopLevel:
        curr_token = self._get_current_token()

        if curr_token.type == TokenType.KW_FN:
            return self._parse_function_definition()
        elif curr_token.type == TokenType.KW_STRUCT:
            return self._parse_struct_definition()

        raise ValueError("Unable to parse top level statement")

    def _parse_struct_definition(self) -> s.Statement_StructureDefinition:
        self._safe_consume(TokenType.KW_STRUCT)
        struct_name = self._safe_consume(TokenType.IDENTIFIER).value

        fields: list[tuple[str, str]] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            fields.append(self._parse_param())
        self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Statement_StructureDefinition(name=struct_name, fields=fields)

    def _parse_function_definition(self) -> s.Statement_FunctionDefinition:
        self._safe_consume(TokenType.KW_FN)
        func_name = self._safe_consume(TokenType.IDENTIFIER).value
        params: list[tuple[str, str]] = []

        self._safe_consume(TokenType.LEFT_PAREN)
        if self._get_current_token().type != TokenType.RIGHT_PAREN:
            params.append(self._parse_param())

        while self._get_current_token().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            params.append(self._parse_param())
        self._safe_consume(TokenType.RIGHT_PAREN)

        self._safe_consume(TokenType.OP_ARROW)
        fn_type = self._parse_type()
        body = self._parse_block()

        return s.Statement_FunctionDefinition(
            name=func_name,
            params=params,
            type=fn_type,
            body=body,
        )

    def _parse_block(self) -> list[s.Statement_InnerLevel]:
        self._safe_consume(TokenType.LEFT_BRACE)
        statements: list[s.Statement_InnerLevel] = []
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            statements.append(self._parse_inner_level())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return statements

    def _parse_inner_level(self) -> s.Statement_InnerLevel:
        curr_token = self._get_current_token()

        if curr_token.type == TokenType.KW_RET:
            return self._parse_ret()
        if curr_token.type == TokenType.KW_LET:
            return self._parse_let()

        raise NotImplementedError(curr_token)

    def _parse_ret(self) -> s.Statement_Ret:
        self._safe_consume(TokenType.KW_RET)
        expr = self._parse_expression()
        return s.Statement_Ret(expr=expr)

    def _parse_expression(self) -> s.Statement_Expression:
        return self._parse_additive()

    def _parse_additive(self) -> s.Statement_Expression:
        left = self._parse_multiplicative()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_PLUS, TokenType.OP_MINUS}:
                break
            self._unsafe_consume()
            right = self._parse_multiplicative()
            left = s.Expression_BinaryOperation(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_multiplicative(self) -> s.Statement_Expression:
        left = self._parse_unary()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_MULTIPLY, TokenType.OP_DIVIDE, TokenType.OP_MODULO}:
                break
            self._unsafe_consume()
            right = self._parse_unary()
            left = s.Expression_BinaryOperation(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_unary(self) -> s.Statement_Expression:
        tok = self._get_current_token()
        if tok.type in {
            TokenType.OP_PLUS,
            TokenType.OP_MINUS,
            TokenType.OP_NOT,
            TokenType.OP_BIT_NOT,
            TokenType.OP_INCREMENT,
            TokenType.OP_DECREMENT,
        }:
            operator = tok
            self._unsafe_consume()

            expr = self._parse_unary()
            return s.Expression_UnaryOperation(operator=operator.value, expr=expr)

        return self._parse_postfix()

    def _parse_postfix(self) -> s.Statement_Expression:
        return self._parse_primary()

    def _parse_primary(self) -> s.Statement_Expression:
        curr_token = self._get_current_token()

        if curr_token.type == TokenType.IDENTIFIER:
            name = self._safe_consume(TokenType.IDENTIFIER).value
            if self._get_current_token().type == TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)

                args = []
                if self._get_current_token().type != TokenType.RIGHT_BRACE:
                    args.append(self._parse_expression())

                while self._get_current_token().type != TokenType.RIGHT_BRACE:
                    self._safe_consume(TokenType.COMMA)
                    args.append(self._parse_expression())
                self._safe_consume(TokenType.RIGHT_BRACE)

                return s.Expression_StructInitialization(name, args)
            elif self._get_current_token().type == TokenType.DOT:
                self._safe_consume(TokenType.DOT)
                field = self._safe_consume(TokenType.IDENTIFIER).value
                return s.Expression_StructField(name, field)
            elif self._get_current_token().type == TokenType.LEFT_PAREN:
                self._safe_consume(TokenType.LEFT_PAREN)

                args = []
                if self._get_current_token().type != TokenType.RIGHT_PAREN:
                    args.append(self._parse_expression())

                while self._get_current_token().type != TokenType.RIGHT_PAREN:
                    self._safe_consume(TokenType.COMMA)
                    args.append(self._parse_expression())
                self._safe_consume(TokenType.RIGHT_PAREN)
                return s.Expression_Call(name, args)

            else:
                return s.Expression_VariableAccess(name)

        if curr_token.type == TokenType.INTEGER:
            return s.Expression_IntegerLiteral(value=self._safe_consume(TokenType.INTEGER).value)

        if curr_token.type == TokenType.FLOAT:
            return s.Expression_FloatLiteral(value=self._safe_consume(TokenType.FLOAT).value)

        if curr_token.type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            expr = self._parse_expression()
            self._safe_consume(TokenType.RIGHT_PAREN)
            return s.Expression_Parenthesized(expr=expr)

        raise TypeError(f"Unable to parse primary expression, got: {curr_token}")

    def _parse_let(self) -> s.Statement_Let:
        self._safe_consume(TokenType.KW_LET)
        var_name, var_type = self._parse_param()
        self._safe_consume(TokenType.OP_ASSIGN)
        expr = self._parse_expression()
        return s.Statement_Let(
            name=var_name,
            type=var_type,
            expr=expr,
        )

    def _parse_type(self) -> str:
        return self._safe_consume(TokenType.IDENTIFIER).value

    def _parse_param(self) -> tuple[str, str]:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.COLON)
        type = self._parse_type()
        return (name, type)

    def _is_at_end(self) -> bool:
        return self.current_index >= len(self.tokens)

    def _safe_consume(self, expected_token_type: TokenType) -> Token:
        token = self._consume()

        if token.type != expected_token_type:
            raise TypeError(f"Unexpected token: {token}, expected: {expected_token_type.name}")

        return token

    def _consume(self) -> Token:
        if self._is_at_end():
            raise ValueError

        token = self.tokens[self.current_index]
        self._unsafe_consume()
        return token

    def _unsafe_consume(self):
        self.current_index += 1

    def _get_current_token(self) -> Token:
        if self._is_at_end():
            raise ValueError

        return self.tokens[self.current_index]

    def _get_next_token(self) -> Token:
        if self.current_index + 1 >= len(self.tokens):
            raise ValueError

        return self.tokens[self.current_index + 1]
