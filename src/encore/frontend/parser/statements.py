from abc import ABC
from dataclasses import dataclass
from enum import StrEnum, auto

from ehir.core.type import Type
from ehir.core.variable import Parameter


@dataclass
class Statement:
    pass


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

        def __post_init__(self):
            if self.kind is None:
                self.kind = Statement_Import.ImportKind.SYMBOL

        def __repr__(self) -> str:
            match len(self.dst):
                case 0:
                    return "*" if self.kind == Statement_Import.ImportKind.GLOB else self.src
                case 1:
                    return f"{self.src}::{self.dst[0]}"
                case _:
                    dst_repr = f"{{ {', '.join(x.__repr__() for x in self.dst)} }}"
                    return f"{self.src}::{dst_repr}"

    pair: ImportPair

    def __repr__(self) -> str:
        pair_repr = self.pair.__repr__()
        return f"{super().__repr__()}import {pair_repr}"


@dataclass
class Statement_FunctionDefinition(Statement_TopLevel):
    name: str
    generics: list[Type]
    params: list[Parameter]
    type: Type
    body: list["Statement_InnerLevel"]

    def __repr__(self) -> str:
        r = f"fn {self.name}({', '.join(f'{p.name} : {p.type}' for p in self.params)}) -> {self.type}" + " {"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class StructureDefinition(ABC):
    name: str
    generics: list[Type]

    def __repr__(self) -> str:
        generic_repr = ("[" + ", ".join(str(g) for g in self.generics) + "]") if self.generics else ""
        return f"{self.name}{generic_repr}"


@dataclass
class CLikeStructureDefinition(StructureDefinition):
    fields: list[Parameter]

    def __repr__(self) -> str:
        body_repr = " {\n" + "\n".join(f"  {b}" for b in self.fields) + "\n}"
        return f"{super().__repr__()}{body_repr}"


@dataclass
class TupleStructureDefinition(StructureDefinition):
    fields: list[Type]

    def _to_clike(self) -> CLikeStructureDefinition:
        return CLikeStructureDefinition(
            name=self.name, generics=self.generics, fields=[Parameter(str(i), t) for i, t in enumerate(self.fields)]
        )

    def __repr__(self) -> str:
        return f"{super().__repr__()}(" + ", ".join(str(f) for f in self.fields) + ")"


@dataclass
class UnitStructureDefinition(StructureDefinition):
    def _to_tuple(self) -> TupleStructureDefinition:
        return TupleStructureDefinition(name=self.name, generics=self.generics, fields=[])

    def __repr__(self) -> str:
        return super().__repr__()


@dataclass
class Statement_StructureDefinition(Statement_TopLevel):
    defi: StructureDefinition

    def __repr__(self) -> str:
        return f"{super().__repr__()}struct {self.defi}"


@dataclass
class Statement_EnumDefinition(Statement_TopLevel):
    name: str
    generics: list[Type]
    body: list[StructureDefinition]

    def __repr__(self) -> str:
        generic_repr = "[" + ", ".join(str(g) for g in self.generics) + "]"
        body = " {\n" + "\n".join(f"  {b}" for b in self.body) + "\n}"
        return f"{super().__repr__()}enum {self.name}{generic_repr}{body}"


@dataclass
class Statement_Impl(Statement_TopLevel):
    # @dataclass
    # class FunctionDeclaration(Statement_TopLevel):
    #     name: str
    #     generics: list[str]
    #     params: list[tuple[str, str]]
    #     type: str

    generics: list[Type]
    trait_name: str | None
    struct: Type
    body: list[Statement_FunctionDefinition]
    is_public: bool

    def __post_init__(self):
        self.is_public = False


# =============
@dataclass
class Statement_InnerLevel(Statement):
    pass


@dataclass
class Statement_Let(Statement_InnerLevel):
    name: str
    type: Type
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        return f"let {self.name} : {self.type} = {self.expr}"


@dataclass
class Statement_While(Statement_InnerLevel):
    expr: "Statement_Expression"
    body: list["Statement_InnerLevel"]

    def __repr__(self) -> str:
        r = f"while {self.expr} {{"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class Statement_Loop(Statement_InnerLevel):
    body: list["Statement_InnerLevel"]

    def __repr__(self) -> str:
        r = "loop {"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class Statement_DoWhile(Statement_InnerLevel):
    body: list["Statement_InnerLevel"]
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        r = "do {"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += f"\n}} while {self.expr}"
        return r


@dataclass
class Statement_Assignment(Statement_InnerLevel):
    target: "Statement_Expression"
    expr: "Statement_Expression"

    @property
    def name(self) -> str:
        if isinstance(self.target, Expression_Path):
            return self.target.name
        if isinstance(self.target, Expression_StructField):
            return self.target.name
        return repr(self.target)

    def __repr__(self) -> str:
        return f"{self.target} = {self.expr}"


@dataclass
class Statement_IfBranch:
    expr: "Statement_Expression"
    body: list["Statement_InnerLevel"]

    def __repr__(self) -> str:
        r = f"{self.expr} {{"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class Statement_If(Statement_InnerLevel):
    branches: list[Statement_IfBranch]
    else_body: list["Statement_InnerLevel"] | None = None

    def __repr__(self) -> str:
        r = f"if {self.branches[0]}"
        for branch in self.branches[1:]:
            r += f"\nelif {branch}"
        if self.else_body is not None:
            r += "\nelse {"
            for stmt in self.else_body:
                r += f"\n  {stmt}"
            r += "\n}"
        return r


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
    def __repr__(self) -> str:
        return "break"


@dataclass
class Statement_Continue(Statement_ControlFlow):
    def __repr__(self) -> str:
        return "continue"


# =============
@dataclass
class Statement_Expression(Statement_InnerLevel):
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

    def __repr__(self) -> str:
        return self.value


@dataclass
class Expression_FloatLiteral(Statement_Expression):
    value: str

    def __repr__(self) -> str:
        return self.value


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
    pass


@dataclass
class BinaryOperation_LogicalAnd(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_BitwiseOr(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_BitwiseXor(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_BitwiseAnd(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_Equality(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_Relational(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_Shift(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_Additive(Expression_BinaryOperation):
    pass


@dataclass
class BinaryOperation_Multiplicative(Expression_BinaryOperation):
    pass


# =============
@dataclass
class Expression_UnaryOperation(Statement_Expression):
    operator: str
    expr: Statement_Expression

    def __repr__(self) -> str:
        return f"{self.operator}{self.expr}"


# =============
@dataclass
class Expression_Primary(Statement_Expression):
    pass


@dataclass
class Expression_Parenthesized(Expression_Primary):
    expr: Statement_Expression

    def __repr__(self) -> str:
        return f"({self.expr})"
