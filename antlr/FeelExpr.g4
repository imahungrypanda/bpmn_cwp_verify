grammar FeelExpr;

// Entry points: an expression (conditions) or a task behavior (triples).
start
  : expr EOF
  ;

behavior
  : triple (',' triple)* EOF
  ;

// (target, [inputs], value)
triple
  : '(' name ',' nameList ',' expr ')'
  ;

nameList
  : '[' (name (',' name)*)? ']'
  ;

expr
  : 'if' expr 'then' expr 'else' expr                                   # If
  | 'for' forBinding (',' forBinding)* 'return' expr                    # For
  | quant=('some' | 'every') forBinding (',' forBinding)* 'satisfies' expr  # Quantified
  | orExpr                                                              # ToOr
  ;

forBinding
  : name 'in' expr
  ;

orExpr
  : orExpr 'or' xorExpr                 # Or
  | xorExpr                             # ToXor
  ;

xorExpr
  : xorExpr 'xor' andExpr               # Xor
  | andExpr                             # ToAnd
  ;

andExpr
  : andExpr 'and' notExpr               # And
  | notExpr                             # ToNot
  ;

notExpr
  : 'not' notExpr                       # Not
  | relExpr                             # ToRel
  ;

relExpr
  : relExpr op=('<' | '<=' | '=' | '!=' | '>' | '>=') addSubExpr        # Relational
  | relExpr 'between' addSubExpr 'and' addSubExpr                       # Between
  | relExpr 'in' addSubExpr                                             # InTest
  | addSubExpr                                                          # ToAddSub
  ;

addSubExpr
  : addSubExpr op=('+' | '-') mulDivExpr    # AddSub
  | mulDivExpr                              # ToMulDiv
  ;

mulDivExpr
  : mulDivExpr op=('*' | '/') unaryExpr     # MulDiv
  | unaryExpr                               # ToUnary
  ;

unaryExpr
  : '-' unaryExpr                       # Negate
  | powExpr                             # ToPow
  ;

powExpr
  : powExpr '**' unaryExpr              # Pow
  | postfixExpr                         # ToPostfix
  ;

postfixExpr
  : postfixExpr '[' expr ']'            # Filter
  | atom                                # ToAtom
  ;

atom
  : NUMBER                              # Number
  | 'true'                              # True
  | 'false'                             # False
  | name                                # Ref
  | list                                # ListLit
  | 'choose' list                       # Choose
  | '(' expr ')'                        # Parens
  // Constructs FEEL has but this tool does not use; they parse so they can
  // be reported as unsupported rather than as bad syntax.
  | STRING                              # String
  | 'null'                              # Null
  | '@' STRING                          # DateLiteral
  | name '(' (expr (',' expr)*)? ')'    # Call
  | 'function' '(' (name (',' name)*)? ')' expr  # FunctionDef
  | '{' (contextEntry (',' contextEntry)*)? '}'  # Context
  | start_=('(' | ']' | '[') expr '..' expr end_=(')' | '[' | ']')  # Interval
  ;

contextEntry
  : (name | STRING) ':' expr
  ;

list
  : '[' (expr (',' expr)*)? ']'
  ;

name
  : NAME
  ;

// Lexer rules. Keywords come before NAME so they win ties.
NUMBER
  : [0-9]+ ('.' [0-9]+)?
  | '.' [0-9]+
  ;

STRING
  : '"' (~["\\\r\n] | '\\' .)* '"'
  ;

NAME
  : [a-zA-Z_] [a-zA-Z0-9_]* ('.' [a-zA-Z_] [a-zA-Z0-9_]*)*
  ;

WS  : [ \t\r\n]+ -> skip ;
