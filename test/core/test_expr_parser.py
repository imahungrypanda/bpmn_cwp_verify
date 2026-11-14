# type: ignore
from collections.abc import Iterable

import pytest
from antlr4.error.ErrorStrategy import ParseCancellationException
from returns.pipeline import is_successful

from bpmncwpverify.core.expr import _get_parser


@pytest.fixture(scope="module")
def parenthesis_input() -> Iterable[str]:
    yield "(1 + 1)"


@pytest.fixture(scope="module")
def id_input() -> Iterable[str]:
    yield "a"


@pytest.fixture(scope="module")
def negator_input() -> Iterable[str]:
    yield "-1"


@pytest.fixture(scope="module")
def mult_input() -> Iterable[str]:
    yield "1 * 1"


@pytest.fixture(scope="module")
def div_input() -> Iterable[str]:
    yield "1/1"


@pytest.fixture(scope="module")
def addition_input() -> Iterable[str]:
    yield "1 + 1"


@pytest.fixture(scope="module")
def subtraction_input() -> Iterable[str]:
    yield "1 - 1"


@pytest.fixture(scope="module")
def rel_input() -> Iterable[str]:
    yield "1 == 1"


@pytest.fixture(scope="module")
def not_input() -> Iterable[str]:
    yield "!1"


@pytest.fixture(scope="module")
def and_input() -> Iterable[str]:
    yield "1 && 1"


@pytest.fixture(scope="module")
def or_input() -> Iterable[str]:
    yield "1 || 1"


@pytest.fixture(scope="module")
def bad_input_unaryInBinary() -> Iterable[str]:
    yield "1 ++ 10"


@pytest.fixture(scope="module")
def bad_input_badOperator() -> Iterable[str]:
    yield "a = 10"


@pytest.fixture(scope="module")
def bad_input_binaryInUnary() -> Iterable[str]:
    yield "* 1"


class Test_bad_inputs:
    def test_bad_Unaryinput(self, bad_input_unaryInBinary):
        parser_result = _get_parser(bad_input_unaryInBinary)
        assert is_successful(parser_result)
        parser = parser_result.unwrap()

        with pytest.raises(
            ParseCancellationException, match=r".* extraneous .*"
        ) as exception:
            _ = parser.start()

        assert exception.type is ParseCancellationException
        assert parser.getNumberOfSyntaxErrors() == 1

    def test_bad_Binaryinput(self, bad_input_binaryInUnary):
        parser_result = _get_parser(bad_input_binaryInUnary)
        assert is_successful(parser_result)
        parser = parser_result.unwrap()

        with pytest.raises(
            ParseCancellationException, match=r".* extraneous .*"
        ) as exception:
            _ = parser.start()

        assert exception.type is ParseCancellationException
        assert parser.getNumberOfSyntaxErrors() == 1

    def test_bad_Operatorinput(self, bad_input_badOperator):
        parser_result = _get_parser(bad_input_badOperator)
        assert is_successful(parser_result)
        parser = parser_result.unwrap()

        with pytest.raises(
            ParseCancellationException, match=r".* extraneous .*"
        ) as exception:
            _ = parser.start()

        assert exception.type is ParseCancellationException
        assert parser.getNumberOfSyntaxErrors() == 1


def test_parenthesis_input_test(parenthesis_input):
    parser_result = _get_parser(parenthesis_input)
    parser = parser_result.unwrap()
    id = parser.atom()
    assert id is not None


def test_id_input_test(id_input):
    parser_result = _get_parser(id_input)
    parser = parser_result.unwrap()
    id = parser.atom()
    assert id is not None


def test_negator_input_test(negator_input):
    parser_result = _get_parser(negator_input)
    parser = parser_result.unwrap()
    # tree = parser.start()
    # print("Parse Tree Structure:", tree.toStringTree(recog=parser))
    id = parser.unaryExpr()
    assert id is not None


def test_mult_input_test(mult_input):
    parser_result = _get_parser(mult_input)
    parser = parser_result.unwrap()
    id = parser.mulDivExpr()
    assert id is not None


def test_div_input_test(div_input):
    parser_result = _get_parser(div_input)
    parser = parser_result.unwrap()
    id = parser.mulDivExpr()
    assert id is not None


