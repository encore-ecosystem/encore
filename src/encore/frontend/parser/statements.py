from abc import ABC
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Optional

from ehir.core.instructions.base import Instruction
from ehir.core.type import Type
from ehir.core.variable import Parameter


@dataclass
class Statement:
    pass


@dataclass
class GenericParam(Type):
    bounds: list[Type] = field(default_factory=list)

    def format_declaration(self) -> str:
        if not self.bounds:
            return self.name
        return f"{self.name}:{'+'.join(str(bound) for bound in self.bounds)}"


def format_generic_params(generics: list[Type]) -> str:
    if not generics:
        return ""

    items: list[str] = []
    for generic in generics:
        if isinstance(generic, GenericParam):
            items.append(generic.format_declaration())
        else:
            items.append(str(generic))
    return "[" + ", ".join(items) + "]"


# =============
@dataclass
class Statement_TopLevel(Statement):
    is_public: bool

    def __repr__(self) -> str:
        return "pub " if self.is_public else ""


@dataclass
class Statement_Import(Statement_TopLevel):
    class ImportKind(StrEnum):
        PACKAGE = auto()
        SYMBOL = auto()
        GLOB = auto()

    @dataclass
    class ImportPair:
        src: str
        dst: list["Statement_Import.ImportPair"]
        kind: "Statement_Import.ImportKind | None" = None
        alias: str | None = None

        def __post_init__(self):
            if self.kind is None:
                self.kind = Statement_Import.ImportKind.SYMBOL

        def __repr__(self) -> str:
            match len(self.dst):
                case 0:
                    base = "*" if self.kind == Statement_Import.ImportKind.GLOB else self.src
                case 1:
                    base = f"{self.src}::{self.dst[0]}"
                case _:
                    dst_repr = f"{{ {', '.join(x.__repr__() for x in self.dst)} }}"
                    base = f"{self.src}::{dst_repr}"

            if self.alias is not None:
                return f"{base} as {self.alias}"
            return base

    pair: ImportPair

    def __repr__(self) -> str:
        pair_repr = self.pair.__repr__()
        return f"{super().__repr__()}import {pair_repr}"


@dataclass
class FunctionSignature(Statement_TopLevel):
    is_extern: bool
    name: str
    generics: list[Type]
    params: list[Parameter]
    type: Type | None

    def __repr__(self) -> str:
        extern_repr = "extern " if self.is_extern else ""
        generics_repr = format_generic_params(self.generics)
        type_repr = f"-> {self.type}" if self.type else ""
        return f"{extern_repr}fn {self.name}{generics_repr}({', '.join(str(p) for p in self.params)}){type_repr}"


@dataclass
class Statement_FunctionDefinition(Statement_TopLevel):
    signature: FunctionSignature
    body: "Block"

    @property
    def name(self) -> str:
        return self.signature.name

    @property
    def generics(self) -> list[Type]:
        return self.signature.generics

    @property
    def params(self) -> list[Parameter]:
        return self.signature.params

    @property
    def type(self) -> Type | None:
        return self.signature.type

    def __repr__(self) -> str:
        return f"{self.signature} {self.body}"


@dataclass
class Statement_Trait(Statement_TopLevel):
    name: str
    generics: list[Type]
    body: list[FunctionSignature]
    bases: list[Type] = field(default_factory=list)

    def __repr__(self) -> str:
        generics_repr = format_generic_params(self.generics)
        bases_repr = f" < {', '.join(str(base) for base in self.bases)}" if self.bases else ""
        body_repr = " {\n" + "\n".join(f"  {method}" for method in self.body) + "\n}"
        return f"{super().__repr__()}trait {self.name}{generics_repr}{bases_repr}{body_repr}"


@dataclass
class StructureSignature(ABC):
    name: str
    generics: list[Type]

    def __repr__(self) -> str:
        generic_repr = format_generic_params(self.generics)
        return f"{self.name}{generic_repr}"


@dataclass
class CLikeStructureDefinition(StructureSignature):
    fields: list[Parameter]

    def __repr__(self) -> str:
        body_repr = " {\n" + "\n".join(f"  {b}" for b in self.fields) + "\n}"
        return f"{super().__repr__()}{body_repr}"


