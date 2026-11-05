"""LangChain / Deep Agents adapter.

Implements the middleware protocol (`before_agent`, `wrap_model_call`,
`awrap_model_call`, `after_agent`) without importing LangChain at module load —
the SDK's policy engine stays framework-neutral, and this file degrades
gracefully when LangChain isn't installed.

Per-call routing is supported: `wrap_model_call` routes each model invocation
(step-level), not just the task as a whole.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from mril.core.events import TaskOutcome, VerificationStatus, new_event_id
from mril.core.task import RoutingConstraints, TaskContext
from mril.sdk import Router

try:  # subclassing is required for create_agent to discover the hooks
    from langchain.agents.middleware import AgentMiddleware as _Base
except Exception:  # LangChain not installed — still importable, still testable
    _Base = object

FeatureExtractor = Callable[[Any], dict]
ModelResolver = Callable[[str], Any]


def _default_features(request: Any) -> dict:
    """Extract best-effort task features from a LangChain ModelRequest."""
    state = getattr(request, "state", None) or {}
    feats: dict[str, Any] = {}
    for key in ("task_id", "language", "task_type", "scope", "risk", "harness"):
        val = state.get(key) if isinstance(state, Mapping) else getattr(state, key, None)
        if val is not None:
            feats[key] = val
    return feats


class MRILMiddleware(_Base):
    """Drop-in LangChain middleware driven by an MRIL Router.

    models: mapping from registry model_id -> LangChain chat model instance
    (or a resolver callable model_id -> model). The adapter only *selects*;
    the harness still owns credentials, transport, and execution.
    """

    def __init__(
        self,
        router: Router,
        models: Mapping[str, Any] | ModelResolver,
        *,
        constraints: RoutingConstraints | None = None,
        feature_extractor: FeatureExtractor | None = None,
        task_id: str | None = None,
    ) -> None:
        self.router = router
        self._models = models
        self.constraints = constraints
        self.extract_features = feature_extractor or _default_features
        self._fixed_task_id = task_id
        self._step = 0
        self._attempt_id: str | None = None

    # -- lifecycle -----------------------------------------------------------

    def before_agent(self, state: Any = None, runtime: Any = None) -> None:
        # One agent run == one MRIL attempt. All model calls in this run share
        # the attempt_id; their invocations are steps within it. (TaskStarted
        # itself is emitted lazily by Router.route().)
        self._attempt_id = new_event_id()
        self._step = 0
        return None

    async def abefore_agent(self, state: Any = None, runtime: Any = None) -> None:
        return self.before_agent(state, runtime)

    # NOTE: no after_agent finalization. An MRIL *task* spans multiple agent
    # invocations (attempt -> escalate -> retry); the driver — not the graph —
    # decides when it's done and calls router.finalize(). Auto-finalizing here
    # would close the task before recovery can run.

    # -- model-call interception ----------------------------------------------

    def wrap_model_call(self, request: Any, handler: Callable) -> Any:
        request, decision = self._route(request)
        started = time.monotonic()
        response, api_error = None, None
        try:
            response = handler(request)
            return response
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._observe(decision, response, started, api_error)

    async def awrap_model_call(self, request: Any, handler: Callable) -> Any:
        request, decision = self._route(request)
        started = time.monotonic()
        response, api_error = None, None
        try:
            response = await handler(request)
            return response
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._observe(decision, response, started, api_error)

    # -- extern: the harness reports verification when it has evidence ----------

    def report_verification(
        self,
        attempt_id: str,
        passed: bool | None,
        *,
        verifier_type: str = "test",
        failure_category: str | None = None,
        task_id: str | None = None,
        verification_run_id: str | None = None,
    ) -> None:
        status = (
            VerificationStatus.PASSED
            if passed is True
            else VerificationStatus.FAILED
            if passed is False
            else VerificationStatus.INCONCLUSIVE
        )
        self.router.observe_verification(
            attempt_id,
            status,
            task_id=task_id,
            verifier_type=verifier_type,
            failure_category=failure_category,
            verification_run_id=verification_run_id,
        )

    # -- internals --------------------------------------------------------------

    def _route(self, request: Any):
        feats = self.extract_features(request)
        task_id = self._fixed_task_id or feats.pop("task_id", None) or "agent-session"
        ctx = TaskContext(task_id=task_id, **feats)
        step = self._step
        self._step += 1
        decision = self.router.route(ctx, self.constraints, step_index=step, call_site="model_call")
        model = self._resolve(decision.model_id)
        if model is not None and hasattr(request, "override"):
            request = request.override(model=model)
        return request, decision

    def _observe(self, decision, response: Any, started: float, api_error: str | None) -> None:
        usage = _extract_usage(response)
        if self._attempt_id is None:  # wrapped outside an agent run
            self._attempt_id = new_event_id()
        self.router.observe_invocation(
            decision.decision_id,
            decision.model_id,
            task_id=decision.task_id,
            attempt_id=self._attempt_id,
            input_tokens=_usage_get(usage, "input_tokens"),
            output_tokens=_usage_get(usage, "output_tokens"),
            cached_input_tokens=_usage_get(
                usage, "input_token_details", nested="cache_read"
            ) or _usage_get(usage, "cached_input_tokens"),
            latency_ms=(time.monotonic() - started) * 1000,
            api_error=api_error,
            step_index=decision.step_index,
            call_site=decision.call_site,
        )

    def _resolve(self, model_id: str) -> Any:
        if callable(self._models):
            return self._models(model_id)
        return self._models.get(model_id)


def _extract_usage(response: Any) -> Any:
    """Pull usage_metadata off whatever the handler returned.

    LangChain 1.x handlers may return a ModelResponse (whose `.result` is a
    list of BaseMessage) or an AIMessage directly; usage_metadata lives on the
    AI message in both cases.
    """
    if response is None:
        return None
    if getattr(response, "usage_metadata", None) is not None:
        return response.usage_metadata
    result = getattr(response, "result", None)
    if isinstance(result, (list, tuple)):
        for msg in result:
            if getattr(msg, "usage_metadata", None) is not None:
                return msg.usage_metadata
    elif getattr(result, "usage_metadata", None) is not None:
        return result.usage_metadata
    return None


def _usage_get(usage: Any, key: str, nested: str | None = None) -> int | None:
    if usage is None:
        return None
    val = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
    if nested and isinstance(val, Mapping):
        val = val.get(nested)
    elif nested and val is not None:
        val = getattr(val, nested, None)
    return val if isinstance(val, int) else None


def to_outcome(passed: bool | None) -> TaskOutcome:
    if passed is True:
        return TaskOutcome.VERIFIED_SUCCESS
    if passed is False:
        return TaskOutcome.VERIFIED_FAILURE
    return TaskOutcome.INCONCLUSIVE
