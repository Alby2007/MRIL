def ranges_overlap(a, b):
    """True if inclusive ranges [a0,a1] and [b0,b1] overlap."""
    a0, a1 = a
    b0, b1 = b
    return a0 < b1 and b0 < a1          # BUG: touching endpoints excluded
