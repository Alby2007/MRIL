import random

import pytest

from mril.core.decision import RecoveryType
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.state import AttemptRecord, TaskState
from mril.policy.tiered import TieredPolicy


def ctx(**kw):
    return TaskContext(task_id="t1", **kw)


def test_low_risk_routes_cheap(registry):
    p = TieredPolicy()
    sel = p.select(ctx(scope="single_file", risk="low"),
                   RoutingConstraints(), registry.candidates(), None, random.Random(0))
    assert sel.model_id == "cheap-8b"  # cheapest in the cheap tier
    assert sel.probability == 1.0


def test_high_risk_multi_module_routes_frontier(registry):
    p = TieredPolicy()
    sel = p.select(ctx(scope="multi_module", risk="high"),
                   RoutingConstraints(), registry.candidates(), None, random.Random(0))
    assert sel.model_id == "frontier-x"


def test_restricted_never_selected_even_if_cheapest(registry):
    p = TieredPolicy()
    candidates = registry.candidates()  # excludes restricted-lab
    assert "restricted-lab" not in {m.model_id for m in candidates}
    sel = p.select(ctx(scope="repo_wide", risk="high"),
                   RoutingConstraints(), candidates, None, random.Random(0))
    assert sel.model_id != "restricted-lab"


def test_allowlist_respected(registry):
    p = TieredPolicy()
    c = RoutingConstraints(allowed_models=("frontier-x",))
    sel = p.select(ctx(scope="single_file", risk="low"), c,
                   registry.candidates(c.allowed_models), None, random.Random(0))
    assert sel.model_id == "frontier-x"  # only allowed model, despite cheap preference


def test_deterministic_same_seed(registry):
    p = TieredPolicy(epsilon=0.3)
    cands = registry.candidates()
    s1 = p.select(ctx(scope="single_module"), RoutingConstraints(), cands, None,
                  random.Random(1234))
    s2 = p.select(ctx(scope="single_module"), RoutingConstraints(), cands, None,
                  random.Random(1234))
    assert s1 == s2


def test_epsilon_exploration_records_probability(registry):
    p = TieredPolicy(epsilon=0.5)
    cands = registry.candidates()
    for seed in range(200):
        sel = p.select(ctx(), RoutingConstraints(), cands, None, random.Random(seed))
        if "exploration" in sel.reason:
            assert sel.probability == pytest.approx(0.5 / len(cands))
            return
    pytest.fail("no exploration observed in 200 seeds")


def _state_with_attempt(model_id="cheap-8b", failure="test_failure", tokens=20000,
                        cost=0.002, status="failed"):
    st = TaskState(task_id="t1", scope="single_module")
    st.attempts.append(AttemptRecord(
        attempt_id="a1", model_id=model_id, cost_usd=cost,
        input_tokens=tokens, verification_status=status,
        failure_category=failure,
    ))
    st.total_cost_usd = cost
    return st


def test_capability_failure_escalates_with_switch_cost(registry):
    p = TieredPolicy()
    action = p.recover(_state_with_attempt(), RoutingConstraints(), registry)
    assert action.type == RecoveryType.ESCALATE
    assert action.model_id == "balanced-70b"
    # estimate = context re-ingest (20k @ $0.80/M) + expected attempt (~$0.0216)
    assert action.estimated_cost_usd == pytest.approx(20000 * 0.80 / 1e6 + 15000 * 0.80 / 1e6 + 4000 * 2.40 / 1e6)
    assert "re-ingest" in action.reason


def test_retryable_failure_retries_same_model(registry):
    p = TieredPolicy()
    action = p.recover(_state_with_attempt(failure="timeout"),
                       RoutingConstraints(), registry)
    assert action.type == RecoveryType.RETRY
    assert action.model_id == "cheap-8b"


def test_budget_exhausted_stops(registry):
    p = TieredPolicy()
    action = p.recover(_state_with_attempt(cost=0.40),
                       RoutingConstraints(budget_usd=0.40), registry)
    assert action.type == RecoveryType.STOP


def test_escalation_blocked_when_over_budget(registry):
    p = TieredPolicy()
    st = _state_with_attempt(tokens=50000, cost=0.30)
    action = p.recover(st, RoutingConstraints(budget_usd=0.31), registry)
    assert action.type == RecoveryType.STOP
    assert "budget" in action.reason


def test_passed_verification_continues(registry):
    p = TieredPolicy()
    action = p.recover(_state_with_attempt(status="passed"),
                       RoutingConstraints(), registry)
    assert action.type == RecoveryType.CONTINUE


def test_max_attempts_stops(registry):
    p = TieredPolicy()
    st = _state_with_attempt()
    for _ in range(3):
        st.attempts.append(st.attempts[0])
    action = p.recover(st, RoutingConstraints(max_attempts=4), registry)
    assert action.type == RecoveryType.STOP
