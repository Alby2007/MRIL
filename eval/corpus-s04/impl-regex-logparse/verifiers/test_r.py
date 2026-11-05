from solution import parse_log_line


def test_basic():
    assert parse_log_line('[ERROR] disk full (code 42)') == {
        'level': 'ERROR', 'message': 'disk full', 'code': 42}


def test_code_is_int():
    assert parse_log_line('[WARN] low mem (code 7)')['code'] == 7


def test_bad_level():
    assert parse_log_line('[FATAL] x (code 1)') is None


def test_wrong_shape():
    assert parse_log_line('ERROR no brackets code 1') is None


def test_empty_line():
    assert parse_log_line('') is None


def test_all_levels():
    for lvl in ('DEBUG', 'INFO', 'WARN', 'ERROR'):
        assert parse_log_line(f'[{lvl}] m (code 0)')['level'] == lvl
