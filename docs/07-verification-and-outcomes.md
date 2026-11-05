# 07 — Verification & Outcomes

MRIL's quality claim reduces to one sentence: **we only learn from, and only
report, verified outcomes.** Everything in this doc follows from that.

## The outcome taxonomy

Per attempt, `verification_completed.status`:

| status | meaning |
| --- | --- |
| `passed` | a verifier produced positive evidence |
| `failed` | a verifier produced negative evidence |
| `inconclusive` | no evidence, or evidence that can't be trusted |

Per task, `task_finalized.task_outcome`:

| outcome | derived when |
| --- | --- |
| `verified_success` | last attempt's verification passed |
| `verified_failure` | last attempt's verification failed |
| `inconclusive` | anything else — the honest default |
| `cancelled` | caller ended it |
| `infrastructure_error` | the run failed for infra reasons |

If `finalize()` is called without an explicit outcome, it is *derived* — and
**missing verification derives `inconclusive`, never success.** This is the
single most important honesty rule in the system: a silent gap in the
pipeline cannot manufacture a win. It's enforced in `Router._derive_outcome`
and tested (`test_finalize_derives_inconclusive_without_verification`).

## Verifier quality is first-class

Not all evidence is equal, so `verification_completed` carries
`verifier_type` (`test | build | typecheck | lint | llm_judge | human`) and
`confidence`. Consequences, current and planned:

- **Policy weighting `[planned]`**: a learned policy should weight outcomes
  by verifier strength — an `llm_judge` "pass" and a green `test` suite are
  not the same evidence.
- **The circularity trap**: if the judge is a model, "verified" is only as
  strong as the judge. LLM-judged outcomes should be flagged as such rather
  than blended with test results.
- **MRIL's quality floor is the customer's CI.** If the repo's tests are
  weak, `verified_success` means less. We can record and weight verifier
  strength; we cannot manufacture evidence the harness doesn't produce.

## `failure_category` — the recovery signal

Verification isn't just pass/fail; *why* it failed drives recovery:

- **Infra-shaped** (`timeout`, `rate_limit`, `overloaded`,
  `connection_error`, `parse_error`) → retry same model. The model wasn't
  the problem.
- **Capability-shaped** (`test_failure`, `compile_error`, `wrong_output`,
  `security_finding`, …) → escalate. The model was.

The categories are the feature a learned policy will consume — the reason
they're in the contract rather than buried in a message field.

## Why this matters commercially

"38% cheaper with quality held" is only a sellable claim if the quality side
is *real*. Verified rates computed over `verified_*` outcomes only —
`telemetry.verified_rate()` refuses to count inconclusive tasks — are the
difference between a metric a team can defend to their CFO and a number that
collapses under scrutiny.
