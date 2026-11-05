"""Aggregate metrics over the ledger — the honest "is this saving money" view.

All figures are computed from recorded events only. Verified rates count only
explicitly verified outcomes; inconclusive tasks are reported separately and
never folded into the success rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mril.core.events import Event, RouteDecided, TaskFinalized, TaskOutcome
from mril.policy.state import rebuild_state


@dataclass
class TaskSummary:
    task_id: str
    outcome: str
    attempts: int
    escalations: int
    total_cost_usd: float
    models_used: list[str] = field(default_factory=list)
    degraded: bool = False


def summarize(events: list[Event]) -> list[TaskSummary]:
    by_task: dict[str, list[Event]] = {}
    for e in events:
        if e.task_id:
            by_task.setdefault(e.task_id, []).append(e)

    out = []
    for task_id, evs in by_task.items():
        state = rebuild_state(task_id, evs)
        fin = next((e for e in evs if isinstance(e, TaskFinalized)), None)
        out.append(
            TaskSummary(
                task_id=task_id,
                outcome=fin.task_outcome.value if fin else "open",
                attempts=len(state.attempts),
                escalations=state.escalation_count,
                total_cost_usd=state.total_cost_usd,
                models_used=sorted({a.model_id for a in state.attempts if a.model_id}),
                degraded=any(isinstance(e, RouteDecided) and e.degraded for e in evs),
            )
        )
    return sorted(out, key=lambda s: s.task_id)


def verified_rate(summaries: list[TaskSummary]) -> float | None:
    verified = [
        s
        for s in summaries
        if s.outcome in (TaskOutcome.VERIFIED_SUCCESS.value, TaskOutcome.VERIFIED_FAILURE.value)
    ]
    if not verified:
        return None
    return sum(s.outcome == TaskOutcome.VERIFIED_SUCCESS.value for s in verified) / len(verified)
