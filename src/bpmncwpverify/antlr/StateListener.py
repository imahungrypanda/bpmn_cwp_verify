# Generated from antlr/State.g4 by ANTLR 4.13.1
from antlr4 import *
if "." in __name__:
    from .StateParser import StateParser
else:
    from StateParser import StateParser

# This class defines a complete listener for a parse tree produced by StateParser.
class StateListener(ParseTreeListener):

    # Enter a parse tree produced by StateParser#state.
    def enterState(self, ctx:StateParser.StateContext):
        pass

    # Exit a parse tree produced by StateParser#state.
    def exitState(self, ctx:StateParser.StateContext):
        pass


    # Enter a parse tree produced by StateParser#enum_type_decl.
    def enterEnum_type_decl(self, ctx:StateParser.Enum_type_declContext):
        pass

    # Exit a parse tree produced by StateParser#enum_type_decl.
    def exitEnum_type_decl(self, ctx:StateParser.Enum_type_declContext):
        pass


    # Enter a parse tree produced by StateParser#id_set.
    def enterId_set(self, ctx:StateParser.Id_setContext):
        pass

    # Exit a parse tree produced by StateParser#id_set.
    def exitId_set(self, ctx:StateParser.Id_setContext):
        pass


    # Enter a parse tree produced by StateParser#const_var_decl.
    def enterConst_var_decl(self, ctx:StateParser.Const_var_declContext):
        pass

    # Exit a parse tree produced by StateParser#const_var_decl.
    def exitConst_var_decl(self, ctx:StateParser.Const_var_declContext):
        pass


    # Enter a parse tree produced by StateParser#var_decl.
    def enterVar_decl(self, ctx:StateParser.Var_declContext):
        pass

    # Exit a parse tree produced by StateParser#var_decl.
    def exitVar_decl(self, ctx:StateParser.Var_declContext):
        pass


    # Enter a parse tree produced by StateParser#type.
    def enterType(self, ctx:StateParser.TypeContext):
        pass

    # Exit a parse tree produced by StateParser#type.
    def exitType(self, ctx:StateParser.TypeContext):
        pass


    # Enter a parse tree produced by StateParser#primitive_type.
    def enterPrimitive_type(self, ctx:StateParser.Primitive_typeContext):
        pass

    # Exit a parse tree produced by StateParser#primitive_type.
    def exitPrimitive_type(self, ctx:StateParser.Primitive_typeContext):
        pass



del StateParser