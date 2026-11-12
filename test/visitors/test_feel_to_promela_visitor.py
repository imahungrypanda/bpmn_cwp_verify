# type: ignore
import shutil
import subprocess

import pytest
from returns.result import Success

from bpmncwpverify.core.feel import parse, type_check_behavior, type_check_condition
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.feel_to_promela_visitor import (
    FeelToPromelaError,
    behavior_to_promela,
    condition_to_promela,
)

STATE = """
enum Door {open closed}
enum Light {on off}
const limit: byte = 3
var door: Door = closed
var light: Light = off
var count: byte = 0
var big: int = 0
var flag: bool = false
"""


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).unwrap()


def cond(text, state):
    parsed = parse(text).unwrap()
    assert isinstance(type_check_condition(parsed, state), Success), text
    return condition_to_promela(parsed)


def behavior(text, state):
    parsed = parse(text).unwrap()
    assert isinstance(type_check_behavior(parsed, state), Success), text
    return behavior_to_promela(parsed)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("true", "true"),
        ("false", "false"),
        ("flag", "flag"),
        ("count < 3", "(count < 3)"),
        ("count > 3", "(count > 3)"),
        ("count <= limit", "(count <= limit)"),
        ("count >= 1", "(count >= 1)"),
        ("count = 3", "(count == 3)"),
        ("count != 3", "(count != 3)"),
        ("door = open", "(door == open)"),
        ("count + 1 < big", "((count + 1) < big)"),
        ("count - 1 < big", "((count - 1) < big)"),
        ("count * 2 < big", "((count * 2) < big)"),
        ("big / 2 < count", "((big / 2) < count)"),
        ("-count < 1", "((-count) < 1)"),
        ("count ** 2 < big", "((count * count) < big)"),
        ("count ** 0 = 1", "(1 == 1)"),
        ("(count + 1) * 2 < big", "(((count + 1) * 2) < big)"),
        ("door = open and count < 3", "((door == open) && (count < 3))"),
        ("light = on or count = 3", "((light == on) || (count == 3))"),
        ("flag xor count = 1", "(flag != (count == 1))"),
        ("not flag", "(!flag)"),
        ("not (flag or count = 1)", "(!(flag || (count == 1)))"),
        (
            "(if flag then count else big) < 3",
            "((flag -> count : big) < 3)",
        ),
    ],
)
def test_condition(state, text, expected):
    assert cond(text, state) == expected


def test_if_expression_is_bool_condition(state):
    assert cond("if flag then count < 2 else false", state) == (
        "(flag -> (count < 2) : false)"
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("(door, [], open)", "door = open"),
        ("(count, [count], count + 1)", "count = (count + 1)"),
        ("(flag, [count], count > 1 and not flag)", "flag = ((count > 1) && (!flag))"),
        ("(count, [flag], if flag then 1 else 2)", "count = (flag -> 1 : 2)"),
        ("(big, [count], count ** 3)", "big = (count * count * count)"),
        (
            "((door, [], open), (count, [count], count + 1))",
            "door = open\ncount = (count + 1)",
        ),
        (
            "((count, [], 1), (big, [count], count + 1))",
            "count = 1\nbig = (count + 1)",
        ),
    ],
)
def test_behavior(state, text, expected):
    assert behavior(text, state) == expected


def test_choose_makes_one_branch_per_option(state):
    assert behavior("(light, [], choose [on, off])", state) == (
        "if\n\t:: light = on\n\t:: light = off\nfi"
    )


def test_choose_in_triple_list(state):
    text = "((light, [], choose [on, off]), (count, [count], count + 1))"
    assert behavior(text, state) == (
        "if\n\t:: light = on\n\t:: light = off\nfi\ncount = (count + 1)"
    )


def test_choose_inside_expression(state):
    assert behavior("(count, [count], count + choose [1, 2])", state) == (
        "if\n\t:: count = (count + 1)\n\t:: count = (count + 2)\nfi"
    )


def test_two_chooses_make_every_combination(state):
    out = behavior("(big, [], choose [1, 2] * choose [10, 20])", state)
    assert out.count(":: big =") == 4
    for value in ("(1 * 10)", "(1 * 20)", "(2 * 10)", "(2 * 20)"):
        assert f"big = {value}" in out


