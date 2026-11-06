"""Failure-category classification for verifier verdicts.

Replaces the runner's blanket "test_failure" label. Categories are ordered
and matched on *specific* signatures — not broad substrings — so e.g. a
pytest collection block containing ``SyntaxError`` classifies as
``syntax_error``, never as a generic verifier failure.

Evidence validity:
  - ``verifier_error``  = the verification infrastructure itself failed
    (the command could not be executed). INVALID evidence — it says nothing
    about the generated code and must not feed recovery learning as a
    model-failure observation.
  - ``verify_timeout``  = the verifier timed out. AMBIGUOUS but usually
    genuine: a hung pytest run in this harness is almost always generated
    code looping (or pathologically slow), which is real signal about the
    attempt. Recorded as its own category so analyses can treat the
    ambiguity explicitly.

Deliberately disjoint from the provider-level retryable set in
``mril.policy.tiered._RETRYABLE_FAILURES`` (``timeout``, ``rate_limit`` …):
``verify_timeout`` is a *verifier* timeout, a capability-relevant signal —
not a transient provider error. Keeping names disjoint preserves every
existing policy's retry/escalate behavior unchanged.
"""
from __future__ import annotations

import re

from mril.eval.verifier import Verdict

# Ordered: first matching signature wins. Syntax must precede the generic
# collection/runtime patterns so a parse failure isn't absorbed downstream.
_SYNTAX = re.compile(r"SyntaxError|IndentationError|TabError")
_CONTRACT = re.compile(
    r"ImportError|ModuleNotFoundError|cannot import name"
    r"|module '\S+' has no attribute|has no attribute"
    r"|missing \d+ required positional argument|required positional argument"
    r"|unexpected keyword argument|takes \d+ positional arguments? but"
    r"|'\S+' object is not callable"
)
_ASSERTION = re.compile(r"AssertionError|^\s*E\s+assert", re.M)
_COLLECTION = re.compile(r"ERROR collecting")
_RUNTIME = re.compile(r"\w+Error|\w+Exception|Traceback \(most recent call last\)")

CATEGORIES = (
    "verify_timeout",
    "verifier_error",
    "syntax_error",
    "contract_error",
    "assertion_failure",
    "runtime_error",
    "test_failure",
)


def classify_failure(verdict: Verdict) -> str | None:
    """Map a verdict to a failure category, or None when it passed."""
    if verdict.passed:
        return None
    if verdict.passed is None:
        # Verification never produced an outcome. A timeout is ambiguous but
        # usually code-caused (infinite loop / pathological work) — eligible
        # with the ambiguity explicit in the category. Anything else means
        # the harness itself failed: invalid evidence, marked distinctly.
        return "verify_timeout" if verdict.timed_out else "verifier_error"
    out = verdict.stdout
    if _SYNTAX.search(out):
        return "syntax_error"
    if _CONTRACT.search(out):
        return "contract_error"
    if _ASSERTION.search(out):
        return "assertion_failure"
    if _COLLECTION.search(out):
        # Collection died without a recognizable signature — the module
        # couldn't be exercised at all; closest to a contract-level failure.
        return "contract_error"
    if _RUNTIME.search(out):
        return "runtime_error"
    return "test_failure"


# --------------------------------------------------------------------------
# Study-05B sanitization contract.
#
# Raw pytest output leaks hidden-verifier content: test source lines,
# expected values, test names, and paths. Recovery feedback must carry only
# legitimately available facts: check counts, failure category, exit status.
# --------------------------------------------------------------------------

_COUNT = re.compile(r"(\d+)\s+(failed|passed|error)s?\b", re.I)

# Per-category normalized description (identical information content across
# categories; wording is part of the frozen arm contract).
_CATEGORY_LINE = {
    "assertion_failure": "the code runs but produced wrong results",
    "contract_error": "interface mismatch: missing or mis-named functions or arguments",
    "syntax_error": "the code does not parse",
    "runtime_error": "the code raised an error during execution",
    "verify_timeout": "the code hangs or is too slow",
    "test_failure": "one or more checks failed",
    "verifier_error": "verification infrastructure failed (no information about the code)",
}


def check_counts(stdout: str) -> tuple[int, int]:
    """(failed, passed) check counts parsed from the pytest summary line."""
    failed = passed = 0
    for n, kind in _COUNT.findall(stdout):
        if kind.lower() == "failed":
            failed += int(n)
        elif kind.lower() == "passed":
            passed += int(n)
        else:  # error
            failed += int(n)
    return failed, passed


def sanitize_feedback(verdict: Verdict, category: str) -> str:
    """Control-arm handoff: the current-format outcome sentence, sanitized.

    Contains NO hidden-verifier content — no test source, expected values,
    test names, or paths; only counts + category + status.
    """
    if verdict.passed is None:
        return (
            "Verification could not complete "
            f"(category: {category}). "
            + _CATEGORY_LINE.get(category, "verification was inconclusive")
            + "."
        )
    failed, passed = check_counts(verdict.stdout)
    total = failed + passed
    return (
        f"Verification failed: {failed} of {total} checks failed "
        f"(category: {category})."
    )


def structured_feedback(verdict: Verdict, category: str) -> str:
    """Challenger-arm handoff: the same legitimate facts as a structured
    diagnostic block. Identical information content to sanitize_feedback;
    only the packaging differs."""
    line = _CATEGORY_LINE.get(category, "one or more checks failed")
    if verdict.passed is None:
        return (
            "Recovery context:\n"
            "- status: verification inconclusive\n"
            f"- failure category: {category}\n"
            f"- assessment: {line}"
        )
    failed, passed = check_counts(verdict.stdout)
    total = failed + passed
    return (
        "Recovery context:\n"
        f"- status: {failed} of {total} checks failed\n"
        f"- failure category: {category}\n"
        f"- assessment: {line}"
    )
