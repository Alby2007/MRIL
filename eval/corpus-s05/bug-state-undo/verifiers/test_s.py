from solution import UndoStack


def test_simple():
    u = UndoStack()
    u.do("a"); u.do("b"); u.end_group()
    assert u.undo() == ["b", "a"]


def test_open_group_undone_first():
    u = UndoStack()
    u.do("a"); u.end_group()
    u.do("c")
    assert u.undo() == ["c"]
    assert u.undo() == ["a"]


def test_group_order():
    u = UndoStack()
    u.do("a"); u.end_group()
    u.do("b"); u.do("c"); u.end_group()
    assert u.undo() == ["c", "b"]
    assert u.undo() == ["a"]
    assert u.undo() == []
