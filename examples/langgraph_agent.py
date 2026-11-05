"""Real end-to-end MRIL integration: a LangChain agent + Ollama + pytest.

This is the spike that matters: does instrumentation survive a real agent run?

- A real `create_agent` graph generates a solution as a reply.
- The driver extracts the code, writes it, and runs a real `pytest` —
  verification evidence, not vibes.
- MRILMiddleware routes every model call (the agent's default model is the
  frontier one; the middleware must actually *override* it).
- On failure, next_action() escalates and the retry runs on the big model.

Requires: `ollama serve` running. The two tiers are derived from local weights
(`mril-weak`: 14b @ repeat_penalty 1.9 — deliberately degraded output;
`mril-strong`: 14b @ temp 0) so the demo works offline:
  ollama create mril-weak   -f <(printf 'FROM qwen2.5:14b\nPARAMETER repeat_penalty 1.9\nPARAMETER num_predict 1024')
  ollama create mril-strong -f <(printf 'FROM qwen2.5:14b\nPARAMETER temperature 0\nPARAMETER num_predict 2048')
Prices are synthetic — local models don't bill per token; they exist so cost
accounting and escalation estimates are exercised.

Run:  python examples/langgraph_agent.py
Then: mril --db langgraph.db task palindrome-1
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints
from mril.adapters.langchain import MRILMiddleware
from mril.policy.tiered import TieredPolicy
from mril.store.sqlite import SQLiteEventStore

TASK_ID = "palindrome-1"
WORKDIR = Path(tempfile.mkdtemp(prefix="mril-agent-"))

registry = ModelRegistry(
    version="local-ollama",
    models=(
        ModelSpec("qwen-small", provider="ollama", tier="cheap",
                  input_price=0.10, output_price=0.30),
        ModelSpec("qwen-large", provider="ollama", tier="frontier",
                  input_price=5.00, output_price=25.00),
    ),
)
MODELS = {
    "qwen-small": ChatOllama(model="mril-weak"),
    "qwen-large": ChatOllama(model="mril-strong"),
}

router = Router(
    store=SQLiteEventStore("langgraph.db"),
    registry=registry,
    policy=TieredPolicy(),
    default_constraints=RoutingConstraints(
        fallback_model_id="qwen-large", budget_usd=1.0, max_attempts=3
    ),
)
middleware = MRILMiddleware(
    router,
    MODELS,
    constraints=RoutingConstraints(budget_usd=1.0, max_attempts=3),
    feature_extractor=lambda req: {
        "task_type": "feature",
        "scope": "single_file",
        "risk": "low",
        "language": "python",
        "harness": "langchain-create_agent",
    },
    task_id=TASK_ID,
)

SOLUTION = WORKDIR / "solution.py"

# The agent's default model is the expensive one — the middleware must
# genuinely override it to prove routing happens.
agent = create_agent(model=MODELS["qwen-large"], middleware=[middleware])

PROMPT = (
    "Write a Python module implementing is_palindrome(s: str) -> bool. It "
    "must return True for palindromes while ignoring case and all "
    "non-alphanumeric characters, e.g. 'A man, a plan, a canal: Panama' -> "
    "True, 'hello' -> False, '' -> True. Reply with only the code."
)

TEST_SRC = textwrap.dedent(
    """
    from solution import is_palindrome

    def test_phrase():
        assert is_palindrome("A man, a plan, a canal: Panama")

    def test_negative():
        assert not is_palindrome("hello world")

    def test_empty():
        assert is_palindrome("")

    def test_case():
        assert is_palindrome("RaceCar")
    """
)


def extract_code(messages: list) -> str | None:
    """Pull a Python implementation out of the agent's reply."""
    content = ""
    for m in reversed(messages):
        c = getattr(m, "content", "")
        if isinstance(c, str) and c.strip():
            content = c
            break
    if not content:
        return None
    fenced = re.search(r"```(?:python)?\s*(.*?)```", content, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    if "def is_palindrome" in content:
        return content.strip()
    return None


def verify() -> bool | None:
    """Real verification: run pytest on the generated solution."""
    if not SOLUTION.exists():
        return None
    (WORKDIR / "test_solution.py").write_text(TEST_SRC)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "test_solution.py"],
        cwd=WORKDIR, capture_output=True, text=True, timeout=120,
    )
    return proc.returncode == 0


def run_attempt(step: int) -> bool | None:
    """Invoke the agent once, then verify what it produced."""
    SOLUTION.unlink(missing_ok=True)  # verify this attempt's artifact
    result = agent.invoke({"messages": [HumanMessage(PROMPT)]})
    print(f"  agent finished: {len(result['messages'])} messages")

    code = extract_code(result["messages"])
    if code is not None:
        SOLUTION.write_text(code)
        print(f"  extracted {len(code)} bytes of code")
    else:
        print("  no code extracted")

    passed = verify()
    events = router.store.events_for_task(TASK_ID)
    invs = [e for e in events if e.event_type == "model_invocation_finished"]
    if invs:
        middleware.report_verification(
            invs[-1].attempt_id, passed, verifier_type="test",
            failure_category=None if passed else "test_failure", task_id=TASK_ID,
        )
    return passed


def main() -> int:
    print(f"workdir: {WORKDIR}")

    passed: bool | None = None
    for step in range(3):
        print(f"[{step}] agent attempt")
        passed = run_attempt(step)
        print(f"  verification: {passed}")
        if passed is True:
            break
        action = router.next_action(TASK_ID)
        print(f"  next_action -> {action.type.value} {action.model_id or ''}")
        print(f"    {action.reason}")
        if action.type.value == "stop":
            break
        if action.type.value == "escalate" and action.model_id:
            middleware.constraints = RoutingConstraints(
                allowed_models=(action.model_id,), budget_usd=1.0, max_attempts=3
            )

    fin = router.finalize(TASK_ID)
    print(f"\noutcome={fin.task_outcome.value}  cost=${fin.total_cost_usd:.4f}  "
          f"attempts={fin.attempt_count}")
    print(f"inspect: mril --db langgraph.db task {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
