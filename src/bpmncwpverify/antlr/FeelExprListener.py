# Generated from antlr/FeelExpr.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .FeelExprParser import FeelExprParser
else:
    from FeelExprParser import FeelExprParser

# This class defines a complete listener for a parse tree produced by FeelExprParser.
class FeelExprListener(ParseTreeListener):

    # Enter a parse tree produced by FeelExprParser#start.
    def enterStart(self, ctx:FeelExprParser.StartContext):
        pass

    # Exit a parse tree produced by FeelExprParser#start.
    def exitStart(self, ctx:FeelExprParser.StartContext):
        pass


    # Enter a parse tree produced by FeelExprParser#expr.
    def enterExpr(self, ctx:FeelExprParser.ExprContext):
        pass

    # Exit a parse tree produced by FeelExprParser#expr.
    def exitExpr(self, ctx:FeelExprParser.ExprContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToXor.
    def enterToXor(self, ctx:FeelExprParser.ToXorContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToXor.
    def exitToXor(self, ctx:FeelExprParser.ToXorContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Or.
    def enterOr(self, ctx:FeelExprParser.OrContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Or.
    def exitOr(self, ctx:FeelExprParser.OrContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Xor.
    def enterXor(self, ctx:FeelExprParser.XorContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Xor.
    def exitXor(self, ctx:FeelExprParser.XorContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToAnd.
    def enterToAnd(self, ctx:FeelExprParser.ToAndContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToAnd.
    def exitToAnd(self, ctx:FeelExprParser.ToAndContext):
        pass


    # Enter a parse tree produced by FeelExprParser#And.
    def enterAnd(self, ctx:FeelExprParser.AndContext):
        pass

    # Exit a parse tree produced by FeelExprParser#And.
    def exitAnd(self, ctx:FeelExprParser.AndContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToNot.
    def enterToNot(self, ctx:FeelExprParser.ToNotContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToNot.
    def exitToNot(self, ctx:FeelExprParser.ToNotContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Not.
    def enterNot(self, ctx:FeelExprParser.NotContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Not.
    def exitNot(self, ctx:FeelExprParser.NotContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToRel.
    def enterToRel(self, ctx:FeelExprParser.ToRelContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToRel.
    def exitToRel(self, ctx:FeelExprParser.ToRelContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Relational.
    def enterRelational(self, ctx:FeelExprParser.RelationalContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Relational.
    def exitRelational(self, ctx:FeelExprParser.RelationalContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToAddSub.
    def enterToAddSub(self, ctx:FeelExprParser.ToAddSubContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToAddSub.
    def exitToAddSub(self, ctx:FeelExprParser.ToAddSubContext):
        pass


    # Enter a parse tree produced by FeelExprParser#AddSub.
    def enterAddSub(self, ctx:FeelExprParser.AddSubContext):
        pass

    # Exit a parse tree produced by FeelExprParser#AddSub.
    def exitAddSub(self, ctx:FeelExprParser.AddSubContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToMulDiv.
    def enterToMulDiv(self, ctx:FeelExprParser.ToMulDivContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToMulDiv.
    def exitToMulDiv(self, ctx:FeelExprParser.ToMulDivContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToUnary.
    def enterToUnary(self, ctx:FeelExprParser.ToUnaryContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToUnary.
    def exitToUnary(self, ctx:FeelExprParser.ToUnaryContext):
        pass


    # Enter a parse tree produced by FeelExprParser#MulDiv.
    def enterMulDiv(self, ctx:FeelExprParser.MulDivContext):
        pass

    # Exit a parse tree produced by FeelExprParser#MulDiv.
    def exitMulDiv(self, ctx:FeelExprParser.MulDivContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Negate.
    def enterNegate(self, ctx:FeelExprParser.NegateContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Negate.
    def exitNegate(self, ctx:FeelExprParser.NegateContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToPow.
    def enterToPow(self, ctx:FeelExprParser.ToPowContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToPow.
    def exitToPow(self, ctx:FeelExprParser.ToPowContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToPostfix.
    def enterToPostfix(self, ctx:FeelExprParser.ToPostfixContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToPostfix.
    def exitToPostfix(self, ctx:FeelExprParser.ToPostfixContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Power.
    def enterPower(self, ctx:FeelExprParser.PowerContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Power.
    def exitPower(self, ctx:FeelExprParser.PowerContext):
        pass


    # Enter a parse tree produced by FeelExprParser#PowNegate.
    def enterPowNegate(self, ctx:FeelExprParser.PowNegateContext):
        pass

    # Exit a parse tree produced by FeelExprParser#PowNegate.
    def exitPowNegate(self, ctx:FeelExprParser.PowNegateContext):
        pass


    # Enter a parse tree produced by FeelExprParser#PowToPostfix.
    def enterPowToPostfix(self, ctx:FeelExprParser.PowToPostfixContext):
        pass

    # Exit a parse tree produced by FeelExprParser#PowToPostfix.
    def exitPowToPostfix(self, ctx:FeelExprParser.PowToPostfixContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Filter.
    def enterFilter(self, ctx:FeelExprParser.FilterContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Filter.
    def exitFilter(self, ctx:FeelExprParser.FilterContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToPrimary.
    def enterToPrimary(self, ctx:FeelExprParser.ToPrimaryContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToPrimary.
    def exitToPrimary(self, ctx:FeelExprParser.ToPrimaryContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Number.
    def enterNumber(self, ctx:FeelExprParser.NumberContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Number.
    def exitNumber(self, ctx:FeelExprParser.NumberContext):
        pass


    # Enter a parse tree produced by FeelExprParser#True.
    def enterTrue(self, ctx:FeelExprParser.TrueContext):
        pass

    # Exit a parse tree produced by FeelExprParser#True.
    def exitTrue(self, ctx:FeelExprParser.TrueContext):
        pass


    # Enter a parse tree produced by FeelExprParser#False.
    def enterFalse(self, ctx:FeelExprParser.FalseContext):
        pass

    # Exit a parse tree produced by FeelExprParser#False.
    def exitFalse(self, ctx:FeelExprParser.FalseContext):
        pass


    # Enter a parse tree produced by FeelExprParser#FunctionCall.
    def enterFunctionCall(self, ctx:FeelExprParser.FunctionCallContext):
        pass

    # Exit a parse tree produced by FeelExprParser#FunctionCall.
    def exitFunctionCall(self, ctx:FeelExprParser.FunctionCallContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Name.
    def enterName(self, ctx:FeelExprParser.NameContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Name.
    def exitName(self, ctx:FeelExprParser.NameContext):
        pass


    # Enter a parse tree produced by FeelExprParser#List.
    def enterList(self, ctx:FeelExprParser.ListContext):
        pass

    # Exit a parse tree produced by FeelExprParser#List.
    def exitList(self, ctx:FeelExprParser.ListContext):
        pass


    # Enter a parse tree produced by FeelExprParser#If.
    def enterIf(self, ctx:FeelExprParser.IfContext):
        pass

    # Exit a parse tree produced by FeelExprParser#If.
    def exitIf(self, ctx:FeelExprParser.IfContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Choose.
    def enterChoose(self, ctx:FeelExprParser.ChooseContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Choose.
    def exitChoose(self, ctx:FeelExprParser.ChooseContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToTriple.
    def enterToTriple(self, ctx:FeelExprParser.ToTripleContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToTriple.
    def exitToTriple(self, ctx:FeelExprParser.ToTripleContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ParenTripleList.
    def enterParenTripleList(self, ctx:FeelExprParser.ParenTripleListContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ParenTripleList.
    def exitParenTripleList(self, ctx:FeelExprParser.ParenTripleListContext):
        pass


    # Enter a parse tree produced by FeelExprParser#Parens.
    def enterParens(self, ctx:FeelExprParser.ParensContext):
        pass

    # Exit a parse tree produced by FeelExprParser#Parens.
    def exitParens(self, ctx:FeelExprParser.ParensContext):
        pass


    # Enter a parse tree produced by FeelExprParser#ToUnsupported.
    def enterToUnsupported(self, ctx:FeelExprParser.ToUnsupportedContext):
        pass

    # Exit a parse tree produced by FeelExprParser#ToUnsupported.
    def exitToUnsupported(self, ctx:FeelExprParser.ToUnsupportedContext):
        pass


    # Enter a parse tree produced by FeelExprParser#triple.
    def enterTriple(self, ctx:FeelExprParser.TripleContext):
        pass

    # Exit a parse tree produced by FeelExprParser#triple.
    def exitTriple(self, ctx:FeelExprParser.TripleContext):
        pass


    # Enter a parse tree produced by FeelExprParser#tripleList.
    def enterTripleList(self, ctx:FeelExprParser.TripleListContext):
        pass

    # Exit a parse tree produced by FeelExprParser#tripleList.
    def exitTripleList(self, ctx:FeelExprParser.TripleListContext):
        pass


    # Enter a parse tree produced by FeelExprParser#unsupported.
    def enterUnsupported(self, ctx:FeelExprParser.UnsupportedContext):
        pass

    # Exit a parse tree produced by FeelExprParser#unsupported.
    def exitUnsupported(self, ctx:FeelExprParser.UnsupportedContext):
        pass



del FeelExprParser