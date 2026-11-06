from solution import diff_lines


def test_change():
    assert diff_lines(["a", "b"], ["a", "c"]) == "-b\n+c"


def test_add_remove():
    assert diff_lines(["a"], ["a", "b"]) == "+b"
    assert diff_lines(["a", "b"], ["a"]) == "-b"


def test_no_change_and_empty():
    assert diff_lines(["x"], ["x"]) == ""
    assert diff_lines([], ["n"]) == "+n"
    assert diff_lines(["o"], []) == "-o"


def test_multi():
    assert diff_lines(["a", "b", "c"], ["a", "x", "y"]) == "-b\n-c\n+x\n+y"
