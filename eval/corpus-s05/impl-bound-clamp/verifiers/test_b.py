from solution import clamp


def test_middle():
    assert clamp(5, 0, 10) == 5


def test_endpoints_inclusive():
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_outside_and_negatives():
    assert clamp(-3, 0, 10) == 0
    assert clamp(99, 0, 10) == 10
    assert clamp(-5, -10, -1) == -5
    assert clamp(-20, -10, -1) == -10
