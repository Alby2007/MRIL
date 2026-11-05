from solution import pairs


def test_multiple_pairs():
    assert pairs('a=1 b=2 c=3') == [('a', '1'), ('b', '2'), ('c', '3')]


def test_single():
    assert pairs('key=val') == [('key', 'val')]


def test_none_found():
    assert pairs('no pairs here') == []


def test_mixed_text():
    assert pairs('x=10, junk, y=20!') == [('x', '10'), ('y', '20')]
