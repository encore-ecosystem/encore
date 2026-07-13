from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class BinOp(Assignable):
    lhs: Variable
    rhs: Variable


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
