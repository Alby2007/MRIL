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

## ADR-008 — Logical idempotency alongside event idempotency

`event_id` dedupes *writes*; `dedupe_key` dedupes *occurrences*. Every
observation type carries an SDK-assigned logical key (verification run ids,
provider-namespaced request ids, attempt/step/call-site triples), and
recovery is deduped at an action-independent *checkpoint* — first committed
decision wins, racing callers get the recorded action back.

*Why:* a retried write that mints a fresh UUID would otherwise double-count
cost and inflate `escalation_count`; an action-keyed recovery dedupe would
let two concurrent evaluations both persist. Checkpoint semantics are what
make a future stochastic recovery policy single-draw.

## ADR-009 — Measured means measured

The ledger never labels an estimate as observed. `recovery_decided` splits
`estimated_switch_cost_usd` from the attempt estimate; `task_finalized`
reports `actual_switch_cost_usd` with `switch_cost_basis` — `measured` only
when the post-switch call carried provider cache-usage data.

*And the finer point:* measured post-switch fresh-input spend is the
billed re-ingest, **not** the incremental cost of switching — establishing
that needs the counterfactual (staying on the original model). Analytics
and reports keep the distinction: we show re-ingest spend, honest basis
labels, and `synthetic_token_price` for local inference — never billed
money, never implied savings.

## ADR-010 — Evaluation before learning

No learned policy until the eval harness can replay the decisions it would
replace. v0.2 is the measurement system: immutable corpora, interchangeable
policy arms behind one strategy contract, guardrailed comparison (min cost
s.t. completion within δ of the ceiling arm), and `RecoveryContext`
snapshotted on every recovery decision so policies can be replayed offline.

*Why:* routing intelligence that can't demonstrate economic value is a
wrapper, not infrastructure. A rigorous negative result is a fine v0.2
outcome — the instrument is the deliverable; learning earns its complexity
against it.

## ADR-011 — Run identity lives in private middleware state, not contextvars

The LangChain adapter carries `mril_task_id`/`mril_attempt_id` in a
`PrivateStateAttr` state schema (`before_agent` returns them; every
`wrap_model_call` reads `request.state`). ContextVars remain only as a
fallback for calls made outside a real agent run; step allocation is a
lock-guarded counter keyed by attempt_id.

*Why:* discovered by the first real `create_agent().ainvoke()` integration
test — LangGraph executes each middleware hook in its own scheduled task.
ContextVar writes propagate *down* into spawned children but never
*sideways* between sibling tasks, so `before_agent`'s minted ids were
invisible to `wrap_model_call`: two concurrent runs collapsed into one
`agent-session` task while every unit test (single context) stayed green.
Agent state is the only channel guaranteed to reach every hook in a run
and never cross between runs. Do not "simplify" the adapter back to
contextvar propagation — the sibling-task behavior is a framework
invariant, not a bug we can fix.

*Also:* `after_agent` reads the same state keys to free the per-attempt
step counter; the counter can't live in the context either (parallel
child calls would draw duplicate step indexes and collapse under the
`(attempt, step, call_site)` dedupe key).
