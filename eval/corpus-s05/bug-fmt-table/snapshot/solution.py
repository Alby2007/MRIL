def render_table(rows, widths):
    """rows: list of str lists; widths: column widths. Cells left-aligned,
    space-padded to width, columns joined with ' | '. Missing cells count
    as empty."""
    lines = []
    for row in rows:
        cells = [row[i] if i < len(row) else "" for i in range(len(widths))]
        # BUG: truncates over-wide content instead of letting it overflow
        lines.append(" | ".join(c[:w].ljust(w) for c, w in zip(cells, widths)))
    return "\n".join(lines)
