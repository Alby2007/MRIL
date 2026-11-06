import pytest
from solution import check_user


def test_valid():
    assert check_user({'name': 'ada', 'age': 36}) is True


def test_negative_age_raises():
    with pytest.raises(ValueError):
        check_user({'name': 'ada', 'age': -1})


def test_blank_name_raises():
    with pytest.raises(ValueError):
        check_user({'name': '   ', 'age': 5})


def test_zero_age_ok():
    assert check_user({'name': 'x', 'age': 0}) is True
