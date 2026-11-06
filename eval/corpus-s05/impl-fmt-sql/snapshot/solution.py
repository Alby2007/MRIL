def quote_ident(name):
    """SQL identifier -> "name" (double-quoted, inner quotes doubled)."""
    raise NotImplementedError


def quote_literal(val):
    """SQL string literal -> 'val' (single-quoted, inner quotes doubled).
    ints/floats pass through unquoted; None -> NULL."""
    raise NotImplementedError


def insert(table, row):
    """INSERT INTO "t" ("c1","c2") VALUES ('v',1); row is {col: val}."""
    raise NotImplementedError
