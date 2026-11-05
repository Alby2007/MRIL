import pytest
from solution import Entry, deserialize, serialize


def test_version_key():
    d = serialize(Entry('a1', 2))
    assert d['v'] == 2


def test_unset_note_omitted():
    assert 'note' not in serialize(Entry('a1', 2))


def test_qty_coerced_from_string():
    d = serialize(Entry('a1', '3'))
    assert d['qty'] == 3


def test_roundtrip():
    e = Entry('a1', 2, note='x')
    back = deserialize(serialize(e))
    assert (back.sku, back.qty, back.note) == ('a1', 2, 'x')


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        deserialize({'v': 2, 'sku': 'a1', 'qty': 1, 'surprise': 9})
