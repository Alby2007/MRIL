"""v0.1.1 hardening: logical idempotency, measured-vs-estimated switch cost,
and marginal selection propensities."""

import pytest

from mril import Router, RoutingConstraints, TaskContext
from mril.core.decision import RecoveryType
from mril.core.events import (
    ModelInvocationFinished,
    RecoveryDecided,
    TaskFinalized,
    VerificationStatus,
)
from mril.policy.tiered import TieredPolicy
from mril.store.memory import MemoryEventStore
from mril.store.sqlite import SQLiteEventStore


def make_router(registry, store=None, **kw):
    return Router(
        store=store or MemoryEventStore(),
        registry=registry,
        policy=kw.pop("policy", TieredPolicy()),
        default_constraints=kw.pop(
            "constraints",
            RoutingConstraints(fallback_model_id="balanced-70b", budget_usd=1.0),
        ),
        **kw,
    )


def ctx(**kw):
    kw.setdefault("task_id", "issue-1")
    return TaskContext(task_type="bug_fix", scope="single_module",
                       risk="low", **kw)


def _attempt_flow(r):
    """route -> invoke -> fail, returns (decision, invocation)."""
    d = r.route(ctx())
    inv = r.observe_invocation(
        d.decision_id, d.model_id, task_id="issue-1",
        input_tokens=10_000, output_tokens=2_000,
        step_index=0, call_site="model_call",
    )
    r.observe_verification(inv.attempt_id, VerificationStatus.FAILED,
                           task_id="issue-1", verifier_type="test",
                           failure_category="test_failure")
    return d, inv


# ---------------------------------------------------------------- dedupe

def test_duplicate_invocation_same_step_deduped(registry):
    r = make_router(registry)
    d = r.route(ctx())
    inv = r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                               input_tokens=10_000, output_tokens=2_000,
                               step_index=0, call_site="model_call")
    # producer retry: same logical call, fresh event_id underneath
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         attempt_id=inv.attempt_id,
                         input_tokens=10_000, output_tokens=2_000,
                         step_index=0, call_site="model_call")
    invs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 1
    assert r.task_state("issue-1").total_cost_usd == pytest.approx(inv.cost_usd)


def test_provider_request_id_dedupes(registry):
    r = make_router(registry)
    d = r.route(ctx())
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         input_tokens=100, output_tokens=10,
                         provider_request_id="req_abc")
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         input_tokens=100, output_tokens=10,
                         provider_request_id="req_abc")  # same request, retried report
    invs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 1


def test_bare_attempt_id_not_deduped(registry):
    """Without step/call_site/request_id there is no logical identity to
    dedupe on — distinct calls under one attempt must both land."""
    r = make_router(registry)
    d = r.route(ctx())
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         attempt_id="a1", input_tokens=100, output_tokens=10)
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         attempt_id="a1", input_tokens=200, output_tokens=20)
    invs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 2


def test_verification_same_verdict_deduped_new_verdict_lands(registry):
    r = make_router(registry)
    d, inv = _attempt_flow(r)
    before = len(r.store.all_events())
    r.observe_verification(inv.attempt_id, VerificationStatus.FAILED,
                           task_id="issue-1", verifier_type="test",
                           failure_category="test_failure")  # exact retry
    assert len(r.store.all_events()) == before
    r.observe_verification(inv.attempt_id, VerificationStatus.PASSED,
                           task_id="issue-1", verifier_type="test")  # correction
    assert len(r.store.all_events()) == before + 1


def test_next_action_idempotent_on_unchanged_state(registry):
    r = make_router(registry)
    _attempt_flow(r)
    a1 = r.next_action("issue-1")
    a2 = r.next_action("issue-1")  # harness retry — same state, same decision
    recs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, RecoveryDecided)]
    assert len(recs) == 1
    assert (a1.type, a1.model_id) == (a2.type, a2.model_id) == (
        RecoveryType.ESCALATE, "balanced-70b")
    assert r.task_state("issue-1").escalation_count == 1


