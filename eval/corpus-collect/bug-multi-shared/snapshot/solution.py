_items = []


def add(item):
    _items.append(item)


def total():
    _items = []          # BUG: shadows the module list, always sums nothing
    return sum(_items)
