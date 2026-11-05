# 03 — The Event Contract

The most important interface in the project. Everything downstream — learning,
offline evaluation, analytics, dashboards — is derived by replaying these
events. Get the ledger wrong and nothing built on it can be trusted.

## Rules

1. **Append-only.** Events are immutable once written. Corrections are new
   events; `rebuild_state` replays the stream.
2. **Versioned.** Every event carries `schema_version` (currently
   `mril.event.v1`). Readers tolerate unknown keys so a newer writer never
   breaks an older reader. The raw JSON payload is stored regardless, so no
   information is ever lost to a schema gap.
3. **Idempotent.** `event_id` is a client-generated UUID and unique —
   concurrent workers can safely retry writes.
4. **Step-aware from day one.** `step_index` and `call_site` exist in the
   schema even though v0.1 policies mostly route at task granularity. Adding
   them later would mean re-instrumenting every adapter.
5. **Honest outcomes.** Terminal outcomes distinguish verified results from
   inconclusive ones. A missing verification is *never* promoted to success.

## The six event types

| Event | Emitted when | Key fields |
| --- | --- | --- |
| `task_started` | First `route()` for a task_id | task features (language, task_type, scope, risk), harness |
| `route_decided` | Each `route()` call | model_id, policy name/version/hash, registry version/hash, decision_seed, selection_probability, candidates, **price_snapshot**, degraded flag |
| `model_invocation_finished` | Each model call ends | model_id, input/output/cached tokens, latency_ms, cost_usd, api_error |
| `verification_completed` | A verifier judges an attempt | status (passed/failed/inconclusive), verifier_type, confidence, failure_category |
| `recovery_decided` | Each `next_action()` call | action (continue/retry/escalate/stop), model_id, reason, estimated_cost_usd, budget_remaining |
| `task_finalized` | `finalize()` | task_outcome (verified_success / verified_failure / inconclusive / cancelled / infrastructure_error), total_cost_usd, attempt_count, escalation_count |

All events share an envelope: `event_id`, `occurred_at` (UTC ISO-8601),
`task_id`, `attempt_id`, `decision_id`, `trace_id`, `step_index`,
`call_site`, `schema_version`.

## ID semantics — learned the hard way `[built]`

- **task** — the unit of work. Spans many attempts and many model calls.
- **attempt** — one agent *run* at the task. One `attempt_id` per
  `before_agent`; all model calls inside that run are its steps.
- **decision** — one `route()` call's output. Links a routing choice to the
  invocation it produced.
- **step** — one model call within an attempt (`step_index`).

The spike's big find: an "attempt" is *not* a model call — a LangChain agent
makes several calls per run. Counting calls as attempts made `max_attempts`
fire three times too early. Now `before_agent` mints the attempt_id and
`rebuild_state` aggregates invocations into attempt records (costs summed,
context = max input seen, model = last used).

## Reproducibility

A `route_decided` is replayable: it records `policy_hash` (of policy params),
`registry_hash` (of capabilities *and* prices), `decision_seed` (derived
deterministically from hashes + task_id + step + call_site), and the
`selection_probability` that later off-policy evaluation (IPS/DR) needs to
correct for selection bias. Given the same inputs and seed, the same decision
comes out — that's tested.

## Storage

`SQLiteEventStore` — single table, JSON payloads, `seq` ordering, indexes on
task_id/decision_id. `INSERT OR IGNORE` gives idempotency. `MemoryEventStore`
for tests. The store is a protocol, so Postgres for the self-hosted mode is a
matter of a second implementation, not a rewrite.

## What deliberately isn't in the ledger

No prompts, no code, no diffs, no responses — features and outcomes only.
That's the privacy boundary the eventual cloud sync inherits: metadata and
numbers by default, raw text never.
