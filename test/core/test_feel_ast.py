import pytest
from returns.pipeline import is_successful

from bpmncwpverify.core.error import FeelSyntaxError, FeelUnsupportedError
from bpmncwpverify.core.feel import parse
from bpmncwpverify.core.feel_tree import (
    BinaryOp,
    Boolean,
    Choose,
    FeelExpr,
    FeelVisitor,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
    TripleList,
)


def _ok(text: str) -> FeelExpr:
    result = parse(text)
    assert is_successful(result), text
    return result.unwrap()


def _bin(op: str, left: FeelExpr, right: FeelExpr) -> BinaryOp:
    return BinaryOp(op, left, right)  # type: ignore[arg-type]


def _n(name: str) -> Name:
    return Name(name)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", Number(3)),
        ("2.5", Number(2.5)),
        ("true", Boolean(True)),
        ("false", Boolean(False)),
        ("x", _n("x")),
        ("a.b.c", _n("a.b.c")),
        ("[]", ListExpr(())),
        ("[a, 1, true]", ListExpr((_n("a"), Number(1), Boolean(True)))),
        ("(x)", _n("x")),
        ("((x))", _n("x")),
        ("-x", Negate(_n("x"))),
        ("not x", Not(_n("x"))),
        ("a + b", _bin("+", _n("a"), _n("b"))),
        ("a - b", _bin("-", _n("a"), _n("b"))),
        ("a * b", _bin("*", _n("a"), _n("b"))),
        ("a / b", _bin("/", _n("a"), _n("b"))),
        ("a ** b", _bin("**", _n("a"), _n("b"))),
        ("a < b", _bin("<", _n("a"), _n("b"))),
        ("a > b", _bin(">", _n("a"), _n("b"))),
        ("a <= b", _bin("<=", _n("a"), _n("b"))),
        ("a >= b", _bin(">=", _n("a"), _n("b"))),
        ("a = b", _bin("=", _n("a"), _n("b"))),
        ("a != b", _bin("!=", _n("a"), _n("b"))),
        ("a and b", _bin("and", _n("a"), _n("b"))),
        ("a or b", _bin("or", _n("a"), _n("b"))),
        ("a xor b", _bin("xor", _n("a"), _n("b"))),
        (
            "if c then 1 else 2",
            If(_n("c"), Number(1), Number(2)),
        ),
        (
            "choose [on, off]",
            Choose((_n("on"), _n("off"))),
        ),
        (
            "(door, [], open)",
            Triple("door", (), _n("open")),
        ),
        (
            "(count, [count, x.y], count + 1)",
            Triple("count", ("count", "x.y"), _bin("+", _n("count"), Number(1))),
        ),
        (
            "((x, [], 1), (y, [x], x + 1))",
            TripleList(
                (
                    Triple("x", (), Number(1)),
                    Triple("y", ("x",), _bin("+", _n("x"), Number(1))),
                )
            ),
        ),
        ("((x, [], 1))", Triple("x", (), Number(1))),
    ],
)
def test_parse_construct(text: str, expected: FeelExpr) -> None:
    assert _ok(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a + b * c", _bin("+", _n("a"), _bin("*", _n("b"), _n("c")))),
        ("a - b - c", _bin("-", _bin("-", _n("a"), _n("b")), _n("c"))),
        ("(a + b) * c", _bin("*", _bin("+", _n("a"), _n("b")), _n("c"))),
        ("-x ** 2", Negate(_bin("**", _n("x"), Number(2)))),
        ("a ** -1", _bin("**", _n("a"), Negate(Number(1)))),
        ("a ** b ** c", _bin("**", _bin("**", _n("a"), _n("b")), _n("c"))),
        (
            "a + 1 < b",
            _bin("<", _bin("+", _n("a"), Number(1)), _n("b")),
        ),
        (
            "not a = b",
            Not(_bin("=", _n("a"), _n("b"))),
        ),
        (
            "a or b and c",
            _bin("or", _n("a"), _bin("and", _n("b"), _n("c"))),
        ),
        (
            "a or b xor c and d",
            _bin(
                "or",
                _n("a"),
                _bin("xor", _n("b"), _bin("and", _n("c"), _n("d"))),
            ),
        ),
        (
            "if a then b else c + 1",
            If(_n("a"), _n("b"), _bin("+", _n("c"), Number(1))),
        ),
        (
            "1 + if a then 2 else 3",
            _bin("+", Number(1), If(_n("a"), Number(2), Number(3))),
        ),
        (
            "if a then (x, [], 1) else (y, [], 2)",
            If(_n("a"), Triple("x", (), Number(1)), Triple("y", (), Number(2))),
        ),
        (
            "(x, [], if a then 1 else 2)",
            Triple("x", (), If(_n("a"), Number(1), Number(2))),
        ),
    ],
)
def test_parse_precedence(text: str, expected: FeelExpr) -> None:
    assert _ok(text) == expected


