class WordCounter:
    def __init__(self):
        self._order = []
        self._counts = {}

    def add(self, word):
        if word not in self._counts:
            self._order.append(word)
        self._counts[word] = self._counts.get(word, 0) + 1

    def top(self):
        # BUG: returns first-seen word, not the most frequent
        return self._order[0] if self._order else None
