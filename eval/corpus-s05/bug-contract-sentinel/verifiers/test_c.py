import pytest
from solution import lookup


def test_hit():
    assert lookup({"a": {"b": 1}}, "a.b") == 1
    assert lookup({"a": 5}, "a") == 5


def test_default():
    assert lookup({}, "x", default=0) == 0
    assert lookup({"a": {}}, "a.b", default=None) is None


def test_missing_raises():
    with pytest.raises(KeyError):
        lookup({}, "nope")
    with pytest.raises(KeyError):
        lookup({"a": {}}, "a.b")
