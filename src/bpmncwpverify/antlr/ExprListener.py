# Generated from antlr/Expr.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .ExprParser import ExprParser
else:
    from ExprParser import ExprParser

# This class defines a complete listener for a parse tree produced by ExprParser.
class ExprListener(ParseTreeListener):

    # Enter a parse tree produced by ExprParser#start.
    def enterStart(self, ctx:ExprParser.StartContext):
        pass

    # Exit a parse tree produced by ExprParser#start.
    def exitStart(self, ctx:ExprParser.StartContext):
        pass


    # Enter a parse tree produced by ExprParser#expr.
    def enterExpr(self, ctx:ExprParser.ExprContext):
        pass

    # Exit a parse tree produced by ExprParser#expr.
    def exitExpr(self, ctx:ExprParser.ExprContext):
        pass


    # Enter a parse tree produced by ExprParser#Or.
    def enterOr(self, ctx:ExprParser.OrContext):
        pass

    # Exit a parse tree produced by ExprParser#Or.
    def exitOr(self, ctx:ExprParser.OrContext):
        pass


    # Enter a parse tree produced by ExprParser#ToAnd.
    def enterToAnd(self, ctx:ExprParser.ToAndContext):
        pass

    # Exit a parse tree produced by ExprParser#ToAnd.
    def exitToAnd(self, ctx:ExprParser.ToAndContext):
        pass


    # Enter a parse tree produced by ExprParser#And.
    def enterAnd(self, ctx:ExprParser.AndContext):
        pass

    # Exit a parse tree produced by ExprParser#And.
    def exitAnd(self, ctx:ExprParser.AndContext):
        pass


    # Enter a parse tree produced by ExprParser#ToNot.
    def enterToNot(self, ctx:ExprParser.ToNotContext):
        pass

    # Exit a parse tree produced by ExprParser#ToNot.
    def exitToNot(self, ctx:ExprParser.ToNotContext):
        pass


    # Enter a parse tree produced by ExprParser#Not.
    def enterNot(self, ctx:ExprParser.NotContext):
        pass

    # Exit a parse tree produced by ExprParser#Not.
    def exitNot(self, ctx:ExprParser.NotContext):
        pass


    # Enter a parse tree produced by ExprParser#ToRel.
    def enterToRel(self, ctx:ExprParser.ToRelContext):
        pass

    # Exit a parse tree produced by ExprParser#ToRel.
    def exitToRel(self, ctx:ExprParser.ToRelContext):
        pass


    # Enter a parse tree produced by ExprParser#Relational.
    def enterRelational(self, ctx:ExprParser.RelationalContext):
        pass

    # Exit a parse tree produced by ExprParser#Relational.
    def exitRelational(self, ctx:ExprParser.RelationalContext):
        pass


    # Enter a parse tree produced by ExprParser#ToAddSub.
    def enterToAddSub(self, ctx:ExprParser.ToAddSubContext):
        pass

    # Exit a parse tree produced by ExprParser#ToAddSub.
    def exitToAddSub(self, ctx:ExprParser.ToAddSubContext):
        pass


    # Enter a parse tree produced by ExprParser#AddSub.
    def enterAddSub(self, ctx:ExprParser.AddSubContext):
        pass

    # Exit a parse tree produced by ExprParser#AddSub.
    def exitAddSub(self, ctx:ExprParser.AddSubContext):
        pass


    # Enter a parse tree produced by ExprParser#ToMulDiv.
    def enterToMulDiv(self, ctx:ExprParser.ToMulDivContext):
        pass

    # Exit a parse tree produced by ExprParser#ToMulDiv.
    def exitToMulDiv(self, ctx:ExprParser.ToMulDivContext):
        pass


    # Enter a parse tree produced by ExprParser#ToUnary.
    def enterToUnary(self, ctx:ExprParser.ToUnaryContext):
        pass

    # Exit a parse tree produced by ExprParser#ToUnary.
    def exitToUnary(self, ctx:ExprParser.ToUnaryContext):
        pass


    # Enter a parse tree produced by ExprParser#MulDiv.
    def enterMulDiv(self, ctx:ExprParser.MulDivContext):
        pass

    # Exit a parse tree produced by ExprParser#MulDiv.
    def exitMulDiv(self, ctx:ExprParser.MulDivContext):
        pass


    # Enter a parse tree produced by ExprParser#Negate.
    def enterNegate(self, ctx:ExprParser.NegateContext):
        pass

    # Exit a parse tree produced by ExprParser#Negate.
    def exitNegate(self, ctx:ExprParser.NegateContext):
        pass


    # Enter a parse tree produced by ExprParser#ToAtom.
    def enterToAtom(self, ctx:ExprParser.ToAtomContext):
        pass

    # Exit a parse tree produced by ExprParser#ToAtom.
    def exitToAtom(self, ctx:ExprParser.ToAtomContext):
        pass


    # Enter a parse tree produced by ExprParser#ID.
    def enterID(self, ctx:ExprParser.IDContext):
        pass

    # Exit a parse tree produced by ExprParser#ID.
    def exitID(self, ctx:ExprParser.IDContext):
        pass


    # Enter a parse tree produced by ExprParser#Parens.
    def enterParens(self, ctx:ExprParser.ParensContext):
        pass

    # Exit a parse tree produced by ExprParser#Parens.
    def exitParens(self, ctx:ExprParser.ParensContext):
        pass



del ExprParser