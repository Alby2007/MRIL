from solution import FormValidator


def test_all_present():
    v = FormValidator({'a': 'x', 'b': 'y'})
    v.require('a')
    v.require('b')
    assert v.is_valid() is True
    assert v.errors == []


def test_absent_field_fails():
    v = FormValidator({'a': 'x'})
    v.require('a')
    v.require('b')
    assert v.is_valid() is False
    assert v.errors == ['b']


def test_blank_counts_as_failure():
    v = FormValidator({'a': '   '})
    v.require('a')
    assert v.is_valid() is False
    assert v.errors == ['a']


def test_nothing_required():
    v = FormValidator({})
    assert v.is_valid() is True
