# Generated from antlr/FeelExpr.g4 by ANTLR 4.13.2
from antlr4 import *

if "." in __name__:
    from .FeelExprParser import FeelExprParser
else:
    from FeelExprParser import FeelExprParser

# This class defines a complete generic visitor for a parse tree produced by FeelExprParser.


class FeelExprVisitor(ParseTreeVisitor):
    # Visit a parse tree produced by FeelExprParser#start.
    def visitStart(self, ctx: FeelExprParser.StartContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#behavior.
    def visitBehavior(self, ctx: FeelExprParser.BehaviorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#triple.
    def visitTriple(self, ctx: FeelExprParser.TripleContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#nameList.
    def visitNameList(self, ctx: FeelExprParser.NameListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#If.
    def visitIf(self, ctx: FeelExprParser.IfContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#For.
    def visitFor(self, ctx: FeelExprParser.ForContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Quantified.
    def visitQuantified(self, ctx: FeelExprParser.QuantifiedContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToOr.
    def visitToOr(self, ctx: FeelExprParser.ToOrContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#forBinding.
    def visitForBinding(self, ctx: FeelExprParser.ForBindingContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToXor.
    def visitToXor(self, ctx: FeelExprParser.ToXorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Or.
    def visitOr(self, ctx: FeelExprParser.OrContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Xor.
    def visitXor(self, ctx: FeelExprParser.XorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToAnd.
    def visitToAnd(self, ctx: FeelExprParser.ToAndContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#And.
    def visitAnd(self, ctx: FeelExprParser.AndContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToNot.
    def visitToNot(self, ctx: FeelExprParser.ToNotContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Not.
    def visitNot(self, ctx: FeelExprParser.NotContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToRel.
    def visitToRel(self, ctx: FeelExprParser.ToRelContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#InTest.
    def visitInTest(self, ctx: FeelExprParser.InTestContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Between.
    def visitBetween(self, ctx: FeelExprParser.BetweenContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Relational.
    def visitRelational(self, ctx: FeelExprParser.RelationalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToAddSub.
    def visitToAddSub(self, ctx: FeelExprParser.ToAddSubContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#AddSub.
    def visitAddSub(self, ctx: FeelExprParser.AddSubContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToMulDiv.
    def visitToMulDiv(self, ctx: FeelExprParser.ToMulDivContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToUnary.
    def visitToUnary(self, ctx: FeelExprParser.ToUnaryContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#MulDiv.
    def visitMulDiv(self, ctx: FeelExprParser.MulDivContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Negate.
    def visitNegate(self, ctx: FeelExprParser.NegateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToPow.
    def visitToPow(self, ctx: FeelExprParser.ToPowContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToPostfix.
    def visitToPostfix(self, ctx: FeelExprParser.ToPostfixContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Pow.
    def visitPow(self, ctx: FeelExprParser.PowContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Filter.
    def visitFilter(self, ctx: FeelExprParser.FilterContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ToAtom.
    def visitToAtom(self, ctx: FeelExprParser.ToAtomContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Number.
    def visitNumber(self, ctx: FeelExprParser.NumberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#True.
    def visitTrue(self, ctx: FeelExprParser.TrueContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#False.
    def visitFalse(self, ctx: FeelExprParser.FalseContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Ref.
    def visitRef(self, ctx: FeelExprParser.RefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#ListLit.
    def visitListLit(self, ctx: FeelExprParser.ListLitContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Choose.
    def visitChoose(self, ctx: FeelExprParser.ChooseContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Parens.
    def visitParens(self, ctx: FeelExprParser.ParensContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#String.
    def visitString(self, ctx: FeelExprParser.StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Null.
    def visitNull(self, ctx: FeelExprParser.NullContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#DateLiteral.
    def visitDateLiteral(self, ctx: FeelExprParser.DateLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Call.
    def visitCall(self, ctx: FeelExprParser.CallContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#FunctionDef.
    def visitFunctionDef(self, ctx: FeelExprParser.FunctionDefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Context.
    def visitContext(self, ctx: FeelExprParser.ContextContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#Interval.
    def visitInterval(self, ctx: FeelExprParser.IntervalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#contextEntry.
    def visitContextEntry(self, ctx: FeelExprParser.ContextEntryContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#list.
    def visitList(self, ctx: FeelExprParser.ListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by FeelExprParser#name.
    def visitName(self, ctx: FeelExprParser.NameContext):
        return self.visitChildren(ctx)


del FeelExprParser
