from solution import to_wire, from_wire


def test_roundtrip_basic():
    assert from_wire(to_wire({"a": 1, "b": "x"})) == {"a": 1, "b": "x"}


def test_roundtrip_escapes():
    d = {"k=1": "v;2", "p%": "q"}
    assert from_wire(to_wire(d)) == d


def test_none_and_int():
    d = {"a": None, "n": 0}
    out = from_wire(to_wire(d))
    assert out == d


def test_empty():
    assert from_wire(to_wire({})) == {}
