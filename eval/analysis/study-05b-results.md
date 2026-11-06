# Study 05B Results — Recovery Information Value

**Protocol.** 20 corpus-s05 tasks × cheap-first × 4 seeds = 80 harvest runs
(`eval/runs/study-05b-harvest/`), `--capture-failures` snapshotting every failed
attempt. 79 checkpoints captured; **51 weak-failure attempt-0 checkpoints** met
the probe contract (`model_id=weak-coder`, non-`verifier_error`). Each checkpoint
was replayed once under each handoff arm from the identical workspace state,
same strong recovery model (`qwen2.5:14b`), same generation seed — 102 probes.
Leak audit passed on all checkpoints before any model call (commit `d724831`).

## Headline: compatible with zero; at most a small signal

| arm | verified | rate |
|---|---|---|
| handoff-current (sanitized counts+category sentence) | 20/51 | **0.392** |
| handoff-structured (Recovery-context block) | 23/51 | **0.451** |

**Discordant pairs: 3** — all favor structured
(`bug-state-undo` seeds 0 & 2; `impl-contract-iter` seed 2). One further pair
differed on inconclusive-vs-fail (`bug-cross-lexer` seed 1) — counted as
non-decisive. Sign test on 3/3 discordants: p = 0.125 — **not significant**.

Paired per-checkpoint difference: +0.059 for structured. Task-clustered
(14 task-groups, seeds highly correlated within task) the effective n is ~14;
per-task deltas are non-zero on exactly 2 tasks:

| task | current | structured |
|---|---|---|
| bug-state-undo | 0.25 | **0.75** |
| impl-contract-iter | 0.50 | **0.75** |
| (all 12 others) | identical | identical |

A task-clustered bootstrap would comfortably include zero. **No reliable
improvement demonstrated.**

## Secondary metrics — the challenger is not more expensive

| arm | median input tok | median output tok | median latency |
|---|---|---|---|
| current | 292 | 177 | 6995 ms |
| structured | 309 (+6%) | 170 | 6314 ms |

The structured block adds ~17 input tokens and shows no latency penalty —
cost-neutral within noise. If it ever helped, it would be nearly free. At this
sample size it doesn't demonstrably help.

## The finding that matters more than the headline

**Sanitized-current rescue = 0.392 — statistically indistinguishable from the
leaky-era 0.39–0.42 escalation rates** (Study 04/05A, where `stdout[-2000:]`
carried test source, expected values, and test names). Stripping the answer key
did not collapse rescue on this corpus. The legitimate information channel —
**the failed code plus coarse outcome counts** — is what carries the recovery
value; hidden-verifier detail was contributing little-to-nothing on s05 tasks.

Caveat: s05 verifiers leak *less informative* answers than s04's assertion-heavy
suites, and the leaky rate was measured on different corpora — cross-corpus
comparison is descriptive, not causal. But within-corpus, clean-feedback rescue
is real and substantial.

## Verdict per the stopping rule

- Structured handoff ≠ demonstrated improvement → **do not build a learned
  context planner.** The packaging variable is spent.
- Recovery-context optimization as a lever is **null on this axis**: what
  mattered was never *how* the counts are phrased.
- What remains open (not tested here): *richer* legitimate content — e.g. a
  diff of what the code did vs what the spec said, multi-hypothesis prompts,
  or passing the task spec's own contract text back in. Those change
  *information content*, not packaging, and would need a new checkpoint
  contract.

## Strategic position (updated evidence table)

| intelligence layer | status |
|---|---|
| pre-execution routing features | insufficient vs cheap-first (S04) |
| recovery action selection | fixed map already on the observed-best cell (05A) |
| recovery context *packaging* | **null — no demonstrated value (05B)** |
| legitimate-info rescue channel | **real: ~39% rescue on clean feedback** |

MRIL's evidence-backed shape remains: cheap-first routing + reliable escalation
+ rigorous observability. The escalation channel works at ~39% with honest,
leak-free handoff — that reliability is the product's defensible core.
