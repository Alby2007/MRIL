"""The MRIL SDK — three operations: route(), observe(), next_action().

Design invariants (non-negotiable):
- All decisions are local; there is no network call in this file.
- A policy or learner failure never blocks the agent: route() falls back to the
  explicitly configured fallback model and marks the decision `degraded`.
- A restricted or out-of-candidate model is never returned, even if a buggy or
  malicious policy suggests one.
- Missing verification is never treated as success: finalize() derives
  `inconclusive` unless a verifier explicitly passed or failed.
- Costs prefer provider-reported usage; otherwise they are computed from the
  price snapshot recorded at decision time, not live registry prices.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone

from mril.core.decision import RecoveryAction, RecoveryType, RoutingDecision
from mril.core.errors import NoEligibleModelError
from mril.core.events import (
    ModelInvocationFinished,
    RecoveryDecided,
    RouteDecided,
    TaskFinalized,
    TaskOutcome,
    TaskStarted,
    VerificationCompleted,
    VerificationStatus,
    new_event_id,
)
from mril.core.models import ModelRegistry
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.base import RoutingPolicy
from mril.policy.recovery_context import RecoveryContext
from mril.policy.state import TaskState, rebuild_state
from mril.policy.tiered import TieredPolicy
from mril.store.base import EventStore


class Router:
    def __init__(
        self,
        store: EventStore,
        registry: ModelRegistry,
        policy: RoutingPolicy | None = None,
        default_constraints: RoutingConstraints | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.policy = policy or TieredPolicy()
        self.default_constraints = default_constraints or RoutingConstraints()

    # ------------------------------------------------------------------ route

    def route(
        self,
        ctx: TaskContext,
        constraints: RoutingConstraints | None = None,
        *,
        step_index: int | None = None,
        call_site: str | None = None,
    ) -> RoutingDecision:
        constraints = constraints or self.default_constraints
        self._ensure_task_started(ctx)

        seed = self._decision_seed(ctx.task_id, step_index, call_site)
        rng = random.Random(seed)
        candidates = self.registry.candidates(
            constraints.allowed_models, constraints.require_capabilities
        )
        snapshot = {m.model_id: m.price_snapshot() for m in candidates}

        degraded = False
        try:
            sel = self.policy.select(ctx, constraints, candidates, self._state(ctx.task_id), rng)
            if sel.model_id not in {m.model_id for m in candidates}:
                raise NoEligibleModelError(
                    f"policy selected {sel.model_id!r}, which is not an eligible candidate"
                )
            model_id, prob, reason, est = sel.model_id, sel.probability, sel.reason, sel.estimated_cost_usd
        except Exception as exc:  # policy/learner failure must not block the agent
            model_id = self._fallback_model(constraints, candidates)
            prob, reason, est = 1.0, f"fallback after policy error: {exc}", None
            degraded = True

        decision_id = new_event_id()
        decision = RoutingDecision(
            decision_id=decision_id,
            task_id=ctx.task_id,
            model_id=model_id,
            policy_name=self.policy.name,
            policy_version=self.policy.version,
            policy_hash=self.policy.hash,
            registry_version=self.registry.version,
            registry_hash=self.registry.hash,
            selection_probability=prob,
            reason=reason,
            decision_seed=seed,
            estimated_cost_usd=est,
            candidates=tuple(m.model_id for m in candidates),
            price_snapshot=snapshot,
            step_index=step_index,
            call_site=call_site,
            degraded=degraded,
        )
        self.store.append(
            RouteDecided(
                task_id=ctx.task_id,
                decision_id=decision_id,
                step_index=step_index,
                call_site=call_site,
                model_id=model_id,
                policy_name=decision.policy_name,
                policy_version=decision.policy_version,
                policy_hash=decision.policy_hash,
                registry_version=decision.registry_version,
                registry_hash=decision.registry_hash,
                selection_probability=prob,
                reason=reason,
                estimated_cost_usd=est,
                candidates=list(decision.candidates),
                price_snapshot=snapshot,
                decision_seed=seed,
                degraded=degraded,
            )
        )
        return decision

    # ---------------------------------------------------------------- observe

    def observe_invocation(
        self,
        decision_id: str,
        model_id: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        latency_ms: float | None = None,
        cost_usd: float | None = None,
        api_error: str | None = None,
        provider_request_id: str | None = None,
        step_index: int | None = None,
        call_site: str | None = None,
    ) -> ModelInvocationFinished:
        if cost_usd is None and input_tokens is not None and output_tokens is not None:
            cost_usd = self._compute_cost(
                decision_id, model_id, input_tokens, output_tokens, cached_input_tokens or 0
            )
        attempt_id = attempt_id or new_event_id()
        # Logical identity: the provider's own request id when known —
        # namespaced by provider since request ids aren't globally unique —
        # else (attempt, step, call_site). With neither, no dedupe: a bare
        # attempt_id can host several distinct calls and must not collapse them.
        if provider_request_id:
            spec = self.registry.get(model_id)
            ns = (spec.provider or spec.model_id) if spec else model_id
            dedupe_key = f"inv:req:{ns}:{provider_request_id}"
        elif step_index is not None or call_site is not None:
            dedupe_key = f"inv:{attempt_id}:{step_index}:{call_site}"
        else:
            dedupe_key = None
        event = ModelInvocationFinished(
            task_id=task_id,
            attempt_id=attempt_id,
            decision_id=decision_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            api_error=api_error,
            provider_request_id=provider_request_id,
            step_index=step_index,
            call_site=call_site,
            dedupe_key=dedupe_key,
        )
        self.store.append(event)
        return event

    def observe_verification(
        self,
        attempt_id: str,
        status: VerificationStatus | str,
        *,
        task_id: str | None = None,
        verifier_type: str = "unknown",
        confidence: float | None = None,
        failure_category: str | None = None,
        verification_run_id: str | None = None,
        step_index: int | None = None,
    ) -> VerificationCompleted:
        status = VerificationStatus(status)
        # Each verifier *execution* gets a stable run id from the harness;
        # retries of that execution dedupe, distinct runs never collapse —
        # even when they return the same verdict. Without a run id the key
        # falls back to observation content (approximate, documented).
        dedupe_key = (
            f"ver:run:{verification_run_id}"
            if verification_run_id
            else f"ver:{attempt_id}:{verifier_type}:{status.value}:{failure_category}:{step_index}"
        )
        event = VerificationCompleted(
            task_id=task_id,
            attempt_id=attempt_id,
            status=status,
            verifier_type=verifier_type,
            confidence=confidence,
            failure_category=failure_category,
            step_index=step_index,
            dedupe_key=dedupe_key,
        )
        self.store.append(event)
        return event

    # ------------------------------------------------------------- next_action

    def next_action(
        self, task_id: str, constraints: RoutingConstraints | None = None
    ) -> RecoveryAction:
        constraints = constraints or self.default_constraints
        state = self._state(task_id)
        rctx = RecoveryContext.from_state(state, constraints, self.registry)
        try:
            action = self.policy.recover(state, constraints, self.registry)
        except Exception as exc:
            action = RecoveryAction(RecoveryType.CONTINUE, reason=f"recovery error: {exc}")
        # A recovery *checkpoint* is identified by the state at decision time,
        # never by the action chosen — including the failure evidence observed
        # since the last attempt, so a pre-verification 'continue' can't shadow
        # the decision that fresh evidence demands. First committed decision
        # wins: a repeat or racing call on unchanged state gets the recorded
        # action back — this is what keeps a stochastic policy single-draw.
        last = state.last_attempt
        evidence = "-"
        if last is not None:
            evidence = ":".join(
                (
                    last.attempt_id,
                    last.verification_status.value if last.verification_status else "-",
                    last.failure_category or "-",
                    "err" if last.api_error else "-",
                )
            )
        dedupe_key = f"rec:{task_id}:{len(state.attempts)}:{evidence}"
        event = RecoveryDecided(
            task_id=task_id,
            action=action.type.value,
            model_id=action.model_id,
            reason=action.reason,
            estimated_cost_usd=action.estimated_cost_usd,
            estimated_switch_cost_usd=action.estimated_switch_cost_usd,
            context_tokens=action.context_tokens,
            budget_remaining_usd=action.budget_remaining_usd,
            selection_probability=action.probability,
            feasible_actions=list(action.feasible_actions),
            recovery_context=rctx.to_dict(),
            dedupe_key=dedupe_key,
        )
        if not self.store.append(event):
            stored = next(
                (
                    e
                    for e in reversed(self.store.events_for_task(task_id))
                    if isinstance(e, RecoveryDecided) and e.dedupe_key == dedupe_key
                ),
                None,
            )
            if stored is not None:
                return RecoveryAction(
                    RecoveryType(stored.action),
                    model_id=stored.model_id,
                    reason=stored.reason,
                    estimated_cost_usd=stored.estimated_cost_usd,
                    estimated_switch_cost_usd=stored.estimated_switch_cost_usd,
                    context_tokens=stored.context_tokens,
                    budget_remaining_usd=stored.budget_remaining_usd,
                    probability=stored.selection_probability,
                    feasible_actions=tuple(stored.feasible_actions),
                )
        return action

    # ---------------------------------------------------------------- finalize

    def finalize(self, task_id: str, outcome: TaskOutcome | str | None = None) -> TaskFinalized:
        events = self.store.events_for_task(task_id)
        state = rebuild_state(task_id, events)
        if outcome is None:
            outcome = self._derive_outcome(state)
        switch_cost, switch_basis = self._switch_cost(events)
        event = TaskFinalized(
            task_id=task_id,
            task_outcome=TaskOutcome(outcome),
            total_cost_usd=state.total_cost_usd,
            elapsed_ms=self._elapsed_ms(task_id),
            attempt_count=len(state.attempts),
            escalation_count=state.escalation_count,
            actual_switch_cost_usd=switch_cost,
            switch_cost_basis=switch_basis,
            dedupe_key=f"fin:{task_id}",
        )
        if not self.store.append(event):
            # already finalized — return the recorded verdict, not a phantom
            stored = next(
                (e for e in reversed(events) if isinstance(e, TaskFinalized)), None
            )
            if stored is not None:
                return stored
        return event

    # ------------------------------------------------------------------ state

    def task_state(self, task_id: str) -> TaskState:
        return self._state(task_id)

    # ------------------------------------------------------------------ intern

    def _state(self, task_id: str) -> TaskState:
        return rebuild_state(task_id, self.store.events_for_task(task_id))

    def _ensure_task_started(self, ctx: TaskContext) -> None:
        events = self.store.events_for_task(ctx.task_id)
        if any(e.event_type == "task_started" for e in events):
            return
        self.store.append(
            TaskStarted(
                task_id=ctx.task_id,
                language=ctx.language,
                task_type=ctx.task_type,
                scope=ctx.scope,
                risk=ctx.risk,
                harness=ctx.harness,
                metadata=dict(ctx.metadata),
                dedupe_key=f"ts:{ctx.task_id}",  # race-safe even if check loses
            )
        )

    def _decision_seed(self, task_id: str, step_index: int | None, call_site: str | None) -> int:
        material = f"{self.policy.hash}:{self.registry.hash}:{task_id}:{step_index}:{call_site}"
        return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big")

    def _fallback_model(
        self, constraints: RoutingConstraints, candidates: list
    ) -> str:
        # A configured fallback must itself be routable — restricted or
        # unknown ids are skipped rather than smuggled past eligibility.
        if constraints.fallback_model_id:
            spec = self.registry.get(constraints.fallback_model_id)
            if spec is not None and not spec.restricted:
                return spec.model_id
        if candidates:
            return min(candidates, key=lambda m: (m.input_price + m.output_price, m.model_id)).model_id
        non_restricted = [m for m in self.registry.models if not m.restricted]
        if non_restricted:
            return min(non_restricted, key=lambda m: (m.input_price + m.output_price, m.model_id)).model_id
        raise NoEligibleModelError("no eligible models and no fallback configured")

    def _compute_cost(
        self,
        decision_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
    ) -> float | None:
        # Prefer the price snapshot frozen into the RouteDecided event.
        for e in self.store.events_for_decision(decision_id):
            if isinstance(e, RouteDecided):
                snap = e.price_snapshot.get(model_id)
                if snap:
                    inp = snap.get("input_price") or 0.0
                    outp = snap.get("output_price") or 0.0
                    cp = snap.get("cached_input_price")
                    cp = inp if cp is None else cp
                    cached = min(cached_input_tokens, input_tokens)
                    return ((input_tokens - cached) * inp + cached * cp + output_tokens * outp) / 1e6
        spec = self.registry.get(model_id)
        if spec:
            return spec.cost_usd(input_tokens, output_tokens, cached_input_tokens)
        return None

    def _snapshot_input_price(self, decision_id: str | None, model_id: str) -> float | None:
        """Decision-time input price for a model: the RouteDecided snapshot
        first, live registry as a fallback."""
        if decision_id:
            for e in self.store.events_for_decision(decision_id):
                if isinstance(e, RouteDecided):
                    snap = e.price_snapshot.get(model_id)
                    if snap and snap.get("input_price") is not None:
                        return snap["input_price"]
        spec = self.registry.get(model_id)
        return spec.input_price if spec else None

    def _switch_cost(self, events: list) -> tuple[float | None, str | None]:
        """Re-ingestion spend attributable to model switches, per escalation.

        For each escalate decision, the first subsequent invocation is the
        post-switch call. When the provider reported cached_input_tokens on it,
        the fresh-input share IS the billed re-ingest ("measured"). When cache
        usage is unobservable, the prior warm context is priced at the new
        model's input price ("estimated") — never labelled measured.
        """
        esc_idx = [
            i for i, e in enumerate(events)
            if isinstance(e, RecoveryDecided) and e.action == "escalate" and e.model_id
        ]
        if not esc_idx:
            return None, None
        invs = [(i, e) for i, e in enumerate(events) if isinstance(e, ModelInvocationFinished)]
        total, bases = 0.0, []
        for idx in esc_idx:
            prev = next((e for i, e in reversed(invs) if i < idx), None)
            nxt = next((e for i, e in invs if i > idx), None)
            if nxt is None or (prev and nxt.model_id == prev.model_id):
                continue  # no switch actually happened
            price = self._snapshot_input_price(nxt.decision_id, nxt.model_id or "")
            if price is None:
                continue
            if nxt.input_tokens is not None and nxt.cached_input_tokens is not None:
                total += (nxt.input_tokens - nxt.cached_input_tokens) * price / 1e6
                bases.append("measured")
            else:
                warm = max(
                    (e.input_tokens or 0 for i, e in invs if i < idx), default=0
                )
                total += warm * price / 1e6
                bases.append("estimated")
        if not bases:
            return None, None
        basis = bases[0] if len(set(bases)) == 1 else "mixed"
        return total, basis

    def _derive_outcome(self, state: TaskState) -> TaskOutcome:
        last = state.last_attempt
        if last is None:
            return TaskOutcome.INCONCLUSIVE
        if last.verification_status == VerificationStatus.PASSED:
            return TaskOutcome.VERIFIED_SUCCESS
        if last.verification_status == VerificationStatus.FAILED:
            return TaskOutcome.VERIFIED_FAILURE
        return TaskOutcome.INCONCLUSIVE

    def _elapsed_ms(self, task_id: str) -> float | None:
        started = next(
            (e for e in self.store.events_for_task(task_id) if e.event_type == "task_started"),
            None,
        )
        if started is None:
            return None
        t0 = datetime.fromisoformat(started.occurred_at)
        return (datetime.now(timezone.utc) - t0).total_seconds() * 1000
