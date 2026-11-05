import pytest

from mril import Router, RoutingConstraints, TaskContext
from mril.core.decision import RecoveryType
from mril.core.events import TaskOutcome, VerificationStatus
from mril.policy.tiered import TieredPolicy
from mril.store.memory import MemoryEventStore


def make_router(registry, **kw):
    return Router(
        store=MemoryEventStore(),
        registry=registry,
        policy=kw.pop("policy", TieredPolicy()),
        default_constraints=kw.pop(
            "constraints",
            RoutingConstraints(fallback_model_id="balanced-70b", budget_usd=1.0),
        ),
        **kw,
    )


def ctx(**kw):
    return TaskContext(task_id="issue-1", task_type="bug_fix",
                       scope="single_module", risk="low", **kw)


def test_full_lifecycle(registry):
    r = make_router(registry)
    d = r.route(ctx())
    assert d.model_id == "cheap-8b"

    inv = r.observe_invocation(d.decision_id, d.model_id, task_id=d.task_id,
                               input_tokens=10_000, output_tokens=2_000)
    assert inv.cost_usd == pytest.approx(10_000 * 0.10 / 1e6 + 2_000 * 0.30 / 1e6)

    r.observe_verification(inv.attempt_id, VerificationStatus.FAILED,
                           task_id=d.task_id, verifier_type="test",
                           failure_category="test_failure")
    action = r.next_action(d.task_id)
    assert action.type == RecoveryType.ESCALATE

    fin = r.finalize(d.task_id, TaskOutcome.VERIFIED_SUCCESS)
    assert fin.task_outcome == TaskOutcome.VERIFIED_SUCCESS
    assert fin.attempt_count == 1


def test_decision_is_reproducible(registry):
    r1 = make_router(registry)
    r2 = make_router(registry)
    d1 = r1.route(ctx())
    d2 = r2.route(ctx())
    assert (d1.model_id, d1.decision_seed, d1.selection_probability) == (
        d2.model_id, d2.decision_seed, d2.selection_probability)


def test_task_started_written_once(registry):
    r = make_router(registry)
    r.route(ctx())
    r.route(ctx(), step_index=1)
    started = [e for e in r.store.events_for_task("issue-1")
               if e.event_type == "task_started"]
    assert len(started) == 1


def test_policy_error_falls_back(registry):
    class ExplodingPolicy(TieredPolicy):
        def select(self, *a, **k):
            raise RuntimeError("learner exploded")

    r = make_router(registry, policy=ExplodingPolicy())
    d = r.route(ctx())
    assert d.model_id == "balanced-70b"  # configured fallback
    assert d.degraded is True
    assert "policy error" in d.reason


def test_policy_suggesting_restricted_model_rejected(registry):
    class BadPolicy(TieredPolicy):
        def select(self, ctx, constraints, candidates, state, rng):
            from mril.policy.base import PolicySelection
            return PolicySelection("restricted-lab", 1.0, "evil")

    r = make_router(registry, policy=BadPolicy())
    d = r.route(ctx())
    assert d.model_id != "restricted-lab"
    assert d.degraded is True


def test_finalize_derives_inconclusive_without_verification(registry):
    r = make_router(registry)
    d = r.route(ctx())
    r.observe_invocation(d.decision_id, d.model_id, task_id=d.task_id,
                         input_tokens=100, output_tokens=10)
    fin = r.finalize(d.task_id)
    assert fin.task_outcome == TaskOutcome.INCONCLUSIVE  # never silent success


def test_cost_uses_decision_time_snapshot(registry):
    r = make_router(registry)
    d = r.route(ctx())
    # Registry price changes after the decision; snapshot must win.
    new_registry = registry.__class__(
        version="test-2",
        models=tuple(
            m if m.model_id != "cheap-8b"
            else m.__class__(**{**m.__dict__, "input_price": 99.0})
            for m in registry.models
        ),
    )
    r.registry = new_registry
    inv = r.observe_invocation(d.decision_id, d.model_id, task_id=d.task_id,
                               input_tokens=1_000_000, output_tokens=0)
    assert inv.cost_usd == pytest.approx(0.10)  # snapshot price, not $99
