from solution import WordCounter


def test_most_frequent():
    c = WordCounter()
    for w in ['a', 'b', 'a', 'c', 'a', 'b']:
        c.add(w)
    assert c.top() == 'a'


def test_late_surge_wins():
    c = WordCounter()
    for w in ['x', 'x', 'y', 'y', 'y']:
        c.add(w)
    assert c.top() == 'y'


def test_empty():
    assert WordCounter().top() is None
