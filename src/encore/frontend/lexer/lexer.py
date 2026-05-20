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
                    self._consume_and_push(TokenType.NEWLINE)

                case "+":
                    self._consume()
                    match self._peek_curr():
                        case "=":
                            self._consume_and_push(TokenType.PLUS_EQUAL)
                        case "+":
                            self._consume_and_push(TokenType.INCREMENT)
                        case _:
                            self._push_token(TokenType.PLUS)

                case "-":
                    self._consume()
                    match self._peek_curr():
                        case "=":
                            self._consume_and_push(TokenType.MINUS_EQUAL)
                        case ">":
                            self._consume_and_push(TokenType.ARROW)
                        case "-":
                            self._consume_and_push(TokenType.DECREMENT)
                        case _:
                            self._push_token(TokenType.MINUS)

                case "*":
                    self._consume()
                    self._consume_and_push(TokenType.ASTERISK_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.ASTERISK
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
                            self._consume_and_push(TokenType.SLASH_EQUAL)
                        case _:
                            self._push_token(TokenType.SLASH)

                case "%":
                    self._consume()
                    self._consume_and_push(TokenType.PERCENT_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.PERCENT
                    )

                case "<":
                    self._consume()
                    match self._peek_curr():
                        case "<":
                            self._consume()
                            if self._peek_curr() == "=":
                                self._consume_and_push(TokenType.LEFT_SHIFT_EQUAL)
                            else:
                                self._push_token(TokenType.LEFT_SHIFT)
                        case "=":
                            self._consume_and_push(TokenType.LESS_EQUAL)
                        case _:
                            self._push_token(TokenType.LESS)

                case ">":
                    self._consume()
                    match self._peek_curr():
                        case ">":
                            self._consume()
                            if self._peek_curr() == "=":
                                self._consume_and_push(TokenType.RIGHT_SHIFT_EQUAL)
                            else:
                                self._push_token(TokenType.RIGHT_SHIFT)
                        case "=":
                            self._consume_and_push(TokenType.GREATER_EQUAL)
                        case _:
                            self._push_token(TokenType.GREATER)

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
                    self._consume_and_push(TokenType.SCOPE) if self._peek_curr() == ":" else self._push_token(
                        TokenType.COLON
                    )
                case ".":
                    self._consume_and_push(TokenType.DOT)
                case ",":
                    self._consume_and_push(TokenType.COMMA)
                case ";":
                    self._consume_and_push(TokenType.SEMICOLON)
                case "=":
                    self._consume()
                    match self._peek_curr():
                        case "=":
                            self._consume_and_push(TokenType.EQUAL_EQUAL)
                        case ">":
                            self._consume_and_push(TokenType.FAT_ARROW)
                        case _:
                            self._push_token(TokenType.ASSIGN)

                case "!":
                    self._consume()
                    self._consume_and_push(TokenType.BANG_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.BANG
                    )

                case "&":
                    self._consume()
                    match self._peek_curr():
                        case "&":
                            self._consume_and_push(TokenType.AND_AND)
                        case "=":
                            self._consume_and_push(TokenType.AMPERSAND_EQUAL)
                        case _:
                            self._push_token(TokenType.AMPERSAND)

                case "|":
                    self._consume()
                    match self._peek_curr():
                        case "|":
                            self._consume_and_push(TokenType.PIPE_PIPE)
                        case "=":
                            self._consume_and_push(TokenType.PIPE_EQUAL)
                        case _:
                            self._push_token(TokenType.PIPE)

                case "^":
                    self._consume()
                    self._consume_and_push(TokenType.CARET_EQUAL) if self._peek_curr() == "=" else self._push_token(
                        TokenType.CARET
                    )

                case "~":
                    self._consume_and_push(TokenType.TILDE)

                case "?":
                    self._consume_and_push(TokenType.QUESTION)
                case "#":
                    self._consume_and_push(TokenType.HASH)

                case '"':
                    self._consume()
                    while not self._is_at_end():
                        if self._peek_curr() == "\\":
                            self._consume()
                            if self._is_at_end():
                                break
                            self._consume()
                            continue
                        if self._peek_curr() == '"':
                            break
                        self._consume()
                    if self._peek_curr() == '"':
                        self._consume_and_push(TokenType.STRING)
                    else:
                        self._push_token(TokenType.UNKNOWN)

                case "'":
                    self._consume_and_push(TokenType.QUOTE)

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
        is_float = False
        while self._peek_curr().isdigit():
            self._consume()
        if self._peek_curr() == "." and self._peek_next().isdigit():
            is_float = True
            self._consume()
            while self._peek_curr().isdigit():
                self._consume()
        self._push_token(TokenType.FLOAT if is_float else TokenType.INTEGER)

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
            "mut": TokenType.KW_MUT,
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
            "as": TokenType.KW_AS,
            "extern": TokenType.KW_EXTERN,
            "unsafe": TokenType.KW_UNSAFE,
            "ehir": TokenType.KW_EHIR,
            "async": TokenType.KW_ASYNC,
            "await": TokenType.KW_AWAIT,
            "not": TokenType.BANG,
            "true": TokenType.BOOLEAN,
            "false": TokenType.BOOLEAN,
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

    def _consume(self) -> str:
        token = super()._consume()
        if token == self._get_eof_token():
            return token
        if token == "\n":
            self._line += 1
            self._column = 0
        else:
            self._column += 1
        return token

    def _push_token(self, token_type: TokenType) -> int:
        match token_type:
            case TokenType.NEWLINE | TokenType.WHITESPACE | TokenType.ONE_LINE_COMMENT | TokenType.MULTI_LINE_COMMENT:
                self._drop()
                return 0
            case _:
                value = "".join(self._value)
                line = self._line
                column = self._column - len(value)
                lt = LexerToken(type=token_type, value=value, line=line, column=max(column, 0))
                self._push(lt)
                return len(lt.value)
