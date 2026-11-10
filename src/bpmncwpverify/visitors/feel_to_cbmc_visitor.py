"""
Turns a type-checked FEEL tree into C for the CBMC back end.

A condition becomes a C expression and a behavior becomes C statements. The C
needs <stdbool.h> and ``unsigned int nondet_uint(void);``, as the program the
CBMC builder writes has.

``choose [a, b, c]`` needs a value that is the same everywhere it is used, so
it is hoisted: a ``unsigned int <prefix>_choose_N = nondet_uint();`` statement
comes first, and the expression is ``(<pick> == 0 ? a : <pick> == 1 ? b : c)``.
Any pick of ``N`` or more selects the last option, so no ``assume`` is needed
and CBMC can reach every option. Such statements come back with the
expression and must be placed before it.

Semantics worth knowing:

- ``/`` is C integer division, as every number in the state is an integer.
- ``**`` is expanded to a product, so the exponent must be a literal
  integer from 0 to ``MAX_POWER``.
- The triples of a behavior run in order, one after the other.
"""

from dataclasses import dataclass

from returns.result import Failure, Result, Success

from bpmncwpverify.core.error import Error, FeelCbmcUnsupportedError
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

MAX_POWER = 16
NONDET_FUNC = "nondet_uint"

_C_OPS = {
    "and": "&&",
    "or": "||",
    "xor": "!=",
    "=": "==",
}


class _Unsupported(Exception):
    def __init__(self, construct: str, reason: str) -> None:
        super().__init__(construct)
        self.error = FeelCbmcUnsupportedError(construct, reason)


@dataclass(frozen=True)
class CExpr:
    """A C expression, and the statements that must come before it."""

    statements: tuple[str, ...]
    expr: str


class FeelToCbmcVisitor(FeelVisitor[str]):
    """
    Visiting an expression returns its C text. The statements it needs first
    are collected in ``statements``. Visiting a triple returns its assignment.
    Names made for ``choose`` start with ``prefix``; use another prefix, or a
    block, when two translations share a scope.
    """

    def __init__(self, prefix: str = "feel") -> None:
        self.prefix = prefix
        self.statements: list[str] = []
        self._count = 0

    def visit_number(self, node: Number) -> str:
        if not isinstance(node.value, int):
            raise _Unsupported(
                f"the number {node.value}", "only integers can be used in C here"
            )
        return str(node.value)

    def visit_boolean(self, node: Boolean) -> str:
        return "true" if node.value else "false"

    def visit_name(self, node: Name) -> str:
        return node.name

    def visit_list_expr(self, node: ListExpr) -> str:
        raise _Unsupported("a list", "a list is only supported inside 'choose'")

    def visit_negate(self, node: Negate) -> str:
        return f"(-{self.visit(node.operand)})"

    def visit_not(self, node: Not) -> str:
        return f"(!{self.visit(node.operand)})"

    def visit_binary(self, node: Binary) -> str:
        if node.op == "**":
            return self._power(node)
        left = self.visit(node.left)
        right = self.visit(node.right)
        return f"({left} {_C_OPS.get(node.op, node.op)} {right})"

    def visit_if(self, node: If) -> str:
        condition = self.visit(node.condition)
        then_branch = self.visit(node.then_branch)
        else_branch = self.visit(node.else_branch)
        return f"({condition} ? {then_branch} : {else_branch})"

    def visit_choose(self, node: Choose) -> str:
        if not node.options:
            raise _Unsupported("'choose'", "it has no options")
        options = [self.visit(option) for option in node.options]
        if len(options) == 1:
            return options[0]
        pick = f"{self.prefix}_choose_{self._count}"
        self._count += 1
        self.statements.append(f"unsigned int {pick} = {NONDET_FUNC}();")
        result = options[-1]
        for i in range(len(options) - 2, -1, -1):
            result = f"{pick} == {i} ? {options[i]} : {result}"
        return f"({result})"

    def visit_triple(self, node: Triple) -> str:
        return f"{node.target.name} = {self.visit(node.value)};"

    def visit_behavior(self, node: Behavior) -> str:
        return "\n".join(self.triple_lines(t) for t in node.triples)

    def triple_lines(self, triple: Triple) -> str:
        """The triple's statements, in a block when it needs ``choose`` variables."""
        self.statements = []
        assignment = self.visit_triple(triple)
        if not self.statements:
            return assignment
        return "\n".join(["{", *self.statements, assignment, "}"])

    def _power(self, node: Binary) -> str:
        exponent = node.right
        if (
            not isinstance(exponent, Number)
            or not isinstance(exponent.value, int)
            or not 0 <= exponent.value <= MAX_POWER
        ):
            raise _Unsupported(
                "'**'",
                f"the exponent must be a literal integer from 0 to {MAX_POWER}",
            )
        if exponent.value == 0:
            return "1"
        base = self.visit(node.left)
        return "(" + " * ".join([base] * exponent.value) + ")"


def condition_to_c(node: FeelNode, prefix: str = "feel") -> Result[CExpr, Error]:
    """A condition as a C expression, with the statements to put before it."""
    visitor = FeelToCbmcVisitor(prefix)
    try:
        expr = visitor.visit(node)
    except _Unsupported as unsupported:
        return Failure(unsupported.error)
    return Success(CExpr(tuple(visitor.statements), expr))


def behavior_to_c(
    node: Behavior | Triple, prefix: str = "feel"
) -> Result[tuple[str, ...], Error]:
    """
    C statements for a behavior, one line each. A triple that needs ``choose``
    variables is wrapped in a block; lines that end in ``{`` or start with
    ``}`` open and close it, as in the BPMN visitor's behaviors.
    """
    visitor = FeelToCbmcVisitor(prefix)
    try:
        triples = node.triples if isinstance(node, Behavior) else (node,)
        text = "\n".join(visitor.triple_lines(t) for t in triples)
    except _Unsupported as unsupported:
        return Failure(unsupported.error)
    return Success(tuple(text.split("\n")) if text else ())
