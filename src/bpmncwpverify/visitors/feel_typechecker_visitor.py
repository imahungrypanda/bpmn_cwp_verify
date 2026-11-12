from returns.result import Failure, Result, Success

from bpmncwpverify.core import typechecking
from bpmncwpverify.core.error import (
    Error,
    FeelAssignTypeError,
    FeelBehaviorTypeError,
    FeelConditionTypeError,
    FeelInvalidTargetError,
    FeelMixedTypesError,
    FeelNumberTypeError,
    FeelOperatorTypeError,
    FeelUnknownNameError,
)
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
from bpmncwpverify.core.state import State

TRIPLE = "triple"
TRIPLE_LIST = "triple list"
_LIST_PREFIX = "list of "

_ARITHMETIC = {"+", "-", "*", "/"}
_ORDERING = {"<", ">", "<=", ">="}
_EQUALITY = {"=", "!="}
_LOGIC = {"and", "or", "xor"}


class _FeelTypeError(Exception):
    """Carries an Error out of the visitor; never leaves this module."""

    def __init__(self, error: Error) -> None:
        super().__init__()
        self.error = error


def _is_value(type_: str) -> bool:
    return type_ not in {TRIPLE, TRIPLE_LIST} and not type_.startswith(_LIST_PREFIX)


class FeelTypeCheckerVisitor(FeelVisitor[str]):
    """
    Computes the type of a FEEL expression. Types are the state file's:
    bit, byte, short, int, bool, and the name of an enum. Lists are
    "list of T", and triples are "triple" and "triple list".

    Failures are raised as _FeelTypeError; use type_check() to get a Result.
    """

    def __init__(self, state: State) -> None:
        # requires state.type_check() to have succeeded
        self.state = state
        self._vars = {v.id for v in state.vars}

    def _require_value(self, node: FeelNode, op: str, *types: str) -> None:
        if not all(_is_value(t) for t in types):
            raise _FeelTypeError(
                FeelOperatorTypeError(op, types, node.line, node.column)
            )

    def _operator_error(self, node: FeelNode, op: str, *types: str) -> Error:
        return FeelOperatorTypeError(op, types, node.line, node.column)

    def _unify(self, node: FeelNode, construct: str, types: list[str]) -> str:
        mixed = FeelMixedTypesError(construct, tuple(types), node.line, node.column)
        if not all(_is_value(t) for t in types):
            raise _FeelTypeError(mixed)
        result = types[0]
        for t in types[1:]:
            unified = typechecking.get_feel_unified_type_result(result, t)
            if not isinstance(unified, Success):
                raise _FeelTypeError(mixed)
            result = unified.unwrap()
        return result

    def _lookup(self, name: str, line: int, column: int) -> str:
        result = self.state.get_type(name)
        type_: str = result.unwrap() if isinstance(result, Success) else ""
        if type_ in {"", typechecking.ENUM}:
            raise _FeelTypeError(FeelUnknownNameError(name, line, column))
        return type_

    def visit_number(self, node: Number) -> str:
        if isinstance(node.value, float):
            raise _FeelTypeError(
                FeelNumberTypeError(str(node.value), node.line, node.column)
            )
        result = typechecking.get_type_literal(str(node.value))
        if not isinstance(result, Success):
            raise _FeelTypeError(
                FeelNumberTypeError(str(node.value), node.line, node.column)
            )
        type_: str = result.unwrap()
        return type_

    def visit_boolean(self, node: Boolean) -> str:
        return typechecking.BOOL

    def visit_name(self, node: Name) -> str:
        return self._lookup(node.name, node.line, node.column)

    def visit_list(self, node: ListExpr) -> str:
        if not node.items:
            return _LIST_PREFIX + "nothing"
        return _LIST_PREFIX + self._unify(
            node, "a list", [self.visit(i) for i in node.items]
        )

    def visit_binary_op(self, node: BinaryOp) -> str:
        ltype = self.visit(node.left)
        rtype = self.visit(node.right)
        self._require_value(node, node.op, ltype, rtype)

        def error(lt: str, rt: str) -> Error:
            return self._operator_error(node, node.op, lt, rt)

        result: Result[str, Error]
        if node.op in _ARITHMETIC:
            result = typechecking.get_feel_arithmetic_type_result(ltype, rtype, error)
        elif node.op == "**":
            result = typechecking.get_feel_arithmetic_type_result(
                ltype, rtype, error
            ).map(lambda _: typechecking.INT)
        elif node.op in _ORDERING or node.op in _EQUALITY:
            result = typechecking.get_feel_comparison_type_result(
                ltype, rtype, node.op in _ORDERING, error
            )
        else:
            assert node.op in _LOGIC
            result = typechecking.get_and_or_type_result(ltype, rtype, error)
        if isinstance(result, Failure):
            raise _FeelTypeError(result.failure())
        return result.unwrap()

    def visit_not(self, node: Not) -> str:
        operand = self.visit(node.operand)
        if operand != typechecking.BOOL:
            raise _FeelTypeError(self._operator_error(node, "not", operand))
        return typechecking.BOOL

    def visit_negate(self, node: Negate) -> str:
        operand = self.visit(node.operand)
        self._require_value(node, "-", operand)
        result = typechecking.get_feel_negate_type_result(
            operand, lambda t: self._operator_error(node, "-", t)
        )
        if isinstance(result, Failure):
            raise _FeelTypeError(result.failure())
        return result.unwrap()

    def visit_if(self, node: If) -> str:
        condition = self.visit(node.condition)
        if condition != typechecking.BOOL:
            raise _FeelTypeError(
                FeelConditionTypeError(condition, node.line, node.column)
            )
        return self._unify(
            node,
            "an if",
            [self.visit(node.then_branch), self.visit(node.else_branch)],
        )

    def visit_choose(self, node: Choose) -> str:
        if not node.options:
            raise _FeelTypeError(
                FeelMixedTypesError("a choose", (), node.line, node.column)
            )
        return self._unify(node, "a choose", [self.visit(o) for o in node.options])

    def visit_triple(self, node: Triple) -> str:
        if node.target not in self._vars:
            reason = (
                "it is not a variable"
                if self.state.is_defined(node.target)
                else "it is not defined"
            )
            raise _FeelTypeError(
                FeelInvalidTargetError(node.target, reason, node.line, node.column)
            )
        target_type = self._lookup(node.target, node.line, node.column)
        for name in node.inputs:
            self._lookup(name, node.line, node.column)
        value_type = self.visit(node.value)
        if not _is_value(value_type) or not isinstance(
            typechecking.get_type_assign(target_type, value_type), Success
        ):
            raise _FeelTypeError(
                FeelAssignTypeError(
                    node.target, target_type, value_type, node.line, node.column
                )
            )
        return TRIPLE

    def visit_triple_list(self, node: TripleList) -> str:
        for triple in node.triples:
            self.visit(triple)
        return TRIPLE_LIST


def type_check(expr: FeelExpr, state: State) -> Result[str, Error]:
    """
    Returns the type of expr, or the first type error found. The state must
    already be type checked.
    """
    try:
        return Success(FeelTypeCheckerVisitor(state).visit(expr))
    except _FeelTypeError as exc:
        return Failure(exc.error)


def type_check_condition(expr: FeelExpr, state: State) -> Result[str, Error]:
    """Like type_check, and the expression must be a bool."""
    result = type_check(expr, state)
    if isinstance(result, Success) and result.unwrap() != typechecking.BOOL:
        return Failure(FeelConditionTypeError(result.unwrap(), expr.line, expr.column))
    return result


def type_check_behavior(expr: FeelExpr, state: State) -> Result[str, Error]:
    """Like type_check, and the expression must be a triple or a triple list."""
    result = type_check(expr, state)
    if isinstance(result, Success) and result.unwrap() not in {TRIPLE, TRIPLE_LIST}:
        return Failure(FeelBehaviorTypeError(result.unwrap()))
    return result
