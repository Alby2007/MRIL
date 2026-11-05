"""RecoveryContext — the decision-time input contract for recovery policies.

A frozen, serializable snapshot of everything `recover()` was allowed to see:
task features, attempt history, failure evidence, budget position, and the
eligible candidate set. Never future verification results. Logged onto every
`recovery_decided` event so the eval harness and future learners can replay
recovery decisions independently — same context in, same action out (or, for
a stochastic policy, the same action distribution).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mril.core.models import ModelRegistry
from mril.core.task import RoutingConstraints
from mril.policy.state import TaskState


@dataclass(frozen=True)
class RecoveryContext:
    task_id: str
    language: str | None = None
    task_type: str | None = None
    scope: str | None = None
    risk: str | None = None
    attempt_count: int = 0
    escalation_count: int = 0
    last_attempt_id: str | None = None
    last_model_id: str | None = None
    last_verification_status: str | None = None
    last_failure_category: str | None = None
    last_api_error: str | None = None
    total_cost_usd: float = 0.0
    context_tokens: int = 0
    budget_usd: float | None = None
    budget_remaining_usd: float | None = None
    max_attempts: int = 0
    candidate_model_ids: tuple[str, ...] = ()

    @classmethod
    def from_state(
        cls,
        state: TaskState,
        constraints: RoutingConstraints,
        registry: ModelRegistry,
    ) -> "RecoveryContext":
        last = state.last_attempt
        remaining = (
            constraints.budget_usd - state.total_cost_usd
            if constraints.budget_usd is not None
            else None
        )
        candidates = registry.candidates(
            constraints.allowed_models, constraints.require_capabilities
        )
        return cls(
            task_id=state.task_id,
            language=state.language,
            task_type=state.task_type,
            scope=state.scope,
            risk=state.risk,
            attempt_count=len(state.attempts),
            escalation_count=state.escalation_count,
            last_attempt_id=last.attempt_id if last else None,
            last_model_id=last.model_id if last else None,
            last_verification_status=(
                last.verification_status.value if last and last.verification_status else None
            ),
            last_failure_category=last.failure_category if last else None,
            last_api_error=last.api_error if last else None,
            total_cost_usd=state.total_cost_usd,
            context_tokens=state.context_tokens,
            budget_usd=constraints.budget_usd,
            budget_remaining_usd=remaining,
            max_attempts=constraints.max_attempts,
            candidate_model_ids=tuple(m.model_id for m in candidates),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
