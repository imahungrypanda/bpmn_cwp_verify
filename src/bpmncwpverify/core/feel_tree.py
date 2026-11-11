from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

T = TypeVar("T")

BinaryOpName = Literal[
    "+", "-", "*", "/", "**", "<", ">", "<=", ">=", "=", "!=", "and", "or", "xor"
]


@dataclass(frozen=True, slots=True)
class FeelNode:
    """
    Base of the FEEL syntax tree. line and column locate the node in the
    source text and are ignored when comparing nodes.
    """

    line: int = field(default=0, kw_only=True, compare=False, repr=False)
    column: int = field(default=0, kw_only=True, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class Number(FeelNode):
    value: int | float


@dataclass(frozen=True, slots=True)
class Boolean(FeelNode):
    value: bool


@dataclass(frozen=True, slots=True)
class Name(FeelNode):
    """A state variable or constant; may be dotted, e.g. `a.b`."""

    name: str


@dataclass(frozen=True, slots=True)
class ListExpr(FeelNode):
    items: tuple[FeelExpr, ...]


@dataclass(frozen=True, slots=True)
class BinaryOp(FeelNode):
    """Arithmetic, comparison and logic operators; `op` is the operator text."""

    op: BinaryOpName
    left: FeelExpr
    right: FeelExpr


@dataclass(frozen=True, slots=True)
class Not(FeelNode):
    operand: FeelExpr


@dataclass(frozen=True, slots=True)
class Negate(FeelNode):
    operand: FeelExpr


@dataclass(frozen=True, slots=True)
class If(FeelNode):
    condition: FeelExpr
    then_branch: FeelExpr
    else_branch: FeelExpr


@dataclass(frozen=True, slots=True)
class Choose(FeelNode):
    """`choose [a, b, c]`: any one of the options, picked nondeterministically."""

    options: tuple[FeelExpr, ...]


@dataclass(frozen=True, slots=True)
class Triple(FeelNode):
    """`(target, [inputs], value)`: sets target to value, which reads inputs."""

    target: str
    inputs: tuple[str, ...]
    value: FeelExpr


@dataclass(frozen=True, slots=True)
class TripleList(FeelNode):
    """Two or more triples, run in order. Written in (ordinary) parentheses."""

    triples: tuple[Triple, ...]


FeelExpr = (
    Number
    | Boolean
    | Name
    | ListExpr
    | BinaryOp
    | Not
    | Negate
    | If
    | Choose
    | Triple
    | TripleList
)


class FeelVisitor(Generic[T]):
    """
    Visits a FEEL syntax tree. Subclass and override the visit_* methods
    for the nodes you handle; the others raise NotImplementedError.
    Parenthesized expressions leave no node in the tree.
    """

    def visit(self, node: FeelExpr) -> T:
        match node:
            case Number():
                return self.visit_number(node)
            case Boolean():
                return self.visit_boolean(node)
            case Name():
                return self.visit_name(node)
            case ListExpr():
                return self.visit_list(node)
            case BinaryOp():
                return self.visit_binary_op(node)
            case Not():
                return self.visit_not(node)
            case Negate():
                return self.visit_negate(node)
            case If():
                return self.visit_if(node)
            case Choose():
                return self.visit_choose(node)
            case Triple():
                return self.visit_triple(node)
            case TripleList():
                return self.visit_triple_list(node)
        raise NotImplementedError(f"unknown FEEL node {node!r}")

    def visit_number(self, node: Number) -> T:
        raise NotImplementedError

    def visit_boolean(self, node: Boolean) -> T:
        raise NotImplementedError

    def visit_name(self, node: Name) -> T:
        raise NotImplementedError

    def visit_list(self, node: ListExpr) -> T:
        raise NotImplementedError

    def visit_binary_op(self, node: BinaryOp) -> T:
        raise NotImplementedError

    def visit_not(self, node: Not) -> T:
        raise NotImplementedError

    def visit_negate(self, node: Negate) -> T:
        raise NotImplementedError

    def visit_if(self, node: If) -> T:
        raise NotImplementedError

    def visit_choose(self, node: Choose) -> T:
        raise NotImplementedError

    def visit_triple(self, node: Triple) -> T:
        raise NotImplementedError

    def visit_triple_list(self, node: TripleList) -> T:
        raise NotImplementedError
