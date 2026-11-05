class MRILError(Exception):
    pass


class NoEligibleModelError(MRILError):
    """Constraints exclude every model and no fallback is configured."""
