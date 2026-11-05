import pytest
from solution import validate_order


def test_valid():
    assert validate_order(1, 9.5, 'new') is True


def test_zero_price_ok():
    assert validate_order(1, 0, 'paid') is True


def test_bad_status_raises():
    with pytest.raises(ValueError):
        validate_order(1, 5.0, 'delivered')


def test_bad_quantity_raises():
    with pytest.raises(ValueError):
        validate_order(0, 5.0, 'new')


def test_float_quantity_raises():
    with pytest.raises(ValueError):
        validate_order(1.5, 5.0, 'new')
