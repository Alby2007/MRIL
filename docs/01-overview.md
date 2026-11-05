# 01 — Overview

## What MRIL is

MRIL (Model Routing Intelligence Layer) is a decision engine that sits inside a
coding agent's harness and chooses which model should handle each task or step,
then learns — from *verified* outcomes, not vibes — whether that choice was a
good one.

It answers three questions a coding agent currently answers by default or by
guesswork:

1. **Which model should do this work?** (`route`)
2. **What actually happened?** (`observe` — cost, latency, verification)
3. **What should we do about it?** (`next_action` — continue, retry,
   escalate, stop)

## The problem

Coding agents are expensive to run, and most of the spend is undifferentiated:
every turn goes to the same model regardless of whether it's a frontier-worthy
reasoning problem or a mechanical edit. The obvious fix — "use cheaper models
for easy tasks" — is easy to say and hard to do safely:

- **You can't tell easy from hard upfront.** A one-line diff can hide a
  cross-module invariant. Under-routing produces failing attempts that cost
  more than the savings.
- **Retries aren't free.** When a cheap model's output fails tests, the retry
  burns tokens *and* time — and escalating mid-session forces the new model to
  re-ingest the whole context (the KV cache doesn't transfer), a cost naive
  routers ignore entirely.
- **"It worked" is unverifiable without evidence.** If there's no test run,
  there is no outcome — only an assumption. Most cost-routing tools can't even
  see verification results, because they live in the harness, not the gateway.

## The bet

The unit of value isn't the routing decision — it's the **recorded,
replayable, verified history of routing decisions**. Whoever owns a clean
ledger of (task features → model chosen → cost → verified outcome) owns the
dataset needed to learn routing policies that actually beat heuristics. So we
built the ledger first and the learning later.

Two consequences of betting on the ledger:

- **Observation before intelligence.** v0.1 ships deterministic rules +
  complete outcome logging. Learning arrives when the data is real enough to
  trust, evaluated offline against logged selection probabilities.
- **Local-first.** The ledger lives in SQLite next to the agent. No account,
  no cloud dependency, no prompts leaving the building. Any hosted service is
  asynchronous and optional — never in the path of a model call.

## Who it's for

Teams running coding agents they control — custom LangGraph/Deep Agents
graphs, Open SWE, internal harnesses — who pay real money for inference and
have real verification (CI, test suites) to learn from.

It is **not** for users of closed coding agents whose harness internals can't
be instrumented. That's an honest market boundary, not a gap we're
embarrassed about.

## What it is not

- **Not a model gateway.** LiteLLM already does provider normalization,
  retries, load balancing, and request-level fallbacks. MRIL's escalation is a
  different thing: it escalates when *verification fails*, not when a request
  times out. The two coexist.
- **Not an agent framework.** The harness owns tools, files, sandboxing, and
  execution. MRIL returns decisions; the harness acts on them.
- **Not (yet) a learned router.** The shipped policy is deterministic and
  interpretable. That's deliberate — see [08 — Roadmap](08-roadmap.md).

## The competitive landscape, honestly

- **Not Diamond Code** does nearly exactly this, closed-source: per-step
  routing for coding agents, RL-driven, claims 20–61% cost reduction. MRIL's
  counters: open source, local-first (nothing leaves your environment), and
  learning grounded in *verified* outcomes rather than inferred feedback
  signals.
- **OpenRouter `auto`**, **LiteLLM Router**, **Martian** — request-level or
  aggregate routing without outcome loops. They can see requests; they can't
  see whether the code worked.

If you only need request-level cost/latency routing, use LiteLLM. MRIL exists
for the loop above it.
