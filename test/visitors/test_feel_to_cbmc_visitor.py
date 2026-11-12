# type: ignore
import subprocess

import pytest
from returns.result import Failure, Success

from bpmncwpverify.core.error import FeelCbmcUnsupportedError
from bpmncwpverify.core.feel import parse, type_check_behavior, type_check_condition
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.feel_to_cbmc_visitor import (
    behavior_to_c,
    condition_to_c,
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

DECLS = """#include <stdbool.h>
unsigned int nondet_uint(void);
#define limit 3
typedef enum { open, closed } Door;
typedef enum { on, off } Light;
Door door = closed;
Light light = off;
unsigned char count = 0;
int big = 0;
bool flag = false;
"""


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).unwrap()


def cond(text, state):
    parsed = parse(text).unwrap()
    assert isinstance(type_check_condition(parsed, state), Success), text
    return condition_to_c(parsed)


def behavior(text, state):
    parsed = parse(text).unwrap()
    assert isinstance(type_check_behavior(parsed, state), Success), text
    return behavior_to_c(parsed)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("true", "true"),
        ("false", "false"),
        ("flag", "flag"),
        ("count < 3", "(count < 3)"),
        ("count <= limit", "(count <= limit)"),
        ("big > 1", "(big > 1)"),
        ("big >= 1", "(big >= 1)"),
        ("door = open", "(door == open)"),
        ("door != open", "(door != open)"),
        ("big + 1 = 2", "((big + 1) == 2)"),
        ("big - 1 = 2", "((big - 1) == 2)"),
        ("big * 2 = 2", "((big * 2) == 2)"),
        ("big / 2 = 2", "((big / 2) == 2)"),
        ("-big < 0", "((-big) < 0)"),
        ("big ** 2 = 4", "((big * big) == 4)"),
        ("big ** 0 = 1", "(1 == 1)"),
        ("not flag", "(!flag)"),
        ("flag and true", "(flag && true)"),
        ("flag or true", "(flag || true)"),
        ("flag xor true", "(flag != true)"),
        ("door = open and count < 3", "((door == open) && (count < 3))"),
        ("(if flag then big else 2) = 2", "((flag ? big : 2) == 2)"),
        ("(big + 1) * 2 = 4", "(((big + 1) * 2) == 4)"),
    ],
)
def test_condition(state, text, expected):
    assert cond(text, state) == Success(expected)


def test_xor_of_comparisons_is_logical(state):
    # 2 and 1 are both true, so xor is false even though 2 != 1
    assert cond("(big > 0) xor (big > 1)", state) == Success("((big > 0) != (big > 1))")


@pytest.mark.parametrize(
    "text, construct",
    [
        ("choose [true, false] = flag", "choose"),
        ("big ** count = 1", "'**'"),
        ("big ** 9 = 1", "'**'"),
        ("big ** -1 = 1", "'**'"),
    ],
)
def test_condition_unsupported(state, text, construct):
    parsed = parse(text).unwrap()
    result = condition_to_c(parsed)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelCbmcUnsupportedError)
    assert construct in result.failure().construct


def test_list_is_unsupported():
    result = condition_to_c(parse("[1, 2]").unwrap())
    assert isinstance(result.failure(), FeelCbmcUnsupportedError)
    assert result.failure().construct == "a list"


def test_float_is_unsupported():
    result = condition_to_c(parse("2.5").unwrap())
    assert isinstance(result.failure(), FeelCbmcUnsupportedError)


def test_non_behavior_is_unsupported():
    result = behavior_to_c(parse("1").unwrap())
    assert isinstance(result.failure(), FeelCbmcUnsupportedError)


def test_triple(state):
    assert behavior("(door, [], open)", state) == Success(["{", "  door = open;", "}"])


def test_triple_inputs_are_not_in_the_c(state):
    assert behavior("(count, [count], count + 1)", state) == Success(
        ["{", "  count = (count + 1);", "}"]
    )


def test_triple_list_runs_in_order(state):
    result = behavior(
        "((light, [], choose [on, off]), (count, [count], count + 1))", state
    )
    assert result == Success(
        [
            "{",
            "  unsigned int feel_choice_0 = nondet_uint();",
            "  __CPROVER_assume(feel_choice_0 < 2u);",
            "  light = (feel_choice_0 == 0u ? on : off);",
            "}",
            "{",
            "  count = (count + 1);",
            "}",
        ]
    )


def test_choose_with_three_options_and_nesting(state):
    lines = behavior("(big, [], (choose [1, 2, 3]) + choose [10, 20])", state).unwrap()
    text = "\n".join(lines)
    assert "feel_choice_0 < 3u" in text
    assert "feel_choice_1 < 2u" in text
    assert "(feel_choice_0 == 0u ? 1 : (feel_choice_0 == 1u ? 2 : 3))" in text


def test_choose_with_one_option_needs_no_selector(state):
    assert behavior("(big, [], choose [7])", state) == Success(["{", "  big = 7;", "}"])


def test_if_in_triple(state):
    assert behavior("(big, [flag], if flag then 1 else 2)", state) == Success(
        ["{", "  big = (flag ? 1 : 2);", "}"]
    )


def run_cbmc(tmp_path, body, extra=""):
    src = tmp_path / "model.c"
    src.write_text(f"{DECLS}\nint main(void) {{\n{body}\n{extra}\nreturn 0;\n}}\n")
    return subprocess.run(
        ["cbmc", str(src)],
        capture_output=True,
        text=True,
    ).stdout


def test_generated_c_compiles_and_runs_in_cbmc(tmp_path, state):
    lines = behavior(
        "((light, [], choose [on, off]), (count, [count], count + 1),"
        " (big, [count], if count = 1 then count ** 2 else 5))",
        state,
    ).unwrap()
    out = run_cbmc(
        tmp_path,
        "\n".join(lines),
        '__CPROVER_assert(count == 1 && big == 1, "later triples see earlier");',
    )
    assert "VERIFICATION SUCCESSFUL" in out


def test_cbmc_reaches_each_choice(tmp_path, state):
    lines = behavior("(count, [], choose [1, 2, 3])", state).unwrap()
    for value in (1, 2, 3):
        out = run_cbmc(
            tmp_path,
            "\n".join(lines),
            f'__CPROVER_assert(count != {value}, "reached {value}");',
        )
        assert "VERIFICATION FAILED" in out, value
    out = run_cbmc(
        tmp_path,
        "\n".join(lines),
        '__CPROVER_assert(count >= 1 && count <= 3, "only the options");',
    )
    assert "VERIFICATION SUCCESSFUL" in out


def test_cbmc_reaches_each_enum_choice(tmp_path, state):
    lines = behavior("(light, [], choose [on, off])", state).unwrap()
    for value in ("on", "off"):
        out = run_cbmc(
            tmp_path,
            "light = on; " + "\n".join(lines),
            f'__CPROVER_assert(light != {value}, "reached {value}");',
        )
        assert "VERIFICATION FAILED" in out, value


def test_cbmc_condition(tmp_path, state):
    c = cond("door = open and count < 3", state).unwrap()
    out = run_cbmc(
        tmp_path,
        f'door = open; count = 2; __CPROVER_assert({c}, "holds");'
        f' count = 3; __CPROVER_assert(!{c}, "fails");',
    )
    assert "VERIFICATION SUCCESSFUL" in out
