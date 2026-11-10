import re
import shutil
import subprocess

import pytest
from returns.result import Failure

from bpmncwpverify.core.error import FeelUnsupportedError
from bpmncwpverify.core.feel import parse_behavior, parse_expression, type_check
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.feel_to_promela_visitor import (
    FeelToPromelaVisitor,
    behavior_to_promela,
    condition_to_promela,
)

STATE = """
const limit: int = 100
var a: int = 0
var b: byte = 0
var flag: bool = false
var other: bool = false
"""


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).bind(lambda s: s.type_check()).unwrap()


def cond(state, text):
    node = parse_expression(text).unwrap()
    type_check(node, state).unwrap()
    return condition_to_promela(node).unwrap()


def behavior(state, text):
    node = parse_behavior(text).unwrap()
    type_check(node, state).unwrap()
    return behavior_to_promela(node).unwrap()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1", "1"),
        ("true", "true"),
        ("false", "false"),
        ("flag", "flag"),
        ("a + 1", "(a + 1)"),
        ("a - b", "(a - b)"),
        ("a * 2 + 1", "((a * 2) + 1)"),
        ("a * (2 + 1)", "(a * (2 + 1))"),
        ("a / 2 > 1", "((a / 2) > 1)"),
        ("-a < 0", "((-a) < 0)"),
        ("a ** 3 > 0", "((a * a * a) > 0)"),
        ("a ** 0 = 1", "(1 == 1)"),
        ("a < 1", "(a < 1)"),
        ("a > 1", "(a > 1)"),
        ("a <= 1", "(a <= 1)"),
        ("a >= 1", "(a >= 1)"),
        ("a = 1", "(a == 1)"),
        ("a != 1", "(a != 1)"),
        ("flag and other", "(flag && other)"),
        ("flag or other", "(flag || other)"),
        ("flag xor other", "(flag != other)"),
        ("not flag", "(!flag)"),
        ("(if flag then a else b) > 0", "((flag -> a : b) > 0)"),
    ],
)
def test_expression(state, text, expected):
    node = parse_expression(text).unwrap()
    assert FeelToPromelaVisitor().visit(node).unwrap() == expected


def test_not_expression(state):
    assert cond(state, "not flag") == "(!flag)"


def test_single_triple(state):
    assert behavior(state, "(a, [b], b + 1)") == "a = (b + 1)"


def test_several_triples(state):
    assert behavior(state, "(a, [], 1), (flag, [a], a > 0)") == "a = 1\nflag = (a > 0)"


def test_if_value(state):
    assert (
        behavior(state, "(a, [flag, b], if flag then b else 2)")
        == "a = (flag -> b : 2)"
    )


def test_choose_value(state):
    assert behavior(state, "(a, [], choose [1, 2, b])") == (
        "if\n:: a = 1\n:: a = 2\n:: a = b\nfi"
    )


def test_choose_nested_in_expression(state):
    assert behavior(state, "(a, [], choose [1, 2] + choose [10, 20])") == (
        "if\n:: a = (1 + 10)\n:: a = (1 + 20)\n:: a = (2 + 10)\n:: a = (2 + 20)\nfi"
    )


def test_choose_of_booleans(state):
    assert behavior(state, "(flag, [], choose [true, false])") == (
        "if\n:: flag = true\n:: flag = false\nfi"
    )


def test_choose_in_condition_is_unsupported(state):
    node = parse_expression("choose [true, false]").unwrap()
    result = condition_to_promela(node)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelUnsupportedError)


def test_single_option_choose_in_condition(state):
    assert cond(state, "choose [a > 1]") == "(a > 1)"


def test_unsupported_exponent(state):
    node = parse_expression("a ** b > 1").unwrap()
    result = condition_to_promela(node)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelUnsupportedError)


def test_list_is_unsupported(state):
    node = parse_behavior("(a, [], [1, 2])").unwrap()
    result = behavior_to_promela(node)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelUnsupportedError)


@pytest.mark.skipif(shutil.which("spin") is None, reason="spin is not installed")
def test_choose_reaches_every_choice_in_spin(state, tmp_path):
    values = [1, 2, 3]
    statements = behavior(state, "(a, [], choose [1, 2, 3])")
    flag_stmts = behavior(state, "(flag, [], choose [true, false])")
    # One run per value: assert a != v must fail for each v, so SPIN reaches it.
    for value in values:
        model = f"""
byte a = 0
bool flag = false
active proctype p() {{
{statements}
assert(a != {value})
}}
"""
        assert _spin_finds_violation(tmp_path, model), value
    # And no other value is reachable.
    model = f"""
byte a = 0
bool flag = false
active proctype p() {{
{statements}
assert(a == 1 || a == 2 || a == 3)
}}
"""
    assert not _spin_finds_violation(tmp_path, model)
    for flag_value in ("true", "false"):
        model = f"""
byte a = 0
bool flag = false
active proctype p() {{
{flag_stmts}
assert(flag != {flag_value})
}}
"""
        assert _spin_finds_violation(tmp_path, model), flag_value


@pytest.mark.skipif(shutil.which("spin") is None, reason="spin is not installed")
def test_expressions_run_in_spin(state, tmp_path):
    statements = behavior(
        state,
        "(a, [b], if b > 1 then b ** 2 - -1 else 0), (flag, [a], a > 4 xor other)",
    )
    model = f"""
byte b = 3
int a = 0
bool flag = false
bool other = false
active proctype p() {{
{statements}
assert(a == 10 && flag == true)
}}
"""
    assert not _spin_finds_violation(tmp_path, model)


def _spin_finds_violation(tmp_path, model):
    (tmp_path / "m.pml").write_text(model)
    out = subprocess.run(
        ["spin", "-run", "-a", "m.pml"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    text = out.stdout + out.stderr
    assert "syntax error" not in text, text
    match = re.search(r"errors: (\d+)", text)
    assert match, text
    return int(match.group(1)) > 0
