"""Study-05B handoff sanitization + checkpoint tests."""
import json
import shutil
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from mril.eval.failures import (
    check_counts,
    sanitize_feedback,
    structured_feedback,
)
from mril.eval.probe import audit_checkpoint

# Realistic pytest tail — same shape as the leaktest output that exposed
# hidden-verifier material: test names, source lines, expected values, paths.
RAW_PYTEST = """\
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-8.2.0
rootdir: C:\\Users\\x\\MRIL
collected 4 items

verifiers/test_e.py ..F.                                               [100%]

=================================== FAILURES ===================================
_________________________ test_evicts_oldest_fresh _________________________

    def test_evicts_oldest_fresh():
        c = Cache(capacity=2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
>       assert c.get("a") is None and c.get("c") == 3
E       assert [2] == [2, 3]
E         At index 1 diff: 3 != None

verifiers\\test_e.py:42: AssertionError
=========================== short test summary info ============================
FAILED verifiers/test_e.py::test_evicts_oldest_fresh - assert [2] == [2, 3]
========================= 1 failed, 3 passed in 0.42s ==========================
"""


@dataclass
class FakeVerdict:
    passed: bool | None
    stdout: str
    exit_code: int = 1


# "assert" excluded: the legitimate category label "assertion_failure"
# contains it — it is not leaked verifier content.
LEAK_TOKENS = [
    "test_evicts_oldest_fresh", "==", "[2]", "verifiers",
    "test_e.py", ">", "E ", "rootdir",
]


class SanitizerTest(unittest.TestCase):
    def setUp(self):
        self.v = FakeVerdict(passed=False, stdout=RAW_PYTEST)

    def test_counts_parse(self):
        self.assertEqual(check_counts(RAW_PYTEST), (1, 3))

    def test_sanitized_keeps_legit_facts(self):
        out = sanitize_feedback(self.v, "assertion_failure")
        self.assertIn("1 of 4", out)
        self.assertIn("assertion_failure", out)

    def test_sanitized_strips_hidden_content(self):
        out = sanitize_feedback(self.v, "assertion_failure")
        for tok in LEAK_TOKENS:
            self.assertNotIn(tok, out, f"leaked {tok!r}")

    def test_structured_strips_hidden_content(self):
        out = structured_feedback(self.v, "assertion_failure")
        for tok in LEAK_TOKENS:
            self.assertNotIn(tok, out, f"leaked {tok!r}")

    def test_structured_keeps_legit_facts(self):
        out = structured_feedback(self.v, "assertion_failure")
        self.assertIn("1 of 4", out)
        self.assertIn("assertion_failure", out)
        self.assertIn("wrong results", out)

    def test_inconclusive_verdict(self):
        v = FakeVerdict(passed=None, stdout="")
        for fn in (sanitize_feedback, structured_feedback):
            out = fn(v, "verify_timeout")
            self.assertIn("verify_timeout", out)
            self.assertNotIn("assert", out)

    def test_fallback_line(self):
        out = structured_feedback(
            FakeVerdict(passed=False, stdout="== 2 failed, 1 passed =="),
            "test_failure",
        )
        self.assertIn("test_failure", out)


class AuditTest(unittest.TestCase):
    def test_audit_catches_leak(self):
        meta = {
            "checkpoint_id": "cp1",
            "feedback_sanitized": "Verification failed: 1 of 4 checks failed",
            "feedback_structured": "test_evicts_oldest_fresh failed: assert 1 == 2",
        }
        hits = audit_checkpoint(meta)
        self.assertTrue(hits)

    def test_audit_clean_checkpoint(self):
        meta = {
            "checkpoint_id": "cp1",
            "feedback_sanitized": "Verification failed: 1 of 4 checks failed (category: assertion_failure).",
            "feedback_structured": "Recovery context:\n- status: 1 of 4 checks failed\n- failure category: assertion_failure",
        }
        self.assertEqual(audit_checkpoint(meta), [])


class CheckpointTest(unittest.TestCase):
    """Capture produces a self-contained replay unit."""

    def test_checkpoint_roundtrip(self):
        from mril.eval.runner import EvalRunner
        # Exercise _capture_checkpoint directly with a minimal runner stub.
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "caps"
            ws_dir = Path(td) / "ws"
            ws_dir.mkdir()
            (ws_dir / "solution.py").write_text("def f(): return 1\n")
            (ws_dir / "other.py").write_text("x = 1\n")

            class _WS:
                path = ws_dir

            @dataclass
            class _V:
                passed: bool
                stdout: str

            @dataclass
            class _Spec:
                task_id: str

            @dataclass
            class _Verifier:
                corpus_root: Path

            runner = EvalRunner.__new__(EvalRunner)
            object.__setattr__(runner, "capture_dir", cap)
            object.__setattr__(runner, "verifier",
                               _Verifier(Path("eval/corpus-s05")))
            runner._capture_checkpoint(
                _Spec("bug-x"), _WS(), "t1:arm:0", 0, "weak-coder",
                _V(False, RAW_PYTEST), "assertion_failure",
            )
            caps = list(cap.iterdir())
            self.assertEqual(len(caps), 1)
            meta = json.loads((caps[0] / "checkpoint.json").read_text())
            self.assertEqual(meta["attempt_index"], 0)
            self.assertEqual(meta["failure_category"], "assertion_failure")
            self.assertEqual(
                (caps[0] / "workspace" / "solution.py").read_text(),
                "def f(): return 1\n",
            )
            self.assertEqual(audit_checkpoint(meta), [])
            # Workspace copy is a snapshot — mutating source doesn't touch it.
            (ws_dir / "solution.py").write_text("MUTATED")
            self.assertIn("return 1",
                          (caps[0] / "workspace" / "solution.py").read_text())


if __name__ == "__main__":
    unittest.main()
