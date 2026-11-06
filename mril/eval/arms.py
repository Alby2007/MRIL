"""Evaluation arms — interchangeable routing strategies.

The runner knows nothing about how a model was chosen: an Arm is just a
named RoutingPolicy plus the shared recovery-tightening rule. The three
baseline arms differ only in policy — identical harness, identical limits.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, replace

from mril.core.decision import RecoveryAction, RecoveryType
from mril.core.events import VerificationStatus
from mril.core.models import ModelRegistry, ModelSpec, tier_index
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.base import PolicySelection, RoutingPolicy, params_hash
from mril.policy.state import TaskState
from mril.policy.tiered import (
    _DEFAULT_TOKENS,
    _EXPECTED_TOKENS,
    TieredPolicy,
    _blended_price,
)


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


@dataclass(frozen=True)
class CollectionPolicy(TieredPolicy):
    """Study-05 randomized recovery collection policy.

    Initial routing is deterministic (``entry="weak"`` picks cheapest
    eligible, ``"strong"`` picks strongest eligible). At each recovery
    checkpoint the policy enumerates the *feasible* action set — retry the
    same model, switch to each other eligible model, or stop — restricted
    by remaining attempt slots and (when set) budget. It then draws
    uniformly with the exact propensity recorded, and logs the complete
    feasible set so off-policy evaluation has the decision-time support.

    The draw index derives from ``collection_seed`` plus the checkpoint
    identity ``(task_id, attempt_count, last_attempt_id)`` — the same
    checkpoint always reproduces the same draw, and the ledger's
    state-keyed dedupe separately guarantees a repeat call returns the
    first committed decision rather than drawing again.

    ``verifier_error`` (infrastructure failure = invalid evidence) shrinks
    the set to {retry, stop}: no capability signal exists to justify a
    model switch. ``verify_timeout`` and other inconclusive states keep the
    full set — a hung verification in this harness is almost always
    code-caused, so it counts as failure evidence with ambiguity noted.
    """

    name: str = "collect-weak"
    version: str = "0.1.0"
    entry: str = "weak"
    collection_seed: int = 0

    @property
    def hash(self) -> str:
        return params_hash(
            {"name": self.name, "version": self.version,
             "entry": self.entry, "collection_seed": self.collection_seed}
        )

    def select(self, ctx, constraints, candidates, state, rng) -> PolicySelection:
        if not candidates:
            raise ValueError("no eligible models after constraints")
        if self.entry == "strong":
            pick = max(
                candidates,
                key=lambda m: (tier_index(m.tier), _blended_price(m, ctx.scope), m.model_id),
            )
            reason = "collection entry: strongest eligible"
        else:
            pick = min(candidates, key=lambda m: (_blended_price(m, ctx.scope), m.model_id))
            reason = "collection entry: cheapest eligible"
        return PolicySelection(
            model_id=pick.model_id,
            probability=1.0,
            reason=reason,
            estimated_cost_usd=self._estimate(pick, ctx.scope),
        )

    def _feasible(self, state, constraints, registry) -> list[str]:
        last = state.last_attempt
        assert last is not None
        slots_left = constraints.max_attempts - len(state.attempts)
        if slots_left <= 0:
            return ["stop"]
        remaining = (
            constraints.budget_usd - state.total_cost_usd
            if constraints.budget_usd is not None
            else None
        )
        it, ot = _EXPECTED_TOKENS.get(state.scope or "", _DEFAULT_TOKENS)

        def afford(est: float) -> bool:
            return remaining is None or est <= remaining

        # Infrastructure failure = invalid evidence: re-attempt the same
        # model or stop, but never spend a switch on zero capability signal.
        invalid_evidence = (
            last.verification_status == "inconclusive"
            and last.failure_category == "verifier_error"
        )
        actions: list[str] = []
        if not invalid_evidence:
            for m in registry.candidates(
                constraints.allowed_models, constraints.require_capabilities
            ):
                if m.model_id == last.model_id:
                    continue
                est = m.switch_cost_usd(state.context_tokens) + m.cost_usd(it, ot)
                if afford(est):
                    actions.append(f"switch:{m.model_id}")
        last_spec = registry.get(last.model_id or "")
        retry_est = last_spec.cost_usd(it, ot) if last_spec else 0.0
        if afford(retry_est):
            actions.append(f"retry:{last.model_id}")
        actions.append("stop")
        return actions

    def recover(self, state, constraints, registry) -> RecoveryAction:
        last = state.last_attempt
        if last is None:
            return RecoveryAction(RecoveryType.CONTINUE, reason="no attempts yet")
        if last.verification_status == "passed":
            return RecoveryAction(RecoveryType.CONTINUE, reason="verification passed")
        feasible = self._feasible(state, constraints, registry)
        key = f"{self.collection_seed}:{state.task_id}:{len(state.attempts)}:{last.attempt_id}"
        idx = zlib.crc32(key.encode()) % len(feasible)
        chosen, prob = feasible[idx], 1.0 / len(feasible)
        reason = f"uniform draw {idx + 1}/{len(feasible)} over {feasible}"
        if chosen == "stop":
            return RecoveryAction(
                RecoveryType.STOP, reason=reason,
                probability=prob, feasible_actions=tuple(feasible),
            )
        kind, model_id = chosen.split(":", 1)
        if kind == "retry":
            return RecoveryAction(
                RecoveryType.RETRY, model_id=model_id,
                reason=f"randomized retry | {reason}",
                probability=prob, feasible_actions=tuple(feasible),
            )
        direction = (
            "downgrade"
            if registry.get(model_id)
            and tier_index(registry.get(model_id).tier) <= tier_index(
                registry.get(last.model_id or "").tier
            )
            else "escalate"
        )
        return RecoveryAction(
            RecoveryType.ESCALATE, model_id=model_id,
            reason=f"randomized {direction} | {reason}",
            probability=prob, feasible_actions=tuple(feasible),
        )


def default_arms() -> tuple[Arm, ...]:
    return (
        Arm("strongest-only", StrongestPolicy()),
        Arm("cheap-first", CheapFirstPolicy()),
        Arm("mril-tiered", TieredPolicy()),
    )


def collection_arms(collection_seed: int = 0) -> tuple[Arm, ...]:
    """Study-05 randomized recovery collection arms (opt-in, not default)."""
    kw = {"collection_seed": collection_seed}
    return (
        Arm("collect-weak", CollectionPolicy(name="collect-weak", entry="weak", **kw)),
        Arm("collect-strong", CollectionPolicy(name="collect-strong", entry="strong", **kw)),
    )
