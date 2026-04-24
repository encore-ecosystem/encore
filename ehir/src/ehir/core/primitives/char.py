from .base import Primitive, PrimitiveType


class Char_t(PrimitiveType):
    def __init__(self):
        super().__init__(name="char")


class Char(Primitive):
    val: str
    type: Char_t

    def __init__(self, val: str):
        if len(val) != 1:
            raise ValueError("char literal must contain exactly one character")
        super().__init__(type=Char_t())
        self.val = val

    def __str__(self) -> str:
        escaped = self.val.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
