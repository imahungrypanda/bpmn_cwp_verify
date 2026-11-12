import itertools
from dataclasses import replace

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

_PROMELA_OPS = {
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
}


class FeelToPromelaError(Exception):
    """
    Raised for a FEEL construct that has no Promela translation. A tree that
    passed the type checker only reaches this for `**` with an exponent that
    is not a non-negative whole number literal, and for `choose` outside
    the value of a triple.
    """

    def __init__(self, message: str, node: FeelNode) -> None:
        super().__init__(f"line {node.line}:{node.column} {message}")


def _alternatives(node: FeelExpr) -> list[FeelExpr]:
    """
    Returns the choose-free expressions that node can stand for: one per
    combination of choices. SPIN gets one branch of an if per alternative.
    """
    alts: list[FeelExpr]
    match node:
        case Choose():
            alts = [a for option in node.options for a in _alternatives(option)]
        case BinaryOp():
            alts = [
                replace(node, left=left, right=right)
                for left, right in itertools.product(
                    _alternatives(node.left), _alternatives(node.right)
                )
            ]
        case Not() | Negate():
            alts = [replace(node, operand=a) for a in _alternatives(node.operand)]
        case If():
            alts = [
                replace(node, condition=c, then_branch=t, else_branch=e)
                for c, t, e in itertools.product(
                    _alternatives(node.condition),
                    _alternatives(node.then_branch),
                    _alternatives(node.else_branch),
                )
            ]
        case _:
            return [node]
    return list(dict.fromkeys(alts))  # drop repeats, keep order


class FeelToPromelaVisitor(FeelVisitor[str]):
    """
    Turns a type-checked FEEL tree into Promela.

    Values and conditions become a Promela expression. A triple becomes
    the statements that assign its target, and a triple list becomes those
    statements in order. A `choose` in a triple's value becomes an
    `if` with one branch per choice, so SPIN tries each one. Every
    operator is parenthesized, so the result can be placed in any context.
    """

    def visit_number(self, node: Number) -> str:
        return str(node.value)

    def visit_boolean(self, node: Boolean) -> str:
        return "true" if node.value else "false"

    def visit_name(self, node: Name) -> str:
        return node.name

    def visit_list(self, node: ListExpr) -> str:
        raise FeelToPromelaError("a list is only allowed inside 'choose'", node)

    def visit_binary_op(self, node: BinaryOp) -> str:
        left = self.visit(node.left)
        if node.op == "**":
            return self._power(node, left)
        right = self.visit(node.right)
        if node.op == "xor":
            return f"({left} != {right})"
        return f"({left} {_PROMELA_OPS[node.op]} {right})"

    def _power(self, node: BinaryOp, base: str) -> str:
        # Promela has no power operator, so a literal exponent is unrolled
        exponent = node.right
        if (
            not isinstance(exponent, Number)
            or not isinstance(exponent.value, int)
            or exponent.value < 0
        ):
            raise FeelToPromelaError(
                "'**' needs a non-negative whole number literal as its exponent", node
            )
        if exponent.value == 0:
            return "1"
        return "(" + " * ".join([base] * exponent.value) + ")"

    def visit_not(self, node: Not) -> str:
        return f"(!{self.visit(node.operand)})"

    def visit_negate(self, node: Negate) -> str:
        return f"(-{self.visit(node.operand)})"

    def visit_if(self, node: If) -> str:
        return (
            f"({self.visit(node.condition)} -> {self.visit(node.then_branch)}"
            f" : {self.visit(node.else_branch)})"
        )

    def visit_choose(self, node: Choose) -> str:
        raise FeelToPromelaError(
            "'choose' is only allowed in the value of a triple", node
        )

    def visit_triple(self, node: Triple) -> str:
        alternatives = [self.visit(a) for a in _alternatives(node.value)]
        if len(alternatives) == 1:
            return f"{node.target} = {alternatives[0]}"
        branches = "\n".join(f"\t:: {node.target} = {a}" for a in alternatives)
        return f"if\n{branches}\nfi"

    def visit_triple_list(self, node: TripleList) -> str:
        return "\n".join(self.visit_triple(t) for t in node.triples)


def condition_to_promela(expr: FeelExpr) -> str:
    """Returns a Promela expression for a type-checked FEEL condition."""
    return FeelToPromelaVisitor().visit(expr)


def behavior_to_promela(expr: FeelExpr) -> str:
    """
    Returns Promela statements, one per line, for a type-checked FEEL
    behavior: a triple or a triple list.
    """
    if not isinstance(expr, Triple | TripleList):
        raise FeelToPromelaError("a behavior must be a triple or a triple list", expr)
    return FeelToPromelaVisitor().visit(expr)
