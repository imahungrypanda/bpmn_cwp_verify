import pytest
from returns.result import Failure, Success

from bpmncwpverify.core.error import (
    FeelParseError,
    FeelUnsupportedError,
    get_error_message,
)
from bpmncwpverify.core.feel import parse_behavior, parse_expression
from bpmncwpverify.core.feel_tree import (
    Behavior,
    Binary,
    Boolean,
    Choose,
    FeelVisitor,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
)


def expr(text):
    result = parse_expression(text)
    assert isinstance(result, Success), text
    return result.unwrap()


@pytest.mark.parametrize(
    ["text", "expected"],
    [
        ("42", Number(42)),
        ("1.5", Number(1.5)),
        ("true", Boolean(True)),
        ("false", Boolean(False)),
        ("x", Name("x")),
        ("a.b.c", Name("a.b.c")),
        ("[]", ListExpr(())),
        ("[a, 1, true]", ListExpr((Name("a"), Number(1), Boolean(True)))),
        ("-x", Negate(Name("x"))),
        ("not x", Not(Name("x"))),
        ("not(x)", Not(Name("x"))),
        ("(x)", Name("x")),
        ("choose [1, 2, 3]", Choose((Number(1), Number(2), Number(3)))),
        (
            "if c then 1 else 2",
            If(Name("c"), Number(1), Number(2)),
        ),
    ],
)
def test_atoms_and_simple_forms(text, expected):
    assert expr(text) == expected


@pytest.mark.parametrize(
    "op",
    ["+", "-", "*", "/", "**", "<", ">", "<=", ">=", "=", "!=", "and", "or", "xor"],
)
def test_binary_operators(op):
    assert expr(f"a {op} b") == Binary(op, Name("a"), Name("b"))


def test_arithmetic_precedence():
    assert expr("1 + 2 * 3") == Binary(
        "+", Number(1), Binary("*", Number(2), Number(3))
    )
    assert expr("(1 + 2) * 3") == Binary(
        "*", Binary("+", Number(1), Number(2)), Number(3)
    )


def test_left_associativity():
    assert expr("1 - 2 - 3") == Binary(
        "-", Binary("-", Number(1), Number(2)), Number(3)
    )


def test_power_binds_tighter_than_negation():
    assert expr("-2 ** 2") == Negate(Binary("**", Number(2), Number(2)))
    assert expr("2 ** -1") == Binary("**", Number(2), Negate(Number(1)))


def test_logic_precedence():
    assert expr("a or b xor c and d") == Binary(
        "or", Name("a"), Binary("xor", Name("b"), Binary("and", Name("c"), Name("d")))
    )
    assert expr("not a = b") == Not(Binary("=", Name("a"), Name("b")))
    assert expr("a < 1 and b > 2") == Binary(
        "and",
        Binary("<", Name("a"), Number(1)),
        Binary(">", Name("b"), Number(2)),
    )


def test_if_nested_and_choose_in_expression():
    assert expr("if a then choose [1, 2] else if b then 3 else 4") == If(
        Name("a"),
        Choose((Number(1), Number(2))),
        If(Name("b"), Number(3), Number(4)),
    )
    assert expr("choose [x + 1, y]") == Choose(
        (Binary("+", Name("x"), Number(1)), Name("y"))
    )


def test_keyword_prefix_names_are_names():
    assert expr("android or iffy") == Binary("or", Name("android"), Name("iffy"))


def test_triple():
    result = parse_behavior("(x, [a, b.c], a + b)")
    assert result == Success(
        Behavior(
            (
                Triple(
                    Name("x"),
                    (Name("a"), Name("b.c")),
                    Binary("+", Name("a"), Name("b")),
                ),
            )
        )
    )


def test_multiple_triples():
    result = parse_behavior("(x, [], 1), (y, [x], choose [x, 2])").unwrap()
    assert result == Behavior(
        (
            Triple(Name("x"), (), Number(1)),
            Triple(Name("y"), (Name("x"),), Choose((Name("x"), Number(2)))),
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        '"a string"',
        "null",
        "f(1)",
        "f()",
        "for i in [1, 2] return i",
        "some i in [1] satisfies i > 0",
        "every i in [1] satisfies i > 0",
        "{a: 1}",
        "{}",
        "[1..5]",
        "(1..5)",
        "x in [1..5]",
        "x between 1 and 5",
        "x[1]",
        '@"2020-01-01"',
        "function(a) a",
        "1 + f(x)",
        "if a then 1 else sum([1])",
    ],
)
def test_unsupported_constructs(text):
    result = parse_expression(text)
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, FeelUnsupportedError)
    assert "not supported" in get_error_message(error)


def test_unsupported_in_behavior():
    result = parse_behavior("(x, [], f(1))")
    assert isinstance(result.failure(), FeelUnsupportedError)


@pytest.mark.parametrize(
    "text", ["", "a +", "(a", "a b", "1 $ 2", "if a then b", "[1, 2", "a ! b", '"open']
)
def test_bad_expression_syntax_is_parse_error(text):
    result = parse_expression(text)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelParseError)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "x",
        "(x, [a], 1",
        "(x, a, 1)",
        "(x, [a])",
        "(x, [], 1) (y, [], 2)",
        "(x, [], 1),",
    ],
)
def test_bad_behavior_syntax_is_parse_error(text):
    result = parse_behavior(text)
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), FeelParseError)


def test_visitor_dispatches_every_node():
    class Show(FeelVisitor[str]):
        def visit_number(self, node):
            return str(node.value)

        def visit_name(self, node):
            return node.name

        def visit_binary(self, node):
            return f"({self.visit(node.left)} {node.op} {self.visit(node.right)})"

    assert Show().visit(expr("a + 2 * b")) == "(a + (2 * b))"
    with pytest.raises(NotImplementedError):
        Show().visit(expr("true"))
