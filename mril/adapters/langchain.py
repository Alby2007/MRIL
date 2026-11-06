"""LangChain / Deep Agents adapter.

Implements the middleware protocol (`before_agent`, `wrap_model_call`,
`awrap_model_call`, `after_agent`) without importing LangChain at module load —
the SDK's policy engine stays framework-neutral, and this file degrades
gracefully when LangChain isn't installed.

Per-call routing is supported: `wrap_model_call` routes each model invocation
(step-level), not just the task as a whole.
"""

from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar
from typing import Any, Callable, Mapping

from mril.core.events import TaskOutcome, VerificationStatus, new_event_id
from mril.core.task import RoutingConstraints, TaskContext
from mril.sdk import Router

try:  # subclassing is required for create_agent to discover the hooks
    from typing import Annotated, NotRequired

    from langchain.agents.middleware import AgentMiddleware as _Base
    from langchain.agents.middleware.types import AgentState, PrivateStateAttr
except Exception:  # LangChain not installed — still importable, still testable
    _Base = object
    _MRILState = None
else:

    class _MRILState(AgentState):
        """Private per-run identity carried through the agent graph.

        LangGraph executes each middleware hook in its own async task, so
        ContextVar writes in ``before_agent`` are invisible to the sibling
        task running ``wrap_model_call``. Private state keys are merged into
        the agent state instead — the only channel that reliably reaches
        every hook within a run (and never crosses between runs).
        """

        mril_task_id: NotRequired[Annotated[str, PrivateStateAttr]]
        mril_attempt_id: NotRequired[Annotated[str, PrivateStateAttr]]

FeatureExtractor = Callable[[Any], dict]
ModelResolver = Callable[[str], Any]

