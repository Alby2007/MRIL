"""EmpiricalCheapFirstPolicy + PolicyTrainer — Study 03 tests."""

from __future__ import annotations

import json
import random

import pytest

from mril.core.models import ModelRegistry, ModelSpec
from mril.core.task import RoutingConstraints, TaskContext
from mril.eval.train import fit
from mril.policy.empirical import EmpiricalCheapFirstPolicy, PolicySnapshot
from mril.policy.features import FEATURE_VERSION, TaskFeatures, features_from_context
from mril.store.sqlite import SQLiteEventStore
from mril.store.memory import MemoryEventStore
from mril.sdk import Router
from mril.policy.tiered import TieredPolicy


def _spec(mid, tier, inp=0.0, out=0.0):
    return ModelSpec(
        model_id=mid, provider="t", tier=tier,
        input_price=inp, output_price=out, cached_input_price=inp,
    )


WEAK = _spec("weak-coder", "cheap", 1e-7, 1e-7)
STRONG = _spec("strong-coder", "frontier", 1e-6, 3e-6)


def _ctx(features=None, task_id="t1"):
    return TaskContext(
        task_id=task_id, task_type="feature", scope="single_module",
        metadata={"features": features} if features is not None else {},
    )


FEATS_FAILING = {"category": "feature", "scope": "single_module",
                 "api_kind": "function", "spec_clauses": "many",
                 "rule_markers": "numeric+ordering"}
FEATS_PASSING = {"category": "feature", "scope": "single_module",
                 "api_kind": "class", "spec_clauses": "single",
                 "rule_markers": ""}


def _snap(beta=None, cm=None, **kw):
    base = {"c_weak": 0.0002, "c_strong_fresh": 0.005, "c_strong_after_fail": 0.006,
            "c_handoff": 0.002, "q_recovery": 0.8, "q_fresh": 0.8}
    base.update(cm or {})
    kw.setdefault("feature_version", FEATURE_VERSION)
    return PolicySnapshot(
        version="1", prior_strength=3.0,
        beta={"global": [10.0, 3.0]} if beta is None else beta,
        cost_model=base, quality_margin=0.05, **kw)


# ------------------------------------------------------------- estimator


def test_estimator_uniform_when_empty():
    snap = _snap(beta={})
    p, ev = snap.estimate(TaskFeatures("a", "b", "c", "d", "e"))
    assert p == pytest.approx(0.5)
    assert ev == 0


def test_estimator_uses_global_for_unseen_features():
    snap = _snap(beta={"global": [20.0, 5.0]})  # 20/25 observed
    p, _ = snap.estimate(TaskFeatures("x", "y", "z", "w", ""))
    assert p == pytest.approx((20 + 1.5) / (25 + 3))  # shrunk toward .5


def test_estimator_feature_pull_and_signature_pull():
    beta = {
        "global": [10.0, 10.0],
        "feat:api_kind=function": [0.0, 8.0],   # functions fail
        "sig:x": [2.0, 0.0],                      # but THIS signature passes
    }
    f = TaskFeatures("c", "s", "function", "d", "")
    # feature-only estimate should be dragged toward failing
    snap = _snap(beta=beta)
    p_feat, _ = snap.estimate(
        TaskFeatures("c", "s", "function", "d", ""))
    # p_global=.5; feat: (0 + 3*.5)/(8+3) = .136; blend incl. other keys:
    assert p_feat < 0.5
    # signature overrides: (2 + 3*p_feat)/(2+3) closer to 1
    f2 = TaskFeatures("c", "s", "function", "d", "")
    p_sig = snap._post_mean("sig:x", p_feat)[0]
    assert p_sig > p_feat


# ------------------------------------------------------------- decision


def _select(policy, features, cands=(WEAK, STRONG)):
    ctx = _ctx(features)
    return policy.select(ctx, RoutingConstraints(), list(cands), None,
                         random.Random(0))


def test_policy_goes_cheap_when_weak_likely_succeeds():
    pol = EmpiricalCheapFirstPolicy(snapshot=_snap())  # global 10/13 ≈ .77
    sel = _select(pol, FEATS_PASSING)
    assert sel.model_id == "weak-coder"
    assert "E[cheap]" in sel.reason


