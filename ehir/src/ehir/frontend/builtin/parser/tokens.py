from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    # Generic
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    CHAR = auto()

    UNKNOWN = auto()
    EOF = auto()

    # Multi-char operators
    ARROW = auto()  # ->
    BOLD_ARROW = auto()  # =>
    OP_SCOPE = auto()  # ::

    # Symbols
    AMPERSAND = auto()

    # Keywords
    KW_FN = auto()
    KW_STRUCT = auto()
    KW_ENUM = auto()
    KW_TRAIT = auto()
    KW_IMPL = auto()
    KW_PUB = auto()
    KW_IMP = auto()
    KW_EXTERN = auto()
    KW_UNSAFE = auto()
    KW_FOR = auto()
    KW_WHERE = auto()
    KW_TYPE = auto()

    # IR / Instructions
    KW_CAPPRIM = auto()
    KW_CAPENUM = auto()
    KW_CAPSTRUCT = auto()
    KW_WRAPS = auto()
    KW_WRAPH = auto()
    KW_GETPTR = auto()
    KW_GETFIELD = auto()
    KW_GETFIELDPTR = auto()
    KW_SETFIELD = auto()
    KW_GEP = auto()

    KW_SGETFIELD = auto()
    KW_SGETFIELDPTR = auto()

    KW_PCAST = auto()

    KW_BR = auto()
    KW_CBR = auto()
    KW_MATCH = auto()
    KW_SWITCH = auto()
    KW_RET = auto()
    KW_CALL = auto()

    KW_ADD = auto()
    KW_SUB = auto()
    KW_MUL = auto()
    KW_DIV = auto()
    KW_MOD = auto()

    KW_SHL = auto()
    KW_SHR = auto()

    KW_LES = auto()
    KW_LEQ = auto()
    KW_GRT = auto()
    KW_GEQ = auto()
    KW_IEQ = auto()
    KW_NEQ = auto()

    KW_AND = auto()
    KW_OR = auto()
    KW_XOR = auto()

    KW_SALLOC = auto()
    KW_HALLOC = auto()
    KW_HREALLOC = auto()

    KW_PUT = auto()
    KW_LOAD = auto()
    KW_STORE = auto()
    KW_HFREE = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    EQUAL = auto()
    STAR = auto()
    LESS = auto()
    GREATER = auto()

    # Punctuation
    COMMA = auto()
    SEMICOLON = auto()
    COLON = auto()
    DOT = auto()
    DOLLAR = auto()
    HASH = auto()

    # Delimiters
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()

    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()

    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()

    # Whitespace
    WHITESPACE = auto()
    NEWLINE = auto()
    TAB = auto()


@dataclass(slots=True)
class Token:
    type: TokenType
    value: str
    line: int
    column: int

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TokenType):
            return self.type == other
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.line}:{self.column}({self.type.name}: {self.value})"