def test_choose_in_if_branches(state):
    out = behavior("(count, [flag], if flag then choose [1, 2] else 3)", state)
    assert out == ("if\n\t:: count = (flag -> 1 : 3)\n\t:: count = (flag -> 2 : 3)\nfi")


def test_choose_repeated_option_is_one_branch(state):
    out = behavior("(count, [], choose [1, 1, 2])", state)
    assert out.count(":: count =") == 2


def test_single_option_choose_is_plain_assignment(state):
    assert behavior("(count, [], choose [4])", state) == "count = 4"


def test_choose_in_condition_is_an_error(state):
    parsed = parse("count = choose [1, 2]").unwrap()
    with pytest.raises(FeelToPromelaError, match="choose"):
        condition_to_promela(parsed)


def test_power_needs_literal_exponent(state):
    parsed = parse("count ** limit < big").unwrap()
    with pytest.raises(FeelToPromelaError, match=r"\*\*"):
        condition_to_promela(parsed)
    parsed = parse("count ** -1 < big").unwrap()
    with pytest.raises(FeelToPromelaError, match=r"\*\*"):
        condition_to_promela(parsed)


def test_bare_list_is_an_error():
    with pytest.raises(FeelToPromelaError, match="list"):
        condition_to_promela(parse("[1, 2]").unwrap())


def test_behavior_must_be_triple():
    with pytest.raises(FeelToPromelaError, match="triple"):
        behavior_to_promela(parse("1 + 2").unwrap())


# SPIN


needs_spin = pytest.mark.skipif(
    shutil.which("spin") is None or shutil.which("gcc") is None,
    reason="needs spin and gcc",
)

PREAMBLE = """
mtype = { open, closed, on, off }
mtype door = closed
mtype light = off
byte count = 0
int big = 0
bool flag = false
"""


def spin_reaches(tmp_path, statements, check):
    """True if SPIN can reach a state where `check` holds after `statements`."""
    model = (
        PREAMBLE
        + f"\nactive proctype main() {{\n{statements}\nassert(!({check}))\n}}\n"
    )
    (tmp_path / "m.pml").write_text(model)

    def run(*cmd):
        return subprocess.run(
            cmd, cwd=tmp_path, capture_output=True, text=True, check=True
        )

    run("spin", "-a", "m.pml")
    run("gcc", "-o", "pan", "pan.c")
    out = run("./pan").stdout
    return "errors: 1" in out


@needs_spin
@pytest.mark.parametrize("light, reached", [("on", True), ("off", True)])
def test_spin_reaches_each_choice(state, tmp_path, light, reached):
    stmts = behavior("(light, [], choose [on, off])", state)
    assert spin_reaches(tmp_path, stmts, f"light == {light}") is reached


@needs_spin
@pytest.mark.parametrize("value", [1, 2, 5])
def test_spin_reaches_each_numeric_choice(state, tmp_path, value):
    stmts = behavior("(count, [], choose [1, 2, 5])", state)
    assert spin_reaches(tmp_path, stmts, f"count == {value}")


@needs_spin
def test_spin_does_not_reach_unchosen_value(state, tmp_path):
    stmts = behavior("(count, [], choose [1, 2])", state)
    assert not spin_reaches(tmp_path, stmts, "count == 3")


@needs_spin
@pytest.mark.parametrize("value", [11, 12, 21, 22])
def test_spin_reaches_each_choose_combination(state, tmp_path, value):
    stmts = behavior("(big, [], choose [10, 20] + choose [1, 2])", state)
    assert spin_reaches(tmp_path, stmts, f"big == {value}")


@needs_spin
def test_spin_triple_list_sees_earlier_assignment(state, tmp_path):
    stmts = behavior("((count, [], choose [1, 2]), (big, [count], count * 10))", state)
    assert spin_reaches(tmp_path, stmts, "big == 20")
    assert not spin_reaches(tmp_path, stmts, "big == 15")


@needs_spin
def test_spin_condition_evaluates(state, tmp_path):
    stmts = behavior("((count, [], 2), (door, [], open))", state)
    guard = cond("door = open and count < 3 and not flag", state)
    assert spin_reaches(tmp_path, stmts, guard)
    assert not spin_reaches(tmp_path, stmts, cond("count ** 3 < 8", state))
