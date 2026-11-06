"""v0.2 eval harness: immutable specs, isolated workspaces, interchangeable
arms, ledger-derived results, guardrailed reports."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from mril import ModelRegistry, ModelSpec, RoutingConstraints
from mril.core.decision import RecoveryType
from mril.core.events import ModelInvocationFinished, RecoveryDecided
from mril.eval import (
    CommandVerifier, Corpus, EvalRunner, SpecError, TaskSpec, Workspace,
    default_arms, load_corpus, run_matrix,
)
from mril.eval.arms import Arm, CheapFirstPolicy, StrongestPolicy
from mril.policy.tiered import TieredPolicy
from mril.eval.report import build_report, write_report
from mril.eval.results import load_results
from mril.eval.runner import EvalRunner as _R  # noqa
from mril.eval.spec import snapshot_sha256
from mril.store.sqlite import SQLiteEventStore


# ------------------------------------------------------------ fixtures

BUGGY = "def add(a, b):\n    return a - b  # still wrong\n"
FIXED = "def add(a, b):\n    return a + b\n"

VERIFY_SRC = """
from solution import add

def test_add():
    assert add(2, 3) == 5
"""


def _write_corpus(root: Path) -> Path:
    task = root / "task-a"
    (task / "snapshot").mkdir(parents=True)
    (task / "snapshot" / "solution.py").write_text(BUGGY)
    (task / "verifiers").mkdir()
    (task / "verifiers" / "test_a.py").write_text(VERIFY_SRC)
    spec = {
        "id": "add-fix-001",
        "schema_version": 1,
        "repository": {
            "snapshot": "task-a/snapshot",
            "sha256": snapshot_sha256(task / "snapshot"),
        },
        "task": {
            "instruction": "Fix add() so tests pass",
            "language": "python", "category": "bug_fix",
            "scope": "single_file", "risk": "low",
            "target_file": "solution.py",
        },
        "verification": {
            "files": ["task-a/verifiers/test_a.py"],
            "command": "{python} -m pytest {verify}test_a.py -q",
            "timeout_seconds": 60,
        },
        "limits": {"max_attempts": 3, "max_model_calls": 10,
                   "max_wall_seconds": 120},
    }
    (task / "task.json").write_text(json.dumps(spec))
    return root


@pytest.fixture
def corpus(tmp_path) -> Corpus:
    return load_corpus(_write_corpus(tmp_path / "corpus"))


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry(version="eval-1", models=(
        ModelSpec("weak", tier="cheap", input_price=0.10, output_price=0.30),
        ModelSpec("strong", tier="frontier", input_price=5.00, output_price=25.00),
    ))


class ScriptedDriver:
    """model_id -> list of file bodies per attempt (clamped)."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def generate(self, *, model_id, spec, workspace, attempt_index, prior_feedback, seed=None):
        self.calls.append(model_id)
        body = self.script[model_id][min(attempt_index, len(self.script[model_id]) - 1)]
        workspace.write(spec.target_file, body)
        from mril.eval.drivers import DriverResult
        return DriverResult(text=body, input_tokens=1000, output_tokens=100,
                            latency_ms=50.0)


def _runner(registry, corpus, driver):
    return EvalRunner(
        registry=registry, driver=driver,
        verifier=CommandVerifier(corpus.root),
        default_constraints=RoutingConstraints(fallback_model_id="strong",
                                               budget_usd=1.0),
    )


# ------------------------------------------------------------ spec/corpus

def test_corpus_loads_and_versions(corpus):
    assert len(corpus.tasks) == 1
    assert corpus.version
    assert corpus.tasks[0].digest()


def test_snapshot_tamper_detected(corpus):
    (corpus.root / "task-a" / "snapshot" / "extra.py").write_text("x=1")
    with pytest.raises(SpecError, match="digest mismatch"):
        corpus.tasks[0].verify_snapshot(corpus.root)


def test_spec_missing_key_rejected(tmp_path):
    with pytest.raises(SpecError):
        TaskSpec.from_dict({"id": "x"})


# ------------------------------------------------------- workspace/verifier

