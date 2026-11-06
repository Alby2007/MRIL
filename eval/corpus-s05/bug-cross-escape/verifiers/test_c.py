from solution import encode, decode


def test_roundtrip_plain():
    assert decode(encode("a,b,c")) == "a,b,c"


def test_roundtrip_percent():
    assert decode(encode("100%")) == "100%"
    assert decode(encode("%2C")) == "%2C"   # literal percent sequence survives


def test_roundtrip_mixed():
    assert decode(encode("a%,b%2C")) == "a%,b%2C"
