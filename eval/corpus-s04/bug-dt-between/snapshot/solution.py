def days_between(a, b):
    return (b - a).days   # BUG: signed; should be a non-negative count