def test_parse_task_behavior_example() -> None:
    tree = _ok("((light, [], choose [on, off]),\n(count, [count], count + 1))")
    assert tree == TripleList(
        (
            Triple("light", (), Choose((_n("on"), _n("off")))),
            Triple("count", ("count",), _bin("+", _n("count"), Number(1))),
        )
    )


def test_parse_condition_examples() -> None:
    assert _ok("door = open and count < 3") == _bin(
        "and",
        _bin("=", _n("door"), _n("open")),
        _bin("<", _n("count"), Number(3)),
    )
    assert _ok("light = on or count = 3") == _bin(
        "or",
        _bin("=", _n("light"), _n("on")),
        _bin("=", _n("count"), Number(3)),
    )


def test_parse_records_position() -> None:
    tree = _ok("a +\n  b")
    assert isinstance(tree, BinaryOp)
    assert (tree.line, tree.column) == (1, 0)
    assert (tree.right.line, tree.right.column) == (2, 2)


@pytest.mark.parametrize(
    "text",
    [
        '"abc"',
        '@"2020-01-01"',
        "null",
        "f(x)",
        "abs(1)",
        "a.b(1)",
        "[1..5]",
        "(1..5)",
        "{a: 1}",
        "for x in [1, 2] return x",
        "some x in [1, 2] satisfies x > 1",
        "every x in [1, 2] satisfies x > 1",
        "x in [1, 2]",
        "x between 1 and 2",
        "x instance of number",
        "function(x) x",
        "a[1]",
        "(x, [], f(1))",
    ],
)
def test_unsupported_feel_gives_unsupported_error(text: str) -> None:
    result = parse(text)
    assert not is_successful(result)
    error = result.failure()
    assert isinstance(error, FeelUnsupportedError)
    assert error.line == 1


def test_unsupported_error_names_construct_and_position() -> None:
    error = parse("a and\n  f(1)").failure()
    assert isinstance(error, FeelUnsupportedError)
    assert "f(...)" in error.construct
    assert (error.line, error.column) == (2, 2)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1 +",
        "a b",
        "a, b",
        "(a, b)",
        "(x, [], 1) (y, [], 2)",
        "(x, 1, 2)",
        "(x, [], )",
        "(1, [], 2)",
        "choose []",
        "choose a",
        "if a then b",
        "[1, 2",
        "(a",
        "a)",
        "a % b",
        "a == b",
        "a && b",
        "$",
        '"unterminated',
    ],
)
def test_bad_syntax_gives_syntax_error(text: str) -> None:
    result = parse(text)
    assert not is_successful(result)
    assert isinstance(result.failure(), FeelSyntaxError)


class _Printer(FeelVisitor[str]):
    def visit_number(self, node: Number) -> str:
        return str(node.value)

    def visit_boolean(self, node: Boolean) -> str:
        return str(node.value).lower()

    def visit_name(self, node: Name) -> str:
        return node.name

    def visit_list(self, node: ListExpr) -> str:
        return "[" + ",".join(self.visit(i) for i in node.items) + "]"

    def visit_binary_op(self, node: BinaryOp) -> str:
        return f"({self.visit(node.left)} {node.op} {self.visit(node.right)})"

    def visit_not(self, node: Not) -> str:
        return f"not {self.visit(node.operand)}"

    def visit_negate(self, node: Negate) -> str:
        return f"-{self.visit(node.operand)}"

    def visit_if(self, node: If) -> str:
        return f"if {self.visit(node.condition)} then {self.visit(node.then_branch)} else {self.visit(node.else_branch)}"

    def visit_choose(self, node: Choose) -> str:
        return "choose [" + ",".join(self.visit(o) for o in node.options) + "]"

    def visit_triple(self, node: Triple) -> str:
        return f"<{node.target}|{','.join(node.inputs)}|{self.visit(node.value)}>"

    def visit_triple_list(self, node: TripleList) -> str:
        return ";".join(self.visit(t) for t in node.triples)


def test_visitor_dispatches_every_node_type() -> None:
    assert (
        _Printer().visit(_ok("((x, [], 1), (y, [x], x / 2))")) == "<x||1>;<y|x|(x / 2)>"
    )
    assert _Printer().visit(
        _ok("if not a then [1, -b, true] else choose [1, 3 ** 2]")
    ) == ("if not a then [1,-b,true] else choose [1,(3 ** 2)]")


def test_visitor_default_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        FeelVisitor[int]().visit(Number(1))
