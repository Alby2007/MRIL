from solution import render_table


def test_basic():
    out = render_table([["a", "bb"], ["ccc", "d"]], [3, 2])
    assert out == "a   | bb\nccc | d "


def test_missing_cells():
    out = render_table([["x"], ["y", "z", "extra"]], [2, 2])
    assert out == "x  |   \ny  | z "   # extra cell beyond widths dropped


def test_wide_cells_not_truncated():
    out = render_table([["longer", "b"]], [2, 1])
    assert out == "longer | b"
