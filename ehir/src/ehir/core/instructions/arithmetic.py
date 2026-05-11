from .operator_base import BinOp


class Instruction_add(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}add {self.lhs}, {self.rhs}"


class Instruction_sub(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}sub {self.lhs}, {self.rhs}"


class Instruction_mul(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}mul {self.lhs}, {self.rhs}"


class Instruction_div(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}div {self.lhs}, {self.rhs}"


class Instruction_mod(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}mod {self.lhs}, {self.rhs}"


class Instruction_shl(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}shl {self.lhs}, {self.rhs}"


class Instruction_shr(BinOp):
    def __str__(self) -> str:
        return f"{super().__str__()}shr {self.lhs}, {self.rhs}"
