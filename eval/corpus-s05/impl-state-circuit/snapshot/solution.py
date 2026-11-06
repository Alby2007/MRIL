class CircuitBreaker:
    """closed -> open after `threshold` CONSECUTIVE failures.
    open: calls rejected (call() returns 'OPEN').
    after `reset_after` ticks the next call is a probe -> half-open:
    success closes the circuit; failure reopens it (failure count resets).
    call(ok, t) records success/failure at time t and returns
    'ok' | 'fail' | 'open'."""

    def __init__(self, threshold=3, reset_after=30):
        raise NotImplementedError
