"""TieredPolicy — interpretable rules + tier baseline (v0.1 default).

Selection: derive a minimum capability tier from task features, then pick the
cheapest candidate at or above it. Deterministic given (context, candidates,
seed); optional epsilon-exploration is seeded and its probability is recorded.

Recovery: retry infrastructure failures, escalate on repeated capability
failures — but only when the escalation cost model (KV-cache rewrite + expected
attempt cost) fits the remaining budget. Stop rather than silently bypass it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from mril.core.decision import RecoveryAction, RecoveryType
from mril.core.models import ModelRegistry, ModelSpec, tier_index
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.base import PolicySelection, params_hash
from mril.policy.state import TaskState

# Expected token usage per scope — used only for cost *estimates*.
_EXPECTED_TOKENS = {
    "single_file": (6_000, 1_500),
    "single_module": (15_000, 4_000),
    "multi_module": (40_000, 10_000),
    "repo_wide": (120_000, 30_000),
}
_DEFAULT_TOKENS = (20_000, 5_000)

# Failures caused by infrastructure, not model capability — same model is fine.
_RETRYABLE_FAILURES = frozenset(
    {"timeout", "rate_limit", "overloaded", "connection_error", "parse_error"}
)


def _min_tier(scope: str | None, risk: str | None) -> str:
    if risk == "high":
        return "frontier" if scope in ("multi_module", "repo_wide") else "balanced"
    if risk == "medium":
        return "frontier" if scope == "repo_wide" else "balanced"
    # low or unknown risk
    if scope in ("multi_module", "repo_wide"):
        return "balanced"
    return "cheap"


def _blended_price(m: ModelSpec, scope: str | None) -> float:
    it, ot = _EXPECTED_TOKENS.get(scope or "", _DEFAULT_TOKENS)
    return it * m.input_price + ot * m.output_price


@dataclass(frozen=True)
class TieredPolicy:
    name: str = "tiered"
    version: str = "0.1.0"
    epsilon: float = 0.0
    retryable_failures: frozenset[str] = field(default=_RETRYABLE_FAILURES)

    @property
    def hash(self) -> str:
        return params_hash(
            {
                "name": self.name,
                "version": self.version,
                "epsilon": self.epsilon,
                "retryable_failures": sorted(self.retryable_failures),
            }
        )

    # -- initial routing -----------------------------------------------------

    def select(
        self,
        ctx: TaskContext,
        constraints: RoutingConstraints,
        candidates: list[ModelSpec],
        state: TaskState | None,
        rng: random.Random,
    ) -> PolicySelection:
        if not candidates:
            raise ValueError("no eligible models after constraints")

        n = len(candidates)
        if self.epsilon > 0 and rng.random() < self.epsilon:
            pick = candidates[rng.randrange(n)]
            return PolicySelection(
                model_id=pick.model_id,
                probability=self.epsilon / n,
                reason=f"epsilon-exploration (eps={self.epsilon})",
                estimated_cost_usd=self._estimate(pick, ctx.scope),
            )

        minimum = _min_tier(ctx.scope, ctx.risk)
        eligible = [m for m in candidates if tier_index(m.tier) >= tier_index(minimum)]
        pool = eligible if eligible else list(candidates)
        reason = (
            f"min_tier={minimum} (scope={ctx.scope}, risk={ctx.risk})"
            if eligible
            else f"no candidate meets min_tier={minimum}; cheapest allowed"
        )
        pick = min(pool, key=lambda m: (_blended_price(m, ctx.scope), m.model_id))
        prob = 1.0 - self.epsilon if self.epsilon > 0 else 1.0
        return PolicySelection(
            model_id=pick.model_id,
            probability=prob,
            reason=reason,
            estimated_cost_usd=self._estimate(pick, ctx.scope),
        )

    # -- recovery ------------------------------------------------------------

    def recover(
        self,
        state: TaskState,
        constraints: RoutingConstraints,
        registry: ModelRegistry,
    ) -> RecoveryAction:
        budget = constraints.budget_usd
        remaining = (budget - state.total_cost_usd) if budget is not None else None
        if state.finalized:
            return RecoveryAction(RecoveryType.STOP, reason="task already finalized",
                                  budget_remaining_usd=remaining)
        if remaining is not None and remaining <= 0:
            return RecoveryAction(RecoveryType.STOP, reason="budget exhausted",
                                  budget_remaining_usd=remaining)

        last = state.last_attempt
        if last is None:
            return RecoveryAction(RecoveryType.CONTINUE, reason="no attempts yet",
                                  budget_remaining_usd=remaining)
        if len(state.attempts) >= constraints.max_attempts:
            return RecoveryAction(
                RecoveryType.STOP,
                reason=f"max attempts reached ({constraints.max_attempts})",
                budget_remaining_usd=remaining,
            )
        if last.api_error:
            return RecoveryAction(RecoveryType.RETRY, model_id=last.model_id,
                                  reason=f"provider error: {last.api_error}",
                                  budget_remaining_usd=remaining)
        if last.verification_status == "passed":
            return RecoveryAction(RecoveryType.CONTINUE, reason="verification passed",
                                  budget_remaining_usd=remaining)
        if last.verification_status in (None, "inconclusive"):
            return RecoveryAction(RecoveryType.CONTINUE,
                                  reason="no conclusive verification yet",
                                  budget_remaining_usd=remaining)

        # verification failed
        if last.failure_category in self.retryable_failures:
            return RecoveryAction(RecoveryType.RETRY, model_id=last.model_id,
                                  reason=f"retryable failure: {last.failure_category}",
                                  budget_remaining_usd=remaining)

        # capability failure — try to escalate, pricing in the cache rewrite
        target = self._escalation_target(state, constraints, registry)
        if target is None:
            if len(state.attempts) + 1 < constraints.max_attempts:
                return RecoveryAction(RecoveryType.RETRY, model_id=last.model_id,
                                      reason="no higher-tier candidate available",
                                      budget_remaining_usd=remaining)
            return RecoveryAction(RecoveryType.STOP, reason="no escalation path",
                                  budget_remaining_usd=remaining)

        it, ot = _EXPECTED_TOKENS.get(state.scope or "", _DEFAULT_TOKENS)
        est = target.switch_cost_usd(state.context_tokens) + target.cost_usd(it, ot)
        if remaining is not None and est > remaining:
            return RecoveryAction(
                RecoveryType.STOP,
                reason=f"escalation to {target.model_id} (~${est:.4f}) exceeds remaining budget",
                estimated_cost_usd=est,
                budget_remaining_usd=remaining,
            )
        return RecoveryAction(
            RecoveryType.ESCALATE,
            model_id=target.model_id,
            reason=f"capability failure ({last.failure_category}); escalating tier "
            f"(includes ~${target.switch_cost_usd(state.context_tokens):.4f} context re-ingest)",
            estimated_cost_usd=est,
            budget_remaining_usd=remaining,
        )

    # -- helpers ---------------------------------------------------------------

    def _escalation_target(
        self,
        state: TaskState,
        constraints: RoutingConstraints,
        registry: ModelRegistry,
    ) -> ModelSpec | None:
        current = registry.get(state.last_model_id or "")
        current_tier = tier_index(current.tier) if current else -1
        pool = [
            m
            for m in registry.candidates(constraints.allowed_models, constraints.require_capabilities)
            if tier_index(m.tier) > current_tier and m.model_id != state.last_model_id
        ]
        if not pool:
            return None
        return min(
            pool,
            key=lambda m: (
                tier_index(m.tier),
                m.switch_cost_usd(state.context_tokens),
                m.model_id,
            ),
        )

    @staticmethod
    def _estimate(m: ModelSpec, scope: str | None) -> float:
        it, ot = _EXPECTED_TOKENS.get(scope or "", _DEFAULT_TOKENS)
        return m.cost_usd(it, ot)
