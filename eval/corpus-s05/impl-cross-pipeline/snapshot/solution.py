def normalize(rec):
    """Lowercase keys, strip string values. Leave non-str values as-is."""
    raise NotImplementedError


def validate(rec):
    """Return list of error strings; [] when valid. 'name' and 'qty' required,
    qty must be a positive int."""
    raise NotImplementedError


def serialize(rec):
    """'name=x;qty=N' for a VALID normalized record."""
    raise NotImplementedError


def process(rec):
    """normalize -> validate -> serialize. Return serialized string on success,
    'ERR:'-prefixed first error on failure."""
    raise NotImplementedError
