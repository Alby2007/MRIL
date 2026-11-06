from solution import windowed


def test_basic():
    assert list(windowed(range(5), 3)) == [(0, 1, 2), (1, 2, 3), (2, 3, 4)]


def test_returns_tuples():
    first = next(iter(windowed([1, 2, 3], 2)))
    assert isinstance(first, tuple)


def test_short_input():
    assert list(windowed([1], 2)) == []
    assert list(windowed([], 1)) == []
    assert list(windowed([1, 2], 2)) == [(1, 2)]


def test_lazy_single_pass():
    seen = []

    def gen():
        for i in range(10):
            seen.append(i)
            yield i

    it = windowed(gen(), 3)
    next(it)
    assert len(seen) <= 4         # must not consume all 10 up front
    assert len(list(it)) == 7
