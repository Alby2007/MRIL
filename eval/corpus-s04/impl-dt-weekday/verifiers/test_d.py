from datetime import date
from solution import weekday_name


def test_known_dates():
    assert weekday_name(date(2024, 1, 1)) == 'Monday'    # 2024-01-01 was Monday
    assert weekday_name(date(2024, 1, 7)) == 'Sunday'
    assert weekday_name(date(2000, 1, 1)) == 'Saturday'


def test_leap_year_date():
    assert weekday_name(date(2024, 2, 29)) == 'Thursday'
