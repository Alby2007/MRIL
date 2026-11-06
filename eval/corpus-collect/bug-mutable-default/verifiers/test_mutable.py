from solution import append_item

def test_first(): assert append_item(1) == [1]
def test_independent():
    append_item(1)
    assert append_item(2) == [2]
def test_explicit(): assert append_item(3, [9]) == [9, 3]
