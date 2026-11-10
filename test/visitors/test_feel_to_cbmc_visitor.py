import shutil
import subprocess

import pytest
from returns.result import Failure

from bpmncwpverify.core.error import FeelCbmcUnsupportedError
from bpmncwpverify.core.feel import parse_behavior, parse_expression, type_check
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.feel_to_cbmc_visitor import (
    behavior_to_c,
    condition_to_c,
)

STATE = """
enum Color { red green }
const limit: int = 100
var a: int = 0
var b: byte = 0
var c: int = 0
var flag: bool = false
var other: bool = false
var color: Color = red
"""

PRELUDE = """#include <assert.h>
#include <stdbool.h>
unsigned int nondet_uint(void);
#define limit 100
enum Color { red, green };
int a = 0; unsigned char b = 0; int c = 0;
bool flag = false; bool other = false; enum Color color = red;
"""

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


@pytest.fixture(scope="module")
def state() -> State:
    return State.from_str(STATE).bind(lambda s: s.type_check()).unwrap()


def cond(state, text):
    node = parse_expression(text).bind(lambda n: type_check(n, state)).unwrap()
    return condition_to_c(node).unwrap()


def behavior(state, text):
    node = parse_behavior(text).bind(lambda n: type_check(n, state)).unwrap()
    return behavior_to_c(node).unwrap()


def run_cbmc(tmp_path, body):
    source = tmp_path / "t.c"
    source.write_text(f"{PRELUDE}\nint main(void) {{\n{body}\nreturn 0;\n}}\n")
    done = subprocess.run(
        ["cbmc", str(source), "--unwind", "5"], capture_output=True, text=True
    )
    return done.returncode, done.stdout


def holds(tmp_path, body):
    code, out = run_cbmc(tmp_path, body)
    assert "VERIFICATION" in out, out
    return code == 0


@pytest.mark.parametrize(
    "text, expected",
    [
        ("42 = 42", "(42 == 42)"),
        ("flag = true", "(flag == true)"),
        ("flag = false", "(flag == false)"),
        ("a = 0", "(a == 0)"),
        ("limit = 1", "(limit == 1)"),
        ("a + 1 = 0", "((a + 1) == 0)"),
        ("a - b = 0", "((a - b) == 0)"),
        ("a * 2 = 0", "((a * 2) == 0)"),
        ("a / 2 > 1", "((a / 2) > 1)"),
        ("-a < 0", "((-a) < 0)"),
        ("a < 1", "(a < 1)"),
        ("a > 1", "(a > 1)"),
        ("a <= 1", "(a <= 1)"),
        ("a >= 1", "(a >= 1)"),
        ("a != 1", "(a != 1)"),
        ("flag and other", "(flag && other)"),
        ("flag or other", "(flag || other)"),
        ("flag xor other", "(flag != other)"),
        ("not flag", "(!flag)"),
        ("color = red", "(color == red)"),
        ("a ** 2 = 4", "((a * a) == 4)"),
        ("a ** 0 = 1", "(1 == 1)"),
        ("(if flag then a else b) > 1", "((flag ? a : b) > 1)"),
    ],
)
def test_conditions(state, text, expected):
    result = cond(state, text)
    assert result.statements == ()
    assert result.expr == expected


def test_nested_precedence_is_kept_by_parentheses(state):
    assert cond(state, "(a + 1) * 2 = 4").expr == "(((a + 1) * 2) == 4)"


def test_dotted_name_is_kept():
    from bpmncwpverify.core.feel_tree import Name

    assert condition_to_c(Name("x.y")).unwrap().expr == "x.y"


def test_single_triple(state):
    assert behavior(state, "(a, [b], b + 1)") == ("a = (b + 1);",)


def test_several_triples_in_order(state):
    assert behavior(state, "(a, [b], b), (c, [a], a * 2)") == (
        "a = b;",
        "c = (a * 2);",
    )


def test_boolean_and_enum_targets(state):
    assert behavior(state, "(flag, [], true), (color, [], green)") == (
        "flag = true;",
        "color = green;",
    )


def test_triple_node_alone(state):
    node = parse_behavior("(a, [], 1)").unwrap().triples[0]
    assert behavior_to_c(node).unwrap() == ("a = 1;",)


def test_if_value(state):
    assert behavior(state, "(a, [flag, b], if flag then b else 0)") == (
        "a = (flag ? b : 0);",
    )


