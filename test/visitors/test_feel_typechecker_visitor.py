import pytest
from returns.result import Failure, Success

from bpmncwpverify.core.error import (
    FeelAssignTargetError,
    FeelConditionTypeError,
    FeelListTypeError,
    FeelNotAValueError,
    FeelOperatorTypeError,
    FeelUnknownNameError,
    TypingAssignCompatabilityError,
    TypingNoTypeError,
)
from bpmncwpverify.core.feel import (
    parse_behavior,
    parse_expression,
    type_check,
)
from bpmncwpverify.core.feel_tree import Name, Number
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.feel_typechecker_visitor import type_of

STATE = """
enum Color { red green }
enum Size { small large }
const limit: int = 100
var a: int = 0
var b: byte = 0
var s: short = 0
var bit1: bit = 0
var flag: bool = false
var color: Color = red
var size: Size = small
"""


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).bind(lambda s: s.type_check()).unwrap()


def same(result, expected):
    """Errors have no equality; compare the failure's type and fields."""
    if isinstance(expected, Failure) and isinstance(result, Failure):
        a, b = result.failure(), expected.failure()
        return type(a) is type(b) and all(
            getattr(a, f) == getattr(b, f) for f in type(a).__slots__
        )
    return result == expected


def expr_type(state, text):
    return type_of(parse_expression(text).unwrap(), state)


def ok(state, text, expected):
    assert expr_type(state, text) == Success(expected), text


def bad(state, text, error_type):
    result = expr_type(state, text)
    assert isinstance(result, Failure), text
    assert isinstance(result.failure(), error_type), text


# names and literals


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a", "int"),  # state variable
        ("limit", "int"),  # constant
        ("red", "Color"),  # enum value
        ("flag", "bool"),
        ("0", "bit"),
        ("200", "byte"),
        ("1000", "short"),
        ("100000", "int"),
        ("true", "bool"),
    ],
)
def test_names_and_literals(state, text, expected):
    ok(state, text, expected)


def test_unknown_name(state):
    bad(state, "nope", FeelUnknownNameError)


def test_enum_type_is_not_a_value(state):
    bad(state, "Color", FeelNotAValueError)


def test_float_literal_has_no_type(state):
    result = type_of(Number(1.5), state)
    assert result == Failure(TypingNoTypeError("1.5"))


def test_dotted_name_unknown(state):
    assert same(type_of(Name("a.b"), state), Failure(FeelUnknownNameError("a.b")))


# arithmetic


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "**"])
def test_arithmetic_ok(state, op):
    ok(state, f"a {op} b", "int")
    ok(state, f"b {op} 2", "byte")


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "**"])
def test_arithmetic_fails_on_non_numbers(state, op):
    bad(state, f"a {op} flag", FeelOperatorTypeError)
    bad(state, f"red {op} red", FeelOperatorTypeError)


def test_bit_arithmetic_widens(state):
    ok(state, "bit1 + bit1", "byte")


def test_negate(state):
    ok(state, "-b", "short")
    ok(state, "-a", "int")
    bad(state, "-flag", FeelOperatorTypeError)


# comparisons


@pytest.mark.parametrize("op", ["<", ">", "<=", ">=", "=", "!="])
def test_comparison_ok(state, op):
    ok(state, f"a {op} b", "bool")


@pytest.mark.parametrize("op", ["<", ">", "<=", ">="])
def test_ordering_fails_on_non_numbers(state, op):
    bad(state, f"flag {op} flag", FeelOperatorTypeError)
    bad(state, f"red {op} green", FeelOperatorTypeError)
    bad(state, f"a {op} flag", FeelOperatorTypeError)


@pytest.mark.parametrize("op", ["=", "!="])
def test_equality_on_same_kind(state, op):
    ok(state, f"flag {op} true", "bool")
    ok(state, f"color {op} red", "bool")
    bad(state, f"color {op} small", FeelOperatorTypeError)
    bad(state, f"a {op} flag", FeelOperatorTypeError)
    bad(state, f"[a] {op} [a]", FeelOperatorTypeError)