_log = logging.getLogger(__name__)


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

    Task identity: pass ``task_id=`` (or expose ``task_id`` in state for the
    feature extractor) when a task should span multiple agent runs —
    escalation/retries across invokes live on one task. Without it, each
    agent run is its own ``agent-session-*`` task; unrelated sessions must
    never collapse into one shared task.

    Per-run identity rides in private middleware state
    (``mril_task_id``/``mril_attempt_id``), so concurrent agent runs sharing
    this middleware instance cannot race each other's attempt/step ids;
    contextvars cover calls made outside a real agent run.
    """

    if _Base is not object:
        state_schema = _MRILState

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
        self._attempt_id: ContextVar[str | None] = ContextVar(
            "mril_attempt_id", default=None
        )
        self._run_task_id: ContextVar[str | None] = ContextVar(
            "mril_run_task_id", default=None
        )
        # Step allocation is shared per-attempt, NOT per-context: contextvars
        # copy into spawned child tasks, so a context-local counter would give
        # siblings the same step_index — collapsing distinct calls under the
        # (attempt, step, call_site) dedupe key. attempt_id -> next step.
        self._steps: dict[str, int] = {}
        self._step_lock = threading.Lock()
        if _Base is object:
            _log.warning(
                "langchain is not installed — MRILMiddleware still works "
                "standalone, but create_agent will not discover its hooks; "
                "install with `pip install mril[langchain]`"
            )

    # -- lifecycle -----------------------------------------------------------

    def before_agent(self, state: Any = None, runtime: Any = None):
        # One agent run == one MRIL attempt. All model calls in this run share
        # the attempt_id; their invocations are steps within it. (TaskStarted
        # itself is emitted lazily by Router.route().)
        # The returned dict merges into private middleware state so the
        # sibling-task wrap_model_call hooks can see this run's identity.
        prev = self._attempt_id.get()
        if prev is not None:
            self._steps.pop(prev, None)
        attempt_id = new_event_id()
        self._attempt_id.set(attempt_id)
        self._steps[attempt_id] = 0
        task_id = self._fixed_task_id or f"agent-session-{attempt_id[:12]}"
        self._run_task_id.set(task_id)
        return {"mril_task_id": task_id, "mril_attempt_id": attempt_id}

    async def abefore_agent(self, state: Any = None, runtime: Any = None):
        return self.before_agent(state, runtime)

    def after_agent(self, state: Any = None, runtime: Any = None) -> None:
        # Lifecycle cleanup only — NOT finalization (a task spans invokes).
        # Free this run's step counter so long-lived middleware/workers
        # don't accumulate per-attempt state.
        state_attempt = (
            state.get("mril_attempt_id") if isinstance(state, Mapping) else None
        )
        attempt_id = state_attempt or self._attempt_id.get()
        if attempt_id is not None:
            self._steps.pop(attempt_id, None)
        return None

    async def aafter_agent(self, state: Any = None, runtime: Any = None) -> None:
        return self.after_agent(state, runtime)

    # NOTE: no after_agent finalization. An MRIL *task* spans multiple agent
    # invocations (attempt -> escalate -> retry); the driver — not the graph —
    # decides when it's done and calls router.finalize(). Auto-finalizing here
    # would close the task before recovery can run.

    # -- model-call interception ----------------------------------------------

    def wrap_model_call(self, request: Any, handler: Callable) -> Any:
        request, decision, attempt_id = self._route(request)
        started = time.monotonic()
        response, api_error = None, None
        try:
            response = handler(request)
            return response
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._safe_observe(decision, response, started, api_error, attempt_id)

    async def awrap_model_call(self, request: Any, handler: Callable) -> Any:
        request, decision, attempt_id = self._route(request)
        started = time.monotonic()
        response, api_error = None, None
        try:
            response = await handler(request)
            return response
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._safe_observe(decision, response, started, api_error, attempt_id)

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
        state_task = feats.pop("task_id", None)
        state = getattr(request, "state", None)
        if not isinstance(state, Mapping):
            state = {}
        task_id = (
            self._fixed_task_id
            or state_task                    # user-supplied "task_id" in state
            or state.get("mril_task_id")     # minted by our before_agent hook
            or self._run_task_id.get()
            or "agent-session"  # wrapped outside an agent run
        )
        ctx = TaskContext(task_id=task_id, **feats)
        attempt_id = state.get("mril_attempt_id") or self._attempt_id.get()
        if attempt_id is None:  # wrapped outside an agent run
            attempt_id = new_event_id()
            self._attempt_id.set(attempt_id)
        with self._step_lock:
            step = self._steps.get(attempt_id, 0)
            self._steps[attempt_id] = step + 1
        decision = self.router.route(ctx, self.constraints, step_index=step, call_site="model_call")
        model = self._resolve(decision.model_id)
        if model is not None and hasattr(request, "override"):
            request = request.override(model=model)
        return request, decision, attempt_id

    def _safe_observe(
        self, decision, response: Any, started: float, api_error: str | None, attempt_id: str
    ) -> None:
        # Telemetry must never block or mask the agent's result — a store
        # failure here would otherwise replace the handler's return value
        # (or its real exception) in the finally block.
        try:
            self._observe(decision, response, started, api_error, attempt_id)
        except Exception:
            _log.warning("mril: invocation observation dropped", exc_info=True)

    def _observe(
        self, decision, response: Any, started: float, api_error: str | None, attempt_id: str
    ) -> None:
        usage = _extract_usage(response)
        self.router.observe_invocation(
            decision.decision_id,
            decision.model_id,
            task_id=decision.task_id,
            attempt_id=attempt_id,
            input_tokens=_usage_get(usage, "input_tokens"),
            output_tokens=_usage_get(usage, "output_tokens"),
            cached_input_tokens=_cached_tokens(usage),
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


def _cached_tokens(usage: Any) -> int | None:
    """Provider-reported cache reads. 0 is real data — a cold cache miss,
    exactly what a post-switch call reports — so only None means unreported."""
    val = _usage_get(usage, "input_token_details", nested="cache_read")
    if val is None:
        val = _usage_get(usage, "cached_input_tokens")
    return val


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
