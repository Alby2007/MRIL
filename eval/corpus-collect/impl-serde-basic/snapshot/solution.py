class Product:
    def __init__(self, name, price, tags):
        self.name = name
        self.price = price
        self.tags = tags

    def __eq__(self, other):
        return (self.name, self.price, self.tags) == (other.name, other.price, other.tags)


def product_to_dict(p):
    pass


def dict_to_product(d):
    pass
