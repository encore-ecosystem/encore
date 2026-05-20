from abc import ABC
from dataclasses import dataclass

from ehir.core.derectives import Derective_extern_fn
from ehir.core.derectives.base import Derective
from ehir.core.type import Type
from ehir.core.variable import Parameter
from ehir.postprocessor.special import ProcessedBlock


@dataclass
class ProcessedDerective(ABC, Derective): ...


@dataclass
class ProcessedDerective_extern_fn(ProcessedDerective, Derective_extern_fn):
    def __repr__(self) -> str:
        params_repr = ", ".join(str(p) for p in self.params)
        return f"extern fn {self.name}({params_repr}) -> {self.ret_type}"


@dataclass
class ProcessedDerective_fn(ProcessedDerective):
    name: str
    params: list[Parameter]
    ret_type: Type
    entry_block: ProcessedBlock
    body: list[ProcessedBlock]
    exit_block: ProcessedBlock

    def get_body(self) -> list[ProcessedBlock]:
        return [self.entry_block, *self.body, self.exit_block]

    def __str__(self) -> str:
        params_repr = ", ".join(str(p) for p in self.params)
        body_repr = "\n".join("\n".join(f"  {line}" for line in str(b).splitlines()) for b in self.get_body())
        return f"fn {self.name}({params_repr}) -> {self.ret_type}" + " {\n" + body_repr + "\n}"

    def __repr__(self) -> str:
        return self.__str__()


@dataclass
class ProcessedDerective_struct(ProcessedDerective):
    name: str
    fields: list[Parameter]

    def __repr__(self) -> str:
        fields_repr = "\n  ".join(str(field) for field in self.fields)
        return f"struct {self.name} {{\n  {fields_repr}\n}}"
