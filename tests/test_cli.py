"""CLI task-summary tests — everything derived from the ledger."""

from __future__ import annotations

import json

import pytest

from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints
from mril.cli import _task_summary, main
from mril.core.events import VerificationStatus
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore


@pytest.fixture
def ledger(tmp_path):
    """A task with a failed cheap attempt, an escalation, and a pass."""
    db = tmp_path / "ledger.db"
    reg = ModelRegistry(
        version="t1",
        models=(
            ModelSpec("weak", provider="p", tier="cheap",
                      input_price=0.10, output_price=0.30),
            ModelSpec("strong", provider="p", tier="frontier",
                      input_price=5.0, output_price=25.0),
        ),
    )
    store = SQLiteEventStore(str(db))
    r = Router(store=store, registry=reg, policy=TieredPolicy(),
               default_constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3))
    att1 = "a1"
    d1 = r.route(_ctx("t1"), step_index=0, call_site="model_call")
    r.observe_invocation(d1.decision_id, "weak", task_id="t1", attempt_id=att1,
                         input_tokens=100, output_tokens=50, step_index=0,
                         call_site="model_call")
    r.observe_verification(att1, VerificationStatus.FAILED, task_id="t1",
                           verifier_type="test", failure_category="test_failure")
    act = r.next_action("t1")
    assert act.type.value == "escalate" and act.model_id == "strong"
    att2 = "a2"
    d2 = r.route(_ctx("t1"), step_index=0, call_site="model_call")
    r.observe_invocation(d2.decision_id, "strong", task_id="t1", attempt_id=att2,
                         input_tokens=120, output_tokens=60, step_index=0,
                         call_site="model_call")
    r.observe_verification(att2, VerificationStatus.PASSED, task_id="t1",
                           verifier_type="test")
    r.finalize("t1")
    store.close()
    return db


def _ctx(task_id):
    from mril.core.task import TaskContext

    return TaskContext(task_id=task_id, task_type="feature", scope="single_file",
                       risk="low", language="python")


def test_task_summary_groups_attempts_and_recovery(ledger):
    store = SQLiteEventStore(str(ledger))
    s = _task_summary("t1", store.events_for_task("t1"))
    store.close()

    assert s["outcome"] == "verified_success" and s["finalized"]
    assert len(s["attempts"]) == 2
    a1, a2 = s["attempts"]
    assert a1["model_id"] == "weak" and a1["verification_status"] == "failed"
    assert a1["failure_category"] == "test_failure"
    assert a1["cost_usd"] == pytest.approx((100 * 0.10 + 50 * 0.30) / 1e6)
    assert a2["model_id"] == "strong" and a2["verification_status"] == "passed"
    assert len(s["recoveries"]) == 1
    rec = s["recoveries"][0]
    assert rec["action"] == "escalate" and rec["model_id"] == "strong"
    assert rec["after_attempt_id"] == a1["attempt_id"]
    assert a1["decision_ids"] and a2["decision_ids"]


def test_cmd_task_prints_summary(ledger, capsys):
    rc = main(["--db", str(ledger), "task", "t1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "VERIFIED_SUCCESS" in out
    assert "ATTEMPT 1" in out and "ATTEMPT 2" in out
    assert "weak" in out and "strong" in out
    assert "escalate -> strong" in out
    assert "FAILED (test_failure)" in out and "PASSED" in out
    assert "mril explain" in out


def test_cmd_task_json_roundtrip(ledger, capsys):
    rc = main(["--db", str(ledger), "task", "t1", "--json"])
    assert rc == 0
    s = json.loads(capsys.readouterr().out)
    assert s["task_id"] == "t1" and s["outcome"] == "verified_success"
    assert [a["model_id"] for a in s["attempts"]] == ["weak", "strong"]


def test_cmd_task_missing(ledger, capsys):
    assert main(["--db", str(ledger), "task", "nope"]) == 1
    assert "no events" in capsys.readouterr().err


def test_cmd_task_timeline_still_available(ledger, capsys):
    rc = main(["--db", str(ledger), "task", "t1", "--timeline"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "route_decided" in out and "task_finalized" in out


# --- audit-projection edge cases ---------------------------------------------


def _store_with_events(tmp_path, events):
    db = tmp_path / "audit.db"
    store = SQLiteEventStore(str(db))
    for e in events:
        store.append(e)
    return store


def test_recovery_attributed_via_recorded_context_not_position(tmp_path):
    """Interleaved concurrent attempts: a recovery committed after attempt B's
    events but *about* attempt A must attribute to A via recovery_context."""
    from mril.core.events import ModelInvocationFinished, RecoveryDecided

    store = _store_with_events(
        tmp_path,
        [
            ModelInvocationFinished(task_id="t", attempt_id="att-A",
                                    model_id="weak", step_index=0),
            ModelInvocationFinished(task_id="t", attempt_id="att-B",
                                    model_id="weak", step_index=0),
            # committed last in ledger order, but its recorded context names A
            RecoveryDecided(
                task_id="t", action="escalate", model_id="strong",
                reason="test", dedupe_key="rec:t:x",
                recovery_context={"last_attempt_id": "att-A"},
            ),
        ],
    )
    s = _task_summary("t", store.events_for_task("t"))
    store.close()
    assert s["recoveries"][0]["after_attempt_id"] == "att-A"
    assert s["recoveries"][0]["attribution"] == "recorded"


def test_recovery_without_context_is_labeled_inferred(tmp_path, capsys):
    from mril.core.events import ModelInvocationFinished, RecoveryDecided

    store = _store_with_events(
        tmp_path,
        [
            ModelInvocationFinished(task_id="t", attempt_id="att-A",
                                    model_id="weak", step_index=0),
            RecoveryDecided(task_id="t", action="retry", reason="x",
                            dedupe_key="rec:t:y"),
        ],
    )
    s = _task_summary("t", store.events_for_task("t"))
    store.close()
    assert s["recoveries"][0]["attribution"] == "inferred"
    assert s["recoveries"][0]["after_attempt_id"] == "att-A"
    main(["--db", str(tmp_path / "audit.db"), "task", "t"])
    assert "inferred from ledger order" in capsys.readouterr().out


def test_orphan_route_decision_is_surfaced(tmp_path, capsys):
    """A route_decided that never produced an invocation must appear in the
    audit view — silence would hide a crash between route and observe."""
    from mril.core.events import RouteDecided

    store = _store_with_events(
        tmp_path,
        [
            RouteDecided(task_id="t", decision_id="dec-orphan", model_id="weak",
                         step_index=0, call_site="model_call", reason="test"),
        ],
    )
    s = _task_summary("t", store.events_for_task("t"))
    store.close()
    assert len(s["orphan_decisions"]) == 1
    assert s["orphan_decisions"][0]["decision_id"] == "dec-orphan"

    main(["--db", str(tmp_path / "audit.db"), "task", "t"])
    assert "never invoked" in capsys.readouterr().out


def test_recovery_with_no_prior_attempt_is_unresolved(tmp_path, capsys):
    from mril.core.events import RecoveryDecided

    store = _store_with_events(
        tmp_path,
        [RecoveryDecided(task_id="t", action="stop", reason="x",
                         dedupe_key="rec:t:z")],
    )
    s = _task_summary("t", store.events_for_task("t"))
    store.close()
    assert s["recoveries"][0]["after_attempt_id"] is None
    main(["--db", str(tmp_path / "audit.db"), "task", "t"])
    assert "UNRESOLVED" in capsys.readouterr().out
