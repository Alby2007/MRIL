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


def test_zero_cache_read_is_reported_not_dropped(registry):
    """cache_read=0 is a real cold-cache miss — exactly what the first call
    after a model switch reports. Only None means 'provider didn't say'."""
    router, mw = make_middleware(registry)

    class ColdCacheResponse:
        usage_metadata = {"input_tokens": 5000, "output_tokens": 100,
                          "input_token_details": {"cache_read": 0}}

    mw.wrap_model_call(FakeRequest("m"), lambda r: ColdCacheResponse())
    inv = next(e for e in router.store.events_for_task("sess-1")
               if e.event_type == "model_invocation_finished")
    assert inv.cached_input_tokens == 0


def test_api_error_recorded(registry):
    router, mw = make_middleware(registry)

    def handler(request):
        raise RuntimeError("rate limited")

    with pytest.raises(RuntimeError):
        mw.wrap_model_call(FakeRequest("m"), handler)
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert "rate limited" in invs[0].api_error


def test_default_task_id_scoped_per_run(registry):
    """Without task_id=, each agent run is its own task — unrelated sessions
    must not collapse into one shared 'agent-session' task."""
    router = Router(store=MemoryEventStore(), registry=registry,
                    policy=TieredPolicy())
    mw = MRILMiddleware(router, {"cheap-8b": "M"})  # no task_id
    for _ in range(2):
        mw.before_agent()
        mw.wrap_model_call(FakeRequest("m"), lambda r: FakeResponse())
    tids = {e.task_id for e in router.store.all_events()
            if e.event_type == "model_invocation_finished"}
    assert len(tids) == 2
    assert all(t.startswith("agent-session-") for t in tids)


def test_runs_isolate_attempt_and_step_state(registry):
    """A second before_agent starts a fresh attempt at step 0 — sequential
    runs on one middleware don't bleed counters."""
    router, mw = make_middleware(registry)
    mw.before_agent()
    mw.wrap_model_call(FakeRequest("m"), lambda r: FakeResponse())
    mw.before_agent()
    mw.wrap_model_call(FakeRequest("m"), lambda r: FakeResponse())
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert len({e.attempt_id for e in invs}) == 2
    assert [e.step_index for e in invs] == [0, 0]


def test_observe_failure_does_not_break_call(registry):
    """A dead store must not mask the handler's real result — telemetry is
    best-effort, never blocking."""
    router, mw = make_middleware(registry)

    def boom(*a, **k):
        raise RuntimeError("db gone")

    router.observe_invocation = boom
    resp = mw.wrap_model_call(FakeRequest("m"), lambda r: FakeResponse())
    assert resp.usage_metadata is not None


def test_fixed_task_id_with_state_task_id_no_crash(registry):
    """state carrying task_id plus task_id= must not double-bind TaskContext —
    the fixed id wins."""
    router, mw = make_middleware(registry)
    req = FakeRequest("m", state={"task_id": "from-state"})
    mw.wrap_model_call(req, lambda r: FakeResponse())
    assert router.store.events_for_task("sess-1")


def test_concurrent_async_runs_isolate_state(registry):
    """Two concurrent runs on one middleware instance: separate attempts,
    steps, and tasks — the isolation create_agent.ainvoke() relies on."""
    import asyncio
    router = Router(store=MemoryEventStore(), registry=registry,
                    policy=TieredPolicy())
    mw = MRILMiddleware(router, {"cheap-8b": "M"})

    async def handler(request):
        await asyncio.sleep(0)  # force interleaving
        return FakeResponse()

    async def session():
        mw.before_agent()
        for _ in range(3):
            await mw.awrap_model_call(FakeRequest("m"), handler)

    async def main():
        await asyncio.gather(session(), session())

    asyncio.run(main())
    by_task: dict[str, list] = {}
    for e in router.store.all_events():
        if e.event_type == "model_invocation_finished":
            by_task.setdefault(e.task_id, []).append(e)
    assert len(by_task) == 2
    for invs in by_task.values():
        assert len({e.attempt_id for e in invs}) == 1
        assert sorted(e.step_index for e in invs) == [0, 1, 2]


def test_spawned_child_tasks_share_attempt_not_steps(registry):
    """Hooks inside spawned tasks share the run's attempt (contextvars
    propagate in) but draw DISTINCT steps — a context-local counter would
    give siblings identical step_indexes and silently dedupe real calls."""
    import asyncio
    router, mw = make_middleware(registry)

    async def handler(request):
        await asyncio.sleep(0)
        return FakeResponse()

    async def child():
        await mw.awrap_model_call(FakeRequest("m"), handler)

    async def main():
        mw.before_agent()
        await asyncio.gather(child(), child())
        await mw.awrap_model_call(FakeRequest("m"), handler)

    asyncio.run(main())
    invs = [e for e in router.store.events_for_task("sess-1")
            if e.event_type == "model_invocation_finished"]
    assert len(invs) == 3  # no sibling collapsed by the dedupe key
    assert sorted(e.step_index for e in invs) == [0, 1, 2]
    assert len({e.attempt_id for e in invs}) == 1


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
