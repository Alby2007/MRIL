from solution import parse_ini


def test_sections():
    d = parse_ini('[db]\nhost = localhost\nport = 5432\n')
    assert d['db']['host'] == 'localhost' and d['db']['port'] == 5432


def test_types():
    d = parse_ini('[a]\nx = 3.5\nflag = true\nname = bob\n')
    assert d['a']['x'] == 3.5 and d['a']['flag'] is True and d['a']['name'] == 'bob'


def test_comments():
    d = parse_ini('; comment\n[a]\n# note\nk = 1\n')
    assert d == {'a': {'k': 1}}


def test_top_level():
    d = parse_ini('k = 9\n[s]\nx = 1\n')
    assert d['k'] == 9 and d['s']['x'] == 1
