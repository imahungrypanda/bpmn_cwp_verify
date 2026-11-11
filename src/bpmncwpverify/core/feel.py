from typing import Any, cast

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ConsoleErrorListener, ErrorListener
from antlr4.error.ErrorStrategy import ParseCancellationException
from returns.result import Failure, Result, Success

from bpmncwpverify.antlr.FeelExprLexer import FeelExprLexer
from bpmncwpverify.antlr.FeelExprParser import FeelExprParser
from bpmncwpverify.core.error import Error, FeelSyntaxError, FeelUnsupportedError
from bpmncwpverify.core.feel_tree import (
    BinaryOp,
    BinaryOpName,
    Boolean,
    Choose,
    FeelExpr,
    If,
    ListExpr,
    Name,
    Negate,
    Not,
    Number,
    Triple,
    TripleList,
)

# Tokens that only occur in FEEL constructs this tool does not use.
_UNSUPPORTED_TOKENS: dict[int, str] = {
    FeelExprLexer.STRING: "a string",
    FeelExprLexer.NULL: "'null'",
    FeelExprLexer.DATE_LITERAL: "a date/time literal",
    FeelExprLexer.AT: "a date/time literal",
    FeelExprLexer.FOR: "a 'for' expression",
    FeelExprLexer.RETURN: "'return'",
    FeelExprLexer.SOME: "a 'some' expression",
    FeelExprLexer.EVERY: "an 'every' expression",
    FeelExprLexer.SATISFIES: "'satisfies'",
    FeelExprLexer.IN: "the 'in' operator",
    FeelExprLexer.BETWEEN: "the 'between' operator",
    FeelExprLexer.INSTANCE: "'instance of'",
    FeelExprLexer.OF: "'of'",
    FeelExprLexer.FUNCTION: "a function definition",
    FeelExprLexer.RANGE: "an interval",
    FeelExprLexer.LBRACE: "a context",
    FeelExprLexer.RBRACE: "a context",
    FeelExprLexer.COLON: "a context",
    FeelExprLexer.QUESTION: "'?'",
}


class _Unsupported(Exception):
    def __init__(self, construct: str, line: int, column: int) -> None:
        super().__init__(construct)
        self.error = FeelUnsupportedError(construct, line, column)


class _ThrowingErrorListener(ErrorListener):  # type: ignore[misc]
    """Turns syntax errors into exceptions instead of printing them."""

    def syntaxError(
        self,
        recognizer: Any,
        offendingSymbol: Any,
        line: int,
        column: int,
        msg: str,
        e: Exception,
    ) -> None:
        if offendingSymbol is not None and offendingSymbol.type in _UNSUPPORTED_TOKENS:
            raise _Unsupported(_UNSUPPORTED_TOKENS[offendingSymbol.type], line, column)
        raise ParseCancellationException(f"line {line}:{column} {msg}")


def _pos(ctx: Any) -> dict[str, int]:
    return {"line": ctx.start.line, "column": ctx.start.column}


def _build_triple(ctx: Any) -> Triple:
    names = [n.getText() for n in ctx.NAME()]
    return Triple(names[0], tuple(names[1:]), _build(ctx.expr()), **_pos(ctx))


def _binary(ctx: Any, op: str, left: Any, right: Any) -> BinaryOp:
    return BinaryOp(cast(BinaryOpName, op), _build(left), _build(right), **_pos(ctx))


