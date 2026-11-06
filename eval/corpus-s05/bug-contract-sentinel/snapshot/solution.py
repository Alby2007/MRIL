MISSING = object()


def lookup(d, path, default=MISSING):
    """lookup({'a': {'b': 1}}, 'a.b') -> 1. Missing path -> default if given,
    else KeyError."""
    cur = d
    for part in path.split("."):
        if part not in cur:
            return default            # BUG: returns the sentinel object and
        cur = cur[part]               # never raises even without default
    return cur
