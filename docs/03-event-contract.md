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
3. **Idempotent — twice over.** `event_id` is a client-generated UUID and
   unique — concurrent workers can safely retry writes. Events observing the
   same *logical* occurrence also carry a `dedupe_key` enforced by a UNIQUE
   index, so a worker retry that mints a fresh UUID still lands once.
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
| `model_invocation_finished` | Each model call ends | model_id, input/output/cached tokens, latency_ms, cost_usd, api_error, provider_request_id |
| `verification_completed` | A verifier judges an attempt | status (passed/failed/inconclusive), verifier_type, confidence, failure_category, verification_run_id (via dedupe) |
| `recovery_decided` | Each `next_action()` call | action (continue/retry/escalate/stop), model_id, reason, estimated_cost_usd, **estimated_switch_cost_usd**, context_tokens, budget_remaining, **selection_probability**, **recovery_context** |
| `task_finalized` | `finalize()` | task_outcome (verified_success / verified_failure / inconclusive / cancelled / infrastructure_error), total_cost_usd, attempt_count, escalation_count, **actual_switch_cost_usd**, switch_cost_basis |

All events share an envelope: `event_id`, `occurred_at` (UTC ISO-8601),
`task_id`, `attempt_id`, `decision_id`, `trace_id`, `step_index`,
`call_site`, `dedupe_key`, `schema_version`.

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

## Dedupe keys — logical identity `[built]`

`event_id` dedupes *writes*; `dedupe_key` dedupes *occurrences*. A worker
timeout that retries an observation with a fresh UUID would otherwise
double-count cost and inflate `escalation_count`. Keys are assigned by the
SDK, not the caller:

| Event | Key | One logical… |
| --- | --- | --- |
| `task_started` | `ts:<task_id>` | task |
| `model_invocation_finished` | `inv:req:<provider>:<request_id>`, else `inv:<attempt>:<step>:<call_site>` | model call. Request ids are namespaced by provider — uniqueness isn't global. No key when neither exists: a bare attempt_id can host many calls |
| `verification_completed` | `ver:run:<verification_run_id>`; fallback `ver:<attempt>:<verifier>:<status>:<category>:<step>` | verifier *execution*. Distinct runs never collapse even on identical verdicts; the content fallback is approximate |
| `recovery_decided` | `rec:<task>:<#attempts>:<last_attempt>` — a *checkpoint*, action-independent | recovery decision. First committed wins; repeat or racing callers on unchanged state get the **recorded** action back — keeps a stochastic policy single-draw |
| `task_finalized` | `fin:<task_id>` | terminal verdict — `finalize()` returns the recorded event on repeat calls |
| `route_decided` | — (none) | every `route()` is a new decision by definition |

## Estimated vs measured switch cost `[built]`

`recovery_decided` splits its estimate: `estimated_switch_cost_usd` is the
KV-cache rewrite alone; `estimated_cost_usd` is switch + expected attempt.
`task_finalized.actual_switch_cost_usd` reports the *observed* re-ingest
spend, summed over escalations, with `switch_cost_basis`:

- **measured** — the post-switch invocation carried provider cache usage, so
  the fresh-input share *is* the billed re-ingest
- **estimated** — cache usage unobservable; priced from the recorded warm
  `context_tokens` at the new model's decision-time input price
- **mixed** — several escalations, some of each
- **null** — no escalation happened

An estimate is never labelled measured. Per-(provider, model-pair) switch
costs can later be learned off these ingredients.

## Reproducibility

A `route_decided` is replayable: it records `policy_hash` (of policy params),
`registry_hash` (of capabilities *and* prices), `decision_seed` (derived
deterministically from hashes + task_id + step + call_site), and the
`selection_probability` that later off-policy evaluation (IPS/DR) needs to
correct for selection bias. Given the same inputs and seed, the same decision
comes out — that's tested.

## Storage

`SQLiteEventStore` — single table, JSON payloads, `seq` ordering, indexes on
task_id/decision_id, a UNIQUE index on `dedupe_key`. `INSERT OR IGNORE`
gives both idempotencies; old databases gain the column on open.
`MemoryEventStore` for tests. The store is a protocol, so Postgres for the self-hosted mode is a
matter of a second implementation, not a rewrite.

## What deliberately isn't in the ledger

No prompts, no code, no diffs, no responses — features and outcomes only.
That's the privacy boundary the eventual cloud sync inherits: metadata and
numbers by default, raw text never.