def _build(ctx: Any) -> FeelExpr:
    P: Any = FeelExprParser  # generated contexts are untyped
    match ctx:
        # Rules that only forward to another rule
        case (
            P.ExprContext()
            | P.ToXorContext()
            | P.ToAndContext()
            | P.ToNotContext()
            | P.ToRelContext()
            | P.ToAddSubContext()
            | P.ToMulDivContext()
            | P.ToUnaryContext()
            | P.ToPowContext()
            | P.ToPostfixContext()
            | P.PowToPostfixContext()
            | P.ToPrimaryContext()
        ):
            return _build(ctx.getChild(0))
        case P.ToTripleContext():
            return _build_triple(ctx.triple())
        case P.ToUnsupportedContext():
            tok = ctx.start
            raise _Unsupported(
                _UNSUPPORTED_TOKENS.get(tok.type, "this construct"),
                tok.line,
                tok.column,
            )
        case P.OrContext():
            return _binary(ctx, "or", ctx.orExpr(), ctx.xorExpr())
        case P.XorContext():
            return _binary(ctx, "xor", ctx.xorExpr(), ctx.andExpr())
        case P.AndContext():
            return _binary(ctx, "and", ctx.andExpr(), ctx.notExpr())
        case P.NotContext():
            return Not(_build(ctx.notExpr()), **_pos(ctx))
        case P.RelationalContext():
            return _binary(ctx, ctx.op.text, ctx.relExpr(), ctx.addSubExpr())
        case P.AddSubContext():
            return _binary(ctx, ctx.op.text, ctx.addSubExpr(), ctx.mulDivExpr())
        case P.MulDivContext():
            return _binary(ctx, ctx.op.text, ctx.mulDivExpr(), ctx.unaryExpr())
        case P.NegateContext():
            return Negate(_build(ctx.unaryExpr()), **_pos(ctx))
        case P.PowerContext():
            return _binary(ctx, "**", ctx.powExpr(), ctx.powOperand())
        case P.PowNegateContext():
            return Negate(_build(ctx.powOperand()), **_pos(ctx))
        case P.FilterContext():
            raise _Unsupported(
                "a list filter or index", ctx.start.line, ctx.start.column
            )
        case P.FunctionCallContext():
            raise _Unsupported(
                f"the function call '{ctx.NAME().getText()}(...)'",
                ctx.start.line,
                ctx.start.column,
            )
        case P.NumberContext():
            text = ctx.NUMBER().getText()
            return Number(float(text) if "." in text else int(text), **_pos(ctx))
        case P.TrueContext():
            return Boolean(True, **_pos(ctx))
        case P.FalseContext():
            return Boolean(False, **_pos(ctx))
        case P.NameContext():
            return Name(ctx.NAME().getText(), **_pos(ctx))
        case P.ListContext():
            return ListExpr(tuple(_build(e) for e in ctx.expr()), **_pos(ctx))
        case P.IfContext():
            c, t, e = ctx.expr()
            return If(_build(c), _build(t), _build(e), **_pos(ctx))
        case P.ChooseContext():
            return Choose(tuple(_build(e) for e in ctx.expr()), **_pos(ctx))
        case P.ParenTripleListContext():
            triples = tuple(_build_triple(t) for t in ctx.tripleList().triple())
            return TripleList(triples, **_pos(ctx))
        case P.ParensContext():
            return _build(ctx.expr())
        case _:
            raise NotImplementedError(f"unhandled parse tree node {type(ctx).__name__}")


def parse(text: str) -> Result[FeelExpr, Error]:
    """
    Parses FEEL text into a syntax tree.

    Fails with FeelUnsupportedError for FEEL constructs this tool does not
    use, and with FeelSyntaxError for anything else that is not valid.
    """
    listener = _ThrowingErrorListener()
    lexer = FeelExprLexer(InputStream(text))
    lexer.removeErrorListener(ConsoleErrorListener.INSTANCE)  # type: ignore[unused-ignore]
    lexer.addErrorListener(listener)  # type: ignore[unused-ignore]
    parser = FeelExprParser(CommonTokenStream(lexer))
    parser.removeErrorListener(ConsoleErrorListener.INSTANCE)  # type: ignore[unused-ignore]
    parser.addErrorListener(listener)  # type: ignore[unused-ignore]
    try:
        tree = parser.start()  # type: ignore[unused-ignore,no-untyped-call]
        return Success(_build(tree.expr()))
    except _Unsupported as unsupported:
        return Failure(unsupported.error)
    except ParseCancellationException as exception:
        return Failure(FeelSyntaxError(str(exception)))
