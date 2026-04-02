from dataclasses import replace

from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type
from ehir.core.variable import Parameter

from encore.frontend.lexer import Token
from encore.frontend.lexer.tokens import TokenType
from encore.frontend.parser import statements as s
from encore.frontend.parser.statements import Statement_Import

ASSIGNMENT_OPERATORS: dict[TokenType, str] = {
    TokenType.OP_ASSIGN: "=",
    TokenType.OP_PLUS_ASSIGN: "+=",
    TokenType.OP_MINUS_ASSIGN: "-=",
    TokenType.OP_MULT_ASSIGN: "*=",
    TokenType.OP_DIV_ASSIGN: "/=",
    TokenType.OP_MOD_ASSIGN: "%=",
    TokenType.OP_AND_ASSIGN: "&=",
    TokenType.OP_OR_ASSIGN: "|=",
    TokenType.OP_XOR_ASSIGN: "^=",
    TokenType.OP_LSHIFT_ASSIGN: "<<=",
    TokenType.OP_RSHIFT_ASSIGN: ">>=",
}


class Parser:
    def parse(self, tokens: list[Token]) -> list[s.Statement]:
        self.tokens = tokens
        self.current_index = 0
        self._parsing_match_header = False
        self._current_loop_depth = 0

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
        elif curr_token.type == TokenType.KW_EXTERN:
            return self._parse_extern_function_definition(is_public)
        elif curr_token.type == TokenType.KW_STRUCT:
            return self._parse_struct_definition(is_public)
        elif curr_token.type == TokenType.KW_IMPORT:
            return self._parse_import(is_public)
        elif curr_token.type == TokenType.IDENTIFIER and curr_token.value == "cimp":
            return self._parse_cimport()
        elif curr_token.type == TokenType.KW_UNSAFE:
            return self._parse_unsafe_function_definition(is_public)
        elif curr_token.type == TokenType.KW_ENUM:
            return self._parse_enum(is_public)
        elif curr_token.type == TokenType.KW_TRAIT:
            return self._parse_trait(is_public)

        raise ValueError(f"Unable to parse top level statement: {curr_token}")

    def _parse_import(self, is_public: bool) -> s.Statement_Import:
        self._safe_consume(TokenType.KW_IMPORT)
        imp = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE)
        return s.Statement_Import(is_public=is_public, pair=imp)

    def _parse_cimport(self) -> s.Statement_Import:
        cimp_token = self._safe_consume(TokenType.IDENTIFIER)
        if cimp_token.value != "cimp":
            raise ValueError(f"Unexpected token: {cimp_token}, expected 'cimp'")
        imp = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE)
        return s.Statement_Import(is_public=True, pair=imp)

    def _parse_import_path(self, default_leaf_kind: s.Statement_Import.ImportKind) -> Statement_Import.ImportPair:
        module = self._safe_consume(TokenType.IDENTIFIER).value

        if self._is_at_end() or self._get_current_token().type != TokenType.OP_SCOPE:
            return Statement_Import.ImportPair(module, [], default_leaf_kind)

        self._safe_consume(TokenType.OP_SCOPE)
        if self._is_at_end():
            raise ValueError("Import path cannot end with ::")

        curr_token = self._get_current_token()
        match curr_token.type:
            case TokenType.OP_MULTIPLY:
                self._consume()
                if not self._is_at_end() and self._get_current_token().type == TokenType.OP_SCOPE:
                    raise TypeError("Wildcard '*' must be terminal in import path")
                return Statement_Import.ImportPair(
                    module,
                    [Statement_Import.ImportPair("*", [], s.Statement_Import.ImportKind.GLOB)],
                )
            case TokenType.LEFT_BRACE:
                self._safe_consume(TokenType.LEFT_BRACE)
                mods: list[Statement_Import.ImportPair] = []
                if self._get_current_token().type != TokenType.RIGHT_BRACE:
                    mods.append(self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE))
                    while self._get_current_token().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._get_current_token().type == TokenType.RIGHT_BRACE:
                            break
                        mods.append(self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.PACKAGE))
                self._safe_consume(TokenType.RIGHT_BRACE)
                return Statement_Import.ImportPair(module, mods)
            case TokenType.IDENTIFIER:
                nested = self._parse_import_path(default_leaf_kind=s.Statement_Import.ImportKind.SYMBOL)
                return Statement_Import.ImportPair(module, [nested])
            case _:
                raise ValueError(f"Unexpected Token: {curr_token}")

    def _parse_struct_definition(self, is_public: bool) -> s.Statement_StructureDefinition:
        self._safe_consume(TokenType.KW_STRUCT)
        definition = self._parse_raw_struct_definition()
        return s.Statement_StructureDefinition(is_public=is_public, defi=definition)

    def _parse_function_signature(
        self,
        require_return_type: bool,
        allow_self_param: bool = False,
        self_param_type: Type | None = None,
    ) -> tuple[str, list[Type], list[Parameter], Type | None]:
        self._safe_consume(TokenType.KW_FN)
        func_name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
        params: list[Parameter] = []

        self._safe_consume(TokenType.LEFT_PAREN)
        if self._get_current_token().type != TokenType.RIGHT_PAREN:
            params.append(self._parse_param(allow_self_param=allow_self_param, self_param_type=self_param_type))

        while self._get_current_token().type != TokenType.RIGHT_PAREN:
            self._safe_consume(TokenType.COMMA)
            params.append(self._parse_param(allow_self_param=allow_self_param, self_param_type=self_param_type))
        self._safe_consume(TokenType.RIGHT_PAREN)

        fn_type = None
        if self._get_current_token().type == TokenType.OP_ARROW:
            self._safe_consume(TokenType.OP_ARROW)
            fn_type = self._parse_type()
        elif require_return_type:
            raise TypeError(f"Function '{func_name}' must declare a return type")

        return func_name, generics, params, fn_type

    def _parse_function_definition(
        self, is_public: bool, allow_self_param: bool = False, self_param_type: Type | None = None
    ) -> s.Statement_FunctionDefinition:
        func_name, generics, params, fn_type = self._parse_function_signature(
            require_return_type=False,
            allow_self_param=allow_self_param,
            self_param_type=self_param_type,
        )
        body = self._parse_block(loop_depth=0)

        return s.Statement_FunctionDefinition(
            is_public=is_public,
            name=func_name,
            generics=generics,
            params=params,
            type=fn_type,
            body=body,
        )

    def _parse_extern_function_definition(self, is_public: bool) -> s.Statement_ExternFunctionDefinition:
        self._safe_consume(TokenType.KW_EXTERN)
        if self._get_current_token().type == TokenType.KW_UNSAFE:
            self._safe_consume(TokenType.KW_UNSAFE)
        func_name, generics, params, fn_type = self._parse_function_signature(require_return_type=True)
        assert fn_type is not None
        return s.Statement_ExternFunctionDefinition(
            is_public=is_public,
            name=func_name,
            generics=generics,
            params=params,
            type=fn_type,
        )

    def _parse_unsafe_function_definition(self, is_public: bool) -> s.Statement_FunctionDefinition:
        self._safe_consume(TokenType.KW_UNSAFE)
        return self._parse_function_definition(is_public=is_public)

    def _parse_trait(self, is_public: bool) -> s.Statement_Trait:
        self._safe_consume(TokenType.KW_TRAIT)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        body: list[s.TraitMethodDeclaration] = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            method_name, method_generics, params, method_type = self._parse_function_signature(
                require_return_type=True, allow_self_param=True, self_param_type=Type("Self")
            )
            assert method_type is not None
            body.append(
                s.TraitMethodDeclaration(
                    name=method_name,
                    generics=method_generics,
                    params=params,
                    type=method_type,
                )
            )
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Statement_Trait(is_public=is_public, name=name, generics=generics, body=body)

    def _parse_enum(self, is_public: bool) -> s.Statement_EnumDefinition:
        self._safe_consume(TokenType.KW_ENUM)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        # Enum body
        body = []
        self._safe_consume(TokenType.LEFT_BRACE)
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            body.append(self._parse_raw_struct_definition())
            if self._get_current_token().type == TokenType.COMMA:
                self._safe_consume(TokenType.COMMA)
                if self._get_current_token().type == TokenType.RIGHT_BRACE:
                    break
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
                    if self._get_current_token().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._get_current_token().type == TokenType.RIGHT_BRACE:
                            break
                self._safe_consume(TokenType.RIGHT_BRACE)
                return s.CLikeStructureDefinition(name=name, generics=generics, fields=fields)
            case TokenType.LEFT_PAREN:
                self._safe_consume(TokenType.LEFT_PAREN)
                fields: list[Type] = []
                while self._get_current_token().type != TokenType.RIGHT_PAREN:
                    fields.append(self._parse_type())
                    if self._get_current_token().type == TokenType.COMMA:
                        self._safe_consume(TokenType.COMMA)
                        if self._get_current_token().type == TokenType.RIGHT_PAREN:
                            break
                self._safe_consume(TokenType.RIGHT_PAREN)
                return s.TupleStructureDefinition(name=name, generics=generics, fields=fields)
            case _:
                return s.UnitStructureDefinition(name=name, generics=generics)

    def _parse_impl(self) -> s.Statement_Impl:
        self._safe_consume(TokenType.KW_IMPL)
        generics = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []

        trait_name = None
        trait_args: list[Type] = []
        if self._get_current_token().type != TokenType.KW_FOR:
            trait_name = self._safe_consume(TokenType.IDENTIFIER).value
            trait_args = self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
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
                body.append(self._parse_function_definition(is_public, allow_self_param=True, self_param_type=struct))
            self._safe_consume(TokenType.RIGHT_BRACE)

        return s.Statement_Impl(
            is_public=False,
            generics=generics,
            trait_name=trait_name,
            trait_args=trait_args,
            struct=struct,
            body=body,
        )

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

    def _parse_block(self, loop_depth: int = 0) -> list[s.Statement_InnerLevel]:
        prev_loop_depth = self._current_loop_depth
        self._current_loop_depth = loop_depth
        self._safe_consume(TokenType.LEFT_BRACE)
        statements: list[s.Statement_InnerLevel] = []
        try:
            while self._get_current_token().type != TokenType.RIGHT_BRACE:
                statements.append(self._parse_inner_level(loop_depth=loop_depth))
            self._safe_consume(TokenType.RIGHT_BRACE)
            return statements
        finally:
            self._current_loop_depth = prev_loop_depth

    def _parse_inner_level(self, loop_depth: int | None = None) -> s.Statement_InnerLevel:
        if loop_depth is None:
            loop_depth = self._current_loop_depth
        curr_token = self._get_current_token()

        if curr_token.type == TokenType.KW_RET:
            return self._parse_ret()
        if curr_token.type == TokenType.KW_LET:
            return self._parse_let()
        if curr_token.type == TokenType.KW_DO:
            return self._parse_do_while(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_WHILE:
            return self._parse_while(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_LOOP:
            return self._parse_loop(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_IF:
            return self._parse_if_block(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_MATCH:
            return self._parse_match(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_UNSAFE:
            return self._parse_unsafe_block(loop_depth=loop_depth)
        if curr_token.type == TokenType.KW_BREAK:
            if loop_depth <= 0:
                raise TypeError("'break' is only allowed inside loop bodies")
            return self._parse_break()
        if curr_token.type == TokenType.KW_CONTINUE:
            if loop_depth <= 0:
                raise TypeError("'continue' is only allowed inside loop bodies")
            return self._parse_continue()
        if curr_token.type == TokenType.IDENTIFIER:
            target = self._parse_expression()
            if self._is_assignment_operator(self._get_current_token().type):
                return self._parse_assignment(target)
            return s.Statement_Expr(target)

        raise NotImplementedError(curr_token)

    def _parse_ret(self) -> s.Statement_Ret:
        self._safe_consume(TokenType.KW_RET)
        expr = self._parse_expression()
        return s.Statement_Ret(expr=expr)

    def _parse_while(self, loop_depth: int = 0) -> s.Statement_While:
        self._safe_consume(TokenType.KW_WHILE)
        expr = self._parse_expression()
        body = self._parse_block(loop_depth=loop_depth + 1)
        return s.Statement_While(expr, body)

    def _parse_loop(self, loop_depth: int = 0) -> s.Statement_Loop:
        self._safe_consume(TokenType.KW_LOOP)
        body = self._parse_block(loop_depth=loop_depth + 1)
        return s.Statement_Loop(body)

    def _parse_break(self):
        self._safe_consume(TokenType.KW_BREAK)
        return s.Statement_Break()

    def _parse_continue(self):
        self._safe_consume(TokenType.KW_CONTINUE)
        return s.Statement_Continue()

    def _parse_do_while(self, loop_depth: int = 0) -> s.Statement_DoWhile:
        self._safe_consume(TokenType.KW_DO)
        body = self._parse_block(loop_depth=loop_depth + 1)
        self._safe_consume(TokenType.KW_WHILE)
        expr = self._parse_expression()
        return s.Statement_DoWhile(body, expr)

    def _parse_if_block(self, loop_depth: int = 0):
        self._safe_consume(TokenType.KW_IF)
        branches = [s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block(loop_depth=loop_depth))]

        while not self._is_at_end() and self._get_current_token().type == TokenType.KW_ELIF:
            self._safe_consume(TokenType.KW_ELIF)
            branches.append(
                s.Statement_IfBranch(expr=self._parse_expression(), body=self._parse_block(loop_depth=loop_depth))
            )

        else_body = None
        if not self._is_at_end() and self._get_current_token().type == TokenType.KW_ELSE:
            self._safe_consume(TokenType.KW_ELSE)
            else_body = self._parse_block(loop_depth=loop_depth)

        return s.Statement_If(branches=branches, else_body=else_body)

    def _parse_if_expression(self) -> s.Expression_If:
        self._safe_consume(TokenType.KW_IF)
        branches = [s.Expression_IfBranch(expr=self._parse_expression(), body=self._parse_expression_block())]

        while not self._is_at_end() and self._get_current_token().type == TokenType.KW_ELIF:
            self._safe_consume(TokenType.KW_ELIF)
            branches.append(s.Expression_IfBranch(expr=self._parse_expression(), body=self._parse_expression_block()))

        if self._is_at_end() or self._get_current_token().type != TokenType.KW_ELSE:
            raise TypeError("If expression must have an else branch")

        self._safe_consume(TokenType.KW_ELSE)
        else_body = self._parse_expression_block()
        return s.Expression_If(branches=branches, else_body=else_body)

    def _parse_match(self, loop_depth: int = 0) -> s.Statement_Match:
        self._safe_consume(TokenType.KW_MATCH)
        self._parsing_match_header = True
        expr = self._parse_expression()
        self._parsing_match_header = False
        self._safe_consume(TokenType.LEFT_BRACE)
        arms: list[s.Statement_MatchArm] = []
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            arms.append(self._parse_match_arm(loop_depth=loop_depth))
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Statement_Match(expr=expr, arms=arms)

    def _parse_match_arm(self, loop_depth: int = 0) -> s.Statement_MatchArm:
        pattern = None
        if self._get_current_token().type == TokenType.IDENTIFIER and self._get_current_token().value == "_":
            self._unsafe_consume()
        else:
            pattern = self._parse_path()
        binding = None
        if self._get_current_token().type == TokenType.LEFT_PAREN:
            self._safe_consume(TokenType.LEFT_PAREN)
            binding = self._safe_consume(TokenType.IDENTIFIER).value
            self._safe_consume(TokenType.RIGHT_PAREN)
        self._safe_consume(TokenType.OP_FAT_ARROW)
        body = self._parse_block(loop_depth=loop_depth)
        return s.Statement_MatchArm(pattern=pattern, binding=binding, body=body)

    def _parse_match_expression(self) -> s.Expression_Match:
        self._safe_consume(TokenType.KW_MATCH)
        self._parsing_match_header = True
        expr = self._parse_expression()
        self._parsing_match_header = False
        self._safe_consume(TokenType.LEFT_BRACE)
        arms: list[s.Expression_MatchArm] = []
        while self._get_current_token().type != TokenType.RIGHT_BRACE:
            arms.append(self._parse_match_expression_arm())
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Expression_Match(expr=expr, arms=arms)

    def _parse_unsafe_block(self, loop_depth: int = 0) -> s.Statement_Unsafe:
        self._safe_consume(TokenType.KW_UNSAFE)
        body = self._parse_block(loop_depth=loop_depth)
        return s.Statement_Unsafe(body=body)

    def _parse_unsafe_expression(self) -> s.Expression_Unsafe:
        self._safe_consume(TokenType.KW_UNSAFE)
        self._safe_consume(TokenType.LEFT_BRACE)
        body: list[s.Statement_InnerLevel] = []
        while self._starts_expression_block_statement():
            body.append(self._parse_inner_level())
        expr = self._parse_expression()
        self._safe_consume(TokenType.RIGHT_BRACE)
        return s.Expression_Unsafe(body=body, expr=expr)

    def _parse_match_expression_arm(self) -> s.Expression_MatchArm:
        pattern = None
        if self._get_current_token().type == TokenType.IDENTIFIER and self._get_current_token().value == "_":
            self._unsafe_consume()
        else:
            pattern = self._parse_path()
        binding = None
        if self._get_current_token().type == TokenType.LEFT_PAREN:
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
        expr = self._parse_primary()
        while not self._is_at_end():
            token = self._get_current_token()
            if token.type == TokenType.LEFT_PAREN:
                if not isinstance(expr, s.Expression_Path):
                    raise TypeError(f"Call target must be a path expression, got: {expr}")
                expr = self._parse_call(expr)
                continue
            if token.type == TokenType.DOT:
                expr = self._parse_dotted_postfix(expr)
                continue
            if token.type == TokenType.OP_TRY:
                self._unsafe_consume()
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
        return s.Expression_StringLiteral(self._unescape_string_literal(raw[1:-1]))

    def _parse_parenthesized(self) -> s.Expression_Parenthesized:
        self._safe_consume(TokenType.LEFT_PAREN)
        expr = self._parse_expression()
        self._safe_consume(TokenType.RIGHT_PAREN)
        return s.Expression_Parenthesized(expr=expr)

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

    def _parse_call_args(self) -> list[s.Statement_Expression]:
        self._safe_consume(TokenType.LEFT_PAREN)
        args: list[s.Statement_Expression] = []
        if self._get_current_token().type != TokenType.RIGHT_PAREN:
            args.append(self._parse_expression())
        while self._get_current_token().type != TokenType.RIGHT_PAREN:
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
        while not self._is_at_end() and self._get_current_token().type == TokenType.DOT:
            self._safe_consume(TokenType.DOT)
            member = self._safe_consume(TokenType.IDENTIFIER).value
            member_generics = (
                self._parse_generics_args() if self._get_current_token().type == TokenType.LEFT_BRACKET else []
            )

            if not self._is_at_end() and self._get_current_token().type == TokenType.LEFT_PAREN:
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
        while self._get_current_token().type == TokenType.OP_SCOPE:
            self._safe_consume(TokenType.OP_SCOPE)
            segments.append(self._parse_type())
        return s.Expression_Path(segments)

    def _parse_primary(self) -> s.Statement_Expression:
        curr_token = self._get_current_token()

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
            while self._get_current_token().type == TokenType.OP_SCOPE:
                self._safe_consume(TokenType.OP_SCOPE)
                segment = self._parse_type()
                segments.append(segment)
            path = s.Expression_Path(segments)

            if self._get_current_token().type == TokenType.LEFT_BRACE:
                if self._parsing_match_header:
                    return path
                return self._parse_struct_initialization(first)
            return path

        raise TypeError(f"Unable to parse primary expression, got: {curr_token}")

    def _parse_assignment(self, target: s.Statement_Expression) -> s.Statement_Assignment:
        curr_token = self._get_current_token()
        if not self._is_assignment_operator(curr_token.type):
            raise TypeError(f"Unexpected token: {curr_token}, expected assignment operator")
        self._consume()
        expr = self._parse_expression()
        return s.Statement_Assignment(target=target, expr=expr, operator=ASSIGNMENT_OPERATORS[curr_token.type])

    def _parse_let(self) -> s.Statement_Let:
        self._safe_consume(TokenType.KW_LET)
        name = self._safe_consume(TokenType.IDENTIFIER).value
        typ = None
        if self._get_current_token().type == TokenType.COLON:
            self._safe_consume(TokenType.COLON)
            typ = self._parse_type()
        self._safe_consume(TokenType.OP_ASSIGN)
        expr = self._parse_expression()
        return s.Statement_Let(
            name=name,
            type=typ,
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

    def _is_smart_pointer_suffix(self) -> bool:
        if self._get_current_token().type != TokenType.OP_LESS:
            return False
        try:
            pointer = self._peek_token(1)
            closer = self._peek_token(2)
        except ValueError:
            return False
        return (
            pointer.type == TokenType.IDENTIFIER and pointer.value in ("H", "S") and closer.type == TokenType.OP_GREATER
        )

    def _parse_param(self, allow_self_param: bool = False, self_param_type: Type | None = None) -> Parameter:
        curr = self._get_current_token()
        if allow_self_param and curr.type == TokenType.IDENTIFIER and curr.value == "mut" and not self._is_at_end():
            try:
                maybe_self = self._peek_token(1)
                maybe_delim = self._peek_token(2)
            except ValueError:
                maybe_self = None
                maybe_delim = None

            if (
                maybe_self is not None
                and maybe_delim is not None
                and maybe_self.type == TokenType.IDENTIFIER
                and maybe_self.value == "self"
                and maybe_delim.type in {TokenType.COMMA, TokenType.RIGHT_PAREN}
            ):
                self._safe_consume(TokenType.IDENTIFIER)  # mut
                self._safe_consume(TokenType.IDENTIFIER)  # self
                return Parameter("self", self_param_type or Type("Self"))

        name = self._safe_consume(TokenType.IDENTIFIER).value
        if (
            allow_self_param
            and curr.type == TokenType.IDENTIFIER
            and name == "self"
            and self._get_current_token().type in {TokenType.COMMA, TokenType.RIGHT_PAREN}
        ):
            return Parameter("self", self_param_type or Type("Self"))
        self._safe_consume(TokenType.COLON)
        type = self._parse_type()
        return Parameter(name, type)

    def _parse_numeric_literal_suffix(self) -> Type | None:
        if self._is_at_end():
            return None
        token = self._get_current_token()
        if token.type != TokenType.IDENTIFIER or not token.value.startswith("_"):
            return None

        suffix_name = token.value.removeprefix("_")
        if not self._is_numeric_type_name(suffix_name):
            return None

        self._unsafe_consume()
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

    def _starts_expression_block_statement(self) -> bool:
        if self._get_current_token().type in {
            TokenType.KW_LET,
            TokenType.KW_DO,
            TokenType.KW_WHILE,
            TokenType.KW_LOOP,
            TokenType.KW_RET,
            TokenType.KW_BREAK,
            TokenType.KW_CONTINUE,
        }:
            return True
        if self._get_current_token().type in {TokenType.KW_IF, TokenType.KW_MATCH, TokenType.KW_UNSAFE}:
            # These tokens can start either a statement or an expression.
            # Keep them as statements only if more tokens follow the parsed expression
            # before closing the current expression block.
            saved_index = self.current_index
            try:
                self._parse_expression()
                return not self._is_at_end() and self._get_current_token().type != TokenType.RIGHT_BRACE
            except Exception:
                return True
            finally:
                self.current_index = saved_index

        if self._get_current_token().type != TokenType.IDENTIFIER:
            return False

        saved_index = self.current_index
        try:
            self._parse_expression()
            return not self._is_at_end() and self._is_assignment_operator(self._get_current_token().type)
        except Exception:
            return False
        finally:
            self.current_index = saved_index

    @staticmethod
    def _is_assignment_operator(token_type: TokenType) -> bool:
        return token_type in ASSIGNMENT_OPERATORS

    def _is_at_end(self) -> bool:
        return self.current_index >= len(self.tokens)

    @staticmethod
    def _unescape_string_literal(string: str) -> str:
        return bytes(string, "utf-8").decode("unicode_escape")

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
