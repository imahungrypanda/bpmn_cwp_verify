# type: ignore
import pytest
from returns.pipeline import is_successful

from bpmncwpverify.core.error import (
    ExpressionComputationCompatabilityError,
    ExpressionNegatorError,
    ExpressionRelationalNotError,
    ExpressionRelationCompatabilityError,
    ExpressionUnrecognizedID,
)
from bpmncwpverify.core.expr import ExpressionListener
from bpmncwpverify.core.state import State


@pytest.mark.parametrize(
    "state, expression, expression_type",
    [
        ("var a: bit = 1 var b: bit = 0", "a != b", "bool"),
        ("const x: int = 0 var y: short = 1 var z: short = 0", "x + y - z", "int"),
        ("var a: int = 10 var b: byte = 5", "a > b", "bool"),
        ("const x: bool = true var y: bool = false", "!x || y", "bool"),
        (
            "var m: int = 20 var n: short = 10 var o: bool = true",
            "(m >= n) && !o",
            "bool",
        ),
        (
            "var p: int = 15 var q: short = 3 var r: byte = 2",
            "(p + q) * r == p",
            "bool",
        ),
        ("var a: byte = 1 var b: bit = 0", "(a != b) || (a > b)", "bool"),
        (
            "const x: int = 4 var y: short = 2 var z: byte = 1",
            "x * (y + z) < x",
            "bool",
        ),
        ("var i: int = 0 var j: short = 1 var k: bit = 0", "(i + j) > k", "bool"),
        ("var a: int = 5 var b: short = 3 var c: bool = true", "(a > b) && !c", "bool"),
    ],
)
def test_given_good_state_when_build_then_success(state, expression, expression_type):
    sym_table_result = State.from_str(state)

    assert is_successful(sym_table_result)
    state: State = sym_table_result.unwrap()

    expr_checker_result = ExpressionListener.type_check(expression, state)

    assert is_successful(expr_checker_result)

    assert expr_checker_result.unwrap() == expression_type


@pytest.mark.parametrize(
    "state, expression, error",
    [
        ("const a: bit = 0 var b: short = 1", "b + c", ExpressionUnrecognizedID),
        (
            "const a: bit = 0 var b: short = 1",
            "b + a",
            ExpressionComputationCompatabilityError,
        ),
        (
            "const x: int = 0 var y: short = 1 var z: bit = 0",
            "x + y - z",
            ExpressionComputationCompatabilityError,
        ),
        (
            "const a: bit = 0 var b: short = 1 var c: int = 1",
            "a + (b * c)",
            ExpressionComputationCompatabilityError,
        ),
        (
            "const a: short = 0 var b: short = 1 var c: short = 1",
            "a + (b > c)",
            ExpressionComputationCompatabilityError,
        ),
        ("var a: bit = 0", "!a", ExpressionRelationalNotError),
        (
            "var a: bool = false var b: bool = true",
            "a + b",
            ExpressionComputationCompatabilityError,
        ),
        ("var a: bool = false", "-a", ExpressionNegatorError),
        (
            "var a: int = 1 var b: bool = false",
            "a < b",
            ExpressionRelationCompatabilityError,
        ),
    ],
)
def test_given_bad_state_when_build_then_failure(state, expression, error):
    sym_table_result = State.from_str(state)

    assert is_successful(sym_table_result)
    state: State = sym_table_result.unwrap()

    expr_checker_result = ExpressionListener.type_check(expression, state)

    assert not is_successful(expr_checker_result)

    res_error = expr_checker_result.failure()

    assert isinstance(res_error, error)
