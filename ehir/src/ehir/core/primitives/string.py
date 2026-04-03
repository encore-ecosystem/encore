from .base import Primitive, PrimitiveType


class Str_t(PrimitiveType):
    def __init__(self):
        super().__init__(name="str")


class Str(Primitive):
    val: str
    type: Str_t

    def __init__(self, val: str):
        super().__init__(type=Str_t())
        self.val = val

    def __str__(self) -> str:
        escaped = self.val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"_{self.type}'
