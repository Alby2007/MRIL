from solution import TokenBucket


def test_consumes_then_denies():
    b = TokenBucket(capacity=10, refill_per_sec=1.0)
    assert b.allow(4, now=0.0) is True
    assert b.allow(7, now=0.0) is False
    assert b.allow(6, now=0.0) is True


def test_refills_over_time():
    b = TokenBucket(capacity=10, refill_per_sec=2.0)
    assert b.allow(10, now=0.0) is True
    assert b.allow(1, now=0.0) is False
    assert b.allow(4, now=2.0) is True   # 4 tokens refilled by t=2


def test_refill_capped_at_capacity():
    b = TokenBucket(capacity=5, refill_per_sec=10.0)
    assert b.allow(5, now=0.0) is True
    assert b.allow(6, now=100.0) is False  # capped at 5, never exceeds
    assert b.allow(5, now=100.0) is True


def test_partial_token_accumulation():
    b = TokenBucket(capacity=10, refill_per_sec=1.0)
    b.allow(1, now=0.0)
    # at t=0.5 only ~0.5 token refilled -> 9.5 total; can't spend 10
    assert b.allow(10, now=0.5) is False
    assert b.allow(10, now=1.0) is True
