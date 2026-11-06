from solution import sliding_max


def test_basic():
    assert sliding_max([1, 3, -1, -3, 5, 3, 6, 7], 3) == [3, 3, 5, 5, 6, 7]


def test_full_window():
    assert sliding_max([4, 2], 2) == [4]
    assert sliding_max([5], 1) == [5]


def test_edges():
    assert sliding_max([], 1) == []
    assert sliding_max([1, 2, 3], 2) == [2, 3]