def test_finalize_idempotent_returns_recorded_event(registry):
    r = make_router(registry)
    _attempt_flow(r)
    fin1 = r.finalize("issue-1")
    fin2 = r.finalize("issue-1")
    fins = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, TaskFinalized)]
    assert len(fins) == 1
    assert fin1.event_id == fin2.event_id  # stored verdict, not a phantom


def test_verification_run_id_keeps_distinct_runs(registry):
    """One attempt, three verifier executions, same verdict: all three are
    legitimate observations and must land. Only retries of a run dedupe."""
    r = make_router(registry)
    d = r.route(ctx())
    inv = r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                               input_tokens=10, output_tokens=5)
    for run in ("run-1", "run-2", "run-3"):
        r.observe_verification(inv.attempt_id, VerificationStatus.FAILED,
                               task_id="issue-1", verifier_type="test",
                               failure_category="test_failure",
                               verification_run_id=run)
    # retry of run-2's delivery — dropped
    r.observe_verification(inv.attempt_id, VerificationStatus.FAILED,
                           task_id="issue-1", verifier_type="test",
                           failure_category="test_failure",
                           verification_run_id="run-2")
    vers = [e for e in r.store.events_for_task("issue-1")
            if e.event_type == "verification_completed"]
    assert len(vers) == 3


def test_provider_request_id_namespaced_by_model(registry):
    """Provider request ids aren't globally unique — same id under a different
    provider/model must not dedupe."""
    r = make_router(registry)
    d = r.route(ctx())
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         input_tokens=10, output_tokens=5,
                         provider_request_id="req_1")
    r.observe_invocation(d.decision_id, "balanced-70b", task_id="issue-1",
                         input_tokens=10, output_tokens=5,
                         provider_request_id="req_1")
    invs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 2


def test_recovery_checkpoint_first_committed_wins(registry):
    """The checkpoint key is action-independent: a second evaluation on
    unchanged state retrieves the recorded decision even when the policy
    would now choose differently."""
    from mril.core.events import RecoveryDecided as RD
    r = make_router(registry)
    _, inv = _attempt_flow(r)
    # a stop decision lands first (e.g. a racing caller)
    r.store.append(RD(task_id="issue-1", action="stop", reason="racer",
                      dedupe_key=f"rec:issue-1:1:{inv.attempt_id}"))
    action = r.next_action("issue-1")  # policy would escalate; stored wins
    assert action.type == RecoveryType.STOP
    recs = [e for e in r.store.events_for_task("issue-1")
            if isinstance(e, RecoveryDecided)]
    assert len(recs) == 1


def test_recovery_decided_carries_context_snapshot(registry):
    r = make_router(registry)
    _attempt_flow(r)
    r.next_action("issue-1")
    rec = next(e for e in r.store.events_for_task("issue-1")
               if isinstance(e, RecoveryDecided))
    rc = rec.recovery_context
    assert rc["attempt_count"] == 1
    assert rc["last_failure_category"] == "test_failure"
    assert rc["last_verification_status"] == "failed"
    assert rc["context_tokens"] == 10_000
    assert "cheap-8b" in rc["candidate_model_ids"]
    assert rec.selection_probability == 1.0


