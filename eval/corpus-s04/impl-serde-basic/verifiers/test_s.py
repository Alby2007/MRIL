from solution import Product, dict_to_product, product_to_dict


def test_to_dict():
    d = product_to_dict(Product('mug', 9.5, ['ceramic', 'blue']))
    assert d == {'name': 'mug', 'price': 9.5, 'tags': ['ceramic', 'blue']}


def test_roundtrip():
    p = Product('mug', 9.5, ['ceramic'])
    assert dict_to_product(product_to_dict(p)) == p


def test_from_dict():
    p = dict_to_product({'name': 'x', 'price': 1.0, 'tags': []})
    assert (p.name, p.price, p.tags) == ('x', 1.0, [])
