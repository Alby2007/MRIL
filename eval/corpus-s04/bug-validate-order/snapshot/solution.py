_ALLOWED = {'new', 'paid', 'shipped'}


def validate_order(quantity, price, status):
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError('bad quantity')
    if price <= 0:                      # BUG: rejects price == 0
        raise ValueError('bad price')
    # BUG: status never checked against _ALLOWED
    return True
