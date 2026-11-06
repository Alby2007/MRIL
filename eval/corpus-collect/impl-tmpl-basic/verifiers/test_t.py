from solution import render


def test_basic():
    assert render('hi {n}', {'n': 'bob'}) == 'hi bob'


def test_repeated():
    assert render('{a}/{a}', {'a': 'x'}) == 'x/x'


def test_unknown_kept():
    assert render('{a} {zz}', {'a': '1'}) == '1 {zz}'


def test_multiple():
    out = render('{greet} {who}!', {'greet': 'yo', 'who': 'sam'})
    assert out == 'yo sam!'
