"""Decision types returned by the SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class RoutingDecision:
    """The model choice for one routing call.

    Contains everything needed to explain and replay the decision: policy
    identity and hash, registry identity and hash, the decision seed, the
    selection probability (for off-policy evaluation), and the price snapshot
    used for cost accounting.
    """

    decision_id: str
    task_id: str
    model_id: str
    policy_name: str
    policy_version: str
    policy_hash: str
    registry_version: str
    registry_hash: str
    selection_probability: float
    reason: str
    decision_seed: int
    estimated_cost_usd: float | None = None
    candidates: tuple[str, ...] = ()
    price_snapshot: dict[str, Any] = field(default_factory=dict)
    step_index: int | None = None
    call_site: str | None = None
    degraded: bool = False  # True when produced via the fallback path


class RecoveryType(str, Enum):
    CONTINUE = "continue"
    RETRY = "retry"
    ESCALATE = "escalate"
    STOP = "stop"


@dataclass(frozen=True)
class RecoveryAction:
    type: RecoveryType
    model_id: str | None = None
    reason: str = ""
    estimated_cost_usd: float | None = None
    budget_remaining_usd: float | None = None
