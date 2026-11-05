"""The MRIL event contract.

This is the most important interface in the project: the versioned, append-only
record of routing decisions and verified outcomes. Everything downstream —
learning, evaluation, analytics — is derived by replaying these events.

Design rules:
- Every event carries stable task/attempt/decision identifiers plus a schema
  version, so the ledger can be replayed and migrated.
- Events are immutable once written. Corrections are new events.
- Step-level fields (step_index, call_site) exist from day one so per-call
  routing can be adopted without re-instrumenting adapters.
- Terminal outcomes distinguish verified results from inconclusive ones; a
  missing verification must never be treated as a success.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

SCHEMA_VERSION = "mril.event.v1"

_EVENT_TYPES: dict[str, type["Event"]] = {}


def new_event_id() -> str:
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class TaskOutcome(str, Enum):
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"
    INCONCLUSIVE = "inconclusive"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base envelope for every ledger event."""

    event_type: ClassVar[str]

    event_id: str = field(default_factory=new_event_id)
    occurred_at: str = field(default_factory=utcnow_iso)
    task_id: str | None = None
    attempt_id: str | None = None
    decision_id: str | None = None
    trace_id: str | None = None
    step_index: int | None = None
    call_site: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "event_type", None):
            _EVENT_TYPES[cls.event_type] = cls

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type
        return d


def event_from_dict(d: dict[str, Any]) -> Event:
    et = d.get("event_type")
    cls = _EVENT_TYPES.get(et)
    if cls is None:
        raise ValueError(f"unknown event_type: {et!r}")
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in d.items() if k in known}
    for key in ("task_outcome",):
        if isinstance(kwargs.get(key), str):
            kwargs[key] = TaskOutcome(kwargs[key])
    if isinstance(kwargs.get("status"), str) and cls is VerificationCompleted:
        kwargs["status"] = VerificationStatus(kwargs["status"])
    return cls(**kwargs)


@dataclass(frozen=True, kw_only=True)
class TaskStarted(Event):
    """Task characteristics and agent environment, recorded once per task."""

    event_type: ClassVar[str] = "task_started"

    language: str | None = None
    task_type: str | None = None
    scope: str | None = None
    risk: str | None = None
    harness: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RouteDecided(Event):
    """A model-selection decision, with everything needed to replay it."""

    event_type: ClassVar[str] = "route_decided"

    model_id: str | None = None
    policy_name: str = ""
    policy_version: str = ""
    policy_hash: str = ""
    registry_version: str = ""
    registry_hash: str = ""
    selection_probability: float = 1.0
    reason: str = ""
    estimated_cost_usd: float | None = None
    candidates: list[str] = field(default_factory=list)
    price_snapshot: dict[str, Any] = field(default_factory=dict)
    decision_seed: int = 0
    degraded: bool = False


@dataclass(frozen=True, kw_only=True)
class ModelInvocationFinished(Event):
    """Provider-reported usage for one model call."""

    event_type: ClassVar[str] = "model_invocation_finished"

    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    api_error: str | None = None


@dataclass(frozen=True, kw_only=True)
class VerificationCompleted(Event):
    """A verifier's judgement on an attempt. Never inferred, always explicit."""

    event_type: ClassVar[str] = "verification_completed"

    status: VerificationStatus = VerificationStatus.INCONCLUSIVE
    verifier_type: str = "unknown"  # test | build | typecheck | lint | llm_judge | human
    confidence: float | None = None
    failure_category: str | None = None


@dataclass(frozen=True, kw_only=True)
class RecoveryDecided(Event):
    """The policy's recommendation for how to proceed after an attempt."""

    event_type: ClassVar[str] = "recovery_decided"

    action: str = "continue"  # continue | retry | escalate | stop
    model_id: str | None = None
    reason: str = ""
    estimated_cost_usd: float | None = None
    budget_remaining_usd: float | None = None


@dataclass(frozen=True, kw_only=True)
class TaskFinalized(Event):
    """Terminal outcome for a task."""

    event_type: ClassVar[str] = "task_finalized"

    task_outcome: TaskOutcome = TaskOutcome.INCONCLUSIVE
    total_cost_usd: float | None = None
    elapsed_ms: float | None = None
    attempt_count: int = 0
    escalation_count: int = 0
