class SessionCounter:
    """Counts events per session. add(n) increments the CURRENT session;
    rollover() starts a new session; total() sums only completed sessions;
    current() reports the open session count."""

    def __init__(self):
        raise NotImplementedError
