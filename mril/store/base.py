"""Event store interface — an append-only ledger of MRIL events."""

from __future__ import annotations

from typing import Protocol

from mril.core.events import Event


class EventStore(Protocol):
    def append(self, event: Event) -> bool:
        """Append an event. Returns False if the event_id already exists
        (idempotent retry), True on first write."""
        ...

    def get(self, event_id: str) -> Event | None: ...

    def events_for_task(self, task_id: str) -> list[Event]: ...

    def events_for_decision(self, decision_id: str) -> list[Event]: ...

    def all_events(self) -> list[Event]: ...

    def close(self) -> None: ...
