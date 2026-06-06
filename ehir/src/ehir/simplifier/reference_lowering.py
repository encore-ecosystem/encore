from copy import deepcopy
from dataclasses import fields, is_dataclass

from ehir.core.derectives import Derective_extern_fn, Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.instructions import Instruction_getfield, Instruction_getfieldptr, Instruction_load, Instruction_setfield
from ehir.core.type import Pointer, Reference, Type, box_pointee, is_box_type
from ehir.core.variable import Parameter, TypedVariable, Variable


class ReferenceLoweringPass:
    _BOX_STORAGE_FIELDS = {"ptr", "owner", "0", "1"}

    def run(self, ast: list[Derective]) -> list[Derective]:
        self._rewrite_reference_types(ast)
        for directive in ast:
            if isinstance(directive, (Derective_fn, Derective_extern_fn)):
                directive.params = [Parameter(name=p.name, type=self._lower_type(p.type)) for p in directive.params]
                directive.ret_type = self._lower_type(directive.ret_type)
                if isinstance(directive, Derective_fn):
                    self._lower_reference_field_access(directive)
        return ast

    def _lower_reference_field_access(self, fn: Derective_fn) -> None:
        for block in fn.body:
            new_body = []
            for instr in block.body:
                if isinstance(instr, Instruction_getfield) and instr.src.type is not None and is_box_type(instr.src.type):
                    if instr.field.name not in self._BOX_STORAGE_FIELDS:
                        pointee = box_pointee(instr.src.type)
                        prelude, payload_ptr = self._lower_box_payload_pointer(
                            instr.src,
                            seed=instr.var_out.name,
                            pointee=pointee,
                        )
                        new_body.extend(prelude)
                        new_body.append(
                            Instruction_getfield(
                                var_out=instr.var_out,
                                src=payload_ptr,
                                field=instr.field,
                                field_path=list(instr.field_path),
                            )
                        )
                        continue
                if isinstance(instr, Instruction_setfield) and instr.var.type is not None and is_box_type(instr.var.type):
                    if instr.field.name not in self._BOX_STORAGE_FIELDS:
                        pointee = box_pointee(instr.var.type)
                        prelude, payload_ptr = self._lower_box_payload_pointer(
                            instr.var,
                            seed=instr.var.name,
                            pointee=pointee,
                        )
                        new_body.extend(prelude)
                        new_body.append(
                            Instruction_setfield(
                                var=payload_ptr,
                                field=instr.field,
                                value=instr.value,
                                field_path=list(instr.field_path),
                            )
                        )
                        continue
                new_body.append(instr)
            block.body = new_body

    def _lower_box_payload_pointer(
        self,
        box_var: TypedVariable | Variable,
        *,
        seed: str,
        pointee: Type,
    ) -> tuple[list[Instruction_getfieldptr | Instruction_load], TypedVariable]:
        ptr_type = Pointer(deepcopy(pointee))
        ptr_field = TypedVariable(name=f".{seed}_box_ptr_field", type=Pointer(ptr_type))
        payload_ptr = TypedVariable(name=f".{seed}_box_ptr", type=ptr_type)
        return (
            [
                Instruction_getfieldptr(
                    var_out=ptr_field,
                    src=deepcopy(box_var),
                    field=TypedVariable(name="0", type=ptr_type),
                ),
                Instruction_load(var_out=payload_ptr, var=ptr_field),
            ],
            payload_ptr,
        )

    def _lower_type(self, typ: Type) -> Type:
        if isinstance(typ, Reference):
            return Type("Box", [self._lower_type(typ.pointee)])
        if isinstance(typ, Pointer):
            return Pointer(self._lower_type(typ.pointee))
        if not typ.generics:
            return Type(typ.name)
        return Type(typ.name, [self._lower_type(g) for g in typ.generics])

    def _rewrite_reference_types(self, value):
        if isinstance(value, Type):
            return self._lower_type(value)
        if isinstance(value, Variable):
            if value.type is not None:
                value.type = self._lower_type(value.type)
            return value
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = self._rewrite_reference_types(item)
            return value
        if not is_dataclass(value):
            return value
        for f in fields(value):
            setattr(value, f.name, self._rewrite_reference_types(getattr(value, f.name)))
        return value
