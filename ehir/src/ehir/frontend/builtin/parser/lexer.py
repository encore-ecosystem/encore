import math
from dataclasses import dataclass, field

import ehir.frontend.builtin.parser.tokens as t
from ehir.format import ThemePalette, printfmt

TRACE_MAX_LINES_FOR_UNIT = 5


@dataclass
class Lexer:
    _tokens: list[t.Token] = field(default_factory=list)
    _program: str = ""
    _column: int = 0
    _line: int = 0
    _consumed: int = 0
    _string: str = ""
    _ignored: tuple[type[t.Token], ...] = (t.WHITESPACE, t.NEWLINE)

    def tokenize(self, source_code: str) -> list[t.Token]:
        self._tokens.clear()
        self._program = source_code
        self._column = 0
        self._line = 0
        self._consumed = 0
        self._string = ""
        unknown_tokens: list[t.Token] = []

        while not self._is_at_end():
            curr_char = self._consume()

            match curr_char:
                case " ":
                    self._append_token(t.WHITESPACE)
                case "\n":
                    self._append_token(t.NEWLINE)
                    self._line += 1
                    self._column = 0
                case '"':
                    self._parse_string()

                # Parenthesses
                case "(":
                    self._append_token(t.LEFT_PAREN)
                case ")":
                    self._append_token(t.RIGHT_PAREN)
                case "{":
                    self._append_token(t.LEFT_BRACE)
                case "}":
                    self._append_token(t.RIGHT_BRACE)
                case "[":
                    self._append_token(t.LEFT_BRACKET)
                case "]":
                    self._append_token(t.RIGHT_BRACKET)

                # Operators
                case "-":
                    if self._lookup_curr() == ">":
                        self._consume()
                        self._append_token(t.ARROW)
                    else:
                        self._append_token(t.MINUS)

                case "+":
                    self._append_token(t.PLUS)

                case "=":
                    if self._lookup_curr() == ">":
                        self._consume()
                        self._append_token(t.BOLD_ARROW)
                    else:
                        self._append_token(t.EQUAL)

                case "*":
                    self._append_token(t.STAR)

                case "<":
                    self._append_token(t.LESS)

                case ">":
                    self._append_token(t.GREATER)

                # Punctuation
                case "$":
                    self._append_token(t.DOLLAR)

                case ".":
                    self._append_token(t.DOT)

                case ",":
                    self._append_token(t.COMMA)

                case ":":
                    if self._lookup_curr() == ":":
                        self._consume()
                        self._append_token(t.DOUBLE_COLON)
                    else:
                        self._append_token(t.COLON)

                case ";":
                    self._append_token(t.SEMICOLON)

                case _:
                    if curr_char.isdigit():
                        self._parse_number()
                    elif curr_char.isidentifier():
                        self._parse_identifier()
                    else:
                        self._append_token(t.UNKNOWN)
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
        self._append_token(t.NUMBER)

    def _parse_string(self):
        while not self._is_at_end():
            curr_char = self._consume()
            if curr_char == "\\" and not self._is_at_end():
                self._consume()
                continue
            if curr_char == '"':
                break
        self._append_token(t.STRING)

    def _parse_identifier(self):
        while self._lookup_curr().isalnum() or self._lookup_curr() == "_":
            self._consume()

        match self._string:
            case "fn":
                self._append_token(t.FN)
            case "struct":
                self._append_token(t.STRUCT)
            case "enum":
                self._append_token(t.ENUM)
            case "trait":
                self._append_token(t.TRAIT)
            case "impl":
                self._append_token(t.IMPL)
            case "pub":
                self._append_token(t.PUB)
            case "imp":
                self._append_token(t.IMP)
            case "cimp":
                self._append_token(t.CIMP)
            case "extern":
                self._append_token(t.EXTERN)
            case "unsafe":
                self._append_token(t.UNSAFE)
            case "for":
                self._append_token(t.FOR)
            case "where":
                self._append_token(t.WHERE)
            case "ceoh":
                self._append_token(t.CEOH)
            case "ceos":
                self._append_token(t.CEOS)
            case "lceos":
                self._append_token(t.LCEOS)
            case "cpos":
                self._append_token(t.CPOS)
            case "cpoh":
                self._append_token(t.CPOH)
            case "csos":
                self._append_token(t.CSOS)
            case "csoh":
                self._append_token(t.CSOH)
            case "scpos":
                self._append_token(t.SCPOS)
            case "scpoh":
                self._append_token(t.SCPOH)
            case "scsos":
                self._append_token(t.SCSOS)
            case "scsoh":
                self._append_token(t.SCSOH)
            case "lcpos":
                self._append_token(t.LCPOS)
            case "lcsos":
                self._append_token(t.LCSOS)
            case "pcast":
                self._append_token(t.PCAST)
            case "getptr":
                self._append_token(t.GETPTR)
            case "getfield":
                self._append_token(t.GETFIELD)
            case "getfieldptr":
                self._append_token(t.GETFIELDPTR)
            case "sgetfield":
                self._append_token(t.SGETFIELD)
            case "sgetfieldptr":
                self._append_token(t.SGETFIELDPTR)
            case "call":
                self._append_token(t.CALL)
            case "br":
                self._append_token(t.BR)
            case "cbr":
                self._append_token(t.CBR)
            case "match":
                self._append_token(t.MATCH)
            case "switch":
                self._append_token(t.SWITCH)
            case "ret":
                self._append_token(t.RET)
            case "add":
                self._append_token(t.ADD)
            case "sub":
                self._append_token(t.SUB)
            case "mul":
                self._append_token(t.MUL)
            case "div":
                self._append_token(t.DIV)
            case "mod":
                self._append_token(t.MOD)
            case "shl":
                self._append_token(t.SHL)
            case "shr":
                self._append_token(t.SHR)
            case "and":
                self._append_token(t.AND)
            case "or":
                self._append_token(t.OR)
            case "xor":
                self._append_token(t.XOR)
            case "les":
                self._append_token(t.LES)
            case "leq":
                self._append_token(t.LEQ)
            case "grt":
                self._append_token(t.GRT)
            case "geq":
                self._append_token(t.GEQ)
            case "ieq":
                self._append_token(t.IEQ)
            case "neq":
                self._append_token(t.NEQ)
            case "phi":
                self._append_token(t.PHI)
            case "salloc":
                self._append_token(t.SALLOC)
            case "put":
                self._append_token(t.PUT)
            case "load":
                self._append_token(t.LOAD)
            case "store":
                self._append_token(t.STORE)
            case "halloc":
                self._append_token(t.HALLOC)
            case "hfree":
                self._append_token(t.HFREE)
            case _:
                self._append_token(t.IDENTIFIER)

    def _append_token(self, token_type: type[t.Token]):
        if token_type not in self._ignored:
            self._tokens.append(token_type(self._string, line=self._line, column=self._column - len(self._string)))
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

    def _trace_unexpected_token_error(self, token: t.Token):
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
