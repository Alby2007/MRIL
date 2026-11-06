import pytest
from solution import err, is_ok, map_result, ok, unwrap


def test_roundtrip():
    assert is_ok(ok(3)) is True
    assert is_ok(err("bad")) is False
    assert unwrap(ok(3)) == 3


def test_unwrap_error_raises():
    with pytest.raises(RuntimeError, match="bad"):
        unwrap(err("bad"))


def test_map():
    assert unwrap(map_result(ok(2), lambda x: x * 10)) == 20
    r = map_result(err("e"), lambda x: x * 10)
    assert is_ok(r) is False
    with pytest.raises(RuntimeError):
        unwrap(r)


def test_falsy_values_survive():
    assert unwrap(ok(0)) == 0
    assert is_ok(ok(None)) is True
