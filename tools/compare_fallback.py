"""Hand-written cheap-first fallback vs MRIL -- requirements coverage.

This is NOT a head-to-head benchmark: the baseline deliberately doesn't
implement most operational requirements, so its N/A results are missing
features, not losses. The claim this script supports is narrower and more
credible -- basic fallback is easy to write, and production-grade
accounting, isolation, verification, idempotency and decision provenance
are the additional infrastructure MRIL provides.

Everything runs offline against fake model functions; nothing here calls
a provider. The MRIL side drives the real Router + ledger so every PASS
is a live check, not a claim. Verdicts:

  PASS    guarantee demonstrably holds at runtime
  PARTIAL behavior is close but mislabeled or incomplete
  N/A     the implementation has no mechanism to evaluate -- the
          guarantee would have to be built by hand

Usage:  .venv/Scripts/python tools/compare_fallback.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mril import ModelRegistry, ModelSpec, Router, RoutingConstraints, TaskContext
from mril.core.events import VerificationStatus
from mril.policy.tiered import TieredPolicy
from mril.store.memory import MemoryEventStore

# =====================================================================
# The hand-written baseline -- what a developer actually writes first.
# ~15 lines, zero dependencies, correct for the trivial case.
# =====================================================================

CHEAP, STRONG = "cheap-coder", "strong-coder"
BUGGY = "def add(a: int, b: int) -> int:\n    return a - b\n"
FIXED = "def add(a: int, b: int) -> int:\n    return a + b\n"


def hw_generate(model_id: str, prompt: str) -> str:
    return BUGGY if model_id == CHEAP else FIXED


def hw_run_task(prompt: str, workdir: Path, verify) -> str:
    sol = workdir / "solution.py"
    for model_id in (CHEAP, STRONG):
        sol.write_text(hw_generate(model_id, prompt), encoding="utf-8")
        # Even the minimal baseline needs this: a stale .pyc makes the
        # verifier test the PREVIOUS attempt's artifact (same-size rewrite
        # within one mtime tick reuses cached bytecode). First version of
        # this function skipped it -- and reported "failure" on fixed code.
        shutil.rmtree(workdir / "__pycache__", ignore_errors=True)
        if verify():
            return "success"
    return "failure"


# =====================================================================
# The MRIL driver -- the integration a developer writes instead.
# =====================================================================

def make_router(store=None) -> Router:
    return Router(
        store=store or MemoryEventStore(),
        registry=ModelRegistry(
            version="cmp-1",
            models=(
                ModelSpec(CHEAP, provider="local", tier="cheap",
                          input_price=0.10, output_price=0.30),
                ModelSpec(STRONG, provider="local", tier="frontier",
                          input_price=5.00, output_price=25.00),
                ModelSpec("secret", provider="local", tier="frontier",
                          input_price=1.0, output_price=1.0, restricted=True),
            ),
        ),
        policy=TieredPolicy(),
        default_constraints=RoutingConstraints(
            fallback_model_id=STRONG, budget_usd=1.0, max_attempts=3
        ),
    )


MODELS = {CHEAP: lambda p: BUGGY, STRONG: lambda p: FIXED}


def mril_run_task(router: Router, task_id: str, prompt: str,
                  workdir: Path, verify) -> str:
    sol = workdir / "solution.py"
    constraints = RoutingConstraints(budget_usd=1.0, max_attempts=3)
    attempt = 0
    for _ in range(3):
        attempt += 1
        attempt_id = f"{task_id}-att{attempt}"
        decision = router.route(
            TaskContext(task_id=task_id, task_type="bugfix", scope="single_file",
                        risk="low", language="python"),
            constraints, step_index=0, call_site="model_call",
        )
        sol.write_text(MODELS[decision.model_id](prompt), encoding="utf-8")
        shutil.rmtree(workdir / "__pycache__", ignore_errors=True)
        router.observe_invocation(
            decision.decision_id, decision.model_id, task_id=task_id,
            attempt_id=attempt_id, step_index=0, call_site="model_call",
        )
        passed = verify()
        router.observe_verification(
            attempt_id,
            VerificationStatus.PASSED if passed is True
            else VerificationStatus.FAILED if passed is False
            else VerificationStatus.INCONCLUSIVE,
            task_id=task_id, verifier_type="test",
            failure_category=None if passed else "test_failure",
        )
        if passed is True:
            break
        action = router.next_action(task_id)
        if action.type.value == "stop" or not action.model_id:
            break
        constraints = RoutingConstraints(
            allowed_models=(action.model_id,), budget_usd=1.0, max_attempts=3
        )
    return router.finalize(task_id).task_outcome.value


def make_verifier(workdir: Path):
    test = workdir / "test_solution.py"
    test.write_text("from solution import add\nassert add(2, 3) == 5\n",
                    encoding="utf-8")

    def verify():
        proc = subprocess.run([sys.executable, "test_solution.py"],
                              cwd=workdir, capture_output=True, timeout=60)
        return proc.returncode == 0
    return verify


# =====================================================================
# Scenario suite -- each returns (handwritten verdict, MRIL verdict).
# =====================================================================

def s1_verify_fail_escalates(tmp):
    w1, w2 = tmp / "hw1", tmp / "mril1"
    w1.mkdir(); w2.mkdir()
    hw = hw_run_task("write add()", w1, make_verifier(w1))
    router = make_router()
    mril = mril_run_task(router, "s1", "write add()", w2, make_verifier(w2))
    events = router.store.events_for_task("s1")
    provenance = any(e.event_type == "recovery_decided" and e.action == "escalate"
                     for e in events)
    hw_v = ("PASS" if hw == "success" else "FAIL") + " -- but nothing recorded"
    mril_v = ("PASS + recovery provenance" if mril == "verified_success"
              and provenance else "FAIL")
    return hw_v, mril_v


def s2_multi_call_accounting(tmp):
    """One agent run making several model calls -- attempt vs step."""
    router = make_router()
    store = router.store
    for step in range(3):  # one attempt, three calls
        d = router.route(TaskContext(task_id="s2"), step_index=step,
                         call_site="model_call")
        router.observe_invocation(d.decision_id, d.model_id, task_id="s2",
                                  attempt_id="att-1", step_index=step,
                                  call_site="model_call")
    router.finalize("s2")
    invs = [e for e in store.events_for_task("s2")
            if e.event_type == "model_invocation_finished"]
    mril_v = ("PASS -- 1 attempt, steps "
              f"{sorted(i.step_index for i in invs)}"
              if len({i.attempt_id for i in invs}) == 1
              and sorted(i.step_index for i in invs) == [0, 1, 2] else "FAIL")
    return "N/A -- 'attempts' are retries; model calls aren't tracked", mril_v


def s3_concurrent_isolation(tmp):
    """Two in-flight runs on shared middleware -- real-graph coverage lives
    in tests/test_langchain_integration.py; here the Router-level check."""
    router = make_router()
    for tid, att in (("sess-a", "att-a"), ("sess-b", "att-b")):
        d = router.route(TaskContext(task_id=tid), step_index=0,
                         call_site="model_call")
        router.observe_invocation(d.decision_id, d.model_id, task_id=tid,
                                  attempt_id=att, step_index=0,
                                  call_site="model_call")
    a = router.store.events_for_task("sess-a")
    b = router.store.events_for_task("sess-b")
    ok = all(e.task_id == "sess-a" for e in a) and \
        all(e.task_id == "sess-b" for e in b) and len(a) == len(b)
    return ("N/A -- stateless by accident; nothing recorded either",
            "PASS -- distinct task/attempt ids" if ok else "FAIL")


def s4_duplicate_observation(tmp):
    router = make_router()
    d = router.route(TaskContext(task_id="s4"), step_index=0,
                     call_site="model_call")
    for _ in range(2):  # the driver double-reports the same call
        router.observe_invocation(d.decision_id, d.model_id, task_id="s4",
                                  attempt_id="att", step_index=0,
                                  call_site="model_call")
    for _ in range(2):  # and the same verification verdict
        router.observe_verification("att", VerificationStatus.FAILED,
                                    task_id="s4", verifier_type="test",
                                    failure_category="test_failure")
    ev = router.store.events_for_task("s4")
    invs = [e for e in ev if e.event_type == "model_invocation_finished"]
    vers = [e for e in ev if e.event_type == "verification_completed"]
    ok = len(invs) == 1 and len(vers) == 1
    return ("N/A -- no observation layer; double-counting is whatever you"
            " build", "PASS -- logical dedupe keys" if ok else "FAIL")


def s5_missing_verification(tmp):
    """Verifier never ran -- inconclusive must never read as success."""
    router = make_router()
    d = router.route(TaskContext(task_id="s5"), step_index=0,
                     call_site="model_call")
    router.observe_invocation(d.decision_id, d.model_id, task_id="s5",
                              attempt_id="att", step_index=0,
                              call_site="model_call")
    outcome = router.finalize("s5").task_outcome.value
    hw = ("PARTIAL -- a None verdict is falsy, so it fails *conservatively* "
          "but mislabels inconclusive work as verified_failure")
    mril = ("PASS -- inconclusive, never upgraded"
            if outcome == "inconclusive" else "FAIL")
    return hw, mril


def s6_interrupted_task(tmp):
    """Crash mid-task -- is committed state recoverable and explainable?"""
    router = make_router()
    d = router.route(TaskContext(task_id="s6"), step_index=0,
                     call_site="model_call")
    router.observe_invocation(d.decision_id, d.model_id, task_id="s6",
                              attempt_id="att", step_index=0,
                              call_site="model_call")
    router.observe_verification("att", VerificationStatus.FAILED,
                                task_id="s6", verifier_type="test",
                                failure_category="test_failure")
    # "process dies" here; a fresh reader replays the committed ledger
    events = router.store.events_for_task("s6")
    replayable = any(e.event_type == "route_decided" for e in events) and \
        any(e.event_type == "verification_completed" for e in events)
    return ("N/A -- in-memory only; a crash leaves no record to resume",
            "PASS -- ledger replay reconstructs state" if replayable
            else "FAIL")


def s7_restricted_model(tmp):
    """A restricted model_id must never be auto-selected."""
    router = make_router()
    # force the policy onto the degraded path; fallback must skip 'secret'
    d = router.route(TaskContext(task_id="s7"),
                     RoutingConstraints(allowed_models=("secret",),
                                        fallback_model_id="secret",
                                        budget_usd=1.0))
    # allowed_models=(secret,) is ineligible -> fallback path; 'secret' is
    # restricted -> fallback must pick the cheapest ELIGIBLE model
    return ("N/A -- no registry/policy concept to enforce against",
            "PASS -- restricted skipped" if d.model_id != "secret" else "FAIL")


SCENARIOS = [
    ("cheap model fails verification -> escalate", s1_verify_fail_escalates),
    ("agent makes multiple model calls in a run", s2_multi_call_accounting),
    ("two concurrent agent sessions", s3_concurrent_isolation),
    ("driver double-reports an observation", s4_duplicate_observation),
    ("verification never ran (missing evidence)", s5_missing_verification),
    ("process interrupted mid-task", s6_interrupted_task),
    ("restricted model in the candidate set", s7_restricted_model),
]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mril-compare-"))
    print(f"workdir: {tmp}\n")
    rows = []
    for name, fn in SCENARIOS:
        hw, mril = fn(tmp)
        rows.append((name, hw, mril))
    w = max(len(n) for n, _, _ in rows)
    print(f"{'scenario':<{w}}  handwritten {'':<28} mril")
    print("-" * (w + 78))
    for name, hw, mril in rows:
        print(f"{name:<{w}}  {hw:<42}  {mril}")

    # runtime overhead: route+observe+verify+finalize bookkeeping per call
    router = make_router()
    n = 200
    t0 = time.perf_counter()
    for i in range(n):
        d = router.route(TaskContext(task_id=f"bench-{i}"), step_index=0,
                         call_site="model_call")
        router.observe_invocation(d.decision_id, d.model_id,
                                  task_id=f"bench-{i}", attempt_id="a",
                                  step_index=0, call_site="model_call")
        router.finalize(f"bench-{i}")
    per_call_us = (time.perf_counter() - t0) / n * 1e6

    print(f"\noverhead: ~{per_call_us:.0f} us per route+observe+finalize cycle")
    print("  conditions: in-process MemoryEventStore, 200 sequential synthetic")
    print("  decisions on this machine — decision-path bookkeeping only, NOT")
    print("  end-to-end agent runtime overhead (SQLite adds a commit cost).")
    print("\nLOC: handwritten ~15  |  MRIL driver ~45 (+ zero-deps SDK)")
    print("reading: basic fallback is easy; every N/A or PARTIAL row is")
    print("infrastructure you would otherwise build, test, and maintain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
