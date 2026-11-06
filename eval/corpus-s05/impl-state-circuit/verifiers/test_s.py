from solution import CircuitBreaker


def test_opens_after_threshold():
    c = CircuitBreaker(threshold=2, reset_after=10)
    assert c.call(False, 0) == "fail"
    assert c.call(False, 1) == "fail"
    assert c.call(True, 2) == "open"          # rejected, not counted


def test_probe_and_recover():
    c = CircuitBreaker(threshold=1, reset_after=10)
    c.call(False, 0)                          # opens
    assert c.call(True, 5) == "open"          # still cooling
    assert c.call(True, 11) == "ok"           # probe succeeds -> closed
    assert c.call(True, 12) == "ok"


def test_probe_failure_reopens():
    c = CircuitBreaker(threshold=1, reset_after=10)
    c.call(False, 0)
    assert c.call(False, 11) == "fail"        # probe fails -> open again
    assert c.call(True, 15) == "open"
    assert c.call(True, 22) == "ok"


def test_success_resets_streak():
    c = CircuitBreaker(threshold=2, reset_after=10)
    c.call(False, 0); c.call(True, 1)
    c.call(False, 2); c.call(False, 3)
    assert c.call(True, 4) == "open"
