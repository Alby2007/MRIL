# MRIL — Model Routing Intelligence Layer

Local-first, verified-outcome-aware model routing for coding agents.
**v0.3 developer preview.**

MRIL makes existing coding agents cheaper to operate without sacrificing
task completion quality. It sits inside the agent harness: the developer
owns execution, MRIL owns routing intelligence, and any hosted service is
optional and out of the critical path.

## What it gives you on day one

Not another learning mechanism — verified infrastructure:

- **Verified recovery lifecycle**: cheap model → verifier verdict →
  escalate / retry / stop, with reasons, budgets, and KV-cache
  switch-cost estimates on every decision.
- **An append-only ledger** of every decision, invocation, verdict, and
  outcome — inspectable from the CLI, replayable offline.
- **Idempotent accounting**: logical dedupe keys mean retried
  observations never double-count cost or attempts.
- **Explainability**: `mril task` summarizes attempts/cost/verification/
  recovery; `mril explain` shows exactly why a model was chosen.
- **Reproducible evaluation**: run policy arms against immutable corpora
  with guardrailed comparison reports.

## The boundary

| Responsibility | Owner |
| --- | --- |
| Editing files, running tools, sandboxing | Agent harness |
| Calling models, provider credentials | Existing gateway / harness |
| Choosing models, retry/escalation decisions | MRIL |
| Recording outcomes, learning from them | MRIL ledger |

MRIL is a **decision engine, not a model gateway**. Gateway-level retries
(timeouts, rate limits) stay in LiteLLM or your provider client; MRIL-level
escalation happens when generated code *fails verification*.

## Install

Not on PyPI yet — install from the repo:

```bash
pip install "git+https://github.com/Alby2007/MRIL.git#egg=mril[langchain]"
# or from a clone:
pip install ".[langchain]"      # core + LangChain adapter
pip install .                   # core only — zero dependencies
```

Core import never touches the network and never requires optional
dependencies. Framework adapters import lazily.

## Five-minute example

```bash
pip install -e ".[langchain]"              # from this repo
python examples/langchain_verified_escalation.py
mril --db verified-escalation.db task demo-escalation
mril --db verified-escalation.db explain <decision-id>
```

The example runs a real `create_agent().ainvoke()` loop — fully offline
(fake chat models stand in for the two tiers): a cheap model produces
buggy code, a subprocess verifier fails it, MRIL escalates to the frontier
model, and the retry verifies green. Then inspect the ledger:

```
Task          demo-escalation
Context       bugfix / single_file / low / python / langchain-create_agent
Outcome       VERIFIED_SUCCESS
Attempts      2

ATTEMPT 1   Model weak-coder   Verification FAILED (test_failure) via test
RECOVERY    escalate -> strong-coder   "capability failure..."
ATTEMPT 2   Model strong-coder  Verification PASSED via test

FINAL       verified_success, cost $0.0000, escalations=1
```

(condensed; full output adds costs, reasons, estimates, and per-attempt
`mril explain <decision-id>` pointers. `--json` gives the same projection
for scripts; `--timeline` the raw event log.)

### Integrating into your own agent

```python
from langchain.agents import create_agent
from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints
from mril.adapters.langchain import MRILMiddleware
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore

router = Router(
    store=SQLiteEventStore("agent.db"),
    registry=ModelRegistry(version="mine", models=(
        ModelSpec("weak", provider="...", tier="cheap",
                  input_price=0.10, output_price=0.30),
        ModelSpec("strong", provider="...", tier="frontier",
                  input_price=5.0, output_price=25.0),
    )),
    policy=TieredPolicy(),
    default_constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
)
middleware = MRILMiddleware(router, {"weak": weak_model, "strong": strong_model},
                            task_id="my-task")          # optional: share one
                                                        # task across invokes;
                                                        # omit = one task per run
agent = create_agent(model=strong_model, middleware=[middleware])
```

`before_agent` mints one `attempt_id` per run; every model call inside is
a step of that attempt. Call `middleware.report_verification(...)` when
your verifier has evidence, `router.next_action(task_id)` for the recovery
decision, and `router.finalize(task_id)` when the task ends — MRIL never
auto-finalizes (a task spans multiple invokes).

## Non-negotiable invariants

- **Local-first**: no network call in the decision path; all state in SQLite.
- **Never block the agent**: a policy/learner error produces a `degraded`
  decision on the configured fallback model — it never raises into the harness.
