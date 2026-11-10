"""
Type checks a FEEL syntax tree against the variables, constants and enums of a State.

Types are the strings used by ``core.typechecking``: ``bit``, ``byte``, ``short``,
``int``, ``bool``, or the name of an enum. A list of ``T`` is ``list<T>``.
"""

from typing import Final

from returns.result import Failure, Result, Success

from bpmncwpverify.core import typechecking
from bpmncwpverify.core.error import (
    Error,
    FeelAssignTargetError,
    FeelConditionTypeError,
    FeelListTypeError,
    FeelNotAValueError,
    FeelOperatorTypeError,
    FeelUnknownNameError,
    TypingNoTypeError,
)
from bpmncwpverify.core.feel_tree import (
    ARITHMETIC_OPS,
    COMPARISON_OPS,
    LOGIC_OPS,
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
from bpmncwpverify.core.state import State

_NUMERIC_RANK: Final[dict[str, int]] = {
    typechecking.BIT: 0,
    typechecking.BYTE: 1,
    typechecking.SHORT: 2,
    typechecking.INT: 3,
}
_RANK_TYPE: Final[tuple[str, ...]] = (
    typechecking.BIT,
    typechecking.BYTE,
    typechecking.SHORT,
    typechecking.INT,
)
_LIST_PREFIX: Final[str] = "list<"
_ORDERING_OPS: Final[tuple[str, ...]] = ("<", ">", "<=", ">=")


def _is_numeric(type_: str) -> bool:
    return type_ in _NUMERIC_RANK


def _list_of(element_type: str) -> str:
    return f"{_LIST_PREFIX}{element_type}>"


def _unify(ltype: str, rtype: str) -> str | None:
    """The one type both can be seen as, or None. Numbers widen; others must match."""
    if _is_numeric(ltype) and _is_numeric(rtype):
        return _RANK_TYPE[max(_NUMERIC_RANK[ltype], _NUMERIC_RANK[rtype])]
    return ltype if ltype == rtype else None


def _widen(type_: str, at_least: str) -> str:
    return _RANK_TYPE[max(_NUMERIC_RANK[type_], _NUMERIC_RANK[at_least])]


class FeelTypeChecker(FeelVisitor[Result[str, Error]]):
    """
    Visiting an expression returns its type. Visiting a triple or a behavior
    returns ``bool`` when it is well typed; it has no value of its own.
    """

    def __init__(self, state: State) -> None:
        self.state = state

    def visit_number(self, node: Number) -> Result[str, Error]:
        if isinstance(node.value, int):
            return typechecking.get_type_literal(str(node.value))
        return Failure(TypingNoTypeError(str(node.value)))

    def visit_boolean(self, node: Boolean) -> Result[str, Error]:
        return Success(typechecking.BOOL)

    def visit_name(self, node: Name) -> Result[str, Error]:
        if not self.state.is_defined(node.name):
            return Failure(FeelUnknownNameError(node.name))
        type_ = self.state.get_type(node.name).unwrap()
        if type_ == typechecking.ENUM:
            return Failure(FeelNotAValueError(node.name))
        return Success(type_)

    def visit_list_expr(self, node: ListExpr) -> Result[str, Error]:
        element_type = self._element_type("a list", node.items)
        if isinstance(element_type, Failure):
            return element_type
        return Success(_list_of(element_type.unwrap()))

    def visit_choose(self, node: Choose) -> Result[str, Error]:
        return self._element_type("'choose'", node.options)

    def visit_negate(self, node: Negate) -> Result[str, Error]:
        operand = self.visit(node.operand)
        if isinstance(operand, Failure):
            return operand
        type_ = operand.unwrap()
        if not _is_numeric(type_):
            return Failure(FeelOperatorTypeError("-", (type_,)))
        return Success(_widen(type_, typechecking.SHORT))

    def visit_not(self, node: Not) -> Result[str, Error]:
        operand = self.visit(node.operand)
        if isinstance(operand, Failure):
            return operand
        type_ = operand.unwrap()
        if type_ != typechecking.BOOL:
            return Failure(FeelOperatorTypeError("not", (type_,)))
        return Success(typechecking.BOOL)

    def visit_binary(self, node: Binary) -> Result[str, Error]:
        left = self.visit(node.left)
        if isinstance(left, Failure):
            return left
        right = self.visit(node.right)
        if isinstance(right, Failure):
            return right
        return self._binary_type(node.op, left.unwrap(), right.unwrap())

    def visit_if(self, node: If) -> Result[str, Error]:
        condition = self._condition(node.condition)
        if isinstance(condition, Failure):
            return condition
        then_type = self.visit(node.then_branch)
        if isinstance(then_type, Failure):
            return then_type
        else_type = self.visit(node.else_branch)
        if isinstance(else_type, Failure):
            return else_type
        return self._branch_type(then_type.unwrap(), else_type.unwrap())

    def visit_triple(self, node: Triple) -> Result[str, Error]:
        if not any(var.id == node.target.name for var in self.state.vars):
            if not self.state.is_defined(node.target.name):
                return Failure(FeelUnknownNameError(node.target.name))
            return Failure(FeelAssignTargetError(node.target.name))
        for input_ in node.inputs:
            checked = self.visit_name(input_)
            if isinstance(checked, Failure):
                return checked
        target_type = self.state.get_type(node.target.name).unwrap()
        value = self.visit(node.value)
        if isinstance(value, Failure):
            return value
        assigned = typechecking.get_type_assign(target_type, value.unwrap())
        if isinstance(assigned, Failure):
            return assigned
        return Success(typechecking.BOOL)

    def visit_behavior(self, node: Behavior) -> Result[str, Error]:
        for triple in node.triples:
            checked = self.visit_triple(triple)
            if isinstance(checked, Failure):
                return checked
        return Success(typechecking.BOOL)

    def _condition(self, node: FeelNode) -> Result[str, Error]:
        checked = self.visit(node)
        if isinstance(checked, Failure):
            return checked
        type_ = checked.unwrap()
        if type_ != typechecking.BOOL:
            return Failure(FeelConditionTypeError(type_))
        return Success(type_)

    def _branch_type(self, then_type: str, else_type: str) -> Result[str, Error]:
        unified = _unify(then_type, else_type)
        if unified is None:
            return Failure(FeelOperatorTypeError("if", (then_type, else_type)))
        return Success(unified)

    def _element_type(
        self, construct: str, items: tuple[FeelNode, ...]
    ) -> Result[str, Error]:
        if not items:
            return Failure(FeelListTypeError(construct, "it has no elements"))
        element_type: str | None = None
        for item in items:
            checked = self.visit(item)
            if isinstance(checked, Failure):
                return checked
            item_type = checked.unwrap()
            if item_type.startswith(_LIST_PREFIX):
                return Failure(FeelListTypeError(construct, "lists cannot be nested"))
            unified = (
                item_type if element_type is None else _unify(element_type, item_type)
            )
            if unified is None:
                return Failure(
                    FeelListTypeError(
                        construct,
                        f"'{element_type}' and '{item_type}' elements are mixed",
                    )
                )
            element_type = unified
        assert element_type is not None
        return Success(element_type)

    @staticmethod
    def _binary_type(op: str, ltype: str, rtype: str) -> Result[str, Error]:
        error = Failure(FeelOperatorTypeError(op, (ltype, rtype)))
        if op in ARITHMETIC_OPS:
            if _is_numeric(ltype) and _is_numeric(rtype):
                return Success(_widen(_unify(ltype, rtype) or ltype, typechecking.BYTE))
            return error
        if op in LOGIC_OPS:
            if ltype == typechecking.BOOL and rtype == typechecking.BOOL:
                return Success(typechecking.BOOL)
            return error
        assert op in COMPARISON_OPS
        if _is_numeric(ltype) and _is_numeric(rtype):
            return Success(typechecking.BOOL)
        if (
            op not in _ORDERING_OPS
            and ltype == rtype
            and not ltype.startswith(_LIST_PREFIX)
        ):
            return Success(typechecking.BOOL)
        return error


def type_of(node: FeelNode, state: State) -> Result[str, Error]:
    """The type of an expression, or the first typing error found in it."""
    return FeelTypeChecker(state).visit(node)
