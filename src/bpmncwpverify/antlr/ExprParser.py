# Generated from antlr/Expr.g4 by ANTLR 4.13.2
# encoding: utf-8
# type: ignore
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
	from typing import TextIO
else:
	from typing.io import TextIO

def serializedATN():
    return [
        4,1,18,98,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,6,7,
        6,2,7,7,7,2,8,7,8,2,9,7,9,1,0,1,0,1,0,1,1,1,1,1,2,1,2,1,2,1,2,1,
        2,1,2,5,2,32,8,2,10,2,12,2,35,9,2,1,3,1,3,1,3,1,3,1,3,1,3,5,3,43,
        8,3,10,3,12,3,46,9,3,1,4,1,4,1,4,3,4,51,8,4,1,5,1,5,1,5,1,5,1,5,
        1,5,5,5,59,8,5,10,5,12,5,62,9,5,1,6,1,6,1,6,1,6,1,6,1,6,5,6,70,8,
        6,10,6,12,6,73,9,6,1,7,1,7,1,7,1,7,1,7,1,7,5,7,81,8,7,10,7,12,7,
        84,9,7,1,8,1,8,1,8,3,8,89,8,8,1,9,1,9,1,9,1,9,1,9,3,9,96,8,9,1,9,
        0,5,4,6,10,12,14,10,0,2,4,6,8,10,12,14,16,18,0,3,1,0,4,9,1,0,10,
        11,1,0,12,14,95,0,20,1,0,0,0,2,23,1,0,0,0,4,25,1,0,0,0,6,36,1,0,
        0,0,8,50,1,0,0,0,10,52,1,0,0,0,12,63,1,0,0,0,14,74,1,0,0,0,16,88,
        1,0,0,0,18,95,1,0,0,0,20,21,3,2,1,0,21,22,5,0,0,1,22,1,1,0,0,0,23,
        24,3,4,2,0,24,3,1,0,0,0,25,26,6,2,-1,0,26,27,3,6,3,0,27,33,1,0,0,
        0,28,29,10,2,0,0,29,30,5,1,0,0,30,32,3,6,3,0,31,28,1,0,0,0,32,35,
        1,0,0,0,33,31,1,0,0,0,33,34,1,0,0,0,34,5,1,0,0,0,35,33,1,0,0,0,36,
        37,6,3,-1,0,37,38,3,8,4,0,38,44,1,0,0,0,39,40,10,2,0,0,40,41,5,2,
        0,0,41,43,3,8,4,0,42,39,1,0,0,0,43,46,1,0,0,0,44,42,1,0,0,0,44,45,
        1,0,0,0,45,7,1,0,0,0,46,44,1,0,0,0,47,48,5,3,0,0,48,51,3,8,4,0,49,
        51,3,10,5,0,50,47,1,0,0,0,50,49,1,0,0,0,51,9,1,0,0,0,52,53,6,5,-1,
        0,53,54,3,12,6,0,54,60,1,0,0,0,55,56,10,2,0,0,56,57,7,0,0,0,57,59,
        3,12,6,0,58,55,1,0,0,0,59,62,1,0,0,0,60,58,1,0,0,0,60,61,1,0,0,0,
        61,11,1,0,0,0,62,60,1,0,0,0,63,64,6,6,-1,0,64,65,3,14,7,0,65,71,
        1,0,0,0,66,67,10,2,0,0,67,68,7,1,0,0,68,70,3,14,7,0,69,66,1,0,0,
        0,70,73,1,0,0,0,71,69,1,0,0,0,71,72,1,0,0,0,72,13,1,0,0,0,73,71,
        1,0,0,0,74,75,6,7,-1,0,75,76,3,16,8,0,76,82,1,0,0,0,77,78,10,2,0,
        0,78,79,7,2,0,0,79,81,3,16,8,0,80,77,1,0,0,0,81,84,1,0,0,0,82,80,
        1,0,0,0,82,83,1,0,0,0,83,15,1,0,0,0,84,82,1,0,0,0,85,86,5,11,0,0,
        86,89,3,16,8,0,87,89,3,18,9,0,88,85,1,0,0,0,88,87,1,0,0,0,89,17,
        1,0,0,0,90,96,5,17,0,0,91,92,5,15,0,0,92,93,3,2,1,0,93,94,5,16,0,
        0,94,96,1,0,0,0,95,90,1,0,0,0,95,91,1,0,0,0,96,19,1,0,0,0,8,33,44,
        50,60,71,82,88,95
    ]

