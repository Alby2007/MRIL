"""Verified escalation in a real LangChain agent — fully offline.

The acceptance slice for the v0.3 developer preview:

- `create_agent().ainvoke()` runs a cheap model that produces buggy code.
- A real subprocess verifier runs the artifact's tests — evidence, not
  vibes — and feeds the verdict to MRIL.
- `router.next_action()` escalates; the retry is constrained to the
  frontier model and verifies green.
- Every decision lands in the ledger for `mril task` / `mril explain`.

Requires: `pip install -e ".[langchain]"` — no Ollama, no network, no
API keys. langchain_core's FakeListChatModel stands in for the two tiers;
swap MODELS for `ChatOllama`/`ChatAnthropic`/etc. to go live (see
examples/langgraph_agent.py for a local-weights variant).

Run:  python examples/langchain_verified_escalation.py
Then: mril --db verified-escalation.db task demo-escalation
      mril --db verified-escalation.db explain <decision_id>
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints
from mril.adapters.langchain import MRILMiddleware
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore

TASK_ID = "demo-escalation"
DB = Path("verified-escalation.db")
WORKDIR = Path(tempfile.mkdtemp(prefix="mril-escalation-"))

# The weak tier always returns buggy code; the frontier tier returns the fix.
# FakeListChatModel cycles responses, so behavior is deterministic.
BUGGY = "def add(a: int, b: int) -> int:\n    return a - b\n"
FIXED = "def add(a: int, b: int) -> int:\n    return a + b\n"

registry = ModelRegistry(
    version="demo-1",
    models=(
        ModelSpec("weak-coder", provider="local", tier="cheap",
                  input_price=0.10, output_price=0.30),
        ModelSpec("strong-coder", provider="local", tier="frontier",
                  input_price=5.00, output_price=25.00),
    ),
)
MODELS = {
    "weak-coder": FakeListChatModel(responses=[BUGGY]),
    "strong-coder": FakeListChatModel(responses=[FIXED]),
}

router = Router(
    store=SQLiteEventStore(str(DB)),
    registry=registry,
    policy=TieredPolicy(),
    default_constraints=RoutingConstraints(
        fallback_model_id="strong-coder", budget_usd=1.0, max_attempts=3
    ),
)
middleware = MRILMiddleware(
    router,
    MODELS,
    constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
    feature_extractor=lambda req: {
        "task_type": "bugfix",
        "scope": "single_file",
        "risk": "low",
        "language": "python",
        "harness": "langchain-create_agent",
    },
    task_id=TASK_ID,
)

# The agent's default model is the frontier one — the middleware must
# genuinely override it to prove routing happens.
agent = create_agent(model=MODELS["strong-coder"], middleware=[middleware])

PROMPT = (
    "Write a Python module implementing add(a: int, b: int) -> int that "
    "returns the sum of a and b. Reply with only the code."
)

TEST_SRC = textwrap.dedent(
    """
    from solution import add

    assert add(2, 3) == 5, "add(2, 3) should be 5"
    assert add(-1, 1) == 0, "add(-1, 1) should be 0"
    """
)

SOLUTION = WORKDIR / "solution.py"


def verify() -> bool | None:
    """Real verification: a subprocess runs the test file; a nonzero exit
    is a failure. No pytest needed — keeps the example stdlib-only."""
    if not SOLUTION.exists():
        return None
    (WORKDIR / "test_solution.py").write_text(TEST_SRC, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "test_solution.py"],
        cwd=WORKDIR, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    return proc.returncode == 0


def last_attempt_id() -> str | None:
    invs = [
        e
        for e in router.store.events_for_task(TASK_ID)
        if e.event_type == "model_invocation_finished"
    ]
    return invs[-1].attempt_id if invs else None


async def run_attempt() -> bool | None:
    """Invoke the agent once, then verify what it produced."""
    SOLUTION.unlink(missing_ok=True)
    # Stale bytecode would silently re-verify the PREVIOUS attempt's code:
    # same size + coarse mtime => the interpreter reuses the cached .pyc.
    shutil.rmtree(WORKDIR / "__pycache__", ignore_errors=True)
    result = await agent.ainvoke({"messages": [HumanMessage(PROMPT)]})
    content = result["messages"][-1].content
    if isinstance(content, str) and content.strip():
        SOLUTION.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"  extracted {len(content)} bytes of code")
    else:
        print("  no code extracted")
    passed = verify()
    attempt_id = last_attempt_id()
    if attempt_id is not None:
        middleware.report_verification(
            attempt_id,
            passed,
            verifier_type="test",
            failure_category=None if passed else "test_failure",
            task_id=TASK_ID,
        )
    return passed


async def main() -> int:
    print(f"workdir: {WORKDIR}\nledger:  {DB.resolve()}")

    for step in range(3):
        print(f"[{step}] agent attempt")
        passed = await run_attempt()
        print(f"  verification: {passed}")
        if passed is True:
            break
        action = router.next_action(TASK_ID)
        print(f"  next_action -> {action.type.value} {action.model_id or ''}")
        print(f"    {action.reason}")
        if action.type.value == "stop":
            break
        if action.model_id:
            middleware.constraints = RoutingConstraints(
                allowed_models=(action.model_id,),
                budget_usd=1.0,
                max_attempts=3,
            )

    fin = router.finalize(TASK_ID)
    print(f"\noutcome={fin.task_outcome.value}  cost=${fin.total_cost_usd:.4f}  "
          f"attempts={fin.attempt_count}")
    print(f"inspect: mril --db {DB} task {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
