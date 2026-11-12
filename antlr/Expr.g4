grammar Expr;

start
  : expr EOF
  ;

expr:   orExpr ;

orExpr
    :   orExpr '||' andExpr       # Or
    |   andExpr                   # ToAnd
    ;

andExpr
    :   andExpr '&&' notExpr     # And
    |   notExpr                  # ToNot
    ;

notExpr
    :   '!' notExpr             # Not
    |   relExpr                 # ToRel
    ;

relExpr
    :   relExpr op=('<' | '<=' | '==' | '!=' | '>' | '>=') addSubExpr  # Relational
    |   addSubExpr                                              # ToAddSub
    ;

addSubExpr
    :   addSubExpr op=('+'|'-') mulDivExpr   # AddSub
    |   mulDivExpr                           # ToMulDiv
    ;

mulDivExpr
    :   mulDivExpr op=('*'|'/'|'%') unaryExpr    # MulDiv
    |   unaryExpr                                # ToUnary
    ;

unaryExpr
    :   '-' unaryExpr                       # Negate
    |   atom                                # ToAtom
    ;

atom
    :   ID                                  # ID
    |   '(' expr ')'                        # Parens
    ;

// Lexer rules
ID
  : [a-zA-Z0-9_]+
  ;

WS  :   [ \t\r\n]+ -> skip ;
