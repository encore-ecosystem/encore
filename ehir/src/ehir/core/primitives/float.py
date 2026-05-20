from .base import Primitive, PrimitiveType


class Float_t(PrimitiveType):
    ALLOWED_SIZES = {16, 32, 64, 128}
    size: int

    def __init__(self, size: int):
        if size not in self.ALLOWED_SIZES:
            raise ValueError(f"Unsupported float size: f{size}")
        super().__init__(name=f"f{size}")
        self.size = size


class Float(Primitive):
    val: float
    type: Float_t

    def __init__(self, val: float, size: int):
        super().__init__(type=Float_t(size=size))
        self.val = val

    def __str__(self) -> str:
        return f"{self.val}_{self.type}"