@dataclass
class TupleStructureDefinition(StructureSignature):
    fields: list[Type]

    def _to_clike(self) -> CLikeStructureDefinition:
        return CLikeStructureDefinition(
            name=self.name, generics=self.generics, fields=[Parameter(str(i), t) for i, t in enumerate(self.fields)]
        )

    def __repr__(self) -> str:
        return f"{super().__repr__()}(" + ", ".join(str(f) for f in self.fields) + ")"


@dataclass
class UnitStructureDefinition(StructureSignature):
    def _to_tuple(self) -> TupleStructureDefinition:
        return TupleStructureDefinition(name=self.name, generics=self.generics, fields=[])

    def __repr__(self) -> str:
        return super().__repr__()


@dataclass
class Statement_StructureDefinition(Statement_TopLevel):
    signature: StructureSignature

    def __repr__(self) -> str:
        return f"{super().__repr__()}struct {self.signature}"


@dataclass
class Statement_EnumDefinition(Statement_TopLevel):
    name: str
    generics: list[Type]
    body: list[StructureSignature]

    def __repr__(self) -> str:
        generic_repr = format_generic_params(self.generics)
        body = " {\n" + "\n".join(f"  {b}" for b in self.body) + "\n}"
        return f"{super().__repr__()}enum {self.name}{generic_repr}{body}"


@dataclass
class Statement_Impl(Statement_TopLevel):
    generics: list[Type]
    trait_name: str | None
    trait_args: list[Type]
    struct: Type
    body: list[Statement_FunctionDefinition]
    is_public: bool

    def __post_init__(self):
        self.is_public = False

    def __repr__(self) -> str:
        generics_repr = format_generic_params(self.generics)
        trait_repr = ""
        if self.trait_name is not None:
            trait_args_repr = ("[" + ", ".join(str(g) for g in self.trait_args) + "]") if self.trait_args else ""
            trait_repr = f" {self.trait_name}{trait_args_repr}"
        body_repr = "\n".join(f"  {method}" for method in self.body)
        return f"impl{generics_repr}{trait_repr} for {self.struct} {{\n{body_repr}\n}}"


# =============
@dataclass
class Statement_InnerLevel(Statement):
    pass


@dataclass
class Statement_OneLineComment(Statement_TopLevel, Statement_InnerLevel):
    value: str

    def __repr__(self) -> str:
        return self.value


@dataclass
class Statement_MultiLineComment(Statement_TopLevel, Statement_InnerLevel):
    value: str

    def __repr__(self) -> str:
        return self.value


@dataclass
class Statement_Let(Statement_InnerLevel):
    name: str
    type: Type | None
    expr: "Statement_Expression"
    is_mut: bool = False

    def __repr__(self) -> str:
        mut_repr = "mut " if self.is_mut else ""
        type_repr = f" : {self.type}" if self.type else ""
        return f"let {mut_repr}{self.name}{type_repr} = {self.expr}"


@dataclass
class Statement_While(Statement_InnerLevel):
    label: Optional[str]
    expr: "Statement_Expression"
    body: "Block"

    def __repr__(self) -> str:
        label_repr = f"<'{self.label}>" if self.label else ""
        return f"while{label_repr} {self.body}"


@dataclass
class Statement_Loop(Statement_InnerLevel):
    label: Optional[str]
    body: "Block"

    def __repr__(self) -> str:
        label_repr = f"<'{self.label}>" if self.label else ""
        return f"loop{label_repr} {self.body}"


@dataclass
class Statement_DoWhile(Statement_InnerLevel):
    body: "Block"
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        return f"do {self.body} while {self.expr}"


@dataclass
class Statement_Assignment(Statement_InnerLevel):
    target: "Statement_Expression"
    expr: "Statement_Expression"
    operator: str = "="

    @property
    def name(self) -> str:
        if isinstance(self.target, Expression_Path):
            return self.target.name
        if isinstance(self.target, Expression_StructField):
            return self.target.name
        return repr(self.target)

    def __repr__(self) -> str:
        return f"{self.target} {self.operator} {self.expr}"


@dataclass
class Statement_Expr(Statement_InnerLevel):
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        return str(self.expr)


@dataclass
class Statement_IfBranch:
    expr: "Statement_Expression"
    body: "Block"

    def __repr__(self) -> str:
        return f"{self.expr} {self.body}"


