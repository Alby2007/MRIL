from solution import Item, Order, dict_to_order, order_to_dict


def test_items_are_dicts():
    d = order_to_dict(Order([Item('a1', 2)]))
    assert d['items'] == [{'sku': 'a1', 'qty': 2}]


def test_unset_note_omitted():
    d = order_to_dict(Order([Item('a1', 1)]))
    assert 'note' not in d


def test_note_kept_when_set():
    d = order_to_dict(Order([Item('a1', 1)], note='rush'))
    assert d['note'] == 'rush'


def test_roundtrip():
    o = Order([Item('a1', 2), Item('b2', 1)], note='gift')
    assert dict_to_order(order_to_dict(o)) == o
