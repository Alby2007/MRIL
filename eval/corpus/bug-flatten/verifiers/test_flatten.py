from solution import flatten

def test_nested(): assert flatten({'a': {'b': 1}}) == {'a.b': 1}
def test_deep(): assert flatten({'a': {'b': {'c': 2}}, 'x': 1}) == {'a.b.c': 2, 'x': 1}
def test_flat(): assert flatten({'k': 5}) == {'k': 5}
def test_lists_stay(): assert flatten({'a': [1, 2]}) == {'a': [1, 2]}
