from dataclasses import dataclass
from typing import Literal


@dataclass
class Statement:
    pass


# =============
@dataclass
class Statement_TopLevel(Statement):
    pass


@dataclass
class Statement_FunctionDefinition(Statement_TopLevel):
    name: str
    params: list[tuple[str, str]]
    type: str
    body: list["Statement_InnerLevel"]

    def __repr__(self) -> str:
        r = f"fn {self.name}({', '.join(f'{p[0]} : {p[1]}' for p in self.params)}) -> {self.type}" + " {"
        for stmt in self.body:
            r += f"\n  {stmt}"
        r += "\n}"
        return r


@dataclass
class Statement_StructureDefinition(Statement_TopLevel):
    name: str
    fields: list[tuple[str, str]]


# =============
@dataclass
class Statement_InnerLevel(Statement):
    pass


@dataclass
class Statement_Let(Statement_InnerLevel):
    name: str
    type: str
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
    name: str
    expr: "Statement_Expression"

    def __repr__(self) -> str:
        return f"{self.name} = {self.expr}"


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
class Expression_VariableAccess(Statement_Expression):
    name: str

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
    name: str
    args: list[Statement_Expression]


@dataclass
class Expression_StructField(Statement_Expression):
    name: str
    field: str


@dataclass
class Expression_Call(Statement_Expression):
    name: str
    args: list[Statement_Expression]


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
