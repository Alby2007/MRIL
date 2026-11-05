from solution import render


def test_repeated_placeholder():
    assert render('{a}-{a}', {'a': 'x'}) == 'x-x'


def test_two_keys():
    assert render('{a}{b}{a}', {'a': '1', 'b': '2'}) == '121'


def test_unknown_stays():
    assert render('{a} {zz}', {'a': '1'}) == '1 {zz}'


def test_no_placeholders():
    assert render('plain', {}) == 'plain'
