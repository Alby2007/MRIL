from solution import make_counters


def test_each_returns_own_index():
    fns = make_counters(5)
    assert [f() for f in fns] == [0, 1, 2, 3, 4]


def test_called_later_still_correct():
    fns = make_counters(3)
    first, second, third = fns
    assert third() == 2
    assert first() == 0
    assert second() == 1


def test_single():
    fns = make_counters(1)
    assert fns[0]() == 0
