# type: ignore
import pytest
from returns.result import Failure, Success

from bpmncwpverify.core.error import (
    FeelAssignTypeError,
    FeelBehaviorTypeError,
    FeelConditionTypeError,
    FeelInvalidTargetError,
    FeelMixedTypesError,
    FeelNumberTypeError,
    FeelOperatorTypeError,
    FeelUnknownNameError,
)
from bpmncwpverify.core.feel import (
    parse,
    type_check,
    type_check_behavior,
    type_check_condition,
)
from bpmncwpverify.core.feel_tree import Number
from bpmncwpverify.core.state import State

STATE = """
enum Door {open closed}
enum Light {on off}
const limit: byte = 3
var door: Door = closed
var light: Light = off
var count: byte = 0
var big: int = 0
var flag: bool = false
var b: bit = 0
"""


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).unwrap()


def check(text, state, fn=type_check):
    parsed = parse(text)
    assert isinstance(parsed, Success), text
    return fn(parsed.unwrap(), state)


@pytest.mark.parametrize(
    "text, expected",
    [
        # literals
        ("0", "bit"),
        ("200", "byte"),
        ("1000", "short"),
        ("100000", "int"),
        ("true", "bool"),
        # names: variable, constant, enum value, dotted-free
        ("count", "byte"),
        ("limit", "byte"),
        ("open", "Door"),
        ("door", "Door"),
        # lists
        ("[1, 2, 3]", "list of byte"),
        ("[count, big]", "list of int"),
        ("[open, closed]", "list of Door"),
        # arithmetic
        ("count + 1", "byte"),
        ("b + b", "byte"),
        ("count - big", "int"),
        ("count * 2", "byte"),
        ("big / count", "int"),
        ("count ** 2", "int"),
        ("-count", "short"),
        ("-big", "int"),
        # comparisons
        ("count < 3", "bool"),
        ("count > big", "bool"),
        ("count <= limit", "bool"),
        ("count >= 1", "bool"),
        ("count = 3", "bool"),
        ("count != big", "bool"),
        ("door = open", "bool"),
        ("flag = true", "bool"),
        # logic
        ("flag and true", "bool"),
        ("flag or count < 3", "bool"),
        ("flag xor flag", "bool"),
        ("not flag", "bool"),
        # if
        ("if flag then 1 else 2", "byte"),
        ("if flag then count else big", "int"),
        ("if flag then open else closed", "Door"),
        # choose
        ("choose [on, off]", "Light"),
        ("choose [1, count, 300]", "short"),
        # triples
        ("(door, [], open)", "triple"),
        ("(count, [count], count + 1)", "triple"),
        ("(light, [], choose [on, off])", "triple"),
        ("(big, [count], count)", "triple"),
        (
            "((light, [], choose [on, off]), (count, [count], count + 1))",
            "triple list",
        ),
    ],
)
def test_given_well_typed_when_type_check_then_type(text, expected, state):
    assert check(text, state) == Success(expected)


@pytest.mark.parametrize(
    "text, error",
    [
        # names
        ("nope", FeelUnknownNameError),
        ("Door", FeelUnknownNameError),
        ("count + nope", FeelUnknownNameError),
        # number
        ("2.5", FeelNumberTypeError),
        ("3000000000", FeelNumberTypeError),
        # list
        ("[1, true]", FeelMixedTypesError),
        ("[open, on]", FeelMixedTypesError),
        # arithmetic
        ("count + flag", FeelOperatorTypeError),
        ("door - 1", FeelOperatorTypeError),
        ("flag * flag", FeelOperatorTypeError),
        ("count / open", FeelOperatorTypeError),
        ("flag ** 2", FeelOperatorTypeError),
        ("-flag", FeelOperatorTypeError),
        ("-open", FeelOperatorTypeError),
        ("[1] + 1", FeelOperatorTypeError),
        # comparisons
        ("count < flag", FeelOperatorTypeError),
        ("door > open", FeelOperatorTypeError),
        ("flag <= true", FeelOperatorTypeError),
        ("count >= open", FeelOperatorTypeError),
        ("count = flag", FeelOperatorTypeError),
        ("door != on", FeelOperatorTypeError),
        # logic
        ("count and flag", FeelOperatorTypeError),
        ("flag or 1", FeelOperatorTypeError),
        ("count xor count", FeelOperatorTypeError),
        ("not count", FeelOperatorTypeError),
        # if
        ("if count then 1 else 2", FeelConditionTypeError),
        ("if flag then 1 else true", FeelMixedTypesError),
        # choose
        ("choose [1, true]", FeelMixedTypesError),
        ("choose [on, open]", FeelMixedTypesError),
        # triples
        ("(nope, [], 1)", FeelInvalidTargetError),
        ("(limit, [], 1)", FeelInvalidTargetError),
        ("(open, [], open)", FeelInvalidTargetError),
        ("(count, [nope], 1)", FeelUnknownNameError),
        ("(count, [], true)", FeelAssignTypeError),
        ("(count, [], 1000)", FeelAssignTypeError),
        ("(door, [], on)", FeelAssignTypeError),
        ("(count, [], [1])", FeelAssignTypeError),
        ("(light, [], choose [on, open])", FeelMixedTypesError),
        ("((count, [], 1), (door, [], 1))", FeelAssignTypeError),
        ("(count, [], nope)", FeelUnknownNameError),
        ("(b, [], count)", FeelAssignTypeError),
    ],
)
def test_given_ill_typed_when_type_check_then_error(text, error, state):
    result = check(text, state)
    assert isinstance(result, Failure), text
    assert isinstance(result.failure(), error), (text, result.failure())


def test_given_nested_triple_when_type_check_then_error(state):
    assert isinstance(check("(count, [], 1) + 1", state), Failure)
    assert isinstance(check("[(count, [], 1)]", state), Failure)
    assert isinstance(
        check("if flag then (count, [], 1) else (count, [], 2)", state), Failure
    )


def test_given_later_triple_when_type_check_then_sees_state(state):
    text = "((count, [], 1), (big, [count], count + 1))"
    assert check(text, state) == Success("triple list")


def test_given_float_node_when_type_check_then_error(state):
    assert isinstance(type_check(Number(2.5), state), Failure)


def test_given_deeply_nested_binary_ops_when_type_check_then_type(state):
    text = " + ".join(["count"] * 100)
    assert check(text, state) == Success("byte")


@pytest.mark.parametrize(
    "text, ok",
    [
        ("door = open and count < 3", True),
        ("light = on or count = 3", True),
        ("count + 1", False),
        ("(door, [], open)", False),
        ("nope", False),
    ],
)
def test_given_condition_when_type_check_condition_then_bool_required(text, ok, state):
    result = check(text, state, type_check_condition)
    assert isinstance(result, Success) == ok
    if text == "count + 1":
        assert isinstance(result.failure(), FeelConditionTypeError)


@pytest.mark.parametrize(
    "text, ok",
    [
        ("(door, [], open)", True),
        ("((light, [], choose [on, off]), (count, [count], count + 1))", True),
        ("door = open", False),
        ("count", False),
        ("(count, [], true)", False),
    ],
)
def test_given_behavior_when_type_check_behavior_then_triples_required(text, ok, state):
    result = check(text, state, type_check_behavior)
    assert isinstance(result, Success) == ok
    if text == "door = open":
        assert isinstance(result.failure(), FeelBehaviorTypeError)
