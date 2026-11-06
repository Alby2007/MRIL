from solution import render


def test_escape_renders_literal():
    assert render('{{x}} {a}', {'a': '1'}) == '{x} 1'


def test_absent_key_stays():
    assert render('{a} {zz}', {'a': '1'}) == '1 {zz}'


def test_plain_substitution():
    assert render('hi {n}', {'n': 'bob'}) == 'hi bob'


def test_both_escapes():
    assert render('{{a}} and {{b}}', {}) == '{a} and {b}'
