import pytest
from solution import OrderError, place_order


def test_ok():
    assert place_order(2, 5) == 3


def test_bad_qty_raises_ordererror():
    with pytest.raises(OrderError):
        place_order(0, 5)
    with pytest.raises(OrderError):
        place_order(-1, 5)


def test_stock_raises_ordererror():
    with pytest.raises(OrderError):
        place_order(10, 5)


def test_non_int_rejected():
    with pytest.raises(OrderError):
        place_order(2.5, 5)
