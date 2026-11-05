# MRIL Documentation

MRIL — Model Routing Intelligence Layer. An open-source, local-first
intelligence layer that makes coding agents cheaper to run without sacrificing
verified task completion.

This folder is a reading path. Start at 01 if you want the "why", at 04 if
you want the API, at 08 if you want the plan.

| Doc | What's inside |
| --- | --- |
| [01 — Overview](01-overview.md) | The problem, the bet, who it's for, what it is not |
| [02 — Architecture](02-architecture.md) | Components, ownership boundaries, data flow |
| [03 — Event Contract](03-event-contract.md) | The append-only ledger — MRIL's most important interface |
| [04 — SDK Reference](04-sdk-reference.md) | `route / observe / next_action / finalize` in detail |
| [05 — Routing & Recovery](05-routing-and-recovery.md) | TieredPolicy, tiers, escalation, the switching-cost model |
| [06 — Harness Integration](06-harness-integration.md) | The LangChain adapter and the lifecycle semantics the spike taught us |
| [07 — Verification & Outcomes](07-verification-and-outcomes.md) | Why verified outcomes are the product's quality floor |
| [08 — Roadmap](08-roadmap.md) | Milestones, what we've learned, open questions |
| [09 — Design Decisions](09-design-decisions.md) | ADRs: the calls we've locked in and why |

**Status markers used throughout:** `[built]` = implemented and tested;
`[partial]` = exists with known gaps; `[planned]` = design intent, not code.
