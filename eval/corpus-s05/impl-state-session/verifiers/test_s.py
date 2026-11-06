from solution import SessionCounter


def test_flow():
    s = SessionCounter()
    s.add(2); s.add(3)
    assert s.current() == 5
    assert s.total() == 0          # open session not counted yet
    s.rollover()
    assert s.current() == 0
    assert s.total() == 5


def test_multiple():
    s = SessionCounter()
    s.add(1); s.rollover()
    s.add(2); s.add(2); s.rollover()
    s.add(7)
    assert s.total() == 5
    assert s.current() == 7