def test_add_input_test(addition_input):
    parser_result = _get_parser(addition_input)
    parser = parser_result.unwrap()
    id = parser.addSubExpr()
    assert id is not None


def test_subtract_input_test(subtraction_input):
    parser_result = _get_parser(subtraction_input)
    parser = parser_result.unwrap()
    id = parser.addSubExpr()
    assert id is not None


def test_rel_input_test(rel_input):
    parser_result = _get_parser(rel_input)
    parser = parser_result.unwrap()
    id = parser.relExpr()
    assert id is not None


def test_not_input_test(not_input):
    parser_result = _get_parser(not_input)
    parser = parser_result.unwrap()
    id = parser.notExpr()
    assert id is not None


def test_and_input_test(and_input):
    parser_result = _get_parser(and_input)
    parser = parser_result.unwrap()
    id = parser.andExpr()
    assert id is not None


def test_or_input_test(or_input):
    parser_result = _get_parser(or_input)
    parser = parser_result.unwrap()
    id = parser.orExpr()
    assert id is not None


@pytest.mark.parametrize(
    "input_text",
    [
        "a",
        "(a)",
        "a + b",
        "a * b",
        "-a",
        # Unary and Binary Operations
        "-a + b",
        "a + b * c",
        "a * b + c",
        "(a + b) * c",
        "-a * -b",
        # Logical and Relational Operations
        "a < b",
        "a <= b",
        "a == b",
        "a > b",
        "a >= b",
        "!a",
        "!(a && b)",
        "a && b",
        "a || b",
        "a && b || c",
        "(a || b) && c",
        "a < b && c > d",
        "a + b == c - d",
        "(a < b) && (c >= d)",
        # Complex Nested Expressions
        "a * (b + c) / d",
        "a + b * (c - d) / e",
        "-a + (b * c) / (-d + e)",
        "a && (b || !c)",
        "!(a < b) && (c > d)",
        "a < b + c * d",
        "(a + b) <= (c - d * e)",
        "!(a == b) || (c != d)",
        "a + b * c == d / e - f",
        "!a || !b && !c",
        "a < b || (c >= d && e < f)",
        # Complex Combinations
        "((a + b) * c < d) && e",
        "(a / b) * (c + d) - e",
        "a && b || c && d",
        "(a < b || c > d) && (e >= f || g <= h)",
        "(a < b || c > d) && e >= f || g <= h",
        "((a < b || c > d) && e >= f || g <= h) > (a - b - (c - d - g * h))",
        "a + (b * (c - d / e)) >= f",
        "((a && b) || !c) && d",
        # Edge Cases with Nested Parentheses and Unary Operators
        "((((a))))",
        "-(a + b * c)",
        "!(!(a && b))",
        "((((a + b)) * (c - d)))",
        "a * -(b + c)",
        "!((a + b) * (c - d) / e)",
        "((a && b) || (c && d))",
        "!(!(!a))",
        "((a || b) && (!c || d))",
    ],
)
def test_valid_inputs(input_text):
    try:
        _get_parser(input_text)
        assert True
    except SyntaxError as e:
        pytest.fail(f"Valid input raised SyntaxError: {e}")


@pytest.mark.parametrize(
    "input_text",
    [
        "a +",
        "&& b",
        "a ||",
        "(a + b",
        "a + (b * c",
        "a b + c",
        "a * * b",
        "!",
        "a < < b",
        "(a && b))",
        "a + (b * (c - d)",
        "((a + b) * c < d && e",
        "a * (b + c))",
        "a || (b && c",
        "a && b ||",
        "(a || b &&",
        "(a + b))",
        "a && (b || c",
        "((a + b)",
        "a && || b",
        "a || && b",
        "a + * b",
        "a < > b",
        "a * + b",
        "a / && b",
        "a || b +",
        "! && a",
        "+",
        "*",
        "&&",
        "||",
        "(",
        ")",
        "!((a && b) ||)",
        "((a || b) && c ||)",
        "((a && b) || (c < d &&))",
        "((a || (b * c))) || + d",
        "(a || b)) * c",
    ],
)
def test_invalid_inputs(input_text):
    with pytest.raises(ParseCancellationException):
        parser_res = _get_parser(input_text)
        parser = parser_res.unwrap()
        parser.start()
