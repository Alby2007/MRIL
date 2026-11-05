"""Task context and routing constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskContext:
    """Features describing the unit of work being routed.

    task_type/scope/risk may be declared by the harness or inferred by a
    profiler; missing values are allowed and the policy must cope with them.
    """

    task_id: str
    language: str | None = None
    task_type: str | None = None  # bug_fix | feature | refactor | docs | ...
    scope: str | None = None  # single_file | single_module | multi_module | repo_wide
    risk: str | None = None  # low | medium | high
    harness: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingConstraints:
    """Hard limits the policy must respect. Never overridden by a learned policy."""

    allowed_models: tuple[str, ...] | None = None  # None = all non-restricted
    fallback_model_id: str | None = None
    budget_usd: float | None = None
    max_attempts: int = 4
    require_capabilities: frozenset[str] = frozenset()
