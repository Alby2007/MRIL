from solution import insert, quote_ident, quote_literal


def test_ident():
    assert quote_ident("users") == '"users"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_literal():
    assert quote_literal("o'brien") == "'o''brien'"
    assert quote_literal(42) == "42"
    assert quote_literal(None) == "NULL"


def test_insert():
    assert insert("t", {"a": "x", "n": 1}) == "INSERT INTO \"t\" (\"a\",\"n\") VALUES ('x',1)"


def test_insert_quotes():
    assert insert("t", {"a": "it's"}) == "INSERT INTO \"t\" (\"a\") VALUES ('it''s')"
