# MRIL agent notes

## Commands

- Install: `pip install -e ".[dev]"` (venv at `.venv/`; interpreter is
  `.venv/bin/python` on POSIX, `.venv/Scripts/python` on Windows)
- Test: `.venv/Scripts/python -m pytest`
- Example: `.venv/Scripts/python examples/basic_routing.py`
- Offline agent example: `.venv/Scripts/python examples/langchain_verified_escalation.py`
  (needs `pip install -e ".[langchain]"`; no Ollama/network — fake chat models)
- Real-agent example: `.venv/Scripts/python examples/langgraph_agent.py`
  (needs `ollama serve`; create `mril-weak`/`mril-strong` per the file header)
- CLI: `.venv/Scripts/mril --db <db> explain|task|tasks`
- Eval: `mril eval run --corpus <dir> --registry models.json --out <dir>
  --ollama-model reg_id=tag ...`; rebuild report: `mril eval report <dir>`

## Conventions

- `mril.core` must stay I/O-free and framework-neutral. Adapters own all
  framework imports, and they import lazily — every module must be importable
  with zero optional dependencies installed.
- Events are immutable and append-only; fix forward, never edit the ledger.
- Observations dedupe on `dedupe_key` (logical identity), not just
  `event_id`: retries of the same invocation / verification / recovery /
  finalize must land once. New event types need a logical key — or a
  deliberate reason to have none (route_decided has none by design).
- New event fields: add with defaults, bump `SCHEMA_VERSION` only on breaking
  changes. `event_from_dict` must tolerate unknown keys.
- Policies are pure functions of (context, constraints, candidates, state,
  seeded rng). Any nondeterminism goes through the injected RNG so decisions
  stay replayable.
- Cost math uses price snapshots recorded in `RouteDecided`, never live
  registry prices. Estimates are never labelled measured: switch cost
  reports a `measured|estimated|mixed` basis, and local-driver cost is
  `synthetic_token_price` — comparable numbers, not billed money.
- The eval runner knows nothing about routing internals: arms are
  interchangeable `RoutingPolicy` strategies. Verification runs in a
  throwaway COPY of the workspace with pinned verifier files injected —
  the agent never coexists with the tests that grade it.
- `run_matrix` interleaves task×arm×seed order (seeded, in the manifest)
  so cache warmth / thermal state can't systematically favor one arm.
- When in doubt about an outcome, it's `inconclusive` — never upgrade to
  success without explicit verifier evidence.
- Driver feedback is sanitized (counts + failure category via
  `sanitize_feedback`) — raw verifier stdout must never reach the model;
  it leaks hidden test source and expected values.
- `run_matrix` resumes: re-running an out dir skips cells already
  finalized in `eval.db` and rebuilds their results from the ledger.
  Delete the dir for a fresh matrix.
- Lifecycle semantics learned from the real LangChain spike: one agent
  `invoke()` may contain several model calls — mint ONE `attempt_id` in
  `before_agent` and share it across that run's invocations (invocations are
  steps, attempts are runs). Never auto-finalize in `after_agent` — a task
  spans multiple invokes; the driver calls `router.finalize()`.
- LangGraph runs each middleware hook in its own async task: ContextVar
  writes in `before_agent` are INVISIBLE to the sibling task running
  `wrap_model_call`. Run identity propagates via private middleware state
  (`state_schema` keys `mril_task_id`/`mril_attempt_id`); contextvars are
  only a fallback for calls outside a real agent run. Step allocation is a
  lock-guarded counter keyed by attempt_id so parallel child calls get
  unique step indexes.
- Verifying generated artifacts in-place: clear `__pycache__` between
  attempts — same-size rewrites within one mtime tick make Python reuse a
  stale `.pyc` and silently re-verify the previous attempt's code.
