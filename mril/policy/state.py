"""Task state reconstructed by replaying the event ledger."""

from __future__ import annotations

from dataclasses import dataclass, field

from mril.core.events import (
    Event,
    ModelInvocationFinished,
    RecoveryDecided,
    TaskFinalized,
    TaskOutcome,
    TaskStarted,
    VerificationCompleted,
    VerificationStatus,
)


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    model_id: str | None
    cost_usd: float
    input_tokens: int | None
    api_error: str | None = None
    verification_status: VerificationStatus | None = None
    verifier_type: str | None = None
    failure_category: str | None = None


@dataclass
class TaskState:
    task_id: str
    language: str | None = None
    task_type: str | None = None
    scope: str | None = None
    risk: str | None = None
    attempts: list[AttemptRecord] = field(default_factory=list)
    total_cost_usd: float = 0.0
    escalation_count: int = 0
    finalized: bool = False
    task_outcome: TaskOutcome | None = None

    @property
    def last_attempt(self) -> AttemptRecord | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def last_model_id(self) -> str | None:
        return self.last_attempt.model_id if self.last_attempt else None

    @property
    def context_tokens(self) -> int:
        """Approximate tokens a model switch would have to re-ingest.

        Uses the largest observed input size — the warm-context proxy a router
        must charge against any mid-session model change.
        """
        return max((a.input_tokens or 0 for a in self.attempts), default=0)


def rebuild_state(task_id: str, events: list[Event]) -> TaskState:
    state = TaskState(task_id=task_id)
    inv: dict[str, ModelInvocationFinished] = {}
    ver: dict[str, list[VerificationCompleted]] = {}
    order: list[str] = []

    for e in events:
        if isinstance(e, ModelInvocationFinished) and e.attempt_id:
            if e.attempt_id not in inv:
                order.append(e.attempt_id)
            inv[e.attempt_id] = e
        elif isinstance(e, VerificationCompleted) and e.attempt_id:
            ver.setdefault(e.attempt_id, []).append(e)
        elif isinstance(e, TaskStarted):
            state.language = e.language
            state.task_type = e.task_type
            state.scope = e.scope
            state.risk = e.risk
        elif isinstance(e, RecoveryDecided) and e.action == "escalate":
            state.escalation_count += 1
        elif isinstance(e, TaskFinalized):
            state.finalized = True
            state.task_outcome = e.task_outcome

    for aid in order:
        i = inv[aid]
        cost = i.cost_usd or 0.0
        v = ver.get(aid, [])
        last_v = v[-1] if v else None
        state.attempts.append(
            AttemptRecord(
                attempt_id=aid,
                model_id=i.model_id,
                cost_usd=cost,
                input_tokens=i.input_tokens,
                api_error=i.api_error,
                verification_status=last_v.status if last_v else None,
                verifier_type=last_v.verifier_type if last_v else None,
                failure_category=last_v.failure_category if last_v else None,
            )
        )
        state.total_cost_usd += cost
    return state
