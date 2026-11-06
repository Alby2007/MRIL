def to_wire(d):
    """Serialize a flat dict {str: int|str|None} to a single-line string.
    Format: 'k=v;k=v' with = and ; percent-escaped in values (and keys)."""
    raise NotImplementedError


def from_wire(s):
    """Inverse of to_wire."""
    raise NotImplementedError
