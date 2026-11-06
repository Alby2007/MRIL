"""In-memory event store — for tests and ephemeral runs."""

from __future__ import annotations

from mril.core.events import Event


class MemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_id: dict[str, Event] = {}
        self._dedupe: set[str] = set()

    def append(self, event: Event) -> bool:
        if event.event_id in self._by_id:
            return False
        if event.dedupe_key is not None and event.dedupe_key in self._dedupe:
            return False
        self._by_id[event.event_id] = event
        if event.dedupe_key is not None:
            self._dedupe.add(event.dedupe_key)
        self._events.append(event)
        return True

    def get(self, event_id: str) -> Event | None:
        return self._by_id.get(event_id)

    def events_for_task(self, task_id: str) -> list[Event]:
        return [e for e in self._events if e.task_id == task_id]

    def events_for_decision(self, decision_id: str) -> list[Event]:
        return [e for e in self._events if e.decision_id == decision_id]

    def all_events(self) -> list[Event]:
        return list(self._events)

    def close(self) -> None:
        pass
