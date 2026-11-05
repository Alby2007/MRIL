from solution import count_errors


def test_first_line():
    assert count_errors('ERROR first\nINFO ok') == 1


def test_later_lines():
    assert count_errors('INFO ok\nERROR mid\nWARN w\nERROR last') == 2


def test_none():
    assert count_errors('INFO a\nWARN b') == 0


def test_blank_lines_between():
    assert count_errors('ERROR a\n\n\nERROR b') == 2


def test_midline_not_counted():
    assert count_errors('this says ERROR mid-line') == 0
