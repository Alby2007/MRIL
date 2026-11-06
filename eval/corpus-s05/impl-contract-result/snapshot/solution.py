def ok(v):
    """Wrap a success value."""
    raise NotImplementedError


def err(msg):
    """Wrap an error message."""
    raise NotImplementedError


def is_ok(r):
    raise NotImplementedError


def unwrap(r):
    """Return the success value; if r is an error, raise RuntimeError(msg)."""
    raise NotImplementedError


def map_result(r, fn):
    """ok -> ok(fn(v)); error passes through unchanged."""
    raise NotImplementedError
