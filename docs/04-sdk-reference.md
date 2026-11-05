# 04 — SDK Reference

The public surface is deliberately small: three operations the doc promised,
plus `finalize` and `task_state` for lifecycle bookkeeping.

```python
from mril import (
    Router, TaskContext, RoutingConstraints,
    ModelRegistry, ModelSpec,
)
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore

router = Router(
    store=SQLiteEventStore("mril.db"),
    registry=registry,
    policy=TieredPolicy(),                     # default if omitted
    default_constraints=RoutingConstraints(
        fallback_model_id="balanced-70b",      # required for degraded path
        budget_usd=0.50,
        max_attempts=4,
    ),
)
```

## `route(ctx, constraints=None, *, step_index=None, call_site=None) -> RoutingDecision`

Choose a model. Emits `task_started` (once per task) and `route_decided`.

- `ctx: TaskContext` — `task_id` required; `language`, `task_type`, `scope`,
  `risk`, `harness`, `metadata` optional (policies must cope with missing
  features).
- `constraints: RoutingConstraints` — `allowed_models` (allowlist),
  `fallback_model_id`, `budget_usd`, `max_attempts`, `require_capabilities`.
- Returns `RoutingDecision` — `decision_id`, `model_id`, `reason`,
  `selection_probability`, `decision_seed`, `estimated_cost_usd`,
  `candidates`, `price_snapshot`, `degraded`.

Never raises for policy failures: on any exception it selects the fallback
model and marks `degraded=True` (recorded in the ledger too).

## `observe_invocation(decision_id, model_id, *, task_id=?, attempt_id=?, input_tokens=?, output_tokens=?, cached_input_tokens=?, latency_ms=?, cost_usd=?, api_error=?, ...) -> ModelInvocationFinished`

Record one model call. If `cost_usd` is omitted and token counts are present,
cost is computed from the **price snapshot frozen into that decision's
`route_decided` event** — so provider re-pricing can't corrupt the books.
`attempt_id` auto-generates if omitted (adapters pass a shared one per run).

## `observe_verification(attempt_id, status, *, task_id=?, verifier_type="unknown", confidence=?, failure_category=?, step_index=?) -> VerificationCompleted`

Record verifier evidence. `status ∈ passed | failed | inconclusive`.
`verifier_type`: `test | build | typecheck | lint | llm_judge | human`.
`failure_category` feeds recovery (`timeout`, `rate_limit`, `test_failure`,
`compile_error`, …).

## `next_action(task_id, constraints=None) -> RecoveryAction`

Replays the ledger and asks the policy how to proceed. Emits
`recovery_decided`. Returns `RecoveryAction{type, model_id?, reason,
estimated_cost_usd?, budget_remaining_usd?}` where `type ∈ continue | retry |
escalate | stop`. Policy errors degrade to `continue`, never raise.

## `finalize(task_id, outcome=None) -> TaskFinalized`

Record the terminal outcome. If `outcome` is omitted it's derived from the
last attempt's verification: passed → `verified_success`, failed →
`verified_failure`, anything else → `inconclusive`. **Missing verification
can never become success.**

## `task_state(task_id) -> TaskState`

Replay the ledger into current state: attempts (with per-attempt model, cost,
verification), `total_cost_usd`, `escalation_count`, `finalized`,
`task_outcome`, and `context_tokens` — the largest observed input size, used
as the warm-context estimate for switching costs.

## CLI

```bash
mril --db mril.db explain <decision_id>   # why this model — full provenance
mril --db mril.db task <task_id>          # event timeline + attempt summary
mril --db mril.db tasks                   # all tasks w/ attempts, cost, outcome
```

## The honesty contract

| What route() promises | What it doesn't |
| --- | --- |
| A model from the eligible set (allowlist ∩ non-restricted ∩ capabilities) | That the model is *good* — that's what verification is for |
| `degraded=True` when anything goes wrong | Hidden fallbacks |
| Determinism given (ctx, constraints, registry, policy, seed) | That the same task always routes identically — seeds include step/call_site |
