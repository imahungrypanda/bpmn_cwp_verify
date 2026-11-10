# Generated from antlr/FeelExpr.g4 by ANTLR 4.13.2
from antlr4 import *

if "." in __name__:
    from .FeelExprParser import FeelExprParser
else:
    from FeelExprParser import FeelExprParser


# This class defines a complete listener for a parse tree produced by FeelExprParser.
class FeelExprListener(ParseTreeListener):
    # Enter a parse tree produced by FeelExprParser#start.
    def enterStart(self, ctx: FeelExprParser.StartContext):
        pass

    # Exit a parse tree produced by FeelExprParser#start.
    def exitStart(self, ctx: FeelExprParser.StartContext):
        pass

    # Enter a parse tree produced by FeelExprParser#behavior.
    def enterBehavior(self, ctx: FeelExprParser.BehaviorContext):
        pass

    # Exit a parse tree produced by FeelExprParser#behavior.
    def exitBehavior(self, ctx: FeelExprParser.BehaviorContext):
        pass

    # Enter a parse tree produced by FeelExprParser#triple.
    def enterTriple(self, ctx: FeelExprParser.TripleContext):
        pass

    # Exit a parse tree produced by FeelExprParser#triple.
    def exitTriple(self, ctx: FeelExprParser.TripleContext):
        pass

    # Enter a parse tree produced by FeelExprParser#nameList.
    def enterNameList(self, ctx: FeelExprParser.NameListContext):
        pass

    # Exit a parse tree produced by FeelExprParser#nameList.
    def exitNameList(self, ctx: FeelExprParser.NameListContext):
        pass

    # Enter a parse tree produced by FeelExprParser#If.
    def enterIf(self, ctx: FeelExprParser.IfContext):
        pass

    # Exit a parse tree produced by FeelExprParser#If.
    def exitIf(self, ctx: FeelExprParser.IfContext):
        pass

    # Enter a parse tree produced by FeelExprParser#For.
    def enterFor(self, ctx: FeelExprParser.ForContext):
        pass

    # Exit a parse tree produced by FeelExprParser#For.
    def exitFor(self, ctx: FeelExprParser.ForContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Quantified.
    def enterQuantified(self, ctx: FeelExprParser.QuantifiedContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Quantified.
    def exitQuantified(self, ctx: FeelExprParser.QuantifiedContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToOr.
    def enterToOr(self, ctx: FeelExprParser.ToOrContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToOr.
    def exitToOr(self, ctx: FeelExprParser.ToOrContext):
        pass

    # Enter a parse tree produced by FeelExprParser#forBinding.
    def enterForBinding(self, ctx: FeelExprParser.ForBindingContext):
        pass

    # Exit a parse tree produced by FeelExprParser#forBinding.
    def exitForBinding(self, ctx: FeelExprParser.ForBindingContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToXor.
    def enterToXor(self, ctx: FeelExprParser.ToXorContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToXor.
    def exitToXor(self, ctx: FeelExprParser.ToXorContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Or.
    def enterOr(self, ctx: FeelExprParser.OrContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Or.
    def exitOr(self, ctx: FeelExprParser.OrContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Xor.
    def enterXor(self, ctx: FeelExprParser.XorContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Xor.
    def exitXor(self, ctx: FeelExprParser.XorContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToAnd.
    def enterToAnd(self, ctx: FeelExprParser.ToAndContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToAnd.
    def exitToAnd(self, ctx: FeelExprParser.ToAndContext):
        pass

    # Enter a parse tree produced by FeelExprParser#And.
    def enterAnd(self, ctx: FeelExprParser.AndContext):
        pass

    # Exit a parse tree produced by FeelExprParser#And.
    def exitAnd(self, ctx: FeelExprParser.AndContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToNot.
    def enterToNot(self, ctx: FeelExprParser.ToNotContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToNot.
    def exitToNot(self, ctx: FeelExprParser.ToNotContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Not.
    def enterNot(self, ctx: FeelExprParser.NotContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Not.
    def exitNot(self, ctx: FeelExprParser.NotContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToRel.
    def enterToRel(self, ctx: FeelExprParser.ToRelContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToRel.
    def exitToRel(self, ctx: FeelExprParser.ToRelContext):
        pass

    # Enter a parse tree produced by FeelExprParser#InTest.
    def enterInTest(self, ctx: FeelExprParser.InTestContext):
        pass

    # Exit a parse tree produced by FeelExprParser#InTest.
    def exitInTest(self, ctx: FeelExprParser.InTestContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Between.
    def enterBetween(self, ctx: FeelExprParser.BetweenContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Between.
    def exitBetween(self, ctx: FeelExprParser.BetweenContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Relational.
    def enterRelational(self, ctx: FeelExprParser.RelationalContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Relational.
    def exitRelational(self, ctx: FeelExprParser.RelationalContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToAddSub.
    def enterToAddSub(self, ctx: FeelExprParser.ToAddSubContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToAddSub.
    def exitToAddSub(self, ctx: FeelExprParser.ToAddSubContext):
        pass

    # Enter a parse tree produced by FeelExprParser#AddSub.
    def enterAddSub(self, ctx: FeelExprParser.AddSubContext):
        pass

    # Exit a parse tree produced by FeelExprParser#AddSub.
    def exitAddSub(self, ctx: FeelExprParser.AddSubContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToMulDiv.
    def enterToMulDiv(self, ctx: FeelExprParser.ToMulDivContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToMulDiv.
    def exitToMulDiv(self, ctx: FeelExprParser.ToMulDivContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToUnary.
    def enterToUnary(self, ctx: FeelExprParser.ToUnaryContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToUnary.
    def exitToUnary(self, ctx: FeelExprParser.ToUnaryContext):
        pass

    # Enter a parse tree produced by FeelExprParser#MulDiv.
    def enterMulDiv(self, ctx: FeelExprParser.MulDivContext):
        pass

    # Exit a parse tree produced by FeelExprParser#MulDiv.
    def exitMulDiv(self, ctx: FeelExprParser.MulDivContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Negate.
    def enterNegate(self, ctx: FeelExprParser.NegateContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Negate.
    def exitNegate(self, ctx: FeelExprParser.NegateContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToPow.
    def enterToPow(self, ctx: FeelExprParser.ToPowContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToPow.
    def exitToPow(self, ctx: FeelExprParser.ToPowContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToPostfix.
    def enterToPostfix(self, ctx: FeelExprParser.ToPostfixContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToPostfix.
    def exitToPostfix(self, ctx: FeelExprParser.ToPostfixContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Pow.
    def enterPow(self, ctx: FeelExprParser.PowContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Pow.
    def exitPow(self, ctx: FeelExprParser.PowContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Filter.
    def enterFilter(self, ctx: FeelExprParser.FilterContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Filter.
    def exitFilter(self, ctx: FeelExprParser.FilterContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ToAtom.
    def enterToAtom(self, ctx: FeelExprParser.ToAtomContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToAtom.
    def exitToAtom(self, ctx: FeelExprParser.ToAtomContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Number.
    def enterNumber(self, ctx: FeelExprParser.NumberContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Number.
    def exitNumber(self, ctx: FeelExprParser.NumberContext):
        pass

    # Enter a parse tree produced by FeelExprParser#True.
    def enterTrue(self, ctx: FeelExprParser.TrueContext):
        pass

    # Exit a parse tree produced by FeelExprParser#True.
    def exitTrue(self, ctx: FeelExprParser.TrueContext):
        pass

    # Enter a parse tree produced by FeelExprParser#False.
    def enterFalse(self, ctx: FeelExprParser.FalseContext):
        pass

    # Exit a parse tree produced by FeelExprParser#False.
    def exitFalse(self, ctx: FeelExprParser.FalseContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Ref.
    def enterRef(self, ctx: FeelExprParser.RefContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Ref.
    def exitRef(self, ctx: FeelExprParser.RefContext):
        pass

    # Enter a parse tree produced by FeelExprParser#ListLit.
    def enterListLit(self, ctx: FeelExprParser.ListLitContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ListLit.
    def exitListLit(self, ctx: FeelExprParser.ListLitContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Choose.
    def enterChoose(self, ctx: FeelExprParser.ChooseContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Choose.
    def exitChoose(self, ctx: FeelExprParser.ChooseContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Parens.
    def enterParens(self, ctx: FeelExprParser.ParensContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Parens.
    def exitParens(self, ctx: FeelExprParser.ParensContext):
        pass

    # Enter a parse tree produced by FeelExprParser#String.
    def enterString(self, ctx: FeelExprParser.StringContext):
        pass

    # Exit a parse tree produced by FeelExprParser#String.
    def exitString(self, ctx: FeelExprParser.StringContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Null.
    def enterNull(self, ctx: FeelExprParser.NullContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Null.
    def exitNull(self, ctx: FeelExprParser.NullContext):
        pass

    # Enter a parse tree produced by FeelExprParser#DateLiteral.
    def enterDateLiteral(self, ctx: FeelExprParser.DateLiteralContext):
        pass

    # Exit a parse tree produced by FeelExprParser#DateLiteral.
    def exitDateLiteral(self, ctx: FeelExprParser.DateLiteralContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Call.
    def enterCall(self, ctx: FeelExprParser.CallContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Call.
    def exitCall(self, ctx: FeelExprParser.CallContext):
        pass

    # Enter a parse tree produced by FeelExprParser#FunctionDef.
    def enterFunctionDef(self, ctx: FeelExprParser.FunctionDefContext):
        pass

    # Exit a parse tree produced by FeelExprParser#FunctionDef.
    def exitFunctionDef(self, ctx: FeelExprParser.FunctionDefContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Context.
    def enterContext(self, ctx: FeelExprParser.ContextContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Context.
    def exitContext(self, ctx: FeelExprParser.ContextContext):
        pass

    # Enter a parse tree produced by FeelExprParser#Interval.
    def enterInterval(self, ctx: FeelExprParser.IntervalContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Interval.
    def exitInterval(self, ctx: FeelExprParser.IntervalContext):
        pass

    # Enter a parse tree produced by FeelExprParser#contextEntry.
    def enterContextEntry(self, ctx: FeelExprParser.ContextEntryContext):
        pass

    # Exit a parse tree produced by FeelExprParser#contextEntry.
    def exitContextEntry(self, ctx: FeelExprParser.ContextEntryContext):
        pass

    # Enter a parse tree produced by FeelExprParser#list.
    def enterList(self, ctx: FeelExprParser.ListContext):
        pass

    # Exit a parse tree produced by FeelExprParser#list.
    def exitList(self, ctx: FeelExprParser.ListContext):
        pass

    # Enter a parse tree produced by FeelExprParser#name.
    def enterName(self, ctx: FeelExprParser.NameContext):
        pass

    # Exit a parse tree produced by FeelExprParser#name.
    def exitName(self, ctx: FeelExprParser.NameContext):
        pass


del FeelExprParser
