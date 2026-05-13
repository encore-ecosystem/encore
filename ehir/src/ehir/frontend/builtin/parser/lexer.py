import math
from dataclasses import dataclass, field

from ehir.format import ThemePalette, printfmt
from ehir.frontend.builtin.parser.tokens import Token, TokenType

TRACE_MAX_LINES_FOR_UNIT = 5


@dataclass
class Lexer:
    _tokens: list[Token] = field(default_factory=list)
    _program: str = ""
    _column: int = 0
    _line: int = 0
    _consumed: int = 0
    _string: str = ""
    _ignored: tuple[TokenType, ...] = (TokenType.WHITESPACE, TokenType.NEWLINE)

    def tokenize(self, source_code: str) -> list[Token]:
        self._tokens.clear()
        self._program = source_code
        self._column = 0
        self._line = 0
        self._consumed = 0
        self._string = ""
        unknown_tokens: list[Token] = []

        while not self._is_at_end():
            curr_char = self._consume()

            match curr_char:
                case " ":
                    self._append_token(TokenType.WHITESPACE)
                case "\n":
                    self._append_token(TokenType.NEWLINE)
                    self._line += 1
                    self._column = 0
                case '"':
                    self._parse_string()
                case "'":
                    self._parse_char()

                # Parenthesses
                case "(":
                    self._append_token(TokenType.LEFT_PAREN)
                case ")":
                    self._append_token(TokenType.RIGHT_PAREN)
                case "{":
                    self._append_token(TokenType.LEFT_BRACE)
                case "}":
                    self._append_token(TokenType.RIGHT_BRACE)
                case "[":
                    self._append_token(TokenType.LEFT_BRACKET)
                case "]":
                    self._append_token(TokenType.RIGHT_BRACKET)

                # Operators
                case "-":
                    if self._lookup_curr() == ">":
                        self._consume()
                        self._append_token(TokenType.ARROW)
                    else:
                        self._append_token(TokenType.MINUS)

                case "+":
                    self._append_token(TokenType.PLUS)

                case "=":
                    if self._lookup_curr() == ">":
                        self._consume()
                        self._append_token(TokenType.BOLD_ARROW)
                    else:
                        self._append_token(TokenType.EQUAL)

                case "*":
                    self._append_token(TokenType.STAR)

                case "<":
                    self._append_token(TokenType.LESS)

                case ">":
                    self._append_token(TokenType.GREATER)

                # Punctuation
                case "$":
                    self._append_token(TokenType.DOLLAR)

                case "#":
                    self._append_token(TokenType.HASH)

                case ".":
                    self._append_token(TokenType.DOT)

                case ",":
                    self._append_token(TokenType.COMMA)

                case ":":
                    if self._lookup_curr() == ":":
                        self._consume()
                        self._append_token(TokenType.OP_SCOPE)
                    else:
                        self._append_token(TokenType.COLON)
                case "&":
                    self._append_token(TokenType.AMPERSAND)

                case ";":
                    # Treat ';' as a one-line comment marker in EHIR text dumps.
                    # Newline is intentionally not consumed here.
                    while not self._is_at_end() and self._lookup_curr() != "\n":
                        self._consume()
                    self._append_token(TokenType.WHITESPACE)

                case _:
                    if curr_char.isdigit():
                        self._parse_number()
                    elif curr_char.isidentifier():
                        self._parse_identifier()
                    else:
                        self._append_token(TokenType.UNKNOWN)
                        unknown_tokens.append(self._tokens.pop())

        if unknown_tokens:
            for token in unknown_tokens:
                self._trace_unexpected_token_error(token)
            exit(-1)

        return self._tokens

    def _parse_number(self):
        while self._lookup_curr().isdigit():
            self._consume()
        if self._lookup_curr() == "." and self._lookup_next().isdigit():
            self._consume()
            while self._lookup_curr().isdigit():
                self._consume()
        self._append_token(TokenType.NUMBER)

    def _parse_string(self):
        while not self._is_at_end():
            curr_char = self._consume()
            if curr_char == "\\" and not self._is_at_end():
                self._consume()
                continue
            if curr_char == '"':
                break
        self._append_token(TokenType.STRING)

    def _parse_char(self):
        while not self._is_at_end():
            curr_char = self._consume()
            if curr_char == "\\" and not self._is_at_end():
                self._consume()
                continue
            if curr_char == "'":
                break
        self._append_token(TokenType.CHAR)

    def _parse_identifier(self):
        while self._lookup_curr().isalnum() or self._lookup_curr() == "_":
            self._consume()

        match self._string:
            case "fn":
                self._append_token(TokenType.KW_FN)
            case "struct":
                self._append_token(TokenType.KW_STRUCT)
            case "enum":
                self._append_token(TokenType.KW_ENUM)
            case "trait":
                self._append_token(TokenType.KW_TRAIT)
            case "impl":
                self._append_token(TokenType.KW_IMPL)
            case "pub":
                self._append_token(TokenType.KW_PUB)
            case "imp":
                self._append_token(TokenType.KW_IMP)
            case "extern":
                self._append_token(TokenType.KW_EXTERN)
            case "unsafe":
                self._append_token(TokenType.KW_UNSAFE)
            case "for":
                self._append_token(TokenType.KW_FOR)
            case "where":
                self._append_token(TokenType.KW_WHERE)
            case "type":
                self._append_token(TokenType.KW_TYPE)
            case "capprim":
                self._append_token(TokenType.KW_CAPPRIM)
            case "capenum":
                self._append_token(TokenType.KW_CAPENUM)
            case "capstruct":
                self._append_token(TokenType.KW_CAPSTRUCT)
            case "wraps":
                self._append_token(TokenType.KW_WRAPS)
            case "wraph":
                self._append_token(TokenType.KW_WRAPH)
            case "pcast":
                self._append_token(TokenType.KW_PCAST)
            case "getptr":
                self._append_token(TokenType.KW_GETPTR)
            case "getfield":
                self._append_token(TokenType.KW_GETFIELD)
            case "getfieldptr":
                self._append_token(TokenType.KW_GETFIELDPTR)
            case "setfield":
                self._append_token(TokenType.KW_SETFIELD)
            case "gep":
                self._append_token(TokenType.KW_GEP)
            case "sgetfield":
                self._append_token(TokenType.KW_SGETFIELD)
            case "sgetfieldptr":
                self._append_token(TokenType.KW_SGETFIELDPTR)
            case "call":
                self._append_token(TokenType.KW_CALL)
            case "br":
                self._append_token(TokenType.KW_BR)
            case "cbr":
                self._append_token(TokenType.KW_CBR)
            case "match":
                self._append_token(TokenType.KW_MATCH)
            case "switch":
                self._append_token(TokenType.KW_SWITCH)
            case "ret":
                self._append_token(TokenType.KW_RET)
            case "add":
                self._append_token(TokenType.KW_ADD)
            case "sub":
                self._append_token(TokenType.KW_SUB)
            case "mul":
                self._append_token(TokenType.KW_MUL)
            case "div":
                self._append_token(TokenType.KW_DIV)
            case "mod":
                self._append_token(TokenType.KW_MOD)
            case "shl":
                self._append_token(TokenType.KW_SHL)
            case "shr":
                self._append_token(TokenType.KW_SHR)
            case "and":
                self._append_token(TokenType.KW_AND)
            case "or":
                self._append_token(TokenType.KW_OR)
            case "xor":
                self._append_token(TokenType.KW_XOR)
            case "les":
                self._append_token(TokenType.KW_LES)
            case "leq":
                self._append_token(TokenType.KW_LEQ)
            case "grt":
                self._append_token(TokenType.KW_GRT)
            case "geq":
                self._append_token(TokenType.KW_GEQ)
            case "ieq":
                self._append_token(TokenType.KW_IEQ)
            case "neq":
                self._append_token(TokenType.KW_NEQ)
            case "salloc":
                self._append_token(TokenType.KW_SALLOC)
            case "put":
                self._append_token(TokenType.KW_PUT)
            case "load":
                self._append_token(TokenType.KW_LOAD)
            case "store":
                self._append_token(TokenType.KW_STORE)
            case "halloc":
                self._append_token(TokenType.KW_HALLOC)
            case "hrealloc":
                self._append_token(TokenType.KW_HREALLOC)
            case "hfree":
                self._append_token(TokenType.KW_HFREE)
            case _:
                self._append_token(TokenType.IDENTIFIER)

    def _append_token(self, token_type: TokenType):
        if token_type not in self._ignored:
            self._tokens.append(
                Token(token_type, self._string, line=self._line, column=self._column - len(self._string))
            )
        self._string = ""

    def _lookup_curr(self) -> str:
        return "" if self._is_at_end(0) else self._program[self._consumed + 0]

    def _lookup_next(self) -> str:
        return "" if self._is_at_end(1) else self._program[self._consumed + 1]

    def _consume(self) -> str:
        current_char = self._program[self._consumed]
        self._string += current_char
        self._consumed += 1
        self._column += 1
        return current_char

    def _is_at_end(self, shift: int = 0) -> bool:
        return self._consumed + shift >= len(self._program)

    def _trace_unexpected_token_error(self, token: Token):
        lines = self._program.splitlines()

        num_trace_lines = min(len(lines), TRACE_MAX_LINES_FOR_UNIT)
        trace_start_index = max(0, token.line - math.floor(num_trace_lines / 2))
        trace_stop_index = min(len(lines), trace_start_index + math.ceil(num_trace_lines / 2) + 1)
        indexes = [i for i in range(trace_start_index, trace_stop_index)]
        max_index_len = max(len(str(i + 1)) for i in indexes)
        printfmt("╔" + f"{' Error Frame ':═^64}" + "╗\n", ThemePalette.ERROR_TEXT)
        for i in indexes:
            printfmt(f"{i + 1:>{max_index_len}}    ", ThemePalette.BACKGROUND_TEXT)
            line = lines[i]
            if i == token.line:
                # Colorize error token
                printfmt(f"{line[: token.column]}", ThemePalette.COMMON_TEXT)
                printfmt(f"{line[token.column : token.column + len(token.string)]}", ThemePalette.ERROR_TEXT)
                printfmt(f"{line[token.column + len(token.string) :]}\n", ThemePalette.COMMON_TEXT)

                # print error message
                printfmt(
                    " " * (4 + max_index_len + token.column) + "^\n",
                    ThemePalette.ERROR_TEXT,
                )
                printfmt(
                    f"  Error: Unexpected token '{token.string}' at line {token.line + 1}, column {token.column + 1}\n",
                    ThemePalette.ERROR_TEXT,
                )

            else:
                printfmt(f"{line}\n", ThemePalette.COMMON_TEXT)
        printfmt("\n")
