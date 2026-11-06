"""Run results — derived from the ledger, never from runner bookkeeping."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mril.core.events import (
    ModelInvocationFinished,
    RecoveryDecided,
    TaskFinalized,
    TaskOutcome,
)
from mril.eval.arms import Arm
from mril.policy.state import rebuild_state


@dataclass(frozen=True)
class RunResult:
    run_task_id: str
    task_id: str
    arm: str
    seed: int
    outcome: str
    verified: bool
    attempts: int
    model_calls: int
    escalations: int
    total_cost_usd: float
    wall_ms: float
    invocation_latencies_ms: tuple[float, ...] = ()
    estimated_switch_cost_usd: float | None = None
    actual_switch_cost_usd: float | None = None
    switch_cost_basis: str | None = None
    models_used: tuple[str, ...] = ()
    cost_basis: str = "synthetic_token_price"  # local inference: not billed
    policy_fingerprint: str = ""

    @classmethod
    def from_ledger(
        cls, store, run_task_id, task_id, arm: Arm, seed, *, wall_ms, finalized: TaskFinalized
    ) -> "RunResult":
        events = store.events_for_task(run_task_id)
        state = rebuild_state(run_task_id, events)
        invs = [e for e in events if isinstance(e, ModelInvocationFinished)]
        est_switch = sum(
            e.estimated_switch_cost_usd or 0.0
            for e in events
            if isinstance(e, RecoveryDecided)
        ) or None
        return cls(
            run_task_id=run_task_id,
            task_id=task_id,
            arm=arm.name,
            seed=seed,
            outcome=finalized.task_outcome.value,
            verified=finalized.task_outcome == TaskOutcome.VERIFIED_SUCCESS,
            attempts=finalized.attempt_count,
            model_calls=len(invs),
            escalations=finalized.escalation_count,
            total_cost_usd=finalized.total_cost_usd or 0.0,
            wall_ms=wall_ms,
            invocation_latencies_ms=tuple(
                e.latency_ms for e in invs if e.latency_ms is not None
            ),
            estimated_switch_cost_usd=est_switch,
            actual_switch_cost_usd=finalized.actual_switch_cost_usd,
            switch_cost_basis=finalized.switch_cost_basis,
            models_used=tuple(sorted({a.model_id for a in state.attempts if a.model_id})),
            policy_fingerprint=arm.fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_results(path) -> list[RunResult]:
    import json

    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            d["invocation_latencies_ms"] = tuple(d["invocation_latencies_ms"])
            d["models_used"] = tuple(d["models_used"])
            out.append(RunResult(**d))
    return out
