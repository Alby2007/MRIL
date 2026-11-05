# MRIL — Model Routing Intelligence Layer

Local-first, verified-outcome-aware model routing for coding agents.

MRIL makes existing coding agents cheaper to operate without sacrificing task
completion quality. It sits inside the agent harness: the developer owns
execution, MRIL owns routing intelligence, and any hosted service is optional
and out of the critical path.

## The boundary

| Responsibility | Owner |
| --- | --- |
| Editing files, running tools, sandboxing | Agent harness |
| Calling models, provider credentials | Existing gateway / harness |
| Choosing models, retry/escalation decisions | MRIL |
| Recording outcomes, learning from them | MRIL ledger |

MRIL is a **decision engine, not a model gateway**. Gateway-level retries
(timeouts, rate limits) stay in LiteLLM or your provider client; MRIL-level
escalation happens when generated code *fails verification*. Its cost model
prices the KV-cache rewrite that a mid-session model switch forces — the cost
naive routers ignore.

## The SDK — three operations

```python
router = Router(store, registry, policy, default_constraints)

decision = router.route(ctx, constraints)        # -> RoutingDecision
router.observe_invocation(decision_id, ...)      # usage, cost, errors
router.observe_verification(attempt_id, status)  # verifier evidence
action = router.next_action(task_id)             # continue | retry | escalate | stop
router.finalize(task_id)                         # verified terminal outcome
```

## Non-negotiable invariants

- **Local-first**: no network call in the decision path; all state in SQLite.
- **Never block the agent**: a policy/learner error produces a `degraded`
  decision on the configured fallback model — it never raises into the harness.
- **Never route to a restricted model**, even if the policy suggests one.
- **Never treat missing verification as success** — finalize derives
  `inconclusive`.
- **Never silently bypass a budget**: `next_action` returns `stop`.
- **Reproducible decisions**: same context + registry + policy + seed → same
  decision. Every decision logs policy/registry hashes, seed, price snapshot,
  and the selection probability needed for later off-policy evaluation.

## The event contract

Append-only, schema-versioned (`mril.event.v1`), idempotent by `event_id`:

`TaskStarted → RouteDecided → ModelInvocationFinished → VerificationCompleted
→ RecoveryDecided → TaskFinalized`

Step-level fields (`step_index`, `call_site`) are in the schema from day one so
per-call routing can be adopted without re-instrumenting adapters.

## Layout

```
mril/
  core/      events, models/registry, task context, decisions — zero I/O
  policy/    policy interface, TaskState replay, TieredPolicy (v0.1 rules)
  store/     EventStore protocol; SQLite + in-memory implementations
  adapters/  harness integrations (langchain middleware; duck-typed)
  telemetry/ aggregate summaries over the ledger
  cli.py     mril explain / task / tasks
examples/    runnable flows
tests/
```

## Quick start

```bash
pip install -e ".[dev]"
pytest
python examples/basic_routing.py
mril --db demo.db task issue-1842
mril --db demo.db explain <decision_id>
```

Real-agent demo (LangChain + Ollama + real pytest verification):

```bash
pip install -e ".[langchain]"
ollama serve &
# see examples/langgraph_agent.py header for the two `ollama create` lines
python examples/langgraph_agent.py
mril --db langgraph.db task palindrome-1
```

## Roadmap

- **M1 (here)**: event contract, ledger, deterministic tiered routing,
  recovery with switching-cost model, LangChain middleware, explain CLI.
- M2: richer LangGraph/Deep Agents checkpoint integration, verification
  ingestion from real test runners.
- M3: offline policy evaluation over the ledger (IPS/DR using logged
  selection probabilities), then conservative learned policies.
- M4: optional managed control plane — versioned policy artifacts, opt-in
  metadata-only telemetry sync.
