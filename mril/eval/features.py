"""TaskSpec -> TaskFeatures extraction for the eval harness.

Everything here is computable before execution from what a driver
legitimately sees: the instruction text, the target-file stub, and the
task's categorical metadata. Verifier contents are NOT features — they're
hidden from the agent and would leak the answer contract into routing.
The extracted features travel to the policy via
`TaskContext.metadata["features"]` (see mril/policy/features.py).
"""

from __future__ import annotations

import re
from pathlib import Path

from mril.eval.spec import TaskSpec
from mril.policy.features import FEATURE_VERSION, TaskFeatures

__all__ = ["FEATURE_VERSION", "TaskFeatures", "extract_features"]

# Rule-type markers — keyword groups that signal a specific, checkable
# contract clause in the instruction. Each present group is one more
# independent way a model can be subtly wrong. Word-PREFIX matching: the
# instruction "parse quoted fields" must fire quoting even though the
# literal tokens are "parse"/"quoted" — v1's full-word \b..\b patterns
# under-fired and emptied buckets.
_RULE_MARKERS = {
    "ordering": r"\b(sort|order|rank|alphabet|ascend|descend|tie[- ]?break|frequent)",
    "quoting": r"\b(quote|quoting|escap|pars|serializ|deserializ|delimit|whitespace|strip)",
    "numeric": r"(?:\b(coerce|cast|float|bool|round|precis|ratio|rate|refill|percent)|\bint\b)",
    "edge_cases": r"(?:\b(empty|missing|invalid|null|comment|top[- ]?level|duplicate|boundar)|\bnone\b)",
    "stateful": r"(?:\b(cache|evict|accumulat|bucket|counter|session|track)|\bstate\b)",
}


def _bucket_clauses(n: int) -> str:
    if n <= 1:
        return "single"
    if n <= 3:
        return "few"
    return "many"


def extract_features(spec: TaskSpec, snapshot_dir: Path | None = None) -> TaskFeatures:
    """Derive transferable features from a task spec — pre-execution only."""
    instr = spec.instruction
    clauses = [c for c in re.split(r"[;.]| and ", instr) if c.strip()]
    markers = sorted(
        name for name, pat in _RULE_MARKERS.items()
        if re.search(pat, instr, re.IGNORECASE)
    )
    text = instr.lower()
    stub = ""
    if snapshot_dir is not None:
        try:
            stub = (Path(snapshot_dir) / spec.target_file).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            stub = ""
    if "class" in text or "class " in stub:
        api = "class"
    elif re.match(r"^\s*fix\b", text):
        api = "fix"
    else:
        api = "function"
    return TaskFeatures(
        category=spec.category or "unknown",
        scope=spec.scope or "unknown",
        api_kind=api,
        spec_clauses=_bucket_clauses(len(clauses)),
        rule_markers="+".join(markers),
    )