def test_workspace_isolated_per_run(corpus, tmp_path):
    spec = corpus.tasks[0]
    w1 = Workspace.materialize(spec, corpus.root, tmp_path, "r1")
    w2 = Workspace.materialize(spec, corpus.root, tmp_path, "r2")
    w1.write("solution.py", "mutated")
    assert w2.read("solution.py") == BUGGY


def test_verifier_never_coexists_with_agent(corpus, tmp_path):
    """Tests run in a throwaway copy — the agent's workspace never contains
    the verifier, before, during, or after a verify call."""
    spec = corpus.tasks[0]
    ws = Workspace.materialize(spec, corpus.root, tmp_path, "r1")
    ws.write("solution.py", FIXED)
    # a shell-capable agent planted a fake verifier dir — it's excluded
    # from the verify env and replaced by the pinned corpus copy
    planted = ws.path / ".mril-verify"
    planted.mkdir()
    (planted / "test_a.py").write_text("def test_nothing(): pass")
    v = CommandVerifier(corpus.root).verify(spec, ws)
    assert v.passed is True  # real test ran against the copy, not the plant
    ws.write("solution.py", BUGGY)
    assert CommandVerifier(corpus.root).verify(spec, ws).passed is False


def test_verifier_side_effects_stay_out_of_workspace(corpus, tmp_path):
    spec = corpus.tasks[0]
    ws = Workspace.materialize(spec, corpus.root, tmp_path, "r1")
    ws.write("solution.py", FIXED)
    CommandVerifier(corpus.root).verify(spec, ws)
    leftovers = [p for p in ws.path.rglob("*") if ".mril-verify" in p.parts
                 or "__pycache__" in p.parts or ".pytest_cache" in p.parts]
    assert leftovers == []


# ------------------------------------------------------------------- arms

def test_arms_select_different_models(registry):
    from mril import TaskContext
    ctx = TaskContext(task_id="t", scope="single_file", risk="low")
    candidates = registry.candidates()
    import random
    strong = StrongestPolicy().select(ctx, RoutingConstraints(), candidates, None,
                                      random.Random(0))
    cheap = CheapFirstPolicy().select(ctx, RoutingConstraints(), candidates, None,
                                      random.Random(0))
    assert strong.model_id == "strong" and cheap.model_id == "weak"


def test_cheap_first_retries_until_threshold(registry):
    from mril.core.events import VerificationStatus as VS
    from mril.policy.state import AttemptRecord, TaskState
    pol = CheapFirstPolicy(failure_threshold=2)
    state = TaskState("t")
    state.attempts.append(AttemptRecord(
        attempt_id="a1", model_id="weak", cost_usd=0.001, input_tokens=100,
        verification_status=VS.FAILED, failure_category="test_failure"))
    action = pol.recover(state, RoutingConstraints(max_attempts=3), registry)
    assert action.type == RecoveryType.RETRY and action.model_id == "weak"


# ------------------------------------------------------------- end to end

def test_run_matrix_end_to_end(corpus, registry, tmp_path):
    driver = ScriptedDriver({"weak": [BUGGY, BUGGY], "strong": [FIXED]})
    runner = _runner(registry, corpus, driver)
    out = tmp_path / "eval-out"
    results = run_matrix(corpus, registry, runner, out, seeds=(0,),
                         arms=default_arms(),
                         store_factory=SQLiteEventStore)
    assert len(results) == 3
    by_arm = {r.arm: r for r in results}
    assert by_arm["strongest-only"].verified and by_arm["strongest-only"].attempts == 1
    assert by_arm["cheap-first"].verified and by_arm["cheap-first"].escalations == 1
    assert by_arm["mril-tiered"].verified and by_arm["mril-tiered"].attempts == 2
    # a task the weak model can't solve: escalation honestly costs the wasted
    # attempt + the strong call — the ledger must show both
    assert by_arm["cheap-first"].total_cost_usd == pytest.approx(0.00013 + 0.0075)
    assert by_arm["cheap-first"].models_used == ("strong", "weak")
    assert by_arm["strongest-only"].total_cost_usd == pytest.approx(0.0075)

    # ledger holds every run, namespaced and inspectable
    store = SQLiteEventStore(out / "eval.db")
    invs = [e for e in store.all_events() if isinstance(e, ModelInvocationFinished)]
    assert len(invs) == 5  # 1 + 2 + 2
    recs = [e for e in store.all_events() if isinstance(e, RecoveryDecided)]
    assert all(r.selection_probability == 1.0 and r.recovery_context for r in recs)
    store.close()

    # reproducible artifacts
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["corpus_version"] == corpus.version
    assert manifest["cost_basis"] == "synthetic_token_price"
    loaded = load_results(out / "results.jsonl")
    assert [r.run_task_id for r in loaded] == [r.run_task_id for r in results]

    report = build_report(results, manifest)
    assert report["guardrail"]["violations"] == []
    write_report(report, out)
    assert (out / "REPORT.md").is_file()


