import importlib

import pytest
import solution


def test_push_pop():
    importlib.reload(solution)
    solution.push(3)
    assert solution.pop() == 3


def test_add_op():
    importlib.reload(solution)
    solution.push(2)
    solution.push(5)
    solution.apply('add')
    assert solution.pop() == 7


def test_sub_and_neg():
    importlib.reload(solution)
    solution.push(10)
    solution.push(4)
    solution.apply('sub')
    solution.apply('neg')
    assert solution.pop() == -6


def test_pop_nothing_raises():
    importlib.reload(solution)
    with pytest.raises(IndexError):
        solution.pop()


def test_apply_too_few_raises():
    importlib.reload(solution)
    solution.push(1)
    with pytest.raises(IndexError):
        solution.apply('add')
