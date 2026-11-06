"""Study-05: failure classifier + randomized recovery collection policy."""
from __future__ import annotations

from dataclasses import replace

from mril.core.decision import RecoveryType
from mril.core.models import ModelRegistry
from mril.core.task import RoutingConstraints
from mril.eval.arms import CollectionPolicy
from mril.eval.failures import classify_failure
from mril.eval.verifier import Verdict
from mril.policy.state import AttemptRecord, TaskState

# ---------------------------------------------------------------- classifier


def _verdict(passed, stdout="", timed_out=False):
    return Verdict(
        run_id="r", passed=passed, returncode=None if passed is None else (0 if passed else 1),
        stdout=stdout, duration_ms=1.0, timed_out=timed_out,
    )


def test_classify_passed_returns_none():
    assert classify_failure(_verdict(True, "1 passed")) is None


def test_classify_verifier_infra_error_is_invalid_evidence():
    # passed=None + no timeout => the harness failed, not the model
    assert classify_failure(_verdict(None, "OSError: cannot spawn", timed_out=False)) == "verifier_error"


def test_classify_timeout_is_ambiguous_but_code_eligible():
    assert classify_failure(_verdict(None, "timed out after 30s", timed_out=True)) == "verify_timeout"


def test_classify_syntax_error():
    out = "ERROR collecting verifiers/test_x.py\nE   SyntaxError: invalid syntax (solution.py, line 4)"
    assert classify_failure(_verdict(False, out)) == "syntax_error"


def test_classify_collection_syntax_beats_generic():
    # collection block present AND SyntaxError -> syntax, not a generic error
    out = "=== ERRORS ===\nERROR collecting test session\nsolution.py:3: SyntaxError: unexpected eof"
    assert classify_failure(_verdict(False, out)) == "syntax_error"


def test_classify_collection_import_is_contract():
    out = "ERROR collecting verifiers/test_x.py\nE   ModuleNotFoundError: No module named 'helper'"
    assert classify_failure(_verdict(False, out)) == "contract_error"


def test_classify_contract_signatures():
    for out in (
        "E   ImportError: cannot import name 'parse' from 'solution'",
        "E   AttributeError: module 'solution' has no attribute 'render'",
        "E   TypeError: render() missing 1 required positional argument: 'ctx'",
        "E   TypeError: render() takes 1 positional argument but 2 were given",
    ):
        assert classify_failure(_verdict(False, out)) == "contract_error", out


def test_classify_assertion_failure():
    out = "____ test_render ____\n    def test_render():\n>       assert render('x') == 'y'\nE       AssertionError\nFAILED"
    assert classify_failure(_verdict(False, out)) == "assertion_failure"


def test_classify_runtime_error():
    out = "____ test_parse ____\nE   KeyError: 'missing'\n==== 1 failed ===="
    assert classify_failure(_verdict(False, out)) == "runtime_error"


def test_classify_fallback_is_test_failure():
    out = "==== short test summary ====\nFAILED verifiers/test_x.py::test_case"
    assert classify_failure(_verdict(False, out)) == "test_failure"


# ---------------------------------------------------------------- policy helpers


def _state(task_id="t:collect-weak:0", model="weak-coder", status="failed",
           failcat="assertion_failure", n_attempts=1):
    atts = [
        AttemptRecord(
            attempt_id=f"a{i}", model_id=model, cost_usd=0.001,
            input_tokens=100, verification_status=status, failure_category=failcat,
        )
        for i in range(n_attempts)
    ]
    st = TaskState(task_id=task_id)
    st.attempts = list(atts)
    return st


class _Reg:
    """Minimal registry stand-in matching the methods the policy calls."""

    def __init__(self):
        self.models = {
            "weak-coder": _M("weak-coder", "cheap", 0.0001),
            "strong-coder": _M("strong-coder", "frontier", 0.005),
        }

    def candidates(self, allowed, caps):
        return list(self.models.values())

    def get(self, mid):
        return self.models.get(mid)


class _M:
    def __init__(self, model_id, tier, cost):
        self.model_id, self.tier, self._c = model_id, tier, cost

    def cost_usd(self, it, ot):
        return self._c

    def switch_cost_usd(self, ctx):
        return 0.0005


def _policy(entry="weak"):
    return CollectionPolicy(name=f"collect-{entry}", entry=entry)


def _constraints(**kw):
    return RoutingConstraints(max_attempts=3, **kw)


# ---------------------------------------------------------------- feasible sets


def test_feasible_after_weak_failure():
    a = _policy("weak").recover(_state(model="weak-coder"), _constraints(), _Reg())
    assert set(a.feasible_actions) == {"retry:weak-coder", "switch:strong-coder", "stop"}
    assert abs(a.probability - 1 / 3) < 1e-9


def test_feasible_after_strong_failure_includes_downgrade():
    a = _policy("strong").recover(_state(model="strong-coder"), _constraints(), _Reg())
    assert set(a.feasible_actions) == {"retry:strong-coder", "switch:weak-coder", "stop"}
    if a.type == RecoveryType.ESCALATE:
        assert "downgrade" in a.reason


def test_terminal_state_forces_stop():
    st = _state(n_attempts=3)  # max_attempts=3 -> no slots left
    a = _policy("weak").recover(st, _constraints(), _Reg())
    assert a.type == RecoveryType.STOP
    assert a.feasible_actions == ("stop",)
    assert a.probability == 1.0


def test_budget_exhaustion_shrinks_set():
    st = _state()
    st.total_cost_usd = 0.01  # already spent past the budget
    cons = replace(_constraints(), budget_usd=0.001)
    a = _policy("weak").recover(st, cons, _Reg())
    assert a.feasible_actions == ("stop",)
    assert a.type == RecoveryType.STOP


def test_verifier_error_is_invalid_evidence_no_switch():
    st = _state(status="inconclusive", failcat="verifier_error")
    a = _policy("weak").recover(st, _constraints(), _Reg())
    assert set(a.feasible_actions) == {"retry:weak-coder", "stop"}
    assert not any(x.startswith("switch:") for x in a.feasible_actions)


def test_verify_timeout_keeps_full_set():
    st = _state(status="inconclusive", failcat="verify_timeout")
    a = _policy("weak").recover(st, _constraints(), _Reg())
    assert set(a.feasible_actions) == {"retry:weak-coder", "switch:strong-coder", "stop"}


def test_draw_is_checkpoint_deterministic():
    p = _policy("weak")
    a1 = p.recover(_state(), _constraints(), _Reg())
    a2 = p.recover(_state(), _constraints(), _Reg())
    assert (a1.type, a1.model_id, a1.probability) == (a2.type, a2.model_id, a2.probability)


def test_different_checkpoints_can_differ():
    p = _policy("weak")
    acts = {
        p.recover(_state(task_id=f"t:x:{i}", model="weak-coder"), _constraints(), _Reg()).type
        for i in range(12)
    }
    assert len(acts) > 1  # 12 checkpoints should draw more than one action


def test_propensity_matches_set_size():
    st = _state(status="inconclusive", failcat="verifier_error")  # set of 2
    a = _policy("weak").recover(st, _constraints(), _Reg())
    assert abs(a.probability - 0.5) < 1e-9