def test_runner_feedback_is_sanitized(corpus, registry, tmp_path):
    """Raw verifier stdout (test source, expected values) must never reach
    the driver — feedback carries only counts + category."""
    seen = []

    class RecordingDriver:
        def generate(self, *, model_id, spec, workspace, attempt_index,
                     prior_feedback, seed=None):
            seen.append(prior_feedback)
            workspace.write(spec.target_file, BUGGY)
            from mril.eval.drivers import DriverResult
            return DriverResult(text=BUGGY, input_tokens=10, output_tokens=5)

    runner = _runner(registry, corpus, RecordingDriver())
    spec = corpus.tasks[0]
    store = SQLiteEventStore(tmp_path / "one.db")
    runner.run(spec, default_arms()[1], 0, store, tmp_path)
    store.close()
    assert len(seen) > 1  # at least one retry with feedback
    fb = "\n".join(f for f in seen[1:] if f)
    assert "def test_add" not in fb and "assert add(2, 3) ==" not in fb
    assert "checks failed" in fb


def test_run_matrix_resumes_completed_cells(corpus, registry, tmp_path):
    """Re-running into the same out dir is a resume: finalized cells are
    rebuilt from the ledger, never re-executed."""
    driver = ScriptedDriver({"weak": [FIXED], "strong": [FIXED]})
    runner = _runner(registry, corpus, driver)
    out = tmp_path / "eval-out"
    r1 = run_matrix(corpus, registry, runner, out, seeds=(0,),
                    arms=default_arms(), store_factory=SQLiteEventStore)
    r2 = run_matrix(corpus, registry, runner, out, seeds=(0,),
                    arms=default_arms(), store_factory=SQLiteEventStore)
    assert len(driver.calls) == 3  # nothing re-ran
    assert {r.run_task_id for r in r2} == {r.run_task_id for r in r1}
    assert all(r.verified for r in r2)


def test_run_matrix_extends_matrix_cleanly(corpus, registry, tmp_path):
    driver = ScriptedDriver({"weak": [FIXED], "strong": [FIXED]})
    runner = _runner(registry, corpus, driver)
    out = tmp_path / "eval-out"
    run_matrix(corpus, registry, runner, out, seeds=(0,),
               arms=default_arms(), store_factory=SQLiteEventStore)
    r2 = run_matrix(corpus, registry, runner, out, seeds=(0, 1),
                    arms=default_arms(), store_factory=SQLiteEventStore)
    assert len(driver.calls) == 6  # only the new seed cells ran
    assert len(r2) == 6


