from solution import money


def test_basic():
    assert money(123456) == "$1,234.56"
    assert money(5) == "$0.05"
    assert money(50) == "$0.50"


def test_negative():
    assert money(-123) == "-$1.23"
    assert money(-1000000) == "-$10,000.00"


def test_zero_and_thousands():
    assert money(0) == "$0.00"
    assert money(100000) == "$1,000.00"