def test_policy_goes_strong_when_evidence_says_weak_fails():
    # p_w low AND recovery can't rescue cheaply: q_recovery low enough that
    # Q_cf drops below Q_sf - margin, or cost comparison favors strong.
    beta = {"global": [1.0, 30.0]}  # p_w ≈ .09
    pol = EmpiricalCheapFirstPolicy(snapshot=_snap(beta=beta))
    sel = _select(pol, FEATS_FAILING)
    # E[cheap] = .0002 + .91*(.002+.006) = .0075 > .005 strong AND
    # Q_cf = .09 + .91*.8 = .82 vs Q_sf = .8 — within margin, cost decides
    assert sel.model_id == "strong-coder"


def test_policy_defaults_cheap_on_fallback():
    snap = _snap(beta={}, fallback="cheap")
    pol = EmpiricalCheapFirstPolicy(snapshot=snap)
    assert _select(pol, FEATS_PASSING).model_id == "weak-coder"


def test_policy_quality_margin_forces_strong():
    # p_w low; cheap cost still lower — but quality gap exceeds margin
    cm = {"c_strong_after_fail": 0.001, "q_recovery": 0.3, "q_fresh": 0.9}
    beta = {"global": [1.0, 30.0]}          # p_w ≈ .09
    # Q_cf = .09 + .91*.3 = .36 < .9 - .05 — infeasible -> strong despite cost
    pol = EmpiricalCheapFirstPolicy(snapshot=_snap(beta=beta, cm=cm))
    assert _select(pol, FEATS_FAILING).model_id == "strong-coder"


def test_policy_single_candidate():
    pol = EmpiricalCheapFirstPolicy(snapshot=_snap())
    ctx = _ctx(FEATS_PASSING)
    sel = pol.select(ctx, RoutingConstraints(), [WEAK], None, random.Random(0))
    assert sel.model_id == "weak-coder" and sel.probability == 1.0


def test_policy_epsilon_propensities():
    pol = EmpiricalCheapFirstPolicy(snapshot=_snap(), epsilon=0.3)
    # deterministic greedy -> cheap; explore could pick strong
    ctx = _ctx(FEATS_PASSING)
    probs = {}
    for s in range(300):
        sel = pol.select(ctx, RoutingConstraints(), [WEAK, STRONG], None,
                         random.Random(s))
        probs[sel.model_id] = sel.probability
    assert probs["weak-coder"] == pytest.approx(0.7 + 0.3 / 2)
    assert probs["strong-coder"] == pytest.approx(0.3 / 2)


def test_policy_rejects_stale_feature_version():
    """Beta buckets mean nothing under a different feature extractor — a v1
    snapshot must be retrained, not silently applied. An empty beta is
    exempt: no evidence exists to misapply."""
    with pytest.raises(ValueError, match="feature_version"):
        EmpiricalCheapFirstPolicy(snapshot=_snap(feature_version="1"))
    # empty evidence -> version can't mislead -> construction still works
    EmpiricalCheapFirstPolicy(snapshot=_snap(beta={}, feature_version="1"))


def test_snapshot_hash_covers_decision_knobs():
    """fallback/epsilon/feature_version all change decisions — identical
    hashes across them would break replay."""
    a = _snap()
    for kw in ({"fallback": "strong"}, {"epsilon": 0.1}, {"feature_version": "1"}):
        assert _snap(**kw).hash != a.hash


def test_features_from_context_missing_metadata():
    f = features_from_context(TaskContext(task_id="t"))
    assert f.category == "unknown" and f.api_kind == "unknown"


def test_snapshot_roundtrip(tmp_path):
    snap = _snap(beta={"global": [3.0, 1.0], "feat:x=y": [1.0, 2.0]})
    d = snap.to_dict()
    snap2 = PolicySnapshot.from_dict(json.loads(json.dumps(d)))
    assert snap2.beta == snap.beta and snap2.cost_model == snap.cost_model
    assert snap2.hash == snap.hash
    with pytest.raises(ValueError, match="version"):
        PolicySnapshot.from_dict({"version": "99"})


# ------------------------------------------------------------- trainer