- **Never route to a restricted model**, even if the policy suggests one —
  enforced on the fallback path too.
- **Never treat missing verification as success** — it is `inconclusive`.
- **Never silently bypass a budget**: `next_action` returns `stop`.
- **Reproducible decisions**: same context + registry + policy + seed →
  same decision, with policy/registry hashes and propensities logged.

## Verified against real LangGraph

`tests/test_langchain_integration.py` exercises the actual
`create_agent().ainvoke()` lifecycle — concurrent invocations, multi-call
attempts, failure-to-escalation — and caught a real propagation bug:
LangGraph runs each middleware hook in its own task, so run identity rides
in private middleware state, not contextvars (see
[ADR-011](docs/09-design-decisions.md)).

## vs. hand-written fallback

`python tools/compare_fallback.py` is a **requirements-coverage
demonstration**, not a head-to-head benchmark: a ~15-line hand-written
fallback is easy and correct for one-shot scripts, while production-grade
accounting, concurrency safety, verification honesty, retries, and
decision provenance are the additional infrastructure MRIL provides.
Details: [docs/handwritten-fallback.md](docs/handwritten-fallback.md).

## Known limitations

- **Local-first only**: no managed service; the ledger is a per-machine
  SQLite file (WAL-enabled — concurrent readers are fine).
- **Costs are accounting, not billing**: decision-time price snapshots;
  local inference reports `synthetic_token_price` — comparable numbers,
  never billed money.
- **Evaluation is opt-in**: the `mril eval` harness drives Ollama; other
  providers need a driver implementing the eval driver protocol.
- **Frameworks**: LangChain 1.x is the tested adapter; the middleware is
  duck-typed so other frameworks can reuse the Router API directly.
- **Feedback contract**: manifests record `feedback_contract:
  sanitized-v1`; older raw-traceback runs are not numerically comparable
  and are refused on resume (fail-closed).
- **Learning**: deterministic policies ship in the preview; the empirical
  snapshot policy exists but is experimental — see `docs/08-roadmap.md`.

## What the studies actually showed

We keep the negative results — they shaped this product:

- **Study 04**: empirical initial routing did *not* beat cheap-first out
  of sample.
- **Study 05A**: alternative recovery actions generally underperformed
  simple escalation-on-verified-failure.
- **Study 05B**: insufficient evidence that structured recovery feedback
  beats the sanitized baseline (+0.059, p = 0.125, n.s. —
  `eval/analysis/`).

That's why v0.3 ships verification-driven recovery as the default and
makes no claims about self-learning routing beating static baselines.
Adaptive policy research continues separately.

## Repository layout

```
mril/
  core/      events, models/registry, task context, decisions — zero I/O
  policy/    policy interface, TaskState replay, TieredPolicy, empirical
  store/     EventStore protocol; SQLite (WAL) + in-memory
  adapters/  harness integrations (LangChain middleware; lazy imports)
  eval/      reproducible evaluation: corpora, arms, workspaces, reports
  telemetry/ aggregate summaries over the ledger
  cli.py     mril explain / task [--json|--timeline] / tasks / eval
examples/    runnable flows (offline + Ollama-backed)
tools/       compare_fallback.py and study utilities
tests/       unit + packaging + real-LangChain integration suites
docs/        architecture, event contract, ADRs, roadmap
```

## Development

```bash
pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # or .venv/bin on POSIX
```

The LangChain integration tests `skip` cleanly without the extra — run
`pip install -e ".[langchain]"` to exercise the real framework path.

CI (`.github/workflows/ci.yml`): core matrix on Linux/Windows/macOS ×
Python 3.10–3.13, a dedicated LangChain job that fails rather than skips
(`MRIL_REQUIRE_LANGCHAIN=1`), and a wheel-build → fresh-venv install
smoke — the path a new developer actually takes.

## Roadmap

- **M1 (done)**: event contract, ledger, tiered routing, recovery with
  switch-cost model, LangChain middleware, explain CLI.
- **v0.2 (done)**: ledger hardening + reproducible evaluation harness.
- **v0.3 (here)**: developer preview — strict resume compatibility,
  real-framework lifecycle validation, task summaries, packaging.
- **M3**: offline policy evaluation over logged propensities
  (IPS/DR), then conservative learned policies.
- **M4**: optional managed control plane — versioned policy artifacts,
  opt-in metadata-only telemetry sync.