def test_sqlite_dedupe_key_enforced(registry, tmp_path):
    store = SQLiteEventStore(tmp_path / "m.db")
    r = make_router(registry, store=store)
    d, inv = _attempt_flow(r)
    r.observe_invocation(d.decision_id, "cheap-8b", task_id="issue-1",
                         attempt_id=inv.attempt_id, input_tokens=1, output_tokens=1,
                         step_index=0, call_site="model_call")
    invs = [e for e in store.events_for_task("issue-1")
            if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 1


def test_sqlite_migration_adds_dedupe_column(registry, tmp_path):
    db = tmp_path / "old.db"
    import sqlite3
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            task_id TEXT, attempt_id TEXT, decision_id TEXT,
            occurred_at TEXT NOT NULL, payload TEXT NOT NULL
        );
    """)
    conn.close()
    store = SQLiteEventStore(db)  # should migrate, not crash
    r = make_router(registry, store=store)
    _attempt_flow(r)
    r.next_action("issue-1"); r.next_action("issue-1")
    recs = [e for e in store.events_for_task("issue-1")
            if isinstance(e, RecoveryDecided)]
    assert len(recs) == 1


# ------------------------------------------------------- switch cost fields

def test_recovery_decided_splits_switch_estimate(registry):
    r = make_router(registry)
    _attempt_flow(r)
    r.next_action("issue-1")
    rec = next(e for e in r.store.events_for_task("issue-1")
               if isinstance(e, RecoveryDecided))
    assert rec.estimated_switch_cost_usd is not None
    assert rec.estimated_cost_usd > rec.estimated_switch_cost_usd
    assert rec.context_tokens == 10_000  # max input observed pre-switch


def test_switch_cost_measured_when_cache_reported(registry):
    r = make_router(registry)
    _attempt_flow(r)
    action = r.next_action("issue-1")  # -> balanced-70b @ $0.80/1M in
    d2 = r.route(ctx(), RoutingConstraints(allowed_models=(action.model_id,),
                                           fallback_model_id=action.model_id),
                 step_index=1, call_site="escalation")
    r.observe_invocation(d2.decision_id, "balanced-70b", task_id="issue-1",
                         input_tokens=12_000, output_tokens=3_000,
                         cached_input_tokens=2_000,
                         step_index=1, call_site="escalation")
    fin = r.finalize("issue-1")
    assert fin.switch_cost_basis == "measured"
    assert fin.actual_switch_cost_usd == pytest.approx(10_000 * 0.80 / 1e6)


def test_switch_cost_estimated_when_cache_unobserved(registry):
    r = make_router(registry)
    _attempt_flow(r)
    action = r.next_action("issue-1")
    d2 = r.route(ctx(), RoutingConstraints(allowed_models=(action.model_id,),
                                           fallback_model_id=action.model_id),
                 step_index=1, call_site="escalation")
    r.observe_invocation(d2.decision_id, "balanced-70b", task_id="issue-1",
                         input_tokens=12_000, output_tokens=3_000,
                         step_index=1, call_site="escalation")  # no cache field
    fin = r.finalize("issue-1")
    assert fin.switch_cost_basis == "estimated"
    # warm context (10k) re-priced at the new model's input price
    assert fin.actual_switch_cost_usd == pytest.approx(10_000 * 0.80 / 1e6)


def test_no_switch_no_switch_cost(registry):
    r = make_router(registry)
    d = r.route(ctx())
    r.observe_invocation(d.decision_id, d.model_id, task_id="issue-1",
                         input_tokens=100, output_tokens=10)
    fin = r.finalize("issue-1")
    assert fin.actual_switch_cost_usd is None
    assert fin.switch_cost_basis is None


# ------------------------------------------------------------ propensities

def test_epsilon_marginal_propensities(registry):
    """Greedy arm logs (1-eps) + eps/n; explored arms log eps/n."""
    eps, n = 0.3, 4  # 4 non-restricted models in the fixture
    r = make_router(registry, policy=TieredPolicy(epsilon=eps),
                    constraints=RoutingConstraints(fallback_model_id="balanced-70b"))
    seen = {}
    for i in range(200):  # seeded deterministically per task_id — sample many
        d = r.route(ctx(task_id=f"t{i}"))
        seen.setdefault(d.model_id, set()).add(round(d.selection_probability, 6))
    assert seen["cheap-8b"] == {round(1 - eps + eps / n, 6)}  # greedy arm
    for m in ("mid-small", "balanced-70b", "frontier-x"):
        assert seen.get(m, set()) <= {round(eps / n, 6)}


def test_epsilon_keeps_decisions_deterministic(registry):
    kw = dict(policy=TieredPolicy(epsilon=0.9),
              constraints=RoutingConstraints(fallback_model_id="balanced-70b"))
    d1 = make_router(registry, **kw).route(ctx())
    d2 = make_router(registry, **kw).route(ctx())
    assert (d1.model_id, d1.selection_probability, d1.decision_seed) == (
        d2.model_id, d2.selection_probability, d2.decision_seed)
