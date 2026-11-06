class Item:
    def __init__(self, sku, qty):
        self.sku = sku
        self.qty = qty

    def __eq__(self, other):
        return (self.sku, self.qty) == (other.sku, other.qty)


class Order:
    def __init__(self, items, note=None):
        self.items = items
        self.note = note

    def __eq__(self, other):
        return self.items == other.items and self.note == other.note


def order_to_dict(o):
    return {
        'items': o.items,            # BUG: objects, not dicts
        'note': o.note,              # BUG: None written instead of omitted
    }


def dict_to_order(d):
    items = [Item(i['sku'], i['qty']) for i in d['items']]
    return Order(items, note=d.get('note'))
