class UndoStack:
    """Actions are grouped: end_group() seals the current group; undo()
    reverses the LAST sealed group (or the open group)."""

    def __init__(self):
        self._groups = []
        self._open = []

    def do(self, action):
        self._open.append(action)

    def end_group(self):
        self._groups.append(self._open)
        self._open = []

    def undo(self):
        # BUG: prefers sealed groups over the still-open one and returns
        # members in insertion order instead of reverse-insertion order.
        if self._groups:
            return self._groups.pop()
        g, self._open = self._open, []
        return g
