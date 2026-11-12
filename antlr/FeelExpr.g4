grammar FeelExpr;

// FEEL subset used by bpmn_cwp_verify, plus two extensions: `choose` and triples.
// Constructs of FEEL we do not use (functions, for/some/every, contexts,
// intervals, strings, dates, ...) are lexed or parsed so they can be reported
// as unsupported rather than as plain syntax errors.

start
  : expr EOF
  ;

expr
  : orExpr
  ;

orExpr
  : orExpr 'or' xorExpr     # Or
  | xorExpr                 # ToXor
  ;

xorExpr
  : xorExpr 'xor' andExpr   # Xor
  | andExpr                 # ToAnd
  ;

andExpr
  : andExpr 'and' notExpr   # And
  | notExpr                 # ToNot
  ;

notExpr
  : 'not' notExpr           # Not
  | relExpr                 # ToRel
  ;

relExpr
  : relExpr op=('<' | '<=' | '=' | '!=' | '>' | '>=') addSubExpr  # Relational
  | addSubExpr                                                    # ToAddSub
  ;

addSubExpr
  : addSubExpr op=('+' | '-') mulDivExpr   # AddSub
  | mulDivExpr                             # ToMulDiv
  ;

mulDivExpr
  : mulDivExpr op=('*' | '/') unaryExpr    # MulDiv
  | unaryExpr                              # ToUnary
  ;

unaryExpr
  : '-' unaryExpr           # Negate
  | powExpr                 # ToPow
  ;

powExpr
  : powExpr '**' powOperand # Power
  | postfixExpr             # ToPostfix
  ;

powOperand
  : '-' powOperand          # PowNegate
  | postfixExpr             # PowToPostfix
  ;

postfixExpr
  : postfixExpr '[' expr ']'   # Filter
  | primary                    # ToPrimary
  ;

primary
  : NUMBER                                     # Number
  | 'true'                                     # True
  | 'false'                                    # False
  | NAME '(' (expr (',' expr)*)? ')'           # FunctionCall
  | NAME                                       # Name
  | '[' (expr (',' expr)*)? ']'                # List
  | 'if' expr 'then' expr 'else' expr          # If
  | 'choose' '[' expr (',' expr)* ']'          # Choose
  | triple                                     # ToTriple
  | '(' tripleList ')'                         # ParenTripleList
  | '(' expr ')'                               # Parens
  | unsupported                                # ToUnsupported
  ;

triple
  : '(' NAME ',' '[' (NAME (',' NAME)*)? ']' ',' expr ')'
  ;

tripleList
  : triple (',' triple)+
  ;

// Tokens that only exist in FEEL constructs we do not support.
unsupported
  : STRING
  | NULL
  | DATE_LITERAL
  ;

// Lexer rules
AND      : 'and' ;
OR       : 'or' ;
XOR      : 'xor' ;
NOT      : 'not' ;
IF       : 'if' ;
THEN     : 'then' ;
ELSE     : 'else' ;
CHOOSE   : 'choose' ;
TRUE     : 'true' ;
FALSE    : 'false' ;
NULL     : 'null' ;

// Reserved words of unsupported FEEL constructs.
FOR      : 'for' ;
RETURN   : 'return' ;
SOME     : 'some' ;
EVERY    : 'every' ;
SATISFIES: 'satisfies' ;
IN       : 'in' ;
BETWEEN  : 'between' ;
INSTANCE : 'instance' ;
OF       : 'of' ;
FUNCTION : 'function' ;

NUMBER
  : [0-9]+ ('.' [0-9]+)?
  ;

STRING
  : '"' ( ~["\\\r\n] | '\\' . )* '"'
  ;

NAME
  : [a-zA-Z_] [a-zA-Z0-9_]* ('.' [a-zA-Z_] [a-zA-Z0-9_]*)*
  ;

RANGE  : '..' ;
LBRACE : '{' ;
RBRACE : '}' ;
COLON  : ':' ;
DATE_LITERAL : '@' STRING ;
AT     : '@' ;
QUESTION : '?' ;

WS  : [ \t\r\n]+ -> skip ;
