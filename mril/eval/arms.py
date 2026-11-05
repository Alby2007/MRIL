"""Evaluation arms — interchangeable routing strategies.

The runner knows nothing about how a model was chosen: an Arm is just a
named RoutingPolicy plus the shared recovery-tightening rule. The three
baseline arms differ only in policy — identical harness, identical limits.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from mril.core.decision import RecoveryAction, RecoveryType
from mril.core.events import VerificationStatus
from mril.core.models import ModelRegistry, ModelSpec, tier_index
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.base import PolicySelection, RoutingPolicy, params_hash
from mril.policy.state import TaskState
from mril.policy.tiered import TieredPolicy, _blended_price


@dataclass(frozen=True)
class Arm:
    name: str
    policy: RoutingPolicy

    @property
    def fingerprint(self) -> str:
        return f"{self.name}:{self.policy.name}@{self.policy.version}#{self.policy.hash}"


def apply_recovery(
    constraints: RoutingConstraints, action: RecoveryAction
) -> RoutingConstraints:
    """Act on a recovery decision by constraining the next route to the
    model the policy committed to — keeps RouteDecided honest about what ran."""
    if action.type in (RecoveryType.ESCALATE, RecoveryType.RETRY) and action.model_id:
        return replace(constraints, allowed_models=(action.model_id,))
    return constraints


@dataclass(frozen=True)
class StrongestPolicy(TieredPolicy):
    """Always the strongest eligible model; retry-or-stop, never escalates."""

    name: str = "strongest-only"
    version: str = "0.2.0"

    def select(self, ctx, constraints, candidates, state, rng) -> PolicySelection:
        if not candidates:
            raise ValueError("no eligible models after constraints")
        pick = max(
            candidates,
            key=lambda m: (tier_index(m.tier), _blended_price(m, ctx.scope), m.model_id),
        )
        return PolicySelection(
            model_id=pick.model_id,
            probability=1.0,
            reason=f"strongest eligible (tier={pick.tier})",
            estimated_cost_usd=self._estimate(pick, ctx.scope),
        )

    def _escalation_target(self, state, constraints, registry):
        return None  # ceiling arm: failures retry the same model or stop


@dataclass(frozen=True)
class CheapFirstPolicy(TieredPolicy):
    """Cheapest eligible model; escalate after `failure_threshold` consecutive
    capability failures on it. The fixed-rule baseline MRIL must beat."""

    name: str = "cheap-first"
    version: str = "0.2.0"
    failure_threshold: int = 1

    @property
    def hash(self) -> str:
        return params_hash(
            {"name": self.name, "version": self.version,
             "failure_threshold": self.failure_threshold}
        )

    def select(self, ctx, constraints, candidates, state, rng) -> PolicySelection:
        if not candidates:
            raise ValueError("no eligible models after constraints")
        pick = min(candidates, key=lambda m: (_blended_price(m, ctx.scope), m.model_id))
        return PolicySelection(
            model_id=pick.model_id,
            probability=1.0,
            reason="cheapest eligible",
            estimated_cost_usd=self._estimate(pick, ctx.scope),
        )

    def recover(self, state, constraints, registry) -> RecoveryAction:
        last = state.last_attempt
        capability_failure = (
            last is not None
            and not last.api_error
            and last.verification_status == VerificationStatus.FAILED
            and last.failure_category not in self.retryable_failures
        )
        if capability_failure and len(state.attempts) < constraints.max_attempts:
            consec = 0
            for a in reversed(state.attempts):
                if (
                    a.model_id == last.model_id
                    and a.verification_status == VerificationStatus.FAILED
                    and a.failure_category not in self.retryable_failures
                ):
                    consec += 1
                else:
                    break
            if consec < self.failure_threshold:
                remaining = (
                    constraints.budget_usd - state.total_cost_usd
                    if constraints.budget_usd is not None
                    else None
                )
                return RecoveryAction(
                    RecoveryType.RETRY,
                    model_id=last.model_id,
                    reason=f"failure {consec}/{self.failure_threshold} before escalation",
                    context_tokens=state.context_tokens,
                    budget_remaining_usd=remaining,
                )
        return super().recover(state, constraints, registry)


def default_arms() -> tuple[Arm, ...]:
    return (
        Arm("strongest-only", StrongestPolicy()),
        Arm("cheap-first", CheapFirstPolicy()),
        Arm("mril-tiered", TieredPolicy()),
    )
