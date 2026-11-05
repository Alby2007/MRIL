from datetime import date
from solution import days_between


def test_forward():
    assert days_between(date(2024, 1, 1), date(2024, 1, 10)) == 9


def test_reversed():
    assert days_between(date(2024, 1, 10), date(2024, 1, 1)) == 9


def test_same_day():
    assert days_between(date(2024, 6, 15), date(2024, 6, 15)) == 0


def test_across_year():
    assert days_between(date(2023, 12, 30), date(2024, 1, 2)) == 3
