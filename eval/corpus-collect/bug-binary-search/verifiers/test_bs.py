from solution import binary_search


def test_found_middle():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2


def test_found_edges():
    assert binary_search([1, 3, 5], 1) == 0
    assert binary_search([1, 3, 5], 5) == 2


def test_not_found():
    assert binary_search([1, 3, 5, 7], 4) == -1
    assert binary_search([1, 3, 5, 7], 8) == -1


def test_single_element():
    assert binary_search([42], 42) == 0
    assert binary_search([42], 7) == -1


def test_empty():
    assert binary_search([], 3) == -1


def test_two_elements_no_hang():
    assert binary_search([1, 2], 2) == 1
    assert binary_search([1, 2], 9) == -1
