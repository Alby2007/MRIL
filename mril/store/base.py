"""Event store interface — an append-only ledger of MRIL events."""

from __future__ import annotations

from typing import Protocol

from mril.core.events import Event


class EventStore(Protocol):
    def append(self, event: Event) -> bool:
        """Append an event. Returns False if the event_id already exists
        (idempotent retry) or if the event's dedupe_key was already written
        (same logical occurrence retried with a fresh event_id)."""
        ...

    def get(self, event_id: str) -> Event | None: ...

    def events_for_task(self, task_id: str) -> list[Event]: ...

    def events_for_decision(self, decision_id: str) -> list[Event]: ...

    def all_events(self) -> list[Event]: ...

    def close(self) -> None: ...
