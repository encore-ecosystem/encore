from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    INTEGER = auto()
    FLOAT = auto()
    BOOLEAN = auto()
    STRING = auto()
    IDENTIFIER = auto()

    ONE_LINE_COMMENT = auto()
    MULTI_LINE_COMMENT = auto()

    KW_FN = auto()
    KW_STRUCT = auto()
    KW_TRAIT = auto()
    KW_ENUM = auto()
    KW_IMPL = auto()
    KW_FOR = auto()
    KW_LET = auto()
    KW_MUT = auto()
    KW_RET = auto()
    KW_WHILE = auto()
    KW_LOOP = auto()
    KW_DO = auto()
    KW_CONTINUE = auto()
    KW_BREAK = auto()
    KW_IF = auto()
    KW_ELIF = auto()
    KW_ELSE = auto()
    KW_MATCH = auto()
    KW_PUB = auto()
    KW_IMPORT = auto()
    KW_AS = auto()
    KW_EXTERN = auto()
    KW_UNSAFE = auto()
    KW_EHIR = auto()

    SCOPE = auto()

    PLUS = auto()
    MINUS = auto()
    ASTERISK = auto()
    SLASH = auto()
    PERCENT = auto()

    EQUAL_EQUAL = auto()
    BANG_EQUAL = auto()
    LESS = auto()
    GREATER = auto()
    LESS_EQUAL = auto()
    GREATER_EQUAL = auto()

    AND_AND = auto()
    PIPE_PIPE = auto()
    BANG = auto()

    AMPERSAND = auto()
    PIPE = auto()
    CARET = auto()
    TILDE = auto()
    LEFT_SHIFT = auto()
    RIGHT_SHIFT = auto()

    ASSIGN = auto()
    PLUS_EQUAL = auto()
    MINUS_EQUAL = auto()
    ASTERISK_EQUAL = auto()
    SLASH_EQUAL = auto()
    PERCENT_EQUAL = auto()
    AMPERSAND_EQUAL = auto()
    PIPE_EQUAL = auto()
    CARET_EQUAL = auto()
    LEFT_SHIFT_EQUAL = auto()
    RIGHT_SHIFT_EQUAL = auto()

    INCREMENT = auto()
    DECREMENT = auto()
    QUESTION = auto()

    ARROW = auto()
    FAT_ARROW = auto()

    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    SEMICOLON = auto()
    COLON = auto()
    COMMA = auto()
    DOT = auto()
    QUOTE = auto()

    WHITESPACE = auto()
    NEWLINE = auto()
    EOF = auto()
    UNKNOWN = auto()


@dataclass
class LexerToken:
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self) -> str:
        return f"{self.line}:{self.column}({self.type.name}: {self.value})"
