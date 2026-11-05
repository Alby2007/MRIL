# Study 05 — randomized recovery collection design

Status: DESIGN. Derived entirely from development ledgers (study-01..04 +
corpus-s04). Any challenger policy produced from this data is a *development
artifact* — it must be frozen and evaluated on a fresh corpus before any
generalization claim. Study 04 data is development data for Study 05.

Motivation: the offline audit (study-05-offline-recovery.md) showed the
current recovery map is deterministic on (last_model, attempt_count):
weak@1→escalate, strong@1→retry, anything@2→stop. Zero within-cell action
variation means no challenger policy is evaluable from existing data. This
study manufactures propensity coverage under explicit randomization.

## 1. Instrumentation fix (lands BEFORE collection)

`runner.py:121` currently hardcodes every failure as `"test_failure"`.
Replace with an ordered classifier over `Verdict`:

```python
def _failure_category(verdict: Verdict) -> str | None:
    if verdict.passed:
        return None
    if verdict.passed is None:
        return "verify_timeout" if verdict.timed_out else "verifier_error"
    out = verdict.stdout
    if re.search(r"SyntaxError|IndentationError|ERROR collecting", out):
        return "syntax_error"      # code does not parse/import
    if re.search(r"ImportError|ModuleNotFoundError|AttributeError|NameError", out):
        return "contract_error"    # missing / mis-named symbols
    if re.search(r"assert|AssertionError|Failed:", out):
        return "assertion_failure" # wrong answer, valid execution
    if re.search(r"\bError\b", out):
        return "runtime_error"     # non-assertion exception mid-test
    return "test_failure"          # fallback
```

Constraints:
- `verify_timeout` is deliberately NOT named `timeout`: `timeout` is in
  `_RETRYABLE_FAILURES` (transient-provider semantics). Keeping verifier
  categories disjoint from retryable set preserves existing arms' recovery
  behavior exactly — every new category is a non-retryable capability
  failure, same as `test_failure` was. Frozen arms are unchanged.
- Classification is deterministic string matching on observed verifier
  output — no model calls, no learned component.
- `Retryable` semantics unchanged; `api_error` path untouched.

## 2. Collection policy — RandomizedRecoveryPolicy

Deterministic initial routing, randomized recovery. Two entry arms:

| arm | initial route | recovery |
|---|---|---|
| `collect-weak` | weak-coder | randomized over feasible set |
| `collect-strong` | strong-coder | randomized over feasible set |

Feasible action sets at a failure state (subject to attempts remaining):

| state | actions |
|---|---|
| weak failed @1 (2 slots left) | {retry-weak, escalate-strong, stop} |
| weak failed @2 (1 slot left) | {retry-weak, escalate-strong, stop} |
| strong failed @1 (2 slots left) | {retry-strong, downgrade-weak, stop} |
| strong failed @2 (1 slot left) | {retry-strong, downgrade-weak, stop} |

- `downgrade-weak` is included deliberately: P(weak succeeds | strong failed)
  is unknown and the attempt costs ~$0.0001; measuring it is nearly free.
- Uniform propensities within each feasible set (1/3 or 1/2), seeded by
  decision_seed → reproducible. Exact propensity recorded on
  `RecoveryDecided.selection_probability` (field already exists).
- `stop` is a real measured action: its outcome (final failure, saved spend)
  is directly observable — no counterfactual needed.
- `max_attempts=3` stays; the collection policy ignores `failure_threshold`
  so the third slot actually receives propensity coverage.
- Budget/wall limits unchanged; `api_error` path keeps existing stop logic.

Implementation surface: one policy class (~70 lines, mirrors TieredPolicy's
recover with a sampled action set), an arms.py entry + CLI arm flag. No event
contract changes — RecoveryDecided already carries action, model_id,
selection_probability, and recovery_context.

## 3. Matrix and expected cell coverage

39 development tasks (dev-15 + s04-24) × 2 arms × 4 seeds = 312 executions.

Expected state counts (rates from pooled dev ledgers):
- weak fail @1: ~45–60 states (weak first-pass ~50–73%) → ~15–20 obs/action
- strong fail @1: ~25–35 states (strong fresh pass ~67–75%) → ~8–12 obs/action
- second-order states (fail @2): ~15–30, sparse but non-zero coverage

Precision check (Wilson CI95 half-width at p=0.3):
n=15 → ±0.23 · n=20 → ±0.20 · n=30 → ±0.16

Coarse — but the decision-relevant distinction is "weak retry ≈ 30%"
(valuable channel, near-zero cost) vs "weak retry ≈ 5%" (dead). n≈20/cell
separates those regimes. This study sizes hypotheses, it does not rank them
tightly; ranking the survivor belongs to the out-of-sample comparison.

## 4. Estimands (what the data must produce)

| estimand | current knowledge |
|---|---|
| P(weak retry passes \| weak fail) | ZERO obs — primary target |
| P(strong rescue \| weak fail) | 0.42 pooled, confounded task mix |
| P(weak rescue \| strong fail) | ZERO obs |
| P(strong retry \| strong fail @2, rescue path) | ZERO obs (3rd slot) |
| P(success) × failure category | taxonomy degenerate until §1 lands |
| cost/latency per (state, action) | partially observed, unconfounded here |

All estimates reported with Wilson CIs and distinct-task counts; repeated
seeds on one task are not independent problems.

## 5. Safeguards

- Collection data is development data. Challenger policies trained on it get
  frozen before any held-out evaluation; corpus-s05 (fresh) is required for
  the eventual comparison.
- No "policy X saves Y%" claim from randomized-collection estimates alone —
  they measure per-action success, cost, latency; the policy comparison
  happens out-of-sample.
- The failure-category fix is itself a behavior-preserving instrumentation
  change, validated by re-running a small arm spot-check (existing frozen
  arms must produce identical action sequences).
- Verifiers/corpus/tasks are not modified based on collection outcomes.

## 6. Decision rules for what follows

| collection result | next step |
|---|---|
| weak retry ≥ ~25% | challenger: retry-weak-once-then-escalate (cheap rescue) |
| strong retry @3 ≥ ~20% on rescue path | challenger: extend rescue budget on selected states |
| downgrade-weak ever succeeds | revisit single-direction escalation assumption |
| failure categories predict different recovery yields | category-conditioned challenger |
| nothing beats observed escalate/retry cells | evidence recovery is already near-optimal → value returns to initial routing with better features, or to verifier-quality improvements |
