# 02 — Architecture

## The picture

```
Coding Agent Harness                (you own this — tools, files, sandbox)
        │
        ▼  middleware hooks
┌─────────────────────────────────────────────────────────┐
│ MRIL SDK (in-process, local)                            │
│   route() · observe_*() · next_action() · finalize()    │
│        │                                                │
│   ┌────┴─────┐   ┌──────────────┐   ┌────────────────┐  │
│   │ Policy   │   │ TaskState    │   │ ModelRegistry  │  │
│   │ engine   │   │ (replay)     │   │ (caps+prices)  │  │
│   └──────────┘   └──────────────┘   └────────────────┘  │
└─────────┬───────────────────────────────────────────────┘
          │ append-only events (mril.event.v1)
          ▼
   Experience Ledger                  (SQLite — local-first)
          │
          ▼  [planned] optional, asynchronous, opt-in only
   Managed control plane              (policy registry, analytics)
```

## The one rule that shapes everything

**The developer owns execution. MRIL owns routing intelligence. The cloud is
optional — and never in the critical path of a model call.**

| Responsibility | Owner |
| --- | --- |
| Tools, file edits, sandboxing, running tests | Agent harness |
| Provider credentials, transport, request-level retries | Existing gateway / client |
| Model selection, retry/escalate/stop decisions | MRIL |
| Recording outcomes, maintaining the ledger | MRIL |
| Learning better policies (later) | MRIL, offline |

## Package layout `[built]`

```
mril/
├── core/         # Pure contract: events, model registry, task context,
│                 # decisions. Zero I/O, zero framework imports.
├── policy/       # RoutingPolicy protocol, TaskState replay, TieredPolicy.
│                 # Policies are pure functions of (ctx, constraints,
│                 # candidates, state, seeded rng).
├── store/        # EventStore protocol; SQLite + in-memory impls.
│                 # Idempotent by event_id.
├── adapters/     # Harness integrations. All framework imports are lazy —
│                 # every module imports with zero optional deps installed.
│   └── langchain.py   # AgentMiddleware subclass; sync + async.
├── telemetry/    # Aggregate summaries over the ledger.
└── cli.py        # mril explain | task | tasks
```

Deliberately a **single package with modules**, not a monorepo of five
packages. The split happens when a second adapter or store actually lands —
premature decomposition is how projects die in ceremony.

## Data flow for one task

1. `route(ctx)` — emits `task_started` (once per task), consults the policy,
   emits `route_decided` (model, policy+registry hashes, seed, selection
   probability, price snapshot).
2. The harness calls the chosen model through its own gateway. MRIL is not in
   the transport path.
3. `observe_invocation(...)` — provider-reported tokens/latency/errors;
   computes cost from the *decision-time price snapshot*, not live prices.
4. `observe_verification(...)` — the harness's verifier reports
   passed/failed/inconclusive with verifier type and failure category.
5. `next_action(task_id)` — replays the ledger into `TaskState`, asks the
   policy, emits `recovery_decided` (continue/retry/escalate/stop + cost
   estimate).
6. `finalize(task_id)` — emits `task_finalized` with a terminal outcome.
   Missing verification derives `inconclusive`, never success.

## Failure handling `[built]`

The invariants, enforced in `Router` and tested:

| Situation | Behavior |
| --- | --- |
| Policy/learner throws | Degraded decision on configured fallback model — never raises into the harness |
| Policy suggests a restricted/out-of-set model | Rejected before invocation; degraded fallback instead |
| Budget exhausted | `next_action → stop`; never silently bypassed |
| Missing verification | `task_finalized → inconclusive`, not success |
| Store/event write retried | Idempotent by `event_id`; safe under concurrency |
| Registry re-prices after decision | Cost math uses the frozen price snapshot |

Two honest limits worth stating: per-worker budget enforcement is exact, but a
perfect *global* spend cap across concurrent workers needs a shared quota
service (planned, self-hosted mode). And MRIL's quality guarantee is only as
good as the verifier feeding it — see
[07](07-verification-and-outcomes.md).
