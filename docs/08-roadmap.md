# 08 — Roadmap

Where we are, what we learned building it, and what's next — in that order,
because the order is the point.

## M1 — Routing foundation `[built]`

Done and tested: the event contract, SQLite + memory ledgers (idempotent by
`event_id`), deterministic TieredPolicy with the switching-cost model, the
`route/observe/next_action/finalize` SDK with all failure invariants, the
LangChain adapter (sync + async), the explain/task/tasks CLI, and a real
end-to-end run on a live agent.

**The spike paid for itself.** Three bugs that only existed in the real
world: `after_agent` fired per-invoke and closed tasks early; "attempt"
counted model calls instead of agent runs; Ollama mangles tool args. All
fixed and documented — see [06](06-harness-integration.md).

## v0.2 — Empirical validation `[building]`

Ledger hardening landed first: logical idempotency (`dedupe_key` per event
type — invocation steps, verification run ids, recovery checkpoints,
single-finalize), measured-vs-estimated switch-cost accounting
(`actual_switch_cost_usd` + `switch_cost_basis`), marginal-propensity
logging, and the `RecoveryContext` decision-time snapshot that makes
recovery decisions independently replayable.

The evaluation harness (`mril/eval/`) is scaffolded and tested: immutable
JSON task specs with sha256-pinned snapshots, per-run workspace
materialization, hidden verifiers restaged each run, three interchangeable
arms (strongest-only / cheap-first / mril-tiered) behind one strategy
contract, ledger-derived results, and a guardrailed report — min cost
subject to verified-completion within δ of the ceiling arm. Local cost
figures are labeled `synthetic_token_price`, never billed money.

Exit criteria: same task across all arms `[met in tests]` · real capability
gap `[pending: needs distinct-size Ollama models]` · fresh state per run
`[met]` · agent can't touch the verifier `[met — tests run in a workspace
copy, never beside the agent]` · all
calls in ledger `[met]` · replay from manifest `[met]` · report covers
quality+spend+latency `[met]`. The corpus itself — 30–50 varied tasks — is
the remaining work, and a rigorous negative result still counts.

## M2 — Working coding-agent integration `[next]`

- **Feature provenance.** `feature_extractor` currently returns declared or
  static features. Next: a real profiler — cheap-model task classification
  with caller override — because nobody will label `task_type`/`risk` by hand.
- **Checkpoint-level recovery** on a real LangGraph/Deep Agents loop: today
  the demo drives attempts by re-invoking the agent; real integration steers
  the *same* run at checkpoints.
- **Verification ingestion from real runners**: parse pytest/CI output into
  `failure_category`, not just pass/fail. The categories are the feature the
  learned policy will eat.
- **Per-step policies**: the schema supports `step_index`/`call_site`
  already; policies don't use them yet. This is where the interesting money
  is — summarization and retrieval steps don't deserve frontier prices.

## M3 — Self-learning runtime `[planned]`

- Offline policy evaluation over the ledger: replay with the logged
  `selection_probability` (inverse-propensity / doubly-robust estimators) to
  score candidate policies without new traffic. This is why the probability
  was logged from day one.
- Conservative local learning: success/cost estimates per (task-feature ×
  model) cell, epsilon-bounded exploration, interpretable only — neural
  routers come later if ever.
- Acceptance bar for any candidate: beat the static tiered baseline on
  verified-completion *and* cost on held-out replay, or it doesn't ship.

## M4 — Managed control plane `[planned]`

- Opt-in metadata-only sync (never prompts/diffs/keys), versioned signed
  policy artifacts, local validation before activation — and a downloaded
  policy **cannot** widen the allowlist, raise the budget, or reach a
  restricted model.
- Self-hosted multi-worker mode first (shared Postgres ledger + shared
  policies), then hosted. Org-wide budget caps need a shared quota service;
  per-worker enforcement already exists.

## Open questions we're carrying deliberately

1. **Does local learning ever have enough data?** A small team generates
   hundreds of verified tasks/month — probably not enough to beat rules for
   a long time. The observability value stands alone; learning is honest
   upside, not the pitch.
2. **Where does exploration budget live?** Production epsilon-exploration
   costs real money on deliberately-suboptimal routes. Off-policy replay
   from logged propensities may do most of the work — that's the bet.
3. **The market boundary.** Instrumentable harnesses only (LangGraph, Open
   SWE, custom). Closed agents (Claude Code, etc.) are out — unless a
   gateway-level variant emerges that can see verification some other way.
4. **Not Diamond exists.** Closed, proprietary, well-marketed, similar
   claims. Our edge: open-source, local-first, verified-outcome learning on
   the customer's own data. The positioning has to be honest about that.

## The acceptance criteria for v0.1 (restated)

Integration without modifying the harness core `[met — middleware only]` ·
offline operation `[met]` · enforced model restrictions `[met, tested]` ·
reproducible decision logs `[met, tested]` · no regression in verified task
completion vs. baseline `[met on the demo; unproven at scale — that's M3's
job to measure]`.
