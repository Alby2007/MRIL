from solution import render


def test_escaped_braces():
    assert render('{{lit}} {v}', {'v': 'x'}) == '{lit} x'


def test_padding():
    assert render('[{n:>5}]', {'n': 'ab'}) == '[   ab]'


def test_coerce_values():
    assert render('{n}', {'n': 7}) == '7'


def test_absent_is_empty_text():
    assert render('a{zz}b', {}) == 'ab'


def test_combined():
    # '{{' -> '{', '{v:>4}' -> right-padded width 4, '}}' -> '}'
    assert render('{{{v:>4}}}', {'v': 'k'}) == '{   k}'
