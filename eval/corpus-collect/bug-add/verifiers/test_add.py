from solution import add

def test_basic(): assert add(2, 3) == 5
def test_negative(): assert add(-1, 1) == 0
def test_zero(): assert add(0, 0) == 0
