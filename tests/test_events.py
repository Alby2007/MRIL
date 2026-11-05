import pytest

from mril.core.events import (
    SCHEMA_VERSION,
    ModelInvocationFinished,
    RouteDecided,
    TaskFinalized,
    TaskOutcome,
    TaskStarted,
    VerificationCompleted,
    VerificationStatus,
    event_from_dict,
)


def test_round_trip_all_event_types():
    events = [
        TaskStarted(task_id="t1", task_type="bug_fix", scope="single_file"),
        RouteDecided(task_id="t1", decision_id="d1", model_id="m1",
                     policy_name="tiered", policy_version="0.1.0",
                     decision_seed=42, candidates=["m1", "m2"],
                     price_snapshot={"m1": {"input_price": 1.0}}),
        ModelInvocationFinished(task_id="t1", attempt_id="a1", decision_id="d1",
                                model_id="m1", input_tokens=100, output_tokens=50,
                                cost_usd=0.001),
        VerificationCompleted(task_id="t1", attempt_id="a1",
                              status=VerificationStatus.FAILED,
                              verifier_type="test", failure_category="test_failure"),
        TaskFinalized(task_id="t1", task_outcome=TaskOutcome.VERIFIED_FAILURE,
                      total_cost_usd=0.5, attempt_count=3),
    ]
    for e in events:
        restored = event_from_dict(e.to_dict())
        assert restored == e
        assert restored.event_type == e.event_type
        assert restored.schema_version == SCHEMA_VERSION


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError, match="unknown event_type"):
        event_from_dict({"event_type": "made_up"})


def test_enums_survive_serialization():
    e = event_from_dict(
        TaskFinalized(task_id="t", task_outcome=TaskOutcome.VERIFIED_SUCCESS).to_dict()
    )
    assert e.task_outcome is TaskOutcome.VERIFIED_SUCCESS


def test_event_ids_unique():
    assert TaskStarted(task_id="t").event_id != TaskStarted(task_id="t").event_id