def test_choose_in_behavior(state):
    lines = behavior(state, "(a, [], choose [1, 2, 3])")
    assert lines == (
        "{",
        "unsigned int feel_choose_0 = nondet_uint();",
        "a = (feel_choose_0 == 0 ? 1 : feel_choose_0 == 1 ? 2 : 3);",
        "}",
    )


def test_choose_names_are_distinct_across_triples(state):
    lines = behavior(state, "(a, [], choose [1, 2]), (c, [], choose [3, 4])")
    assert sum("nondet_uint" in line for line in lines) == 2
    assert "feel_choose_0" in lines[1] and "feel_choose_1" in "".join(lines)


def test_choose_with_one_option_is_just_the_option(state):
    assert behavior(state, "(a, [], choose [7])") == ("a = 7;",)


def test_choose_in_condition_comes_with_statements(state):
    result = cond(state, "choose [1, 2] = a")
    assert result.statements == ("unsigned int feel_choose_0 = nondet_uint();",)
    assert result.expr == "((feel_choose_0 == 0 ? 1 : 2) == a)"


def test_choose_picks_once_per_use(state):
    result = cond(state, "choose [1, 2] = choose [1, 2]")
    assert len(result.statements) == 2


def test_prefix(state):
    node = parse_expression("choose [a, b] = 1").unwrap()
    result = condition_to_c(node, prefix="t1").unwrap()
    assert "t1_choose_0" in result.statements[0]


def unsupported(result, construct):
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, FeelCbmcUnsupportedError)
    assert error.construct == construct


def test_list_is_unsupported(state):
    node = parse_expression("[1, 2]").unwrap()
    unsupported(condition_to_c(node), "a list")


def test_variable_exponent_is_unsupported(state):
    node = parse_expression("a ** b = 1").unwrap()
    unsupported(condition_to_c(node), "'**'")


def test_huge_and_negative_exponent_are_unsupported(state):
    unsupported(condition_to_c(parse_expression("a ** 17 = 1").unwrap()), "'**'")
    unsupported(condition_to_c(parse_expression("a ** -1 = 1").unwrap()), "'**'")


def test_real_number_is_unsupported(state):
    node = parse_expression("a = 1.5").unwrap()
    unsupported(condition_to_c(node), "the number 1.5")


def test_error_inside_behavior(state):
    node = parse_behavior("(a, [], 2 ** a)").unwrap()
    unsupported(behavior_to_c(node), "'**'")


@needs_cbmc
@pytest.mark.parametrize(
    "text, holds_",
    [
        ("(a, [], 2 ** 3), (c, [a], a / 3)", "a == 8 && c == 2"),
        ("(a, [], 7 - 10), (c, [a], -a * 2)", "a == -3 && c == 6"),
        ("(a, [], if 1 < 2 then 5 else 6)", "a == 5"),
        ("(flag, [], true xor false), (other, [flag], not flag)", "flag && !other"),
        ("(color, [], green), (a, [color], if color = green then 1 else 2)", "a == 1"),
        ("(a, [limit], limit - 1)", "a == 99"),
    ],
)
def test_c_agrees_with_feel(state, tmp_path, text, holds_):
    body = "\n".join(behavior(state, text)) + f"\nassert({holds_});"
    assert holds(tmp_path, body)


@needs_cbmc
def test_choose_reaches_each_choice(state, tmp_path):
    body = "\n".join(behavior(state, "(a, [], choose [1, 2, 3])"))
    assert holds(tmp_path, body + "\nassert(a >= 1 && a <= 3);")
    for value in (1, 2, 3):
        # CBMC finds a run that reaches each value, so "never this value" fails
        assert not holds(tmp_path, body + f"\nassert(a != {value});"), value
    assert not holds(tmp_path, body + "\nassert(a != 3);")


@needs_cbmc
def test_choose_in_condition_reaches_both_outcomes(state, tmp_path):
    result = cond(state, "choose [1, 2] = 1")
    pre = "\n".join(result.statements)
    assert not holds(tmp_path, f"{pre}\nassert(!{result.expr});")
    assert not holds(tmp_path, f"{pre}\nassert({result.expr});")


@needs_cbmc
def test_choose_nested_and_inside_if_compiles_and_reaches_all(state, tmp_path):
    body = "\n".join(
        behavior(state, "(a, [flag], if flag then 0 else choose [1, choose [2, 3]])")
    )
    assert holds(tmp_path, body + "\nassert(a >= 1 && a <= 3);")
    for value in (1, 2, 3):
        assert not holds(tmp_path, body + f"\nassert(a != {value});"), value
