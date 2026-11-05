# 06 — Harness Integration

MRIL's contract with a harness is an *event* contract, not an orchestration
contract: the harness keeps its tools, state, and execution model; MRIL
watches decisions and outcomes. That's the only way this integrates into
frameworks we haven't met yet.

## The LangChain adapter `[built]` — `MRILMiddleware`

LangChain 1.x middleware hooks: `before_agent`, `wrap_model_call` /
`awrap_model_call` (per model call — step-level routing is real, not
aspirational). `create_agent` discovers hooks on `AgentMiddleware` subclasses
only, so the adapter subclasses it **conditionally**:

```python
try:
    from langchain.agents.middleware import AgentMiddleware as _Base
except Exception:
    _Base = object  # still importable/testable without langchain installed
```

```python
mw = MRILMiddleware(
    router,
    models={"cheap-id": chat_model_1, "frontier-id": chat_model_2},  # or resolver(model_id) -> model
    constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
    feature_extractor=lambda request: {...},  # task features from request/state
    task_id="task-1",                         # or derived per task
)
agent = create_agent(model=expensive_default, middleware=[mw])
```

On each model call the middleware: extracts features → `route()` →
`request.override(model=resolved)` → invokes handler → `observe_invocation()`
with real `usage_metadata` (input/output/cached tokens, latency, api errors).
Verification arrives via `mw.report_verification(attempt_id, passed, ...)`
when the harness has evidence — the middleware never invents it.

## Lifecycle semantics — what the spike taught us `[built]`

These invariants are now encoded and documented in `AGENTS.md` because they
were wrong the first time:

1. **An attempt is one agent run, not one model call.** A LangChain agent
   makes several calls per `invoke()` — model → tool → tool result → model.
   `before_agent` mints one `attempt_id` shared by every call in that run;
   invocations are steps within the attempt. (`rebuild_state` aggregates
   accordingly.)
2. **The driver owns task finalization, not the graph.** `after_agent` fires
   at the end of *every* `invoke()`, but an MRIL task spans multiple
   invocations (attempt → escalate → retry). Auto-finalizing there closed
   tasks before recovery could run — `next_action` correctly answered "stop,
   already finalized." There is deliberately **no** `after_agent`
   finalization; the driver calls `router.finalize()` when the task is done.
3. **Step indices reset per attempt.** `step_index` counts calls *within* an
   attempt so per-step analysis stays comparable across retries.

## Observed real-world quirks worth knowing

- **Ollama double-wraps tool args** (`{'code': {'code': ...}}`) — the tool
  invocation errors inside the agent loop. If your harness uses tools on
  Ollama, handle arg-shape drift or use reply-extraction patterns (the demo
  does the latter).
- **`num_ctx` truncates the rendered prompt from the front** — tools/system
  live there, so small contexts break tool calling before they break task
  content. A weak "small context" tier can't be simulated this way.
- **`repeat_penalty` corrupts output deterministically enough** to stand in
  for a weak tier (mangled code → real test failure → real escalation) — the
  offline demo's trick until a genuinely smaller model is pullable.
- **`usage_metadata` survives** as `{input_tokens, output_tokens,
  input_token_details.cache_read, ...}` on the AI message inside
  `ModelResponse.result`; the adapter handles both response shapes.

## The working example `[built]`

`examples/langgraph_agent.py` — real `create_agent` graph on local Ollama,
reply-extraction harness, real `pytest` verification. Recorded ledger from a
live run:

```
route(cheap) → invocation → verification FAILED →
recovery ESCALATE (+re-ingest est) → route(frontier) →
invocation → verification PASSED → verified_success
```

## Writing the next adapter

Any harness with a per-model-call hook maps onto the same pattern: mint
attempt at run-start, route+override at each call, observe usage at
call-end, report verification when the harness has evidence, finalize at
task-end. If a harness can't switch models per call, route at task scope
only — the event contract already supports both.
