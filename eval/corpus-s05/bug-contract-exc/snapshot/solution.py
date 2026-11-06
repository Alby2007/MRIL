class OrderError(Exception):
    pass


def place_order(qty, stock):
    """qty must be positive int and <= stock, else OrderError."""
    if qty <= 0:
        raise ValueError("qty must be positive")      # BUG: wrong exception type
    if qty > stock:
        raise RuntimeError("insufficient stock")      # BUG: wrong exception type
    return stock - qty
