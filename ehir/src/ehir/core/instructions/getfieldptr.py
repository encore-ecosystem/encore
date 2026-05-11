from dataclasses import dataclass
from dataclasses import field as dataclass_field

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class Instruction_getfieldptr(Assignable):
    field: Variable
    field_path: list[Variable] = dataclass_field(default_factory=list)

    def __str__(self) -> str:
        field_repr = "::".join(str(field) for field in [self.field, *self.field_path])
        return f"{super().__str__()}getfieldptr {field_repr}"
