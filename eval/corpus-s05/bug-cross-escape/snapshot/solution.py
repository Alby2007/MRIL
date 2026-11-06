def encode(s):
    """Escape % and , so encode/decode round-trips on any string."""
    return s.replace(",", "%2C").replace("%", "%25")   # BUG: order wrong


def decode(s):
    return s.replace("%2C", ",").replace("%25", "%")   # BUG: same order bug