def _ledger_run(store, task_id, script):
    """script: [(model_id, verified|None), ...] attempts in order."""
    router = Router(store, ModelRegistry([WEAK, STRONG]), TieredPolicy(),
                    RoutingConstraints())
    ctx = TaskContext(task_id=task_id, metadata={"features": dict(FEATS_PASSING)})
    cons = RoutingConstraints()
    for i, (mid, verified) in enumerate(script):
        d = router.route(ctx, cons, step_index=i, call_site="attempt")
        att = f"att-{task_id}-{i}"
        router.observe_invocation(
            d.decision_id, mid, task_id=task_id, attempt_id=att,
            input_tokens=100, output_tokens=10, latency_ms=100.0 * (i + 1),
            step_index=i, call_site="attempt")
        if verified is not None:
            from mril.core.events import VerificationStatus
            router.observe_verification(
                att,
                VerificationStatus.PASSED if verified
                else VerificationStatus.FAILED,
                task_id=task_id, verifier_type="test",
                verification_run_id=f"vr-{task_id}-{i}")
        # pin the actual model via route ctx feature? observe_invocation takes mid


def test_trainer_attempt_classes(tmp_path):
    store = SQLiteEventStore(tmp_path / "l.db")
    # task A: weak fails first, strong rescues
    _ledger_run(store, "ta", [("weak-coder", False), ("strong-coder", True)])
    # task B: weak passes outright
    _ledger_run(store, "tb", [("weak-coder", True)])
    # task C: strong fresh passes
    _ledger_run(store, "tc", [("strong-coder", True)])
    store.close()

    snap = fit(tmp_path / "l.db", weak_id="weak-coder", strong_id="strong-coder")
    # global weak first-attempt: 1 pass, 1 fail
    assert snap.beta["global"] == [1.0, 1.0]
    # Beta-smoothed toward 0.8 prior (m=3): (1+2.4)/(1+3)
    assert snap.cost_model["q_recovery"] == pytest.approx(0.85)
    assert snap.cost_model["q_fresh"] == pytest.approx(0.85)
    assert snap.trained_on_runs == 3


def test_trainer_ignores_post_escalation_as_weak_evidence(tmp_path):
    store = SQLiteEventStore(tmp_path / "l.db")
    # weak fails, strong rescues — weak bucket must get a FAILURE, not a pass
    _ledger_run(store, "ta", [("weak-coder", False), ("strong-coder", True)])
    store.close()
    snap = fit(tmp_path / "l.db", weak_id="weak-coder", strong_id="strong-coder")
    assert snap.beta["global"] == [0.0, 1.0]


def test_trainer_feature_buckets_from_taskstarted_metadata(tmp_path):
    store = SQLiteEventStore(tmp_path / "l.db")
    _ledger_run(store, "ta", [("weak-coder", False)])
    store.close()
    snap = fit(tmp_path / "l.db", weak_id="weak-coder", strong_id="strong-coder")
    # features recorded on TaskStarted -> feat buckets exist
    feat_keys = [k for k in snap.beta if k.startswith("feat:")]
    assert feat_keys, "expected feature buckets"
    assert snap.beta["feat:api_kind=class"] == [0.0, 1.0]


def test_trainer_uses_last_verdict_per_attempt(tmp_path):
    """A corrected verdict (failed then passed on a re-run verifier) trains
    on the LAST observation — matching rebuild_state, not the first."""
    store = SQLiteEventStore(tmp_path / "l.db")
    router = Router(store, ModelRegistry([WEAK, STRONG]), TieredPolicy(),
                    RoutingConstraints())
    ctx = TaskContext(task_id="tx")
    d = router.route(ctx, RoutingConstraints())
    router.observe_invocation(d.decision_id, "weak-coder", task_id="tx",
                              attempt_id="a1", input_tokens=1, output_tokens=1)
    from mril.core.events import VerificationStatus
    router.observe_verification("a1", VerificationStatus.FAILED, task_id="tx",
                                verification_run_id="r1")
    router.observe_verification("a1", VerificationStatus.PASSED, task_id="tx",
                                verification_run_id="r2")
    store.close()
    snap = fit(tmp_path / "l.db", weak_id="weak-coder", strong_id="strong-coder")
    assert snap.beta["global"] == [1.0, 0.0]


def test_fit_to_file(tmp_path):
    store = SQLiteEventStore(tmp_path / "l.db")
    _ledger_run(store, "ta", [("weak-coder", True)])
    store.close()
    from mril.eval.train import fit_to_file
    out = tmp_path / "snap.json"
    snap = fit_to_file(tmp_path / "l.db", out)
    snap2 = PolicySnapshot.from_dict(json.loads(out.read_text()))
    assert snap2.hash == snap.hash
