from solution import LRUCache


def test_basic_get_put():
    c = LRUCache(2)
    c.put(1, 'a')
    c.put(2, 'b')
    assert c.get(1) == 'a'
    assert c.get(2) == 'b'


def test_evicts_least_recently_used():
    c = LRUCache(2)
    c.put(1, 'a')
    c.put(2, 'b')
    c.get(1)          # 1 is now most-recently used
    c.put(3, 'c')     # evicts 2, not 1
    assert c.get(2) == -1
    assert c.get(1) == 'a'
    assert c.get(3) == 'c'


def test_put_existing_refreshes_recency():
    c = LRUCache(2)
    c.put(1, 'a')
    c.put(2, 'b')
    c.put(1, 'a2')    # refresh 1
    c.put(3, 'c')     # evicts 2
    assert c.get(2) == -1
    assert c.get(1) == 'a2'


def test_capacity_one():
    c = LRUCache(1)
    c.put(1, 'a')
    c.put(2, 'b')
    assert c.get(1) == -1
    assert c.get(2) == 'b'


def test_get_missing():
    c = LRUCache(2)
    assert c.get(99) == -1