class ExprParser ( Parser ):

    grammarFileName = "Expr.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'||'", "'&&'", "'!'", "'<'", "'<='", 
                     "'!='", "'=='", "'>'", "'>='", "'+'", "'-'", "'*'", 
                     "'/'", "'%'", "'('", "')'" ]

    symbolicNames = [ "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                      "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                      "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                      "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                      "<INVALID>", "ID", "WS" ]

    RULE_start = 0
    RULE_expr = 1
    RULE_orExpr = 2
    RULE_andExpr = 3
    RULE_notExpr = 4
    RULE_relExpr = 5
    RULE_addSubExpr = 6
    RULE_mulDivExpr = 7
    RULE_unaryExpr = 8
    RULE_atom = 9

    ruleNames =  [ "start", "expr", "orExpr", "andExpr", "notExpr", "relExpr", 
                   "addSubExpr", "mulDivExpr", "unaryExpr", "atom" ]

    EOF = Token.EOF
    T__0=1
    T__1=2
    T__2=3
    T__3=4
    T__4=5
    T__5=6
    T__6=7
    T__7=8
    T__8=9
    T__9=10
    T__10=11
    T__11=12
    T__12=13
    T__13=14
    T__14=15
    T__15=16
    ID=17
    WS=18

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class StartContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def expr(self):
            return self.getTypedRuleContext(ExprParser.ExprContext,0)


        def EOF(self):
            return self.getToken(ExprParser.EOF, 0)

        def getRuleIndex(self):
            return ExprParser.RULE_start

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterStart" ):
                listener.enterStart(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitStart" ):
                listener.exitStart(self)




    def start(self):

        localctx = ExprParser.StartContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_start)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 20
            self.expr()
            self.state = 21
            self.match(ExprParser.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class ExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def orExpr(self):
            return self.getTypedRuleContext(ExprParser.OrExprContext,0)


        def getRuleIndex(self):
            return ExprParser.RULE_expr

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterExpr" ):
                listener.enterExpr(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitExpr" ):
                listener.exitExpr(self)




    def expr(self):

        localctx = ExprParser.ExprContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_expr)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 23
            self.orExpr(0)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class OrExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_orExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)


    class OrContext(OrExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.OrExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def orExpr(self):
            return self.getTypedRuleContext(ExprParser.OrExprContext,0)

        def andExpr(self):
            return self.getTypedRuleContext(ExprParser.AndExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterOr" ):
                listener.enterOr(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitOr" ):
                listener.exitOr(self)


    class ToAndContext(OrExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.OrExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def andExpr(self):
            return self.getTypedRuleContext(ExprParser.AndExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToAnd" ):
                listener.enterToAnd(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToAnd" ):
                listener.exitToAnd(self)



    def orExpr(self, _p:int=0):
        _parentctx = self._ctx
        _parentState = self.state
        localctx = ExprParser.OrExprContext(self, self._ctx, _parentState)
        _prevctx = localctx
        _startState = 4
        self.enterRecursionRule(localctx, 4, self.RULE_orExpr, _p)
        try:
            self.enterOuterAlt(localctx, 1)
            localctx = ExprParser.ToAndContext(self, localctx)
            self._ctx = localctx
            _prevctx = localctx

            self.state = 26
            self.andExpr(0)
            self._ctx.stop = self._input.LT(-1)
            self.state = 33
            self._errHandler.sync(self)
            _alt = self._interp.adaptivePredict(self._input,0,self._ctx)
            while _alt!=2 and _alt!=ATN.INVALID_ALT_NUMBER:
                if _alt==1:
                    if self._parseListeners is not None:
                        self.triggerExitRuleEvent()
                    _prevctx = localctx
                    localctx = ExprParser.OrContext(self, ExprParser.OrExprContext(self, _parentctx, _parentState))
                    self.pushNewRecursionContext(localctx, _startState, self.RULE_orExpr)
                    self.state = 28
                    if not self.precpred(self._ctx, 2):
                        from antlr4.error.Errors import FailedPredicateException
                        raise FailedPredicateException(self, "self.precpred(self._ctx, 2)")
                    self.state = 29
                    self.match(ExprParser.T__0)
                    self.state = 30
                    self.andExpr(0) 
                self.state = 35
                self._errHandler.sync(self)
                _alt = self._interp.adaptivePredict(self._input,0,self._ctx)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.unrollRecursionContexts(_parentctx)
        return localctx


    class AndExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_andExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)


    class AndContext(AndExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AndExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def andExpr(self):
            return self.getTypedRuleContext(ExprParser.AndExprContext,0)

        def notExpr(self):
            return self.getTypedRuleContext(ExprParser.NotExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterAnd" ):
                listener.enterAnd(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitAnd" ):
                listener.exitAnd(self)


    class ToNotContext(AndExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AndExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def notExpr(self):
            return self.getTypedRuleContext(ExprParser.NotExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToNot" ):
                listener.enterToNot(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToNot" ):
                listener.exitToNot(self)



    def andExpr(self, _p:int=0):
        _parentctx = self._ctx
        _parentState = self.state
        localctx = ExprParser.AndExprContext(self, self._ctx, _parentState)
        _prevctx = localctx
        _startState = 6
        self.enterRecursionRule(localctx, 6, self.RULE_andExpr, _p)
        try:
            self.enterOuterAlt(localctx, 1)
            localctx = ExprParser.ToNotContext(self, localctx)
            self._ctx = localctx
            _prevctx = localctx

            self.state = 37
            self.notExpr()
            self._ctx.stop = self._input.LT(-1)
            self.state = 44
            self._errHandler.sync(self)
            _alt = self._interp.adaptivePredict(self._input,1,self._ctx)
            while _alt!=2 and _alt!=ATN.INVALID_ALT_NUMBER:
                if _alt==1:
                    if self._parseListeners is not None:
                        self.triggerExitRuleEvent()
                    _prevctx = localctx
                    localctx = ExprParser.AndContext(self, ExprParser.AndExprContext(self, _parentctx, _parentState))
                    self.pushNewRecursionContext(localctx, _startState, self.RULE_andExpr)
                    self.state = 39
                    if not self.precpred(self._ctx, 2):
                        from antlr4.error.Errors import FailedPredicateException
                        raise FailedPredicateException(self, "self.precpred(self._ctx, 2)")
                    self.state = 40
                    self.match(ExprParser.T__1)
                    self.state = 41
                    self.notExpr() 
                self.state = 46
                self._errHandler.sync(self)
                _alt = self._interp.adaptivePredict(self._input,1,self._ctx)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.unrollRecursionContexts(_parentctx)
        return localctx


    class NotExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_notExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)



    class NotContext(NotExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.NotExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def notExpr(self):
            return self.getTypedRuleContext(ExprParser.NotExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterNot" ):
                listener.enterNot(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitNot" ):
                listener.exitNot(self)


    class ToRelContext(NotExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.NotExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def relExpr(self):
            return self.getTypedRuleContext(ExprParser.RelExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToRel" ):
                listener.enterToRel(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToRel" ):
                listener.exitToRel(self)



    def notExpr(self):

        localctx = ExprParser.NotExprContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_notExpr)
        try:
            self.state = 50
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [3]:
                localctx = ExprParser.NotContext(self, localctx)
                self.enterOuterAlt(localctx, 1)
                self.state = 47
                self.match(ExprParser.T__2)
                self.state = 48
                self.notExpr()
                pass
            elif token in [11, 15, 17]:
                localctx = ExprParser.ToRelContext(self, localctx)
                self.enterOuterAlt(localctx, 2)
                self.state = 49
                self.relExpr(0)
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class RelExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_relExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)


    class RelationalContext(RelExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.RelExprContext
            super().__init__(parser)
            self.op = None # Token
            self.copyFrom(ctx)

        def relExpr(self):
            return self.getTypedRuleContext(ExprParser.RelExprContext,0)

        def addSubExpr(self):
            return self.getTypedRuleContext(ExprParser.AddSubExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterRelational" ):
                listener.enterRelational(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitRelational" ):
                listener.exitRelational(self)


    class ToAddSubContext(RelExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.RelExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def addSubExpr(self):
            return self.getTypedRuleContext(ExprParser.AddSubExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToAddSub" ):
                listener.enterToAddSub(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToAddSub" ):
                listener.exitToAddSub(self)



    def relExpr(self, _p:int=0):
        _parentctx = self._ctx
        _parentState = self.state
        localctx = ExprParser.RelExprContext(self, self._ctx, _parentState)
        _prevctx = localctx
        _startState = 10
        self.enterRecursionRule(localctx, 10, self.RULE_relExpr, _p)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            localctx = ExprParser.ToAddSubContext(self, localctx)
            self._ctx = localctx
            _prevctx = localctx

            self.state = 53
            self.addSubExpr(0)
            self._ctx.stop = self._input.LT(-1)
            self.state = 60
            self._errHandler.sync(self)
            _alt = self._interp.adaptivePredict(self._input,3,self._ctx)
            while _alt!=2 and _alt!=ATN.INVALID_ALT_NUMBER:
                if _alt==1:
                    if self._parseListeners is not None:
                        self.triggerExitRuleEvent()
                    _prevctx = localctx
                    localctx = ExprParser.RelationalContext(self, ExprParser.RelExprContext(self, _parentctx, _parentState))
                    self.pushNewRecursionContext(localctx, _startState, self.RULE_relExpr)
                    self.state = 55
                    if not self.precpred(self._ctx, 2):
                        from antlr4.error.Errors import FailedPredicateException
                        raise FailedPredicateException(self, "self.precpred(self._ctx, 2)")
                    self.state = 56
                    localctx.op = self._input.LT(1)
                    _la = self._input.LA(1)
                    if not((((_la) & ~0x3f) == 0 and ((1 << _la) & 1008) != 0)):
                        localctx.op = self._errHandler.recoverInline(self)
                    else:
                        self._errHandler.reportMatch(self)
                        self.consume()
                    self.state = 57
                    self.addSubExpr(0) 
                self.state = 62
                self._errHandler.sync(self)
                _alt = self._interp.adaptivePredict(self._input,3,self._ctx)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.unrollRecursionContexts(_parentctx)
        return localctx


    class AddSubExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_addSubExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)


    class AddSubContext(AddSubExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AddSubExprContext
            super().__init__(parser)
            self.op = None # Token
            self.copyFrom(ctx)

        def addSubExpr(self):
            return self.getTypedRuleContext(ExprParser.AddSubExprContext,0)

        def mulDivExpr(self):
            return self.getTypedRuleContext(ExprParser.MulDivExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterAddSub" ):
                listener.enterAddSub(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitAddSub" ):
                listener.exitAddSub(self)


    class ToMulDivContext(AddSubExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AddSubExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def mulDivExpr(self):
            return self.getTypedRuleContext(ExprParser.MulDivExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToMulDiv" ):
                listener.enterToMulDiv(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToMulDiv" ):
                listener.exitToMulDiv(self)



    def addSubExpr(self, _p:int=0):
        _parentctx = self._ctx
        _parentState = self.state
        localctx = ExprParser.AddSubExprContext(self, self._ctx, _parentState)
        _prevctx = localctx
        _startState = 12
        self.enterRecursionRule(localctx, 12, self.RULE_addSubExpr, _p)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            localctx = ExprParser.ToMulDivContext(self, localctx)
            self._ctx = localctx
            _prevctx = localctx

            self.state = 64
            self.mulDivExpr(0)
            self._ctx.stop = self._input.LT(-1)
            self.state = 71
            self._errHandler.sync(self)
            _alt = self._interp.adaptivePredict(self._input,4,self._ctx)
            while _alt!=2 and _alt!=ATN.INVALID_ALT_NUMBER:
                if _alt==1:
                    if self._parseListeners is not None:
                        self.triggerExitRuleEvent()
                    _prevctx = localctx
                    localctx = ExprParser.AddSubContext(self, ExprParser.AddSubExprContext(self, _parentctx, _parentState))
                    self.pushNewRecursionContext(localctx, _startState, self.RULE_addSubExpr)
                    self.state = 66
                    if not self.precpred(self._ctx, 2):
                        from antlr4.error.Errors import FailedPredicateException
                        raise FailedPredicateException(self, "self.precpred(self._ctx, 2)")
                    self.state = 67
                    localctx.op = self._input.LT(1)
                    _la = self._input.LA(1)
                    if not(_la==10 or _la==11):
                        localctx.op = self._errHandler.recoverInline(self)
                    else:
                        self._errHandler.reportMatch(self)
                        self.consume()
                    self.state = 68
                    self.mulDivExpr(0) 
                self.state = 73
                self._errHandler.sync(self)
                _alt = self._interp.adaptivePredict(self._input,4,self._ctx)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.unrollRecursionContexts(_parentctx)
        return localctx


    class MulDivExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_mulDivExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)


    class ToUnaryContext(MulDivExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.MulDivExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def unaryExpr(self):
            return self.getTypedRuleContext(ExprParser.UnaryExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToUnary" ):
                listener.enterToUnary(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToUnary" ):
                listener.exitToUnary(self)


    class MulDivContext(MulDivExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.MulDivExprContext
            super().__init__(parser)
            self.op = None # Token
            self.copyFrom(ctx)

        def mulDivExpr(self):
            return self.getTypedRuleContext(ExprParser.MulDivExprContext,0)

        def unaryExpr(self):
            return self.getTypedRuleContext(ExprParser.UnaryExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterMulDiv" ):
                listener.enterMulDiv(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitMulDiv" ):
                listener.exitMulDiv(self)



    def mulDivExpr(self, _p:int=0):
        _parentctx = self._ctx
        _parentState = self.state
        localctx = ExprParser.MulDivExprContext(self, self._ctx, _parentState)
        _prevctx = localctx
        _startState = 14
        self.enterRecursionRule(localctx, 14, self.RULE_mulDivExpr, _p)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            localctx = ExprParser.ToUnaryContext(self, localctx)
            self._ctx = localctx
            _prevctx = localctx

            self.state = 75
            self.unaryExpr()
            self._ctx.stop = self._input.LT(-1)
            self.state = 82
            self._errHandler.sync(self)
            _alt = self._interp.adaptivePredict(self._input,5,self._ctx)
            while _alt!=2 and _alt!=ATN.INVALID_ALT_NUMBER:
                if _alt==1:
                    if self._parseListeners is not None:
                        self.triggerExitRuleEvent()
                    _prevctx = localctx
                    localctx = ExprParser.MulDivContext(self, ExprParser.MulDivExprContext(self, _parentctx, _parentState))
                    self.pushNewRecursionContext(localctx, _startState, self.RULE_mulDivExpr)
                    self.state = 77
                    if not self.precpred(self._ctx, 2):
                        from antlr4.error.Errors import FailedPredicateException
                        raise FailedPredicateException(self, "self.precpred(self._ctx, 2)")
                    self.state = 78
                    localctx.op = self._input.LT(1)
                    _la = self._input.LA(1)
                    if not((((_la) & ~0x3f) == 0 and ((1 << _la) & 28672) != 0)):
                        localctx.op = self._errHandler.recoverInline(self)
                    else:
                        self._errHandler.reportMatch(self)
                        self.consume()
                    self.state = 79
                    self.unaryExpr() 
                self.state = 84
                self._errHandler.sync(self)
                _alt = self._interp.adaptivePredict(self._input,5,self._ctx)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.unrollRecursionContexts(_parentctx)
        return localctx


    class UnaryExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_unaryExpr

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)



    class NegateContext(UnaryExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.UnaryExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def unaryExpr(self):
            return self.getTypedRuleContext(ExprParser.UnaryExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterNegate" ):
                listener.enterNegate(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitNegate" ):
                listener.exitNegate(self)


    class ToAtomContext(UnaryExprContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.UnaryExprContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def atom(self):
            return self.getTypedRuleContext(ExprParser.AtomContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterToAtom" ):
                listener.enterToAtom(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitToAtom" ):
                listener.exitToAtom(self)



    def unaryExpr(self):

        localctx = ExprParser.UnaryExprContext(self, self._ctx, self.state)
        self.enterRule(localctx, 16, self.RULE_unaryExpr)
        try:
            self.state = 88
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [11]:
                localctx = ExprParser.NegateContext(self, localctx)
                self.enterOuterAlt(localctx, 1)
                self.state = 85
                self.match(ExprParser.T__10)
                self.state = 86
                self.unaryExpr()
                pass
            elif token in [15, 17]:
                localctx = ExprParser.ToAtomContext(self, localctx)
                self.enterOuterAlt(localctx, 2)
                self.state = 87
                self.atom()
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class AtomContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser


        def getRuleIndex(self):
            return ExprParser.RULE_atom

     
        def copyFrom(self, ctx:ParserRuleContext):
            super().copyFrom(ctx)



    class ParensContext(AtomContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AtomContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def expr(self):
            return self.getTypedRuleContext(ExprParser.ExprContext,0)


        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterParens" ):
                listener.enterParens(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitParens" ):
                listener.exitParens(self)


    class IDContext(AtomContext):

        def __init__(self, parser, ctx:ParserRuleContext): # actually a ExprParser.AtomContext
            super().__init__(parser)
            self.copyFrom(ctx)

        def ID(self):
            return self.getToken(ExprParser.ID, 0)

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterID" ):
                listener.enterID(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitID" ):
                listener.exitID(self)



    def atom(self):

        localctx = ExprParser.AtomContext(self, self._ctx, self.state)
        self.enterRule(localctx, 18, self.RULE_atom)
        try:
            self.state = 95
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [17]:
                localctx = ExprParser.IDContext(self, localctx)
                self.enterOuterAlt(localctx, 1)
                self.state = 90
                self.match(ExprParser.ID)
                pass
            elif token in [15]:
                localctx = ExprParser.ParensContext(self, localctx)
                self.enterOuterAlt(localctx, 2)
                self.state = 91
                self.match(ExprParser.T__14)
                self.state = 92
                self.expr()
                self.state = 93
                self.match(ExprParser.T__15)
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx



    def sempred(self, localctx:RuleContext, ruleIndex:int, predIndex:int):
        if self._predicates == None:
            self._predicates = dict()
        self._predicates[2] = self.orExpr_sempred
        self._predicates[3] = self.andExpr_sempred
        self._predicates[5] = self.relExpr_sempred
        self._predicates[6] = self.addSubExpr_sempred
        self._predicates[7] = self.mulDivExpr_sempred
        pred = self._predicates.get(ruleIndex, None)
        if pred is None:
            raise Exception("No predicate with index:" + str(ruleIndex))
        else:
            return pred(localctx, predIndex)

    def orExpr_sempred(self, localctx:OrExprContext, predIndex:int):
            if predIndex == 0:
                return self.precpred(self._ctx, 2)
         

    def andExpr_sempred(self, localctx:AndExprContext, predIndex:int):
            if predIndex == 1:
                return self.precpred(self._ctx, 2)
         

    def relExpr_sempred(self, localctx:RelExprContext, predIndex:int):
            if predIndex == 2:
                return self.precpred(self._ctx, 2)
         

    def addSubExpr_sempred(self, localctx:AddSubExprContext, predIndex:int):
            if predIndex == 3:
                return self.precpred(self._ctx, 2)
         

    def mulDivExpr_sempred(self, localctx:MulDivExprContext, predIndex:int):
            if predIndex == 4:
                return self.precpred(self._ctx, 2)
         




