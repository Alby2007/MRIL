# Study 05B — Recovery Information Value

Status: DESIGN. Development lineage: all prior studies (01–05A) inform it;
the evaluation corpus is `corpus-s05` (frozen at commit 2d8dbb4), unseen by
any of the findings below.

## 0. Leakage audit result (prerequisite — resolved)

The current rescue handoff is `verdict.stdout[-2000:]` — raw pytest output.
Audited output shows it leaks **hidden-verifier content**:

- test source context (`>   assert sliding_max([1,2,3], 2) == [2, 3]`)
- expected values verbatim (`E   assert [2] == [2, 3]`)
- test names (`test_full_window`) and verifier file paths

Consequences:
- All previously measured rescue yields (~39–42%) were achieved WITH leaked
  answer-key material. They are upper bounds on legitimate-information
  rescue, not clean estimates.
- Both Study 05B arms must receive sanitized feedback only — the comparison
  isolates *packaging of identical legitimate information*, never amount.

Sanitization contract (deterministic, unit-tested):
KEEP: pass/fail counts ("3 of 5 checks failed"), failure category, exit
status. STRIP: `>` source-context lines, `E` assertion-detail lines,
expected-value reprs, test names, `verifiers/` + `test_*.py` paths.
Note: test names are excluded — they leak semantic hints (e.g.
`test_evicts_oldest_fresh`). A name-included variant is documented as a
sensitivity probe only, never a frozen arm.

## 1. What 05A established (the negative result that motivates this)

| first-failure action | success | n |
|---|---|---|
| weak → strong (rescue) | 39% | 33 |
| weak → weak (retry)    | 4%  | 26 |
| strong → strong (retry)| 12% | 16 |
| strong → weak (downgrade) | 0% | 17 |

The deterministic escalation map already selects the best observed action
at the dominant checkpoint. Alternative *model* actions are dead or
marginal under observed yields (with stated uncertainty — 0/17 is not
proof of impossibility). The remaining improvement surface is the
*information* the recovering model receives, or attempt-budget
allocation — not action choice.

## 2. Hypothesis

For a fixed failed task state and fixed recovery model, a **structured
diagnostic handoff** improves verified recovery efficiency vs the current
handoff format — at comparable token cost. Null: packaging doesn't
matter; only information content (and the model's own competence) does.
Either outcome is informative.

## 3. Design

- Initial routing: **frozen weak-first** (deterministic, not randomized)
- Recovery action: **frozen weak → strong** — the empirically best cell
- Experimental variable: recovery-context construction
  - **Control** `handoff-current`: prior code + sanitized outcome block
    ("Verification failed: k of n checks failed (category).")
  - **Challenger** `handoff-structured`: prior code + structured
    diagnostic block — same legitimate facts, explicitly organized:
    category, counts, a normalized per-category description line
    (e.g. assertion → "implementation produced wrong values on k checks";
    contract → "interface mismatch: missing or mis-named symbols").
- Same strong model, seeds, limits, verifier, pricing everywhere.

## 4. Matched-state protocol (primary)

Checkpoint capture + replay — isolates handoff effect from upstream
weak-generation variance:

1. **Harvest**: weak-first runs on corpus-s05 (20 tasks × 4 seeds).
   At each first-attempt failure, persist a self-contained checkpoint:
   `{checkpoint_id, task_id, seed, workspace files at failure, raw
   feedback (audit only), sanitized feedback, category, spec digest,
   registry hash, corpus version}`.
2. **Probe**: `mril eval rescue-probe` replays each checkpoint under BOTH
   arms — same workspace, same strong model, per-(checkpoint, arm) draw
   seed — then verifies. Fully paired by construction: each checkpoint
   yields one control and one challenger outcome.
3. Fallback (if capture proves infeasible): within-run randomization of
   handoff variant at the rescue checkpoint; higher variance, same arms.

Expected yield: ~40–70 weak-fail checkpoints at 4 seeds (weak fail rate
on s05 unknown; dev-corpus rate ≈ 50%). Each pair is one discordant-vote
opportunity — power is the binding constraint (§6).

## 5. Metrics

- **Primary**: verified recovery rate per checkpoint — paired comparison,
  McNemar-style discordant-pair analysis; task-clustered uncertainty.
- **Secondary**: total task cost (synthetic, labeled estimate), wall
  latency, **handoff input-token size** — a structured handoff that costs
  3× the tokens needs a proportionally better yield to be interesting.
- Reported: support counts per cell, no smoothing of sparse cells,
  no savings claims.

## 6. Pilot gate + sizing

Before the frozen probe: harvest ~10 checkpoints, run both arms, confirm
the two handoffs (a) are sanitization-clean (no leaked content in either
prompt — audited), and (b) produce non-identical strong-model behavior at
least sometimes (if outputs are bitwise-similar on every probe, the
intervention is inert — stop, document, don't scale).

Sizing honesty: 40–70 pairs detects only a large effect (≳15–20pp) with
useful confidence. A small positive effect will read as "compatible with
zero" — report it as such, don't narrate it as evidence of value.
A secondary dev-corpus cohort (same arms, exploratory label only) may be
added purely to size the effect; corpus-s05 remains the confirmatory set.

## 7. Safeguards

- Both arms' templates versioned + hashed into arm fingerprints; frozen
  before any probe. No template edits after seeing probe outputs.
- Sanitizer unit-tested: assert zero occurrences of `>`, `E `, `assert`,
  `test_`, `verifiers/` in sanitized output across all observed failure
  outputs in the collection ledger.
- Checkpoints immutable once written; probe arms see identical workspace
  bytes (hash-checked per checkpoint).
- **Stopping rule**: if handoff quality shows no value, do not build a
  learned context planner for architectural completeness.
- The sanitizer is an *experiment-scoped* change: making sanitized
  feedback the harness default alters what frozen baselines see — that is
  a separate protocol decision, deferred until 05B results exist.

## 8. Deliberately deferred

- Attempt-budget planner V(s,b): real direction, insufficient multi-step
  coverage today; a planner must first beat escalate-once under the same
  quality constraint on held-out data.
- Category-conditioned recovery: underpowered differential (assert 43%
  vs runtime 30%, overlapping CIs); coarse labels may be the wrong
  abstraction regardless — structure/feedback quality is the better lever.
- Learned recovery policies of any kind until 05B resolves whether
  context quality is a lever at all.
