def make_counters(n):
    """Return a list of n functions; calling the i-th returns i."""
    return [lambda: i for i in range(n)]
