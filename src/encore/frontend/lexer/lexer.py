from encore.frontend.base import ParserBase

from .tokens import LexerToken, TokenType


class Lexer(ParserBase[str, LexerToken]):
    _line: int
    _column: int

    def _parse(self) -> list[LexerToken]:
        self._line = 0
        self._column = 0
        unknowns = []
        while not self._is_at_end():
            curr_char = self._peek_curr()
            match curr_char:
                case " ":
                    self._consume_and_push(TokenType.WHITESPACE)
                case "\n":
                    self._line += 1
                    self._column = 0
                    self._consume_and_push(TokenType.NEWLINE)

                case "+":
                    self._consume()
                    self._consume_and_push(TokenType.OP_PLUS_ASSIGN) if self._peek_curr() == "=" else self._push_token(
                        TokenType.OP_PLUS
                    )

                case "-":
                    self._consume()
                    match self._peek_curr():
                        case "=":
                            self._consume_and_push(TokenType.OP_MINUS_ASSIGN)
                        case ">":
                            self._consume_and_push(TokenType.OP_ARROW)
                        case _:
                            self._push_token(TokenType.OP_MINUS)
                case "*":
                    self._consume()
                    self._consume_and_push(TokenType.OP_MULT_ASSIGN) if self._peek_curr() == "=" else self._push_token(
                        TokenType.OP_MULTIPLY
                    )

                case "/":
                    self._consume()
                    match self._peek_curr():
                        case "/":  # one-line comment
                            self._consume()
                            while self._peek_curr() != "\n":
                                self._consume()
                            self._push_token(TokenType.ONE_LINE_COMMENT)
                        case "*":  # multi-line comment
                            self._consume()
                            while self._peek_curr() != "*" and self._peek_next() != "/":
                                self._consume()
                            self._consume()
                            self._consume_and_push(TokenType.MULTI_LINE_COMMENT)
                        case "=":  # div equal
                            self._consume()
                            self._consume_and_push(TokenType.OP_DIV_ASSIGN)
                        case _:
                            self._consume_and_push(TokenType.OP_DIVIDE)

                case "<":
                    self._consume()
                    self._consume_and_push(TokenType.OP_LESS_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.OP_LESS
                    )

                case ">":
                    self._consume()
                    self._consume_and_push(
                        TokenType.OP_GREATER_EQUAL
                    ) if self._peek_curr() == "=" else self._push_token(TokenType.OP_GREATER)

                case "(":
                    self._consume_and_push(TokenType.LEFT_PAREN)
                case ")":
                    self._consume_and_push(TokenType.RIGHT_PAREN)
                case "[":
                    self._consume_and_push(TokenType.LEFT_BRACKET)
                case "]":
                    self._consume_and_push(TokenType.RIGHT_BRACKET)
                case "{":
                    self._consume_and_push(TokenType.LEFT_BRACE)
                case "}":
                    self._consume_and_push(TokenType.RIGHT_BRACE)
                case ":":
                    self._consume()
                    self._consume_and_push(TokenType.OP_SCOPE) if self._peek_curr() == ":" else self._push_token(
                        TokenType.COLON
                    )
                case ".":
                    self._consume_and_push(TokenType.DOT)
                case ",":
                    self._consume_and_push(TokenType.COMMA)
                case "=":
                    self._consume()
                    match self._peek_curr():
                        case "=":
                            self._consume_and_push(TokenType.OP_EQUAL)
                        case ">":
                            self._consume_and_push(TokenType.OP_FAT_ARROW)
                        case _:
                            self._push_token(TokenType.OP_ASSIGN)

                case "!":
                    self._consume()
                    self._consume_and_push(TokenType.OP_NOT_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.OP_NOT
                    )

                case '"':
                    self._consume()
                    while self._peek_curr() != '"':
                        self._consume()
                    self._consume_and_push(TokenType.STRING)

                case _:
                    if curr_char.isdigit():
                        self._parse_number()
                    elif curr_char.isidentifier():
                        self._parse_identifier()
                    else:
                        self._consume()
                        self._push_token(TokenType.UNKNOWN)
                        unknowns.append(self._result.pop())
        assert len(unknowns) == 0, unknowns
        return self._result

    def _parse_number(self):
        while self._peek_curr().isdigit():
            self._consume()
        if self._peek_curr() == "." and self._peek_next().isdigit():
            self._consume()
            while self._peek_curr().isdigit():
                self._consume()
        self._push_token(TokenType.INTEGER)

    def _parse_identifier(self):
        while self._peek_curr().isalnum() or self._peek_curr() == "_":
            self._consume()

        keywords = {
            "fn": TokenType.KW_FN,
            "struct": TokenType.KW_STRUCT,
            "enum": TokenType.KW_ENUM,
            "trait": TokenType.KW_TRAIT,
            "impl": TokenType.KW_IMPL,
            "for": TokenType.KW_FOR,
            "let": TokenType.KW_LET,
            "ret": TokenType.KW_RET,
            "while": TokenType.KW_WHILE,
            "do": TokenType.KW_DO,
            "break": TokenType.KW_BREAK,
            "continue": TokenType.KW_CONTINUE,
            "loop": TokenType.KW_LOOP,
            "if": TokenType.KW_IF,
            "elif": TokenType.KW_ELIF,
            "else": TokenType.KW_ELSE,
            "match": TokenType.KW_MATCH,
            "pub": TokenType.KW_PUB,
            "import": TokenType.KW_IMPORT,
            "extern": TokenType.KW_EXTERN,
            "unsafe": TokenType.KW_UNSAFE,
            "not": TokenType.OP_NOT,
        }

        token_type = TokenType.IDENTIFIER
        if tt := keywords.get("".join(self._value)):
            token_type = tt
        self._push_token(token_type)

    def _get_eof_token(self) -> str:
        return ""

    def _consume_and_push(self, token_type: TokenType):
        self._consume()
        self._push_token(token_type)

    def _push_token(self, token_type: TokenType) -> int:
        match token_type:
            case TokenType.NEWLINE | TokenType.WHITESPACE:
                self._drop()
                return 0
            case _:
                lt = LexerToken(type=token_type, value="".join(self._value), line=self._line, column=self._column)
                self._push(lt)
                return len(lt.value)
