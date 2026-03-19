import re
from typing import List

from .tokens import Token, TokenType


class Lexer:
    def __init__(self):
        self.keywords = {
            "fn": TokenType.KW_FN,
            "struct": TokenType.KW_STRUCT,
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
        }

        # Tokenization patterns (order matters!)
        self.patterns = [
            # Three-character operators
            (r"<<=", TokenType.OP_LSHIFT_ASSIGN),
            (r">>=", TokenType.OP_RSHIFT_ASSIGN),
            # Two-character operators (must come first!)
            (r"==", TokenType.OP_EQUAL),
            (r"!=", TokenType.OP_NOT_EQUAL),
            (r"<=", TokenType.OP_LESS_EQUAL),
            (r">=", TokenType.OP_GREATER_EQUAL),
            (r"->", TokenType.OP_ARROW),
            (r"&&", TokenType.OP_AND),
            (r"\|\|", TokenType.OP_OR),
            (r"<<", TokenType.OP_LEFT_SHIFT),
            (r">>", TokenType.OP_RIGHT_SHIFT),
            (r"\+=", TokenType.OP_PLUS_ASSIGN),
            (r"-=", TokenType.OP_MINUS_ASSIGN),
            (r"\*=", TokenType.OP_MULT_ASSIGN),
            (r"/=", TokenType.OP_DIV_ASSIGN),
            (r"%=", TokenType.OP_MOD_ASSIGN),
            (r"&=", TokenType.OP_AND_ASSIGN),
            (r"\|=", TokenType.OP_OR_ASSIGN),
            (r"\^=", TokenType.OP_XOR_ASSIGN),
            (r"\+\+", TokenType.OP_INCREMENT),
            (r"--", TokenType.OP_DECREMENT),
            # Single-character operators
            (r"\+", TokenType.OP_PLUS),
            (r"-", TokenType.OP_MINUS),
            (r"\*", TokenType.OP_MULTIPLY),
            (r"/", TokenType.OP_DIVIDE),
            (r"%", TokenType.OP_MODULO),
            (r"<", TokenType.OP_LESS),
            (r">", TokenType.OP_GREATER),
            (r"!", TokenType.OP_NOT),
            (r"=", TokenType.OP_ASSIGN),
            (r"&", TokenType.OP_BIT_AND),
            (r"\|", TokenType.OP_BIT_OR),
            (r"\^", TokenType.OP_BIT_XOR),
            (r"~", TokenType.OP_BIT_NOT),
            # Delimiters
            (r"\(", TokenType.LEFT_PAREN),
            (r"\)", TokenType.RIGHT_PAREN),
            (r"\{", TokenType.LEFT_BRACE),
            (r"\}", TokenType.RIGHT_BRACE),
            (r"\[", TokenType.LEFT_BRACKET),
            (r"\]", TokenType.RIGHT_BRACKET),
            (r":", TokenType.COLON),
            (r",", TokenType.COMMA),
            (r"\.", TokenType.DOT),
            # Literals
            (r"\d+\.\d+", TokenType.FLOAT),  # float (must come before integer!)
            (r"\d+", TokenType.INTEGER),  # integer
            (r"[a-zA-Z_][a-zA-Z0-9_]*", TokenType.IDENTIFIER),  # identifier
            (r"[ \t]+", TokenType.WHITESPACE),
            (r"\n", TokenType.NEWLINE),
        ]

        # Компилируем регулярные выражения
        self.compiled_patterns = [(re.compile(pattern), token_type) for pattern, token_type in self.patterns]

    def tokenize(self, text: str) -> List[Token]:
        tokens = []
        line = 1
        column = 1
        position = 0

        while position < len(text):
            matched = False

            for pattern, token_type in self.compiled_patterns:
                match = pattern.match(text, position)
                if match:
                    value = match.group(0)

                    if token_type == TokenType.IDENTIFIER and value in self.keywords:
                        token_type = self.keywords[value]

                    if token_type not in (TokenType.WHITESPACE, TokenType.NEWLINE):
                        tokens.append(Token(token_type, value, line, column))

                    if token_type == TokenType.NEWLINE:
                        line += 1
                        column = 1
                    else:
                        column += len(value)

                    position = match.end()
                    matched = True
                    break

            if not matched:
                tokens.append(Token(TokenType.UNKNOWN, text[position], line, column))
                position += 1
                column += 1

        return tokens
