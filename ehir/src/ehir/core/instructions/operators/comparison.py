from .base import BinOp


class Instruction_les(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}les {self.lhs}, {self.rhs}"


class Instruction_leq(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}leq {self.lhs}, {self.rhs}"


class Instruction_grt(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}grt {self.lhs}, {self.rhs}"


class Instruction_geq(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}geq {self.lhs}, {self.rhs}"
