from datetime import date


def add_months(d, n):
    m = d.month + n          # BUG: no year rollover, invalid day unhandled
    return date(d.year, m, d.day)
