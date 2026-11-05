"""Transferable task features — the contract between callers and policies.

Features must generalize across tasks — no task IDs, no benchmark leakage.
Callers (the eval runner, a production integration) populate
`TaskContext.metadata["features"]` with a small dict of bucketed values;
the empirical policy reads them via `features_from_context`. All values are
categorical buckets so unseen tasks land in known buckets rather than
unknown signatures.
"""

from __future__ import annotations

from dataclasses import dataclass

from mril.core.task import TaskContext

# v2: rule-marker patterns use word-prefix matching — "\bpars\b" never fired
# on "parse"/"parser", silently emptying the quoting bucket. Schema change:
# any snapshot trained under v1 must be retrained before reuse.
FEATURE_VERSION = "2"

_KEYS = ("category", "scope", "api_kind", "spec_clauses", "rule_markers")


@dataclass(frozen=True)
class TaskFeatures:
    """The feature vector the estimator sees."""

    category: str          # bug_fix | feature | refactor | ...
    scope: str             # single_file | single_module | ...
    api_kind: str          # class | function | fix | unknown
    spec_clauses: str      # single | few | many | unknown
    rule_markers: str      # sorted '+'-joined marker names, '' = none

    def signature(self) -> str:
        """Level-2 (finest) key: the full feature tuple."""
        return "|".join(f"{k}={v}" for k, v in sorted(self.as_dict().items()))

    def feature_keys(self) -> tuple[str, ...]:
        """Level-1 keys: one per feature=value — partial pooling borrows
        strength across signatures sharing a feature value."""
        return tuple(f"{k}={v}" for k, v in sorted(self.as_dict().items()))

    def as_dict(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in _KEYS}


def features_from_context(ctx: TaskContext) -> TaskFeatures:
    """Policy-side access: features arrive via ctx.metadata['features'].

    Missing or malformed metadata yields an all-'unknown' vector that lands
    in the global bucket — never a crash, never a fabricated signal."""
    raw = (ctx.metadata or {}).get("features")
    if not isinstance(raw, dict):
        return TaskFeatures(
            category=ctx.task_type or "unknown",
            scope=ctx.scope or "unknown",
            api_kind="unknown",
            spec_clauses="unknown",
            rule_markers="",
        )
    return TaskFeatures(**{k: str(raw.get(k, "unknown")) for k in _KEYS})
