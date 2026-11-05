# 05 — Routing & Recovery

## The policy contract

A `RoutingPolicy` is a **pure, deterministic function**:

```python
select(ctx, constraints, candidates, state, rng) -> PolicySelection
recover(state, constraints, registry) -> RecoveryAction
```

Every nondeterministic choice goes through the injected, seeded `rng` — never
`random` at module scope — so decisions replay exactly. A policy also declares
`name`, `version`, and `hash` (of its params); all three land in every
`route_decided` event.

Policies never see restricted models: `ModelRegistry.candidates()` filters
`restricted`, the allowlist, and required capabilities *before* selection, and
`Router.route()` rejects anything outside that set even if the policy asks
for it. Customer constraints beat policy output, always — a learned policy
downloaded later cannot widen the allowlist, raise the budget, or reach a
restricted model.

## TieredPolicy `[built]` — the v0.1 default

Interpretable rules, no learning. It exists to make the ledger useful before
any intelligence does.

### Selection

1. Derive a **minimum tier** from task features:

   | risk | scope | min tier |
   | --- | --- | --- |
   | high | multi_module / repo_wide | frontier |
   | high | smaller | balanced |
   | medium | repo_wide | frontier |
   | medium | smaller | balanced |
   | low/unknown | multi_module / repo_wide | balanced |
   | low/unknown | smaller | cheap |

2. Pick the cheapest candidate (by expected blended cost for the scope's
   typical token counts) at or above that tier. If none qualify, take the
   cheapest eligible and say so in the reason.
3. Optional `epsilon` exploration picks uniformly at random instead —
   seeded, and the logged `selection_probability` reflects the mixture
   (needed later for unbiased offline evaluation).

### Recovery — where the interesting logic lives

`recover(state, constraints, registry)` walks a strict ladder:

- **finalized or budget exhausted → stop.** Budgets are hard walls.
- **no attempts → continue.**
- **max_attempts reached → stop.**
- **last call had `api_error` → retry same model** (provider failure, not
  capability).
- **verification passed → continue.**
- **no conclusive verification → continue** (keep going, evidence pending).
- **retryable failure** (`timeout`, `rate_limit`, `overloaded`,
  `connection_error`, `parse_error`) **→ retry same model.**
- **capability failure** (`test_failure`, `compile_error`, `wrong_output`, …)
  **→ escalate** to the cheapest model in the next tier up — *if* the
  escalation fits the remaining budget, priced properly:

## The switching-cost model — the part everyone else skips `[built]`

```
est_escalation_cost =
    target.switch_cost_usd(context_tokens)      # KV-cache rewrite
  + target.cost_usd(expected_in, expected_out)  # the new attempt itself
```

`context_tokens` is the largest input size seen in the attempt — the warm
context the new model must **re-ingest at full price**, because KV cache does
not transfer between models. Routing that ignores this produces decisions
that are locally sensible and globally expensive; Not Diamond's literature
makes the same point, and it's why "just switch to the cheaper model" often
costs *more* mid-session.

If that estimate exceeds `budget_remaining`, the action is `stop` with the
numbers in the reason — never a silent overrun. If no higher-tier candidate
exists, fall back to retry/stop per remaining attempts.

## Cost accounting

- `ModelSpec.cost_usd(in, out, cached_in)` — priced per million tokens;
  cached input billed at `cached_input_price` when set.
- `ModelSpec.switch_cost_usd(context_tokens)` — `context_tokens ×
  input_price`; no cache credit, since the cache can't move.
- Decision estimates use a small per-scope token-expectation table —
  labeled as estimates, never mixed with measured usage.
- **Measured** costs come from provider-reported usage, or from the frozen
  price snapshot — never from live registry prices.

## What a learned policy will look like `[planned]`

Same protocol, richer internals: success-probability estimates per
(task-feature, model) cell updated from ledger outcomes, calibrated
escalation thresholds, still pure and seeded. Offline evaluation replays the
ledger with importance-weighted estimators before any candidate replaces the
rules — see [08](08-roadmap.md).
