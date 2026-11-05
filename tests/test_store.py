import pytest

from mril.core.events import ModelInvocationFinished, RouteDecided, TaskStarted
from mril.store.memory import MemoryEventStore
from mril.store.sqlite import SQLiteEventStore


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = SQLiteEventStore(tmp_path / "ledger.db")
    else:
        s = MemoryEventStore()
    yield s
    s.close()


def test_append_is_idempotent(store):
    e = TaskStarted(task_id="t1", event_id="fixed-id")
    assert store.append(e) is True
    assert store.append(e) is False  # duplicate event_id ignored
    assert len(store.events_for_task("t1")) == 1


def test_events_for_task_ordered(store):
    store.append(TaskStarted(task_id="t1"))
    store.append(RouteDecided(task_id="t1", decision_id="d1", model_id="m"))
    store.append(TaskStarted(task_id="t2"))
    store.append(ModelInvocationFinished(task_id="t1", attempt_id="a1",
                                         decision_id="d1", model_id="m"))
    events = store.events_for_task("t1")
    assert [e.event_type for e in events] == [
        "task_started", "route_decided", "model_invocation_finished",
    ]


def test_events_for_decision(store):
    store.append(RouteDecided(task_id="t1", decision_id="d1"))
    store.append(ModelInvocationFinished(task_id="t1", decision_id="d1", attempt_id="a"))
    store.append(RouteDecided(task_id="t1", decision_id="d2"))
    assert len(store.events_for_decision("d1")) == 2
    assert len(store.events_for_decision("d2")) == 1


def test_sqlite_persists(tmp_path):
    path = tmp_path / "ledger.db"
    s1 = SQLiteEventStore(path)
    s1.append(TaskStarted(task_id="t1"))
    s1.close()
    s2 = SQLiteEventStore(path)
    assert len(s2.events_for_task("t1")) == 1
    s2.close()
