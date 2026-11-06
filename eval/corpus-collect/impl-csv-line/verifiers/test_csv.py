from solution import parse_csv_line


def test_plain():
    assert parse_csv_line('a,b,c') == ['a', 'b', 'c']


def test_quoted_comma():
    assert parse_csv_line('"a,b",c') == ['a,b', 'c']


def test_escaped_quote():
    assert parse_csv_line('"say ""hi""",x') == ['say "hi"', 'x']


def test_empty_fields():
    assert parse_csv_line('a,,b') == ['a', '', 'b']


def test_quoted_spaces():
    assert parse_csv_line(' " padded " ,y') == [' padded ', 'y']


def test_trailing_comma():
    assert parse_csv_line('a,b,') == ['a', 'b', '']
