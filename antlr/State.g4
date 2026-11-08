grammar State;

state
  : (enum_type_decl)* (const_var_decl)* (var_decl)+ EOF
  ;

enum_type_decl
  : ENUM ID LCURLY id_set RCURLY
  ;

id_set
  : (ID)+
  ;

const_var_decl
  : CONST ID COLON type EQUALS ID
  ;

var_decl
  : VAR ID COLON type EQUALS ID (LCURLY id_set RCURLY)?
  ;

type
  : primitive_type
  | ID
  ;

primitive_type
  : BIT
  | BOOL
  | BYTE
  | INT
  | SHORT
  ;

// ---------------------------------------------------------------------------
// Lexer Rules
// ---------------------------------------------------------------------------

COLON
  : ':'
  ;

BIT
  : 'bit'
  ;

BOOL
  : 'bool'
  ;

BYTE
  : 'byte'
  ;

CONST
  : 'const'
  ;

ENUM
  : 'enum'
  ;

INT
  : 'int'
  ;

SHORT
  : 'short'
  ;

EQUALS
  : '='
  ;

LCURLY
  : '{'
  ;

RCURLY
  : '}'
  ;

VAR
  : 'var'
  ;

ID
  : [a-zA-Z0-9_]+
  ;

WS : [ \t\n\r]+ -> skip ;
