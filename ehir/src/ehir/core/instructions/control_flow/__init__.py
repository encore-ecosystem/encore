from .br import Instruction_br
from .call import Instruction_call
from .cbr import Instruction_cbr
from .match import Instruction_match, MatchCase
from .phi import Instruction_phi
from .ret import Instruction_ret
from .switch import Instruction_switch

__all__ = [
    "Instruction_br",
    "Instruction_cbr",
    "Instruction_match",
    "Instruction_ret",
    "Instruction_switch",
    "Instruction_phi",
    "Instruction_call",
    "MatchCase",
]
