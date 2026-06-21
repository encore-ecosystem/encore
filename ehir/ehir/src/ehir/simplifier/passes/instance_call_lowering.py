from copy import deepcopy

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_call, Instruction_callvoid
from ehir.core.type import Reference, Type
from ehir.core.variable import Variable
from ehir.simplifier.base import SimplifierPass
