"""
Turns a type-checked FEEL tree into Promela.

A condition becomes a Promela expression. A behavior becomes Promela
statements, one assignment per triple. ``choose`` has no expression form in
Promela, so a triple whose value contains ``choose`` becomes an ``if`` with one
guard-free option for every combination of choices; SPIN explores all of them.
"""

from itertools import product

from returns.result import Failure, Result, Success

from bpmncwpverify.core.error import Error, FeelUnsupportedError
from bpmncwpverify.core.feel_tree import (
    Behavior,
    Binary,
    Boolean,
    Choose,
    FeelNode,
    FeelVisitor,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
)

_BINARY_OPS = {
    "and": "&&",
    "or": "||",
    "=": "==",
}
_MAX_POWER = 8


def _unsupported(construct: str, node: FeelNode) -> Failure[Error]:
    return Failure(FeelUnsupportedError(construct, repr(node)))


def _expand(node: FeelNode) -> list[FeelNode]:
    """
    Every ``choose``-free tree the node can turn into, one per combination of
    choices.
    """
    if isinstance(node, Choose):
        return [alt for option in node.options for alt in _expand(option)]
    if isinstance(node, Binary):
        return [
            Binary(node.op, left, right)
            for left, right in product(_expand(node.left), _expand(node.right))
        ]
    if isinstance(node, Negate):
        return [Negate(operand) for operand in _expand(node.operand)]
    if isinstance(node, Not):
        return [Not(operand) for operand in _expand(node.operand)]
    if isinstance(node, If):
        return [
            If(cond, then, other)
            for cond, then, other in product(
                _expand(node.condition),
                _expand(node.then_branch),
                _expand(node.else_branch),
            )
        ]
    if isinstance(node, ListExpr):
        return [ListExpr(items) for items in product(*map(_expand, node.items))]
    return [node]


class FeelToPromelaVisitor(FeelVisitor[Result[str, Error]]):
    """
    Visiting an expression returns Promela for it. Visiting a triple or a
    behavior returns Promela statements, one per line. Every operator is fully
    parenthesized, so Promela precedence never matters.
    """

    def visit_number(self, node: Number) -> Result[str, Error]:
        if isinstance(node.value, float):
            return _unsupported("a non-integer number", node)
        return Success(str(node.value))

    def visit_boolean(self, node: Boolean) -> Result[str, Error]:
        return Success("true" if node.value else "false")

    def visit_name(self, node: Name) -> Result[str, Error]:
        return Success(node.name)

    def visit_list_expr(self, node: ListExpr) -> Result[str, Error]:
        return _unsupported("a list outside 'choose'", node)

    def visit_choose(self, node: Choose) -> Result[str, Error]:
        return _unsupported("'choose' outside a behavior's value", node)

    def visit_negate(self, node: Negate) -> Result[str, Error]:
        return self.visit(node.operand).map(lambda operand: f"(-{operand})")

    def visit_not(self, node: Not) -> Result[str, Error]:
        return self.visit(node.operand).map(lambda operand: f"(!{operand})")

    def visit_binary(self, node: Binary) -> Result[str, Error]:
        if node.op == "**":
            return self._power(node)
        left = self.visit(node.left)
        if isinstance(left, Failure):
            return left
        right = self.visit(node.right)
        if isinstance(right, Failure):
            return right
        lhs, rhs = left.unwrap(), right.unwrap()
        if node.op == "xor":
            # Operands are bool, so inequality is exclusive or.
            return Success(f"({lhs} != {rhs})")
        return Success(f"({lhs} {_BINARY_OPS.get(node.op, node.op)} {rhs})")

    def visit_if(self, node: If) -> Result[str, Error]:
        parts = [
            self.visit(n) for n in (node.condition, node.then_branch, node.else_branch)
        ]
        for part in parts:
            if isinstance(part, Failure):
                return part
        cond, then, other = (part.unwrap() for part in parts)
        return Success(f"({cond} -> {then} : {other})")

    def visit_triple(self, node: Triple) -> Result[str, Error]:
        alternatives: list[str] = []
        for value in _expand(node.value):
            text = self.visit(value)
            if isinstance(text, Failure):
                return text
            alternatives.append(f"{node.target.name} = {text.unwrap()}")
        if len(alternatives) == 1:
            return Success(alternatives[0])
        options = "\n".join(f":: {alt}" for alt in alternatives)
        return Success(f"if\n{options}\nfi")

    def visit_behavior(self, node: Behavior) -> Result[str, Error]:
        statements: list[str] = []
        for triple in node.triples:
            statement = self.visit_triple(triple)
            if isinstance(statement, Failure):
                return statement
            statements.append(statement.unwrap())
        return Success("\n".join(statements))

    def _power(self, node: Binary) -> Result[str, Error]:
        """Promela has no power operator; expand a small constant exponent."""
        exponent = node.right
        if not (
            isinstance(exponent, Number)
            and isinstance(exponent.value, int)
            and 0 <= exponent.value <= _MAX_POWER
        ):
            return _unsupported(
                f"'**' with an exponent other than a constant from 0 to {_MAX_POWER}",
                node,
            )
        times = int(exponent.value)
        if times == 0:
            return Success("1")
        base = self.visit(node.left)
        return base.map(lambda text: "(" + " * ".join([text] * times) + ")")


def condition_to_promela(node: FeelNode) -> Result[str, Error]:
    """A type-checked condition as a Promela expression."""
    alternatives = _expand(node)
    if len(alternatives) != 1:
        return _unsupported("'choose' in a condition", node)
    return FeelToPromelaVisitor().visit(alternatives[0])


def behavior_to_promela(node: Behavior | Triple) -> Result[str, Error]:
    """A type-checked behavior or triple as Promela statements, one per line."""
    return FeelToPromelaVisitor().visit(node)


def condition_text(expression: str | FeelNode) -> Result[str, Error]:
    """A flow or edge condition as Promela; a plain string is kept as it is."""
    if isinstance(expression, str):
        return Success(expression)
    return condition_to_promela(expression)


def behavior_text(behavior: str | FeelNode) -> Result[str, Error]:
    """A task behavior as Promela; a plain string is kept as it is."""
    if isinstance(behavior, str):
        return Success(behavior)
    if isinstance(behavior, Behavior | Triple):
        return behavior_to_promela(behavior)
    return _unsupported("a behavior that is not a triple", behavior)
