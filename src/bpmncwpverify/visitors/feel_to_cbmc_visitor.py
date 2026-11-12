from returns.result import Failure, Result, Success

from bpmncwpverify.core.error import Error, FeelCbmcUnsupportedError
from bpmncwpverify.core.feel_tree import (
    BinaryOp,
    Boolean,
    Choose,
    FeelExpr,
    FeelNode,
    FeelVisitor,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
    TripleList,
)

# The helper that gives CBMC a nondeterministic value; the CBMC back end's
# helper definitions declare it.
NONDET_FUNC = "nondet_uint"
CHOICE_PREFIX = "feel_choice_"
# `a ** n` is written out as n multiplications, so n has to be small
MAX_POWER = 8

_C_OPS = {
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
    "=": "==",
    "!=": "!=",
    "and": "&&",
    "or": "||",
    "xor": "!=",
}


class _CUnsupported(Exception):
    """Carries an Error out of the visitor; never leaves this module."""

    def __init__(self, construct: str, node: FeelNode) -> None:
        super().__init__(construct)
        self.error = FeelCbmcUnsupportedError(construct, node.line, node.column)


class FeelToCbmcVisitor(FeelVisitor[str]):
    """
    Turns a type-checked FEEL tree into C. An expression becomes a C
    expression, so integer division truncates, and every operator is
    parenthesized. A triple becomes a block that assigns its target, and a
    triple list becomes its triples' blocks in order, so a later triple sees
    what an earlier one assigned. The inputs of a triple are documentation
    only: C reads whatever the value reads.

    `choose [a, b, c]` becomes a selector declared at the start of the
    enclosing triple's block: it gets a nondeterministic value, assumed to be
    below the number of options, and the choose picks the option it names.
    CBMC explores every selector value, so it tries every option. A choose can
    only be in a triple's value, because a condition is written into the C more
    than once and each copy would pick on its own.

    Failures are raised as _CUnsupported; use condition_to_c() or
    behavior_to_c() to get a Result. The C refers to variables, constants and
    enum values by name, so they must be declared before it, and the code uses
    `nondet_uint`, which must be declared too.
    """

    def __init__(self) -> None:
        self._selectors: list[str] | None = None  # declarations for the open triple
        self._count = 0

    def visit_number(self, node: Number) -> str:
        if isinstance(node.value, float):
            raise _CUnsupported("a non-integer number", node)
        return str(node.value)

    def visit_boolean(self, node: Boolean) -> str:
        return "true" if node.value else "false"

    def visit_name(self, node: Name) -> str:
        return node.name

    def visit_list(self, node: ListExpr) -> str:
        raise _CUnsupported("a list", node)

    def visit_binary_op(self, node: BinaryOp) -> str:
        if node.op == "**":
            return self._power(node)
        left = self.visit(node.left)
        right = self.visit(node.right)
        return f"({left} {_C_OPS[node.op]} {right})"

    def _power(self, node: BinaryOp) -> str:
        exponent = node.right
        if not (
            isinstance(exponent, Number)
            and isinstance(exponent.value, int)
            and 0 <= exponent.value <= MAX_POWER
        ):
            raise _CUnsupported(
                f"'**' with an exponent that is not a literal from 0 to {MAX_POWER}",
                node,
            )
        if exponent.value == 0:
            return "1"
        base = self.visit(node.left)
        return "(" + " * ".join([base] * exponent.value) + ")"

    def visit_not(self, node: Not) -> str:
        return f"(!{self.visit(node.operand)})"

    def visit_negate(self, node: Negate) -> str:
        return f"(-{self.visit(node.operand)})"

    def visit_if(self, node: If) -> str:
        condition = self.visit(node.condition)
        then_branch = self.visit(node.then_branch)
        else_branch = self.visit(node.else_branch)
        return f"({condition} ? {then_branch} : {else_branch})"

    def visit_choose(self, node: Choose) -> str:
        if self._selectors is None:
            raise _CUnsupported("a 'choose' outside a behavior", node)
        if not node.options:
            raise _CUnsupported("a 'choose' with no options", node)
        options = [self.visit(o) for o in node.options]
        if len(options) == 1:
            return options[0]
        selector = f"{CHOICE_PREFIX}{self._count}"
        self._count += 1
        self._selectors.append(f"unsigned int {selector} = {NONDET_FUNC}();")
        self._selectors.append(f"__CPROVER_assume({selector} < {len(options)}u);")
        result = options[-1]
        for index in range(len(options) - 2, -1, -1):
            result = f"({selector} == {index}u ? {options[index]} : {result})"
        return result

    def visit_triple(self, node: Triple) -> str:
        outer = self._selectors
        self._selectors = []
        try:
            value = self.visit(node.value)
            lines = [*self._selectors, f"{node.target} = {value};"]
        finally:
            self._selectors = outer
        return "{\n" + "".join(f"  {line}\n" for line in lines) + "}"

    def visit_triple_list(self, node: TripleList) -> str:
        return "\n".join(self.visit(t) for t in node.triples)


def condition_to_c(expr: FeelExpr) -> Result[str, Error]:
    """The C expression for a type-checked bool expression such as a condition."""
    try:
        return Success(FeelToCbmcVisitor().visit(expr))
    except _CUnsupported as exc:
        return Failure(exc.error)


def behavior_to_c(expr: FeelExpr) -> Result[list[str], Error]:
    """
    The C statements, one per line, for a type-checked triple or triple list.
    Each triple is a block of its own.
    """
    if not isinstance(expr, Triple | TripleList):
        return Failure(
            FeelCbmcUnsupportedError(
                "a behavior that is not a triple", expr.line, expr.column
            )
        )
    try:
        return Success(FeelToCbmcVisitor().visit(expr).splitlines())
    except _CUnsupported as exc:
        return Failure(exc.error)