def test_run_matrix_survives_run_crash_and_resumes(corpus, registry, tmp_path):
    class CrashingDriver:
        def __init__(self):
            self.calls = 0

        def generate(self, *, model_id, spec, workspace, **kw):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("driver died")
            workspace.write(spec.target_file, FIXED)
            from mril.eval.drivers import DriverResult
            return DriverResult(text=FIXED, input_tokens=1, output_tokens=1)

    out = tmp_path / "eval-out"
    runner = _runner(registry, corpus, CrashingDriver())
    with pytest.raises(RuntimeError):
        run_matrix(corpus, registry, runner, out, seeds=(0,),
                   arms=default_arms(), store_factory=SQLiteEventStore)
    # progress persisted: a later process completes the remaining cells
    runner2 = _runner(registry, corpus,
                      ScriptedDriver({"weak": [FIXED], "strong": [FIXED]}))
    results = run_matrix(corpus, registry, runner2, out, seeds=(0,),
                         arms=default_arms(), store_factory=SQLiteEventStore)
    assert len(results) == 3
    lines = (out / "results.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_verify_command_split_before_substitution():
    """{python} expands to a real interpreter path — possibly containing
    spaces — and must survive as ONE argv element. Quoting in the template
    is honored."""
    from mril.eval.verifier import _command_argv
    argv = _command_argv('{python} -m pytest {verify}t_a.py -q --tb="short mode"')
    assert argv[0] == sys.executable
    assert argv[3] == ".mril-verify/t_a.py"
    assert argv[-1] == "--tb=short mode"


def test_failure_classifier_ignores_source_echo():
    """pytest's '>' source-echo lines can contain words like SyntaxError —
    classification must match the error signature, not echoed code."""
    from mril.eval.failures import classify_failure
    from mril.eval.verifier import Verdict
    out = (
        "________________ test_x ________________\n"
        ">       import m  # handles SyntaxError gracefully\n"
        "E       assert 1 == 2\n"
        "1 failed in 0.01s\n"
    )
    assert classify_failure(Verdict("r", False, 1, out, 1.0)) == "assertion_failure"


def test_budget_zero_is_honored(corpus, registry, tmp_path):
    """budget_usd=0.0 is a real budget (zero), not 'unset' — the run must
    stop on budget, not silently inherit the default."""
    import dataclasses
    spec = dataclasses.replace(corpus.tasks[0], budget_usd=0.0)
    runner = _runner(registry, corpus, ScriptedDriver({"weak": [BUGGY]}))
    store = SQLiteEventStore(tmp_path / "b.db")
    r = runner.run(spec, default_arms()[1], 0, store, tmp_path)
    store.close()
    assert r.attempts == 1  # stopped on budget, not on max_attempts


def test_eval_run_rejects_unknown_arm(corpus, tmp_path):
    from mril.cli import main
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"version": "r", "models": [
        {"model_id": "weak", "tier": "cheap"},
        {"model_id": "strong", "tier": "frontier"}]}))
    rc = main(["eval", "run", "--corpus", str(corpus.root),
               "--registry", str(reg), "--out", str(tmp_path / "o"),
               "--arms", "nope"])
    assert rc == 1


def test_retry_denied_when_over_budget(registry):
    """RETRY costs a real attempt — when its estimate exceeds the remaining
    budget the policy must STOP, not silently overspend."""
    from mril.policy.state import AttemptRecord, TaskState
    state = TaskState("t")
    state.attempts.append(AttemptRecord(
        attempt_id="a1", model_id="weak", cost_usd=0.009,
        input_tokens=100, api_error="TimeoutError"))
    state.total_cost_usd = 0.009
    # remaining = 0.01 - 0.009 = 0.001 < retry est (~0.0035 at default tokens)
    action = TieredPolicy().recover(
        state, RoutingConstraints(budget_usd=0.01, max_attempts=5), registry)
    assert action.type == RecoveryType.STOP
    assert "budget" in action.reason


def test_resume_refuses_changed_corpus(corpus, registry, tmp_path):
    """A cell finalized under one corpus digest must never be silently
    resumed under another — same run ids, different experiment."""
    runner = _runner(registry, corpus,
                     ScriptedDriver({"weak": [FIXED], "strong": [FIXED]}))
    out = tmp_path / "eval-out"
    run_matrix(corpus, registry, runner, out, seeds=(0,),
               arms=default_arms(), store_factory=SQLiteEventStore)
    spec_path = corpus.root / "task-a" / "task.json"
    spec_d = json.loads(spec_path.read_text())
    spec_d["task"]["instruction"] = "a different task entirely"
    spec_path.write_text(json.dumps(spec_d))
    corpus2 = load_corpus(corpus.root)
    with pytest.raises(SpecError, match="incompatible"):
        run_matrix(corpus2, registry, runner, out, seeds=(0,),
                   arms=default_arms(), store_factory=SQLiteEventStore)


def test_resume_refuses_changed_registry(corpus, registry, tmp_path):
    runner = _runner(registry, corpus,
                     ScriptedDriver({"weak": [FIXED], "strong": [FIXED]}))
    out = tmp_path / "eval-out"
    run_matrix(corpus, registry, runner, out, seeds=(0,),
               arms=default_arms(), store_factory=SQLiteEventStore)
    registry2 = ModelRegistry(version="eval-2", models=registry.models)
    with pytest.raises(SpecError, match="registry"):
        run_matrix(corpus, registry2, runner, out, seeds=(0,),
                   arms=default_arms(), store_factory=SQLiteEventStore)


