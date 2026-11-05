import importlib

import solution


def test_add_then_total():
    importlib.reload(solution)
    solution.add(3)
    solution.add(4)
    assert solution.total() == 7


def test_total_grows():
    importlib.reload(solution)
    solution.add(1)
    assert solution.total() == 1
    solution.add(2)
    assert solution.total() == 3


def test_fresh_module_zero():
    importlib.reload(solution)
    assert solution.total() == 0
