from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter

from encore.frontend.lexer import Token
from encore.frontend.lexer.tokens import TokenType
from encore.frontend.parser import statements as s
from encore.frontend.parser.statements import Statement_Import


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

        if curr_token.type == TokenType.KW_IMPL:
            return self._parse_impl()

        is_public = False
        if curr_token.type == TokenType.KW_PUB:
            self._consume()
            is_public = True
            curr_token = self._get_current_token()

        if curr_token.type == TokenType.KW_FN:
            return self._parse_function_definition(is_public)
        elif curr_token.type == TokenType.KW_STRUCT:
            return self._parse_struct_definition(is_public)
        elif curr_token.type == TokenType.KW_IMPORT:
            return self._parse_import(is_public)
        elif curr_token.type == TokenType.KW_ENUM:
            return self._parse_enum(is_public)
        # elif curr_token.type == TokenType.KW_TRAIT:
        #     return self._parse_trait(is_public)

        raise ValueError(f"Unable to parse top level statement: {curr_token}")

    def _parse_import(self, is_public: bool) -> s.Statement_Import:
        self._safe_consume(TokenType.KW_IMPORT)
        imp = self._parse_module_import()
        return s.Statement_Import(is_public=is_public, pair=imp)

    def _parse_module_import(self) -> Statement_Import.ImportPair:
        module = self._safe_consume(TokenType.IDENTIFIER).value

        if self._get_current_token().type != TokenType.OP_SCOPE:
            return Statement_Import.ImportPair(module, [])

        self._safe_consume(TokenType.OP_SCOPE)
        curr_token = self._get_current_token()
        match curr_token.type:
            case TokenType.OP_MULTIPLY:
                self._consume()
                return Statement_Import.ImportPair(module, [Statement_Import.ImportPair(curr_token.value, [])])
            case TokenType.IDENTIFIER:
                submodule = self._safe_consume(TokenType.IDENTIFIER).value
                mods = []
                if self._get_current_token().type == TokenType.OP_SCOPE:
                    self._consume()
                    mods.append(self._parse_module_import())
                return Statement_Import.ImportPair(module, [Statement_Import.ImportPair(submodule, mods)])
            case TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)
                mods = []
                mods.append(self._parse_module_import())
                while self._get_current_token().type != TokenType.RIGHT_BRACE:
                    self._safe_consume(TokenType.COMMA)
                    mods.append(self._parse_module_import())
                self._safe_consume(TokenType.RIGHT_BRACE)
                return Statement_Import.ImportPair(module, mods)
            case _:
                raise ValueError(f"Unexpected Token: {curr_token}")

    def _parse_struct_definition(self, is_public: bool) -> s.Statement_StructureDefinition:
        self._safe_consume(TokenType.KW_STRUCT)
        definition = self._parse_raw_struct_definition()
        return s.Statement_StructureDefinition(is_public=is_public, defi=definition)

    def _parse_function_definition(self, is_public: bool) -> s.Statement_FunctionDefinition:
        self._safe_consume(TokenType.KW_FN)
        func_name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
        params: list[Parameter] = []

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
            is_public=is_public,
            name=func_name,
            generics=generics,
            params=params,
            type=fn_type,
            body=body,
        )

    def _parse_enum(self, is_public: bool) -> s.Statement_EnumDefinition:
        self._safe_consume(TokenType.KW_ENUM)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        # Enum body
        body = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            body.append(self._parse_raw_struct_definition())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Statement_EnumDefinition(
            is_public=is_public,
            name=name,
            generics=generics,
            body=body,
        )

    def _parse_raw_struct_definition(self) -> s.StructureDefinition:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
        match self._get_current_token().type:
            case TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)
                fields: list[Parameter] = []
                while self._get_current_token().type != TokenType.RIGHT_BRACE:
                    fields.append(self._parse_param())
                self._safe_consume(TokenType.RIGHT_BRACE)
                return s.CLikeStructureDefinition(name=name, generics=generics, fields=fields)
            case TokenType.LEFT_PAREN:
                self._safe_consume(TokenType.LEFT_PAREN)
                fields: list[Type] = []
                while self._get_current_token().type != TokenType.RIGHT_PAREN:
                    fields.append(self._parse_type())
                self._safe_consume(TokenType.RIGHT_PAREN)
                return s.TupleStructureDefinition(name=name, generics=generics, fields=fields)
            case _:
                return s.UnitStructureDefinition(name=name, generics=generics)

    def _parse_impl(self) -> s.Statement_Impl:
        self._safe_consume(TokenType.KW_IMPL)
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        trait_name = None
        if self._get_current_token().type != TokenType.KW_FOR:
            trait_name = self._safe_consume(TokenType.IDENTIFIER).value
        self._safe_consume(TokenType.KW_FOR)
        struct = self._parse_type()

        body: list[s.Statement_FunctionDefinition] = []
        if self._get_current_token().type == TokenType.LEFT_BRACE:
            self._safe_consume(TokenType.LEFT_BRACE)
            while self._get_current_token().type != TokenType.RIGHT_BRACE:
                is_public = False
                if self._get_current_token().type == TokenType.KW_PUB:
                    self._safe_consume(TokenType.KW_PUB)
                    is_public = True
                body.append(self._parse_function_definition(is_public))
            self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Statement_Impl(is_public=False, generics=generics, trait_name=trait_name, struct=struct, body=body)

    # def _parse_function_declaration(self) -> s.Statement_Impl.FunctionDeclaration:
    #     is_public = False
    #     if self._get_current_token().type == TokenType.KW_PUB:
    #         self._safe_consume(TokenType.KW_PUB)
    #         is_public = True

    #     self._safe_consume(TokenType.KW_FN)
    #     fn_name = self._safe_consume(TokenType.IDENTIFIER).value
    #     generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

    #     params: list[tuple[str, str]] = []
    #     self._safe_consume(TokenType.LEFT_PAREN)
    #     if self._get_current_token().type != TokenType.RIGHT_PAREN:
    #         params.append(self._parse_param())

    #     while self._get_current_token().type != TokenType.RIGHT_PAREN:
    #         self._safe_consume(TokenType.COMMA)
    #         params.append(self._parse_param())
    #     self._safe_consume(TokenType.RIGHT_PAREN)

    #     self._safe_consume(TokenType.OP_ARROW)
    #     fn_type = self._parse_type()

    #     return s.Statement_Impl.FunctionDeclaration(
    #         is_public=is_public,
    #         name=fn_name,
    #         generics=generics,
    #         params=params,
    #         type=fn_type,
    #     )

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
        if curr_token.type == TokenType.KW_DO:
            return self._parse_do_while()
        if curr_token.type == TokenType.KW_WHILE:
            return self._parse_while()
        if curr_token.type == TokenType.KW_LOOP:
            return self._parse_loop()
        if curr_token.type == TokenType.KW_IF:
            return self._parse_if_block()
        if curr_token.type == TokenType.KW_BREAK:
            return self._parse_break()
        if curr_token.type == TokenType.KW_CONTINUE:
            return self._parse_continue()
        if curr_token.type == TokenType.IDENTIFIER:
            target = self._parse_expression()
            if self._get_current_token().type == TokenType.OP_ASSIGN:
                return self._parse_assignment(target)
            raise NotImplementedError(curr_token)

        raise NotImplementedError(curr_token)

    def _parse_ret(self) -> s.Statement_Ret:
        self._safe_consume(TokenType.KW_RET)
        expr = self._parse_expression()
        return s.Statement_Ret(expr=expr)

    def _parse_while(self) -> s.Statement_While:
        self._safe_consume(TokenType.KW_WHILE)
        expr = self._parse_expression()
        body = self._parse_block()
        return s.Statement_While(expr, body)

    def _parse_loop(self) -> s.Statement_Loop:
        self._safe_consume(TokenType.KW_LOOP)
        body = self._parse_block()
        return s.Statement_Loop(body)

    def _parse_break(self):
        self._safe_consume(TokenType.KW_BREAK)
        return s.Statement_Break()

    def _parse_continue(self):
        self._safe_consume(TokenType.KW_CONTINUE)
        return s.Statement_Continue()

    def _parse_do_while(self) -> s.Statement_DoWhile:
        self._safe_consume(TokenType.KW_DO)
        body = self._parse_block()
        self._safe_consume(TokenType.KW_WHILE)
        expr = self._parse_expression()
        return s.Statement_DoWhile(body, expr)

    def _parse_if_block(self):
        self._safe_consume(TokenType.KW_IF)
        branches = [s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block())]

        while not self._is_at_end() and self._get_current_token().type == TokenType.KW_ELIF:
            self._safe_consume(TokenType.KW_ELIF)
            branches.append(s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block()))

        else_body = None
        if not self._is_at_end() and self._get_current_token().type == TokenType.KW_ELSE:
            self._safe_consume(TokenType.KW_ELSE)
            else_body = self._parse_block()

        return s.Statement_If(branches=branches, else_body=else_body)

    def _parse_expression(self) -> s.Statement_Expression:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> s.Statement_Expression:
        left = self._parse_logical_and()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_OR}:
                break
            self._unsafe_consume()
            right = self._parse_logical_and()
            left = s.BinaryOperation_LogicalOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_logical_and(self) -> s.Statement_Expression:
        left = self._parse_bitwise_or()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_AND}:
                break
            self._unsafe_consume()
            right = self._parse_bitwise_or()
            left = s.BinaryOperation_LogicalAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_or(self) -> s.Statement_Expression:
        left = self._parse_bitwise_xor()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_BIT_OR}:
                break
            self._unsafe_consume()
            right = self._parse_bitwise_xor()
            left = s.BinaryOperation_BitwiseOr(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_xor(self) -> s.Statement_Expression:
        left = self._parse_bitwise_and()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_BIT_XOR}:
                break
            self._unsafe_consume()
            right = self._parse_bitwise_and()
            left = s.BinaryOperation_BitwiseXor(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_bitwise_and(self) -> s.Statement_Expression:
        left = self._parse_equality()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_BIT_AND}:
                break
            self._unsafe_consume()
            right = self._parse_equality()
            left = s.BinaryOperation_BitwiseAnd(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_equality(self) -> s.Statement_Expression:
        left = self._parse_relational()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_EQUAL, TokenType.OP_NOT_EQUAL}:
                break
            self._unsafe_consume()
            right = self._parse_relational()
            left = s.BinaryOperation_Equality(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_relational(self) -> s.Statement_Expression:
        left = self._parse_shift()
        while True:
            operator = self._get_current_token()
            if operator.type not in {
                TokenType.OP_LESS,
                TokenType.OP_GREATER,
                TokenType.OP_LESS_EQUAL,
                TokenType.OP_GREATER_EQUAL,
            }:
                break
            self._unsafe_consume()
            right = self._parse_shift()
            left = s.BinaryOperation_Relational(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_shift(self) -> s.Statement_Expression:
        left = self._parse_additive()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_LEFT_SHIFT, TokenType.OP_RIGHT_SHIFT}:
                break
            self._unsafe_consume()
            right = self._parse_additive()
            left = s.BinaryOperation_Shift(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_additive(self) -> s.Statement_Expression:
        left = self._parse_multiplicative()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_PLUS, TokenType.OP_MINUS}:
                break
            self._unsafe_consume()
            right = self._parse_multiplicative()
            left = s.BinaryOperation_Additive(lhs=left, operator=operator.value, rhs=right)
        return left

    def _parse_multiplicative(self) -> s.Statement_Expression:
        left = self._parse_unary()
        while True:
            operator = self._get_current_token()
            if operator.type not in {TokenType.OP_MULTIPLY, TokenType.OP_DIVIDE, TokenType.OP_MODULO}:
                break
            self._unsafe_consume()
            right = self._parse_unary()
            left = s.BinaryOperation_Multiplicative(lhs=left, operator=operator.value, rhs=right)
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

    def _parse_integer_literal(self) -> s.Expression_IntegerLiteral:
        value = self._safe_consume(TokenType.INTEGER).value
        return s.Expression_IntegerLiteral(value)

    def _parse_parenthesized(self) -> s.Expression_Parenthesized:
        self._safe_consume(TokenType.LEFT_PAREN)
        expr = self._parse_expression()
        self._safe_consume(TokenType.RIGHT_PAREN)
        return s.Expression_Parenthesized(expr=expr)

    def _parse_struct_initialization(self, struct: Type) -> s.Expression_StructInitialization:
        self._safe_consume(TokenType.LEFT_BRACE)
        args = []
        if self._get_current_token().type != TokenType.RIGHT_BRACE:
            args.append(self._parse_expression())

        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            self._safe_consume(TokenType.COMMA)
            args.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Expression_StructInitialization(struct, args)

    def _parse_struct_field(self, variable: str) -> s.Expression_StructField:
        self._safe_consume(TokenType.DOT)
        field = self._safe_consume(TokenType.IDENTIFIER).value
        return s.Expression_StructField(variable, field)

    def _parse_call(self, callee: s.Expression_Path) -> s.Expression_Call:
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        self._safe_consume(TokenType.LEFT_PAREN)
        args = []
        if self._get_current_token().type != TokenType.RIGHT_PAREN:
            args.append(self._parse_expression())
        while self._get_current_token().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            args.append(self._parse_expression())
        self._safe_consume(TokenType.RIGHT_PAREN)
        return s.Expression_Call(callee, generics, args)

    def _parse_path(self) -> s.Expression_Path:
        segments = [self._parse_type()]
        while self._get_current_token().type == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.OP_SCOPE)
            segments.append(self._parse_type())
        return s.Expression_Path(segments)

    def _parse_primary(self) -> s.Statement_Expression:
        curr_token = self._get_current_token()

        if curr_token.type == TokenType.INTEGER:
            return self._parse_integer_literal()

        elif curr_token.type == TokenType.LEFT_PAREN:
            return self._parse_parenthesized()

        elif curr_token.type == TokenType.IDENTIFIER:
            first = self._parse_type()
            symbol = str(first)
            segments = [first]
            while self._get_current_token().type == TokenType.OP_SCOPE:
                self._safe_consume(TokenType.OP_SCOPE)
                segment = self._parse_type()
                segments.append(segment)
            path = s.Expression_Path(segments)

            match self._get_current_token().type:
                case TokenType.LEFT_BRACE:
                    return self._parse_struct_initialization(first)
                case TokenType.DOT:
                    return self._parse_struct_field(symbol)
                case TokenType.LEFT_PAREN:
                    return self._parse_call(path)
                case _:
                    return path

        raise TypeError(f"Unable to parse primary expression, got: {curr_token}")

    def _parse_assignment(self, target: s.Statement_Expression) -> s.Statement_Assignment:
        self._safe_consume(TokenType.OP_ASSIGN)
        expr = self._parse_expression()
        return s.Statement_Assignment(target=target, expr=expr)

    def _parse_let(self) -> s.Statement_Let:
        self._safe_consume(TokenType.KW_LET)
        param = self._parse_param()
        self._safe_consume(TokenType.OP_ASSIGN)
        expr = self._parse_expression()
        return s.Statement_Let(
            name=param.name,
            type=param.type,
            expr=expr,
        )

    def _parse_generics_args(self) -> list[Type]:
        generics: list[Type] = []
        if self._get_current_token().type == TokenType.LEFT_BRACKET:
            self._safe_consume(TokenType.LEFT_BRACKET)
            generics.append(self._parse_type())
            while self._get_current_token().type != TokenType.RIGHT_BRACKET:
                self._safe_consume(TokenType.COMMA)
                generics.append(self._parse_type())
            self._safe_consume(TokenType.RIGHT_BRACKET)
        return generics

    def _parse_type(self) -> Type:
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
        typ = Type(name, generics)

        if self._get_current_token().type == TokenType.OP_LESS:
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

    def _peek_token(self, offset: int) -> Token:
        index = self.current_index + offset
        if index >= len(self.tokens):
            raise ValueError

        return self.tokens[index]
