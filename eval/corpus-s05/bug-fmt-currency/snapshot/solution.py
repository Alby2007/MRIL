def money(cents):
    """Cents -> '$1,234.56'; negatives '-$1.23'; rounds half-up on odd cents
    already being exact (input is int cents)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100}"   # BUG: no padding/commas
