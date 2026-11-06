def diff_lines(old, new):
    """Unified-style line diff, simplest form:
    lines only in old -> '-line' (in order)
    lines only in new -> '+line' (in order, after all removals)
    lines identical at same index are skipped.
    Compare by full-line equality; a changed line = '-' then '+'."""
    raise NotImplementedError
