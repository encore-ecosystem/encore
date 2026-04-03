from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class BinOp(Assignable):
    lhs: Variable
    rhs: Variable
