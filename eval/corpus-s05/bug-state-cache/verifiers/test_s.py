from solution import TTLCache


def test_expired_returns_none():
    c = TTLCache(max_size=2, ttl=10)
    c.set("a", 1, now=0)
    assert c.get("a", now=5) == 1
    assert c.get("a", now=11) is None


def test_expired_frees_slot():
    c = TTLCache(max_size=2, ttl=10)
    c.set("a", 1, now=0)
    c.set("b", 2, now=0)
    # a and b expire; inserting c must NOT evict anything still fresh
    c.set("c", 3, now=20)
    assert c.get("c", now=21) == 3


def test_evicts_oldest_fresh():
    c = TTLCache(max_size=2, ttl=100)
    c.set("a", 1, now=0)
    c.set("b", 2, now=1)
    c.set("c", 3, now=2)
    assert c.get("a", now=3) is None
    assert c.get("b", now=3) == 2
    assert c.get("c", now=3) == 3
