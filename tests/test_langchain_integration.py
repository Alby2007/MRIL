"""Real LangChain middleware-path tests.

These exercise the actual create_agent().ainvoke() lifecycle — before_agent,
awrap_model_call, after_agent — not the unit-level call surface. Skipped
without the `langchain` extra; the offline suite must not require it.
"""

from __future__ import annotations

import asyncio
import itertools
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import os

import pytest

if os.environ.get("MRIL_REQUIRE_LANGCHAIN"):
    # CI gate: the integration job must RUN these tests, not skip them.
    import langchain.agents  # noqa: F401
else:
    pytest.importorskip("langchain.agents")

from langchain.agents import create_agent  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    FakeListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints  # noqa: E402
from mril.adapters.langchain import MRILMiddleware  # noqa: E402
from mril.core.decision import RecoveryType  # noqa: E402
from mril.core.events import TaskOutcome, VerificationStatus  # noqa: E402
from mril.policy.tiered import TieredPolicy  # noqa: E402
from mril.store.memory import MemoryEventStore  # noqa: E402


class _ScriptedToolModel(GenericFakeChatModel):
    """GenericFakeChatModel that accepts bind_tools — the agent factory
    calls request.model.bind_tools() whenever the graph has tools."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        return self


def _registry() -> ModelRegistry:
    return ModelRegistry(
        version="it-1",
        models=(
            ModelSpec("weak-coder", provider="local", tier="cheap",
                      input_price=0.10, output_price=0.30),
            ModelSpec("strong-coder", provider="local", tier="frontier",
                      input_price=5.00, output_price=25.00),
        ),
    )


def _router() -> Router:
    return Router(
        store=MemoryEventStore(),
        registry=_registry(),
        policy=TieredPolicy(),
        default_constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
    )


def _mw(router, models, **kw) -> MRILMiddleware:
    return MRILMiddleware(
        router,
        models,
        constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
        feature_extractor=lambda req: {"task_type": "feature", "scope": "single_file",
                                       "language": "python", "harness": "it"},
        **kw,
    )


def _events(router, task_id, event_type):
    return [e for e in router.store.events_for_task(task_id)
            if e.event_type == event_type]


def _task_ids(router) -> set[str]:
    return {e.task_id for e in router.store.all_events()
            if getattr(e, "task_id", None)}


class TestConcurrentAinvoke:
    def test_two_concurrent_invocations_distinct_tasks_and_attempts(self):
        """Two in-flight ainvoke() runs must not share run state."""
        router = _router()
        mw = _mw(router, {"weak-coder": FakeListChatModel(responses=["a"]),
                          "strong-coder": FakeListChatModel(responses=["b"])})
        agent = create_agent(model=FakeListChatModel(responses=["x"]),
                             middleware=[mw])

        async def go():
            return await asyncio.gather(
                agent.ainvoke({"messages": [HumanMessage("hi")]}),
                agent.ainvoke({"messages": [HumanMessage("hi")]}),
            )

        r1, r2 = asyncio.run(go())
        assert r1["messages"][-1].content and r2["messages"][-1].content

        task_ids = _task_ids(router)
        assert len(task_ids) == 2  # no fixed task_id → one task per run
        for tid in task_ids:
            invs = _events(router, tid, "model_invocation_finished")
            routes = _events(router, tid, "route_decided")
            assert len(invs) == 1 and len(routes) == 1
            assert invs[0].task_id == tid == routes[0].task_id
        # attempts are distinct across the two runs
        attempt_ids = {i.attempt_id for tid in task_ids
                       for i in _events(router, tid, "model_invocation_finished")}
        assert len(attempt_ids) == 2

    def test_shared_task_id_concurrent_runs_distinct_attempts(self):
        """Explicit task_id: same task, but each run is its own attempt."""
        router = _router()
        mw = _mw(router, {"weak-coder": FakeListChatModel(responses=["a"]),
                          "strong-coder": FakeListChatModel(responses=["b"])},
                 task_id="shared-task")
        agent = create_agent(model=FakeListChatModel(responses=["x"]),
                             middleware=[mw])

        async def go():
            return await asyncio.gather(
                agent.ainvoke({"messages": [HumanMessage("hi")]}),
                agent.ainvoke({"messages": [HumanMessage("hi")]}),
            )

        asyncio.run(go())

        assert _task_ids(router) == {"shared-task"}
        invs = _events(router, "shared-task", "model_invocation_finished")
        assert len(invs) == 2
        assert len({i.attempt_id for i in invs}) == 2
        assert all(i.step_index == 0 for i in invs)

    def test_multi_call_attempt_has_distinct_steps(self):
        """Tool-call loop: one attempt, several model calls, unique steps."""
        router = _router()

        @tool
        def lookup(q: str) -> str:
            """Look up a fact."""
            return "42"

        scripted = _ScriptedToolModel(messages=itertools.chain(
            [AIMessage(content="", tool_calls=[
                {"name": "lookup", "args": {"q": "x"}, "id": "call_1"}])],
            itertools.repeat(AIMessage(content="the answer is 42")),
        ))
        mw = _mw(router, {"weak-coder": scripted, "strong-coder": scripted},
                 task_id="tool-task")
        agent = create_agent(model=scripted, tools=[lookup], middleware=[mw])

        result = asyncio.run(agent.ainvoke({"messages": [HumanMessage("go")]}))
        assert "42" in result["messages"][-1].content

        invs = _events(router, "tool-task", "model_invocation_finished")
        assert len(invs) == 2
        assert len({i.attempt_id for i in invs}) == 1  # one attempt, two calls
        assert sorted(i.step_index for i in invs) == [0, 1]

    def test_step_counter_freed_after_run(self):
        """The per-attempt allocator must not retain counters for done runs."""
        router = _router()
        mw = _mw(router, {"weak-coder": FakeListChatModel(responses=["a"]),
                          "strong-coder": FakeListChatModel(responses=["b"])},
                 task_id="cleanup-task")
        agent = create_agent(model=FakeListChatModel(responses=["x"]),
                             middleware=[mw])
        asyncio.run(agent.ainvoke({"messages": [HumanMessage("hi")]}))

        invs = _events(router, "cleanup-task", "model_invocation_finished")
        assert invs and invs[0].attempt_id not in mw._steps


TEST_SRC = textwrap.dedent(
    """
    from solution import add

    assert add(2, 3) == 5
    """
)


class TestVerifiedEscalation:
    def _verify(self, workdir: Path) -> bool | None:
        solution = workdir / "solution.py"
        if not solution.exists():
            return None
        (workdir / "test_solution.py").write_text(TEST_SRC, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "test_solution.py"],
            cwd=workdir, capture_output=True, text=True, timeout=120,
        )
        return proc.returncode == 0

    def test_failure_escalates_to_frontier_and_verifies(self):
        """The full loop: cheap attempt fails pytest → escalate → verified."""
        router = _router()
        buggy = "def add(a: int, b: int) -> int:\n    return a - b\n"
        fixed = "def add(a: int, b: int) -> int:\n    return a + b\n"
        mw = _mw(
            router,
            {"weak-coder": FakeListChatModel(responses=[buggy]),
             "strong-coder": FakeListChatModel(responses=[fixed])},
            task_id="esc-task",
        )
        agent = create_agent(
            model=FakeListChatModel(responses=["should be overridden"]),
            middleware=[mw],
        )
        workdir = Path(tempfile.mkdtemp(prefix="mril-it-"))
        solution = workdir / "solution.py"

        async def attempt() -> bool | None:
            solution.unlink(missing_ok=True)
            # kill stale bytecode so this attempt's artifact is verified
            shutil.rmtree(workdir / "__pycache__", ignore_errors=True)
            result = await agent.ainvoke({"messages": [HumanMessage("go")]})
            content = result["messages"][-1].content
            if isinstance(content, str) and content.strip():
                solution.write_text(content.strip() + "\n", encoding="utf-8")
            passed = self._verify(workdir)
            invs = _events(router, "esc-task", "model_invocation_finished")
            mw.report_verification(
                invs[-1].attempt_id, passed, verifier_type="test",
                failure_category=None if passed else "test_failure",
                task_id="esc-task",
            )
            return passed

        async def run() -> None:
            for _ in range(3):
                passed = await attempt()
                if passed is True:
                    break
                action = router.next_action("esc-task")
                if action.type is RecoveryType.STOP:
                    break
                if action.model_id:
                    mw.constraints = RoutingConstraints(
                        allowed_models=(action.model_id,),
                        budget_usd=1.0, max_attempts=3,
                    )
            router.finalize("esc-task")

        asyncio.run(run())

        events = router.store.events_for_task("esc-task")
        routes = [e.model_id for e in events if e.event_type == "route_decided"]
        verdicts = [e.status for e in events
                    if e.event_type == "verification_completed"]
        recoveries = [e.action for e in events
                      if e.event_type == "recovery_decided"]

        # cheap first, failed, escalated to frontier, then verified
        assert routes[0] == "weak-coder" and routes[-1] == "strong-coder"
        assert verdicts == [VerificationStatus.FAILED, VerificationStatus.PASSED]
        assert "escalate" in recoveries
        fin = [e for e in events if e.event_type == "task_finalized"][-1]
        assert fin.task_outcome is TaskOutcome.VERIFIED_SUCCESS
        # the middleware really overrode the agent's default model
        attempt_ids = {e.attempt_id for e in events
                       if e.event_type == "model_invocation_finished"}
        assert len(attempt_ids) == 2


class TestObservationFailure:
    def test_observe_error_does_not_mask_result(self):
        """A store failure inside observation must not replace the result."""
        router = _router()
        mw = _mw(router, {"weak-coder": FakeListChatModel(responses=["ok"]),
                          "strong-coder": FakeListChatModel(responses=["ok"])},
                 task_id="obs-task")
        agent = create_agent(model=FakeListChatModel(responses=["x"]),
                             middleware=[mw])

        def boom(*a, **k):
            raise RuntimeError("store exploded")

        router.observe_invocation = boom  # type: ignore[method-assign]
        result = asyncio.run(agent.ainvoke({"messages": [HumanMessage("hi")]}))
        assert result["messages"][-1].content == "ok"
