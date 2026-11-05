import pytest
from solution import business_days


def test_simple_week():
    # Mon 2024-01-01 .. Fri 2024-01-05, end exclusive
    assert business_days('2024-01-01', '2024-01-06', []) == 5


def test_weekend_skipped():
    # Fri .. Mon: Fri counts, Sat/Sun don't
    assert business_days('2024-01-05', '2024-01-08', []) == 1


def test_holiday_skipped():
    assert business_days('2024-01-01', '2024-01-06', ['2024-01-03']) == 4


def test_reversed_is_negative():
    assert business_days('2024-01-06', '2024-01-01', []) == -5


def test_invalid_date_raises():
    with pytest.raises(ValueError):
        business_days('not-a-date', '2024-01-06', [])


def test_same_day_zero():
    assert business_days('2024-01-03', '2024-01-03', []) == 0
