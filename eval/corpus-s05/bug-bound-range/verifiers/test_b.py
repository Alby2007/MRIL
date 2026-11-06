from solution import ranges_overlap


def test_overlap():
    assert ranges_overlap((1, 5), (3, 8)) is True
    assert ranges_overlap((1, 2), (5, 9)) is False


def test_touching_counts():
    assert ranges_overlap((1, 5), (5, 9)) is True
    assert ranges_overlap((0, 0), (0, 0)) is True


def test_nested():
    assert ranges_overlap((1, 10), (3, 4)) is True
