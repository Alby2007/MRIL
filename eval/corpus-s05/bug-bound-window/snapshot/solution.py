def sliding_max(xs, k):
    """Max of each contiguous window of size k. k >= 1."""
    out = []
    for i in range(len(xs) - k):          # BUG: misses final window
        out.append(max(xs[i:i + k]))
    return out
