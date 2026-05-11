from .operator_base import BinOp


class Instruction_or(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}or {self.lhs}, {self.rhs}"


class Instruction_and(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}and {self.lhs}, {self.rhs}"


class Instruction_neq(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}neq {self.lhs}, {self.rhs}"


class Instruction_ieq(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}ieq {self.lhs}, {self.rhs}"


class Instruction_xor(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}xor {self.lhs}, {self.rhs}"