@dataclass
class Statement_If(Statement_InnerLevel):
    branches: list[Statement_IfBranch]
    else_body: Optional["Block"] = None

    def __repr__(self) -> str:
        r = f"if {self.branches[0]}"
        for branch in self.branches[1:]:
            r += f"\nelif {branch}"
        if self.else_body is not None:
            r += "\nelse {"
            for stmt in self.else_body.body:
                r += f"\n  {stmt}"
            r += "\n}"
        return r


@dataclass
class Statement_MatchArm:
    pattern: "Statement_Expression | None"
    binding: str | None
    body: "Block | Statement_Expression"

    @property
    def is_wildcard(self) -> bool:
        return self.pattern is None

    def __repr__(self) -> str:
        pattern_repr = "_" if self.pattern is None else str(self.pattern)
        if self.binding is not None:
            pattern_repr = f"{pattern_repr}({self.binding})"
        return f"{pattern_repr} => {self.body}"


@dataclass
class Statement_Match(Statement_InnerLevel):
    expr: "Statement_Expression"
    arms: list[Statement_MatchArm]

    def __repr__(self) -> str:
        arms_repr = "\n".join(f"  {arm}" for arm in self.arms)
        return f"match {self.expr} {{\n{arms_repr}\n}}"


@dataclass
class Statement_Unsafe(Statement_InnerLevel):
    body: "Block"

    def __repr__(self) -> str:
        return f"unsafe {self.body}"


@dataclass
class Statement_EHIR(Statement_InnerLevel):
    instructions: list[Instruction]
    is_unsafe: bool = False

    def __repr__(self) -> str:
        prefix = "unsafe ehir" if self.is_unsafe else "ehir"
        if not self.instructions:
            return f"{prefix} {{}}"
        body = "\n".join(f"  {instruction}" for instruction in self.instructions)
        return f"{prefix} {{\n{body}\n}}"


# =============
@dataclass
class Statement_ControlFlow(Statement_InnerLevel):
    pass


@dataclass
class Statement_Ret(Statement_ControlFlow):
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        return f"ret {self.expr if self.expr else 'void'}"


@dataclass
class Statement_Break(Statement_ControlFlow):
    label: Optional[str]

    def __repr__(self) -> str:
        label_repr = f"<'{self.label}>" if self.label else ""
        return f"break{label_repr}"


@dataclass
class Statement_Continue(Statement_ControlFlow):
    label: Optional[str]

    def __repr__(self) -> str:
        label_repr = f"<'{self.label}>" if self.label else ""
        return f"continue{label_repr}"


# =============
@dataclass
class Statement_Expression(Statement_InnerLevel, ABC):
    pass


@dataclass
class Expression_Path(Statement_Expression):
    segments: list[Type]

    @property
    def name(self) -> str:
        return "::".join(str(segment) for segment in self.segments)

    def __repr__(self) -> str:
        return self.name


@dataclass
class Expression_BooleanLiteral(Statement_Expression):
    value: bool

    def __repr__(self) -> str:
        return "true" if self.value else "false"


@dataclass
class Expression_IntegerLiteral(Statement_Expression):
    value: str
    literal_type: Type | None = None

    def __repr__(self) -> str:
        return self.value if self.literal_type is None else f"{self.value}_{self.literal_type}"


@dataclass
class Expression_FloatLiteral(Statement_Expression):
    value: str
    literal_type: Type | None = None

    def __repr__(self) -> str:
        return self.value if self.literal_type is None else f"{self.value}_{self.literal_type}"


@dataclass
class Expression_StringLiteral(Statement_Expression):
    value: str

    def __repr__(self) -> str:
        escaped = self.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'


@dataclass
class Expression_StructInitialization(Statement_Expression):
    name: Type
    args: list[Statement_Expression]

    def __repr__(self) -> str:
        args = "{" + ", ".join(str(a) for a in self.args) + "}"
        return f"{self.name}{args}"


@dataclass
class Expression_StructField(Statement_Expression):
    name: str
    field: str

    def __repr__(self) -> str:
        return f"{self.name}.{self.field}"


