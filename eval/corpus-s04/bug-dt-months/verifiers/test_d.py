from datetime import date
from solution import add_months


def test_simple():
    assert add_months(date(2024, 3, 15), 1) == date(2024, 4, 15)


def test_year_rollover():
    assert add_months(date(2024, 12, 10), 1) == date(2025, 1, 10)


def test_clamp_to_shorter_month():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_clamp_non_leap():
    assert add_months(date(2023, 1, 31), 1) == date(2023, 2, 28)


def test_negative():
    assert add_months(date(2024, 3, 31), -1) == date(2024, 2, 29)
