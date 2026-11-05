"""In-memory event store — for tests and ephemeral runs."""

from __future__ import annotations

from mril.core.events import Event


class MemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._ids: set[str] = set()
        self._dedupe: set[str] = set()

    def append(self, event: Event) -> bool:
        if event.event_id in self._ids:
            return False
        if event.dedupe_key is not None and event.dedupe_key in self._dedupe:
            return False
        self._ids.add(event.event_id)
        if event.dedupe_key is not None:
            self._dedupe.add(event.dedupe_key)
        self._events.append(event)
        return True

    def get(self, event_id: str) -> Event | None:
        for e in self._events:
            if e.event_id == event_id:
                return e
        return None

    def events_for_task(self, task_id: str) -> list[Event]:
        return [e for e in self._events if e.task_id == task_id]

    def events_for_decision(self, decision_id: str) -> list[Event]:
        return [e for e in self._events if e.decision_id == decision_id]

    def all_events(self) -> list[Event]:
        return list(self._events)

    def close(self) -> None:
        pass
