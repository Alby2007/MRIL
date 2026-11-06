import time


class TTLCache:
    """get() returns None for missing or EXPIRED keys; expired entries must
    not count toward max_size."""

    def __init__(self, max_size=2, ttl=60):
        self.max_size = max_size
        self.ttl = ttl
        self._d = {}

    def set(self, k, v, now=None):
        now = time.time() if now is None else now
        if len(self._d) >= self.max_size:
            oldest = max(self._d, key=lambda k: self._d[k][1])   # BUG: evicts
            del self._d[oldest]                                  # NEWEST entry
        self._d[k] = (v, now)

    def get(self, k, now=None):
        now = time.time() if now is None else now
        if k not in self._d:
            return None
        v, t = self._d[k]
        if now - t > self.ttl:
            return None                                          # BUG: not removed
        return v
