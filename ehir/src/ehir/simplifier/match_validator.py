from ehir.core.derectives import Derective_enum, Derective_fn
from ehir.core.derectives.base import Derective
from ehir.core.enum import TupleLikeVariant, UnitLikeVariant
from ehir.core.instructions import Instruction_match
from ehir.errors import EhirCompileError


class MatchValidatorPass:
    def run(self, ast: list[Derective]) -> list[Derective]:
        enums = {directive.name: directive for directive in ast if isinstance(directive, Derective_enum)}
        for directive in ast:
            if not isinstance(directive, Derective_fn):
                continue
            for block in directive.body:
                for instr in block.get_body():
                    if not isinstance(instr, Instruction_match):
                        continue
                    cond_type = instr.cond_var.type
                    if cond_type is None:
                        continue
                    enum_decl = enums.get(cond_type.name)
                    if enum_decl is None:
                        continue

                    variant_by_name = {variant.name: variant for variant in enum_decl.variants}
                    variant_names = set(variant_by_name)
                    seen: set[str] = set()
                    for case in instr.cases:
                        if case.variant not in variant_names:
                            raise EhirCompileError(
                                f"Unknown match variant '{case.variant}' for enum '{enum_decl.name}' "
                                f"in fn '{directive.name}' block '{block.name}'",
                                code="EHIR2001",
                            )
                        variant_decl = variant_by_name[case.variant]
                        if isinstance(variant_decl, UnitLikeVariant) and case.payload_var is not None:
                            raise EhirCompileError(
                                f"Match variant '{case.variant}' of enum '{enum_decl.name}' does not carry payload "
                                f"but payload variable was provided in fn '{directive.name}' block '{block.name}'",
                                code="EHIR2002",
                            )
                        if isinstance(variant_decl, TupleLikeVariant):
                            if len(variant_decl.types) == 0 and case.payload_var is not None:
                                raise EhirCompileError(
                                    f"Match variant '{case.variant}' of enum '{enum_decl.name}' has empty tuple payload "
                                    f"but payload variable was provided in fn '{directive.name}' block '{block.name}'",
                                    code="EHIR2003",
                                )
                            if len(variant_decl.types) > 1 and case.payload_var is not None:
                                raise EhirCompileError(
                                    f"Match variant '{case.variant}' of enum '{enum_decl.name}' has multiple payload fields; "
                                    f"single payload binding is ambiguous in fn '{directive.name}' block '{block.name}'",
                                    code="EHIR2004",
                                )
                        if case.variant in seen:
                            raise EhirCompileError(
                                f"Duplicate match variant '{case.variant}' for enum '{enum_decl.name}' "
                                f"in fn '{directive.name}' block '{block.name}'",
                                code="EHIR2005",
                            )
                        seen.add(case.variant)

                    if seen == variant_names:
                        raise EhirCompileError(
                            f"Unreachable match default branch for enum '{enum_decl.name}' "
                            f"in fn '{directive.name}' block '{block.name}'",
                            code="EHIR2006",
                        )
        return ast
