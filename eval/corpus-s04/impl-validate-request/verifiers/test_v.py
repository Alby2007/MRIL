from solution import RequestValidator

SPEC = {'name': ('required', str, None, None),
        'qty': ('required', int, 1, 99),
        'tag': ('optional', str, None, None)}


def test_valid_payload():
    v = RequestValidator(SPEC)
    assert v.validate({'name': 'a', 'qty': 3}) is True
    assert v.errors == []


def test_collects_every_problem():
    v = RequestValidator(SPEC)
    assert v.validate({'qty': 200, 'oops': 1}) is False
    kinds = {e.split(':')[0] for e in v.errors}
    assert 'missing' in kinds and 'range' in kinds and 'unknown' in kinds


def test_wrong_type_reported():
    v = RequestValidator(SPEC)
    assert v.validate({'name': 'a', 'qty': '3'}) is False
    assert any('type' in e for e in v.errors)


def test_range_ok():
    v = RequestValidator(SPEC)
    assert v.validate({'name': 'a', 'qty': 99}) is True


def test_optional_absent_ok():
    v = RequestValidator(SPEC)
    assert v.validate({'name': 'a', 'qty': 1}) is True
