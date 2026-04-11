from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    INTEGER = auto()
    FLOAT = auto()
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
    KW_EXTERN = auto()
    KW_UNSAFE = auto()

    OP_SCOPE = auto()

    OP_PLUS = auto()
    OP_MINUS = auto()
    OP_MULTIPLY = auto()
    OP_DIVIDE = auto()
    OP_MODULO = auto()

    OP_EQUAL = auto()
    OP_NOT_EQUAL = auto()
    OP_LESS = auto()
    OP_GREATER = auto()
    OP_LESS_EQUAL = auto()
    OP_GREATER_EQUAL = auto()

    OP_AND = auto()
    OP_OR = auto()
    OP_NOT = auto()

    OP_BIT_AND = auto()
    OP_BIT_OR = auto()
    OP_BIT_XOR = auto()
    OP_BIT_NOT = auto()
    OP_LEFT_SHIFT = auto()
    OP_RIGHT_SHIFT = auto()

    OP_ASSIGN = auto()
    OP_PLUS_ASSIGN = auto()
    OP_MINUS_ASSIGN = auto()
    OP_MULT_ASSIGN = auto()
    OP_DIV_ASSIGN = auto()
    OP_MOD_ASSIGN = auto()
    OP_AND_ASSIGN = auto()
    OP_OR_ASSIGN = auto()
    OP_XOR_ASSIGN = auto()
    OP_LSHIFT_ASSIGN = auto()
    OP_RSHIFT_ASSIGN = auto()

    OP_INCREMENT = auto()
    OP_DECREMENT = auto()
    OP_TRY = auto()

    OP_ARROW = auto()
    OP_FAT_ARROW = auto()

    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
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
