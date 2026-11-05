# 09 — Design Decisions

The calls we've locked in, and why. These are the load-bearing choices;
revisit them only with data.

## ADR-001 — Local-first decision execution

All real-time routing decisions happen inside the customer's environment.
Hosted intelligence is asynchronous and optional.

*Why:* coding agents can't tolerate a routing dependency in their critical
path, and enterprises won't ship prompts to a third party for a cost-saving
feature. If MRIL Cloud is unreachable, the last valid local policy keeps
working — that's the product's reliability story.

*Cost:* learning stays local and data-poor longer (acknowledged in
[08](08-roadmap.md)); the cloud has to earn its place through better
policies, not through being required.

## ADR-002 — Framework-neutral intelligence core

`mril.core` and `mril.policy` contain zero framework imports and zero I/O.
Harness-specific code lives only in `mril.adapters`, which import lazily —
every module is importable with no optional dependencies installed.

*Why:* the harness landscape shifts monthly; Open SWE's integration surface
is actively evolving. Coupling the policy engine to one framework's types
would mean rewriting routing logic per adapter.

*Also why the event contract is versioned:* it's the stable API between the
harness world and the learning world.

## ADR-003 — Decision engine, not gateway

MRIL chooses models; it does not transport requests. LiteLLM already solves
provider normalization, retries, load balancing, and request-level
fallbacks — we integrate rather than recreate.

*The distinction that matters:* a gateway retries a *timeout*; MRIL
escalates a *verification failure*. Different budgets, different signals —
they coexist.

## ADR-004 — Ledger before learning

Ship the versioned, append-only event contract with deterministic rules and
full outcome logging *first*; learned policies arrive only when logged data
justifies them.

*Why:* a router you can't evaluate is a liability. Logging
`selection_probability` on every decision from day one is what makes
off-policy evaluation possible later — you can't retrofit propensities onto
decisions that didn't record them.

## ADR-005 — Reproducible decisions

Every decision is replayable: same (context, constraints, registry, policy,
seed) → same model. The seed derives deterministically from policy hash +
registry hash + task_id + step + call_site; prices are snapshotted into each
`route_decided` at decision time.

*Why:* "why was this model chosen" is a support question, a debugging
question, and eventually a compliance question. A router that can't answer
it deterministically can't sell to serious teams.

## ADR-006 — The harness owns the task lifecycle

Adapters mint `attempt_id` at run-start (`before_agent`) and never
auto-finalize at run-end (`after_agent`). The driver calls `finalize()`.

*Why:* discovered the hard way — `after_agent` fires per `invoke()` but a
task spans multiple invokes (attempt → escalate → retry). Auto-finalization
closed tasks before recovery could run. Execution lifecycle belongs to the
owner of execution: the harness. See [06](06-harness-integration.md).

## ADR-007 — Single package, deferred monorepo

`mril/` is one Python package with clean module boundaries — not
`packages/mril-{core,sdk,store,...}`.

*Why:* five packages for one adapter and one store is ceremony, not
architecture. The module boundaries (`core`/`policy`/`store`/`adapters`)
already enforce the dependency rules; physical split happens when a second
implementation actually needs it.
