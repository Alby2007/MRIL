from solution import paginate


def test_middle_pages():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_partial_last_page():
    assert paginate(list(range(10)), 4, 3) == [9]
    assert paginate(list(range(7)), 2, 4) == [4, 5, 6]


def test_out_of_range_and_empty():
    assert paginate(list(range(10)), 5, 3) == []
    assert paginate([], 1, 5) == []
    assert paginate([1, 2, 3], 1, 3) == [1, 2, 3]
