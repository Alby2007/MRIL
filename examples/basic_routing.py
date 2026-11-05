"""End-to-end MRIL flow without any real model calls.

Run:  python examples/basic_routing.py
Then: mril --db demo.db task issue-1842
"""

from mril import (
    ModelRegistry,
    ModelSpec,
    Router,
    RoutingConstraints,
    TaskContext,
)
from mril.core.events import VerificationStatus
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore

registry = ModelRegistry(
    version="2026-11",
    models=(
        ModelSpec("cheap-8b", tier="cheap", input_price=0.10, output_price=0.30),
        ModelSpec("balanced-70b", tier="balanced", input_price=0.80, output_price=2.40,
                  cached_input_price=0.08),
        ModelSpec("frontier-x", tier="frontier", input_price=5.00, output_price=25.00,
                  cached_input_price=0.50),
        ModelSpec("restricted-lab", tier="frontier", restricted=True,
                  input_price=1.0, output_price=1.0),
    ),
)

router = Router(
    store=SQLiteEventStore("demo.db"),
    registry=registry,
    policy=TieredPolicy(),
    default_constraints=RoutingConstraints(
        fallback_model_id="balanced-70b",
        budget_usd=0.50,
        max_attempts=4,
    ),
)

ctx = TaskContext(
    task_id="issue-1842",
    language="python",
    task_type="bug_fix",
    scope="single_module",
    risk="low",
    harness="example",
)

# 1. Route — low-risk single-module bug fix picks the cheap tier.
d = router.route(ctx)
print(f"routed to {d.model_id}: {d.reason}")

# 2. The cheap model's attempt fails verification.
inv = router.observe_invocation(
    d.decision_id, d.model_id, task_id=ctx.task_id,
    input_tokens=14_000, output_tokens=3_800,
)
router.observe_verification(
    inv.attempt_id, VerificationStatus.FAILED,
    task_id=ctx.task_id, verifier_type="test", failure_category="test_failure",
)

# 3. MRIL recommends escalation — priced to include the KV-cache rewrite.
action = router.next_action(ctx.task_id)
print(f"next_action: {action.type.value} -> {action.model_id}")
print(f"  {action.reason}  (est ${action.estimated_cost_usd:.4f})")

# 4. The harness acts on the recovery recommendation. Routing the retry with
#    the escalated model in the allowlist keeps the ledger honest: RouteDecided
#    records what actually ran.
d2 = router.route(
    ctx,
    RoutingConstraints(
        allowed_models=(action.model_id,),
        fallback_model_id="balanced-70b",
        budget_usd=0.50,
    ),
    step_index=1,
    call_site="escalation",
)
inv2 = router.observe_invocation(
    d2.decision_id, "balanced-70b", task_id=ctx.task_id,
    input_tokens=18_000, output_tokens=4_200, cached_input_tokens=15_000,
)
router.observe_verification(
    inv2.attempt_id, VerificationStatus.PASSED,
    task_id=ctx.task_id, verifier_type="test",
)

# 5. Finalize — verified success, with full cost accounting.
fin = router.finalize(ctx.task_id)
print(f"outcome={fin.task_outcome.value}  cost=${fin.total_cost_usd:.4f}  "
      f"attempts={fin.attempt_count}  escalations={fin.escalation_count}")