@dataclass
class Expression_Call(Statement_Expression):
    callee: Expression_Path
    generics: list[Type]
    args: list[Statement_Expression]

    @property
    def name(self) -> str:
        return self.callee.name

    def __repr__(self) -> str:
        generics = f"[{', '.join(str(g) for g in self.generics)}]" if self.generics else ""
        return f"{self.callee}{generics}({', '.join(str(arg) for arg in self.args)})"


@dataclass
class Expression_MethodCall(Statement_Expression):
    receiver: Statement_Expression
    method: str
    generics: list[Type]
    args: list[Statement_Expression]

    def __repr__(self) -> str:
        generics = f"[{', '.join(str(g) for g in self.generics)}]" if self.generics else ""
        args = ", ".join(str(arg) for arg in self.args)
        return f"{self.receiver}.{self.method}{generics}({args})"


@dataclass
class Expression_MatchArm:
    pattern: "Statement_Expression | None"
    binding: str | None
    expr: Statement_Expression

    @property
    def is_wildcard(self) -> bool:
        return self.pattern is None

    def __repr__(self) -> str:
        pattern_repr = "_" if self.pattern is None else str(self.pattern)
        if self.binding is not None:
            pattern_repr = f"{pattern_repr}({self.binding})"
        return f"{pattern_repr} => {self.expr}"


@dataclass
class Expression_Match(Statement_Expression):
    expr: Statement_Expression
    arms: list[Expression_MatchArm]

    def __repr__(self) -> str:
        arms_repr = "\n".join(f"  {arm}" for arm in self.arms)
        return f"match {self.expr} {{\n{arms_repr}\n}}"


# =============
@dataclass
class Expression_IfBranch:
    expr: Statement_Expression
    body: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.expr} {{ {self.body} }}"


@dataclass
class Expression_If(Statement_Expression):
    branches: list[Expression_IfBranch]
    else_body: Statement_Expression

    def __repr__(self) -> str:
        r = f"if {self.branches[0]}"
        for branch in self.branches[1:]:
            r += f"\nelif {branch}"
        return f"{r}\nelse {{ {self.else_body} }}"


# =============
@dataclass
class Expression_Block(Statement_Expression):
    body: list[Statement_InnerLevel]
    expr: Statement_Expression

    def __repr__(self) -> str:
        r = "{"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += f"\n  {self.expr}\n}}"
        return r


@dataclass
class Block:
    body: list[Statement_InnerLevel]

    def __repr__(self) -> str:
        r = "{"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class Expression_Unsafe(Statement_Expression):
    body: "Block"

    def __repr__(self) -> str:
        return f"unsafe {self.body}"


# =============
@dataclass
class Expression_BinaryOperation(Statement_Expression):
    lhs: Statement_Expression
    operator: str
    rhs: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_LogicalOr(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_LogicalAnd(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_BitwiseOr(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_BitwiseXor(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_BitwiseAnd(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_Equality(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_Relational(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_Shift(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_Additive(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


@dataclass
class BinaryOperation_Multiplicative(Expression_BinaryOperation):
    def __repr__(self) -> str:
        return f"{self.lhs} {self.operator} {self.rhs}"


# =============
@dataclass
class Expression_UnaryOperation(Statement_Expression):
    operator: str
    expr: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.operator}{self.expr}"


@dataclass
class Expression_Try(Statement_Expression):
    expr: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.expr}?"


# =============
@dataclass
class Expression_Primary(Statement_Expression):
    pass


@dataclass
class Expression_Parenthesized(Expression_Primary):
    expr: Statement_Expression

    def __repr__(self) -> str:
        return f"({self.expr})"


@dataclass
class Expression_TupleLiteral(Expression_Primary):
    items: list[Statement_Expression]

    def __repr__(self) -> str:
        return "(" + ", ".join(str(item) for item in self.items) + ")"


@dataclass
class Expression_ArrayLiteral(Expression_Primary):
    items: list[Statement_Expression]

    def __repr__(self) -> str:
        return "[" + ", ".join(str(item) for item in self.items) + "]"


@dataclass
class Expression_ArrayRepeat(Expression_Primary):
    value: Statement_Expression
    size: int

    def __repr__(self) -> str:
        return f"[{self.value}; {self.size}]"


@dataclass
class Expression_Index(Statement_Expression):
    base: Statement_Expression
    index: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.base}[{self.index}]"
