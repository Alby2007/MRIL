# MRIL agent notes

## Commands

- Install: `pip install -e ".[dev]"` (venv at `.venv/`)
- Test: `.venv/bin/python -m pytest`
- Example: `.venv/bin/python examples/basic_routing.py`
- Real-agent example: `.venv/bin/python examples/langgraph_agent.py`
  (needs `ollama serve`; create `mril-weak`/`mril-strong` per the file header)
- CLI: `.venv/bin/mril --db <db> explain|task|tasks`

## Conventions

- `mril.core` must stay I/O-free and framework-neutral. Adapters own all
  framework imports, and they import lazily — every module must be importable
  with zero optional dependencies installed.
- Events are immutable and append-only; fix forward, never edit the ledger.
- New event fields: add with defaults, bump `SCHEMA_VERSION` only on breaking
  changes. `event_from_dict` must tolerate unknown keys.
- Policies are pure functions of (context, constraints, candidates, state,
  seeded rng). Any nondeterminism goes through the injected RNG so decisions
  stay replayable.
- Cost math uses price snapshots recorded in `RouteDecided`, never live
  registry prices.
- When in doubt about an outcome, it's `inconclusive` — never upgrade to
  success without explicit verifier evidence.
- Lifecycle semantics learned from the real LangChain spike: one agent
  `invoke()` may contain several model calls — mint ONE `attempt_id` in
  `before_agent` and share it across that run's invocations (invocations are
  steps, attempts are runs). Never auto-finalize in `after_agent` — a task
  spans multiple invokes; the driver calls `router.finalize()`.
