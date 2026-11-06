import pytest
from solution import run


def test_basic():
    assert run("1 + 2") == 3
    assert run("10 - 4 + 1") == 7


def test_negative_operands():
    assert run("1 + -3") == -2
    assert run("-5 + 5") == 0


def test_bad_token_raises_valueerror():
    with pytest.raises(ValueError, match="bad token"):
        run("1 + x")