# logic


@pytest.mark.parametrize("op", ["and", "or", "xor"])
def test_logic(state, op):
    ok(state, f"flag {op} a > 1", "bool")
    bad(state, f"flag {op} a", FeelOperatorTypeError)


def test_not(state):
    ok(state, "not flag", "bool")
    bad(state, "not a", FeelOperatorTypeError)


# if


def test_if_ok(state):
    ok(state, "if flag then a else b", "int")
    ok(state, "if flag then red else green", "Color")


def test_if_condition_must_be_bool(state):
    bad(state, "if a then 1 else 2", FeelConditionTypeError)


def test_if_branches_must_agree(state):
    bad(state, "if flag then red else small", FeelOperatorTypeError)
    bad(state, "if flag then a else flag", FeelOperatorTypeError)


# lists and choose


def test_list_ok(state):
    ok(state, "[a, b, 3]", "list<int>")


def test_list_fails_when_mixed(state):
    bad(state, "[a, flag]", FeelListTypeError)


def test_list_fails_on_bad_item(state):
    bad(state, "[a, nope]", FeelUnknownNameError)


def test_list_cannot_be_used_as_a_number(state):
    bad(state, "[a] + 1", FeelOperatorTypeError)


def test_choose_ok(state):
    ok(state, "choose [red, green]", "Color")
    ok(state, "choose [1, a]", "int")


def test_choose_fails_when_mixed(state):
    bad(state, "choose [red, small]", FeelListTypeError)


def test_choose_fails_on_nested_list(state):
    bad(state, "choose [[1], [2]]", FeelListTypeError)


def test_choose_fails_on_unknown_name(state):
    bad(state, "choose [1, nope]", FeelUnknownNameError)


# triples and behaviors


def behavior(state, text):
    return type_check(parse_behavior(text).unwrap(), state)


@pytest.mark.parametrize(
    "text",
    [
        "(a, [b], b + 1)",
        "(color, [], green)",
        "(color, [], choose [red, green])",
        "(a, [b, s], if flag then b else s), (flag, [a], a > 3)",
        "(a, [], 5)",
    ],
)
def test_triple_ok(state, text):
    assert isinstance(behavior(state, text), Success)


def test_triple_unknown_target(state):
    assert same(behavior(state, "(nope, [], 1)"), Failure(FeelUnknownNameError("nope")))


def test_triple_target_must_be_variable(state):
    assert same(
        behavior(state, "(limit, [], 1)"), Failure(FeelAssignTargetError("limit"))
    )
    assert same(
        behavior(state, "(red, [], red)"), Failure(FeelAssignTargetError("red"))
    )


def test_triple_unknown_input(state):
    assert same(
        behavior(state, "(a, [nope], 1)"), Failure(FeelUnknownNameError("nope"))
    )


def test_triple_value_must_fit_target(state):
    assert same(
        behavior(state, "(b, [], 300)"),
        Failure(TypingAssignCompatabilityError("byte", "short")),
    )
    assert same(
        behavior(state, "(color, [], small)"),
        Failure(TypingAssignCompatabilityError("Color", "Size")),
    )
    assert same(
        behavior(state, "(flag, [], 1)"),
        Failure(TypingAssignCompatabilityError("bool", "bit")),
    )


def test_triple_value_error_propagates(state):
    assert isinstance(
        behavior(state, "(a, [], flag + 1)").failure(), FeelOperatorTypeError
    )


def test_behavior_stops_at_bad_triple(state):
    assert isinstance(behavior(state, "(a, [], 1), (nope, [], 1)"), Failure)


# conditions


def condition(state, text):
    return type_check(parse_expression(text).unwrap(), state)


def test_condition_ok(state):
    assert isinstance(condition(state, "a > 3 and flag"), Success)


def test_condition_must_be_bool(state):
    assert same(condition(state, "a + 1"), Failure(FeelConditionTypeError("int")))


def test_condition_error_is_returned(state):
    assert same(condition(state, "nope"), Failure(FeelUnknownNameError("nope")))
