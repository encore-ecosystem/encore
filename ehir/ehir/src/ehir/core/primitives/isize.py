from .base import Primitive, PrimitiveType


class Isize_t(PrimitiveType):
    size: int | None

    def __init__(self, size: int | None = None):
        if size is not None:
            assert size > 0
        super().__init__(name="isize" if size is None else f"i{size}")
        self.size = size


class Isize(Primitive):
    val: int
    type: Isize_t

    def __init__(self, val: int, size: int | None = None):
        super().__init__(type=Isize_t(size=size))
        self.val = val

    def __str__(self) -> str:
        return f"{self.val}_{self.type}"