def test_resume_refuses_changed_arm_fingerprint(corpus, registry, tmp_path):
    runner = _runner(registry, corpus,
                     ScriptedDriver({"weak": [FIXED], "strong": [FIXED]}))
    out = tmp_path / "eval-out"
    run_matrix(corpus, registry, runner, out, seeds=(0,), arms=default_arms(),
               store_factory=SQLiteEventStore)
    changed = (default_arms()[0],
               Arm("cheap-first", CheapFirstPolicy(failure_threshold=5)),
               default_arms()[2])
    with pytest.raises(SpecError, match="fingerprint"):
        run_matrix(corpus, registry, runner, out, seeds=(0,), arms=changed,
                   store_factory=SQLiteEventStore)


def test_resume_refuses_unprovenanced_ledger(corpus, registry, tmp_path):
    """A ledger without a manifest can't be proven to belong to this
    matrix — fail closed rather than guess."""
    runner = _runner(registry, corpus,
                     ScriptedDriver({"weak": [FIXED], "strong": [FIXED]}))
    out = tmp_path / "eval-out"
    run_matrix(corpus, registry, runner, out, seeds=(0,), arms=default_arms(),
               store_factory=SQLiteEventStore)
    (out / "manifest.json").unlink()
    with pytest.raises(SpecError, match="manifest"):
        run_matrix(corpus, registry, runner, out, seeds=(0,),
                   arms=default_arms(), store_factory=SQLiteEventStore)


def test_probe_audit_accepts_legit_categories_and_catches_leaks():
    """The frozen feedback contract names categories like 'test_failure' —
    the leak audit must pass them but still catch real verifier content."""
    from mril.eval.failures import sanitize_feedback, structured_feedback
    from mril.eval.probe import audit_checkpoint
    from mril.eval.verifier import Verdict

    v = Verdict("r1", False, 1, "1 failed, 2 passed in 0.01s", 10.0)
    meta = {"checkpoint_id": "c1",
            "feedback_sanitized": sanitize_feedback(v, "test_failure"),
            "feedback_structured": structured_feedback(v, "test_failure")}
    assert audit_checkpoint(meta) == []

    leaked = dict(meta)
    leaked["feedback_sanitized"] = "def test_add():\n    assert add(2,3) == 5"
    assert audit_checkpoint(leaked)


def test_report_survives_missing_baseline_arm():
    """A matrix run without the quality-baseline arm still reports — the
    paired section just has no comparisons."""
    from mril.eval.results import RunResult
    results = [RunResult(run_task_id="t:cheap-first:0", task_id="t",
                         arm="cheap-first", seed=0, outcome="verified_success",
                         verified=True, attempts=1, model_calls=1,
                         escalations=0, total_cost_usd=0.01, wall_ms=100)]
    report = build_report(results, {"corpus_version": "x"})
    assert report["paired"]["comparisons"] == {}
    assert report["guardrail"]["violations"] == []


def test_workspace_utf8_roundtrip(tmp_path):
    """Model output routinely contains non-ASCII — workspace I/O is utf-8,
    not the platform default (cp1252 on Windows)."""
    ws = Workspace(tmp_path / "ws")
    ws.write("solution.py", "x = '→ é ✓'\n")
    assert "→" in ws.read("solution.py")


def test_report_flags_quality_regression(registry):
    from mril.eval.results import RunResult
    def rr(arm, verified, cost):
        return RunResult(run_task_id=f"t:{arm}:0", task_id="t", arm=arm, seed=0,
                         outcome="verified_success" if verified else "verified_failure",
                         verified=verified, attempts=1, model_calls=1, escalations=0,
                         total_cost_usd=cost, wall_ms=100)
    results = [rr("strongest-only", True, 1.0)] + [rr("cheap-first", False, 0.01)
                                                 for _ in range(3)]
    report = build_report(results, {"corpus_version": "x"}, delta=0.05)
    assert [v["arm"] for v in report["guardrail"]["violations"]] == ["cheap-first"]
