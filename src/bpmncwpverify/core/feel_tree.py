"""
Syntax tree for the subset of FEEL this tool uses, and a visitor over it.
"""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

ARITHMETIC_OPS = ("+", "-", "*", "/", "**")
COMPARISON_OPS = ("<", ">", "<=", ">=", "=", "!=")
LOGIC_OPS = ("and", "or", "xor")


class FeelNode:
    """Base class of every node in the FEEL syntax tree."""

    __slots__ = ()


@dataclass(frozen=True)
class Number(FeelNode):
    value: int | float


@dataclass(frozen=True)
class Boolean(FeelNode):
    value: bool


@dataclass(frozen=True)
class Name(FeelNode):
    """A state variable or constant; may be dotted, e.g. ``a.b``."""

    name: str


@dataclass(frozen=True)
class ListExpr(FeelNode):
    items: tuple[FeelNode, ...]


@dataclass(frozen=True)
class Binary(FeelNode):
    """``op`` is one of ARITHMETIC_OPS, COMPARISON_OPS or LOGIC_OPS."""

    op: str
    left: FeelNode
    right: FeelNode


@dataclass(frozen=True)
class Negate(FeelNode):
    operand: FeelNode


@dataclass(frozen=True)
class Not(FeelNode):
    operand: FeelNode


@dataclass(frozen=True)
class If(FeelNode):
    condition: FeelNode
    then_branch: FeelNode
    else_branch: FeelNode


@dataclass(frozen=True)
class Choose(FeelNode):
    """Any one of ``options``, picked nondeterministically."""

    options: tuple[FeelNode, ...]


@dataclass(frozen=True)
class Triple(FeelNode):
    """``(target, [inputs], value)``: set ``target`` to ``value``, which reads ``inputs``."""

    target: Name
    inputs: tuple[Name, ...]
    value: FeelNode


@dataclass(frozen=True)
class Behavior(FeelNode):
    """A task behavior: one or more triples."""

    triples: tuple[Triple, ...]


class FeelVisitor(Generic[T]):
    """
    Visits a FEEL tree. ``visit`` calls ``visit_<NodeClass>``, with the class
    name in snake case (``visit_number``, ``visit_list_expr``, ...). Subclasses
    override the methods they need; the rest raise NotImplementedError.
    """

    def visit(self, node: FeelNode) -> T:
        return getattr(self, _METHOD_NAMES[type(node)])(node)  # type: ignore[no-any-return]

    def visit_number(self, node: Number) -> T:
        raise NotImplementedError

    def visit_boolean(self, node: Boolean) -> T:
        raise NotImplementedError

    def visit_name(self, node: Name) -> T:
        raise NotImplementedError

    def visit_list_expr(self, node: ListExpr) -> T:
        raise NotImplementedError

    def visit_binary(self, node: Binary) -> T:
        raise NotImplementedError

    def visit_negate(self, node: Negate) -> T:
        raise NotImplementedError

    def visit_not(self, node: Not) -> T:
        raise NotImplementedError

    def visit_if(self, node: If) -> T:
        raise NotImplementedError

    def visit_choose(self, node: Choose) -> T:
        raise NotImplementedError

    def visit_triple(self, node: Triple) -> T:
        raise NotImplementedError

    def visit_behavior(self, node: Behavior) -> T:
        raise NotImplementedError


_METHOD_NAMES: dict[type[FeelNode], str] = {
    Number: "visit_number",
    Boolean: "visit_boolean",
    Name: "visit_name",
    ListExpr: "visit_list_expr",
    Binary: "visit_binary",
    Negate: "visit_negate",
    Not: "visit_not",
    If: "visit_if",
    Choose: "visit_choose",
    Triple: "visit_triple",
    Behavior: "visit_behavior",
}
