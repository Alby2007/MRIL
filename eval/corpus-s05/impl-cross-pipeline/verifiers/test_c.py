from solution import process


def test_happy():
    assert process({"NAME": " widget ", "QTY": 3}) == "name=widget;qty=3"


def test_qty_string_rejected():
    assert process({"name": "x", "qty": "3"}).startswith("ERR:")


def test_missing_fields():
    assert process({"qty": 2}).startswith("ERR:")
    assert process({}).startswith("ERR:")


def test_bad_qty():
    assert process({"name": "x", "qty": 0}).startswith("ERR:")
    assert process({"name": "x", "qty": -1}).startswith("ERR:")
