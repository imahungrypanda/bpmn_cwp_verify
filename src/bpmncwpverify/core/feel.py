# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
"""
Parses FEEL text into the syntax tree in ``feel_tree``.
"""

from typing import Any, NoReturn

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ConsoleErrorListener
from antlr4.error.ErrorStrategy import ParseCancellationException
from returns.result import Failure, Result, Success

from bpmncwpverify.antlr.FeelExprLexer import FeelExprLexer
from bpmncwpverify.antlr.FeelExprParser import (
    FeelExprParser,
)
from bpmncwpverify.antlr.FeelExprVisitor import FeelExprVisitor
from bpmncwpverify.core.error import Error, FeelParseError, FeelUnsupportedError
from bpmncwpverify.core.expr import ThrowingErrorListener
from bpmncwpverify.core.feel_tree import (
    Behavior,
    Binary,
    Boolean,
    Choose,
    FeelNode,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
)


class _Unsupported(Exception):
    def __init__(self, construct: str, ctx: Any) -> None:
        super().__init__(construct)
        self.construct = construct
        self.text: str = ctx.getText()


def _unsupported(construct: str) -> Any:
    def visit(self: Any, ctx: Any) -> NoReturn:
        raise _Unsupported(construct, ctx)

    return visit


class _TreeBuilder(FeelExprVisitor):
    def visitStart(self, ctx: Any) -> FeelNode:
        return self.visit(ctx.expr())  # type: ignore[no-any-return]

    def visitBehavior(self, ctx: Any) -> Behavior:
        return Behavior(tuple(self.visit(t) for t in ctx.triple()))

    def visitTriple(self, ctx: Any) -> Triple:
        return Triple(
            self.visit(ctx.name()),
            self.visit(ctx.nameList()),
            self.visit(ctx.expr()),
        )

    def visitNameList(self, ctx: Any) -> tuple[Name, ...]:
        return tuple(self.visit(n) for n in ctx.name())

    def visitName(self, ctx: Any) -> Name:
        return Name(ctx.getText())

    def visitIf(self, ctx: Any) -> If:
        cond, then_branch, else_branch = (self.visit(e) for e in ctx.expr())
        return If(cond, then_branch, else_branch)

    def _binary(self, ctx: Any, op: str) -> Binary:
        left, right = (self.visit(c) for c in ctx.getChildren() if _is_rule(c))
        return Binary(op, left, right)

    def visitOr(self, ctx: Any) -> Binary:
        return self._binary(ctx, "or")

    def visitXor(self, ctx: Any) -> Binary:
        return self._binary(ctx, "xor")

    def visitAnd(self, ctx: Any) -> Binary:
        return self._binary(ctx, "and")

    def visitNot(self, ctx: Any) -> Not:
        return Not(self.visit(ctx.notExpr()))

    def visitRelational(self, ctx: Any) -> Binary:
        return self._binary(ctx, ctx.op.text)

    def visitAddSub(self, ctx: Any) -> Binary:
        return self._binary(ctx, ctx.op.text)

    def visitMulDiv(self, ctx: Any) -> Binary:
        return self._binary(ctx, ctx.op.text)

    def visitPow(self, ctx: Any) -> Binary:
        return self._binary(ctx, "**")

    def visitNegate(self, ctx: Any) -> Negate:
        return Negate(self.visit(ctx.unaryExpr()))

    def visitNumber(self, ctx: Any) -> Number:
        text = ctx.getText()
        return Number(float(text) if "." in text else int(text))

    def visitTrue(self, ctx: Any) -> Boolean:
        return Boolean(True)

    def visitFalse(self, ctx: Any) -> Boolean:
        return Boolean(False)

    def visitRef(self, ctx: Any) -> Name:
        return self.visit(ctx.name())  # type: ignore[no-any-return]

    def visitList(self, ctx: Any) -> tuple[FeelNode, ...]:
        return tuple(self.visit(e) for e in ctx.expr())

    def visitListLit(self, ctx: Any) -> ListExpr:
        return ListExpr(self.visit(ctx.list_()))

    def visitChoose(self, ctx: Any) -> Choose:
        return Choose(self.visit(ctx.list_()))

    def visitParens(self, ctx: Any) -> FeelNode:
        return self.visit(ctx.expr())  # type: ignore[no-any-return]

    visitFor = _unsupported("a 'for' expression")
    visitQuantified = _unsupported("a 'some' or 'every' expression")
    visitBetween = _unsupported("'between'")
    visitInTest = _unsupported("'in'")
    visitFilter = _unsupported("a filter expression")
    visitString = _unsupported("a string")
    visitNull = _unsupported("'null'")
    visitDateLiteral = _unsupported("a date or time literal")
    visitCall = _unsupported("a function call")
    visitFunctionDef = _unsupported("a function definition")
    visitContext = _unsupported("a context")
    visitInterval = _unsupported("an interval")


def _is_rule(child: Any) -> bool:
    return hasattr(child, "getRuleIndex")


def _get_parser(text: str) -> FeelExprParser:
    lexer = FeelExprLexer(InputStream(text))
    lexer.removeErrorListener(ConsoleErrorListener.INSTANCE)
    lexer.addErrorListener(ThrowingErrorListener())
    parser = FeelExprParser(CommonTokenStream(lexer))
    parser.removeErrorListener(ConsoleErrorListener.INSTANCE)
    parser.addErrorListener(ThrowingErrorListener())
    return parser


def _parse(text: str, entry: str) -> Result[FeelNode, Error]:
    try:
        parser = _get_parser(text)
        return Success(_TreeBuilder().visit(getattr(parser, entry)()))
    except ParseCancellationException as exception:
        return Failure(FeelParseError(str(exception)))
    except _Unsupported as unsupported:
        return Failure(FeelUnsupportedError(unsupported.construct, unsupported.text))


def parse_expression(text: str) -> Result[FeelNode, Error]:
    """Parse a FEEL expression, such as a flow or edge condition."""
    return _parse(text, "start")


def parse_behavior(text: str) -> Result[Behavior, Error]:
    """Parse a task behavior: a triple, or triples separated by commas."""
    return _parse(text, "behavior")  # type: ignore[return-value]
