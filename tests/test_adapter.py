"""Adapter tests with duck-typed fakes — no LangChain install required."""

import pytest

from mril import Router, RoutingConstraints, TaskContext
from mril.adapters.langchain import MRILMiddleware
from mril.core.events import TaskOutcome
from mril.policy.tiered import TieredPolicy
from mril.store.memory import MemoryEventStore


class FakeRequest:
    def __init__(self, model, state=None):
        self.model = model
        self.state = state or {}

    def override(self, **kw):
        new = FakeRequest(self.model, self.state)
        new.__dict__.update(kw)
        for k, v in kw.items():
            setattr(new, k, v)
        return new


class FakeResponse:
    def __init__(self):
        self.usage_metadata = {"input_tokens": 5000, "output_tokens": 1200}


def make_middleware(registry):
    router = Router(
        store=MemoryEventStore(),
        registry=registry,
        policy=TieredPolicy(),
        default_constraints=RoutingConstraints(budget_usd=1.0),
    )
    return router, MRILMiddleware(
        router,
        {"cheap-8b": "MODEL_cheap", "balanced-70b": "MODEL_balanced",
         "frontier-x": "MODEL_frontier"},
        task_id="sess-1",
    )


def test_wrap_model_call_routes_and_observes(registry):
    router, mw = make_middleware(registry)
    req = FakeRequest("default-model", state={"scope": "single_file", "risk": "low"})

    seen = {}

    def handler(request):
        seen["model"] = request.model
        return FakeResponse()

    resp = mw.wrap_model_call(req, handler)
    assert seen["model"] == "MODEL_cheap"
    assert resp.usage_metadata["input_tokens"] == 5000

    events = router.store.events_for_task("sess-1")
    types = [e.event_type for e in events]
    assert "task_started" in types
    assert "route_decided" in types
    assert "model_invocation_finished" in types
    inv = next(e for e in events if e.event_type == "model_invocation_finished")
    assert inv.input_tokens == 5000
    assert inv.step_index == 0


def test_step_index_increments(registry):
    router, mw = make_middleware(registry)

    def handler(request):
        return FakeResponse()

    mw.wrap_model_call(FakeRequest("m"), handler)
    mw.wrap_model_call(FakeRequest("m"), handler)
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert [e.step_index for e in invs] == [0, 1]


def test_api_error_recorded(registry):
    router, mw = make_middleware(registry)

    def handler(request):
        raise RuntimeError("rate limited")

    with pytest.raises(RuntimeError):
        mw.wrap_model_call(FakeRequest("m"), handler)
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert "rate limited" in invs[0].api_error


def test_report_verification_flows_to_ledger(registry):
    router, mw = make_middleware(registry)

    def handler(request):
        return FakeResponse()

    mw.wrap_model_call(FakeRequest("m"), handler)
    inv = next(e for e in router.store.events_for_task("sess-1")
               if e.event_type == "model_invocation_finished")
    mw.report_verification(inv.attempt_id, True, task_id="sess-1")
    fin = router.finalize("sess-1")
    assert fin.task_outcome == TaskOutcome.VERIFIED_SUCCESS


def test_async_wrap(registry):
    import asyncio

    router, mw = make_middleware(registry)

    async def handler(request):
        return FakeResponse()

    resp = asyncio.run(mw.awrap_model_call(FakeRequest("m"), handler))
    assert resp.usage_metadata is not None
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert len(invs) == 1
