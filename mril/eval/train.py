"""PolicyTrainer — ledger events -> versioned PolicySnapshot.

Reconstructs attempt-level observations from the event ledger and fits the
hierarchical-Beta estimator + cost model the EmpiricalCheapFirstPolicy
consumes. The distinction that matters: a weak-model FIRST attempt that
fails is a negative weak observation even when a later strong attempt
rescues the task — post-escalation success is evidence about recovery,
not about weak capability.

Observation classes extracted per run:
  weak_first     attempt 0 ran the weak model        -> Beta success/failure
  strong_first   attempt 0 ran the strong model      -> q_fresh, c_strong_fresh
  strong_rescue  attempt i>0 ran strong right after  -> q_recovery,
                 a failed weak attempt                  c_strong_after_fail
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from mril.core.events import (
    Event,
    ModelInvocationFinished,
    TaskStarted,
    VerificationCompleted,
    VerificationStatus,
)
from mril.policy.empirical import SNAPSHOT_VERSION, PolicySnapshot
from mril.policy.features import TaskFeatures
from mril.store.sqlite import SQLiteEventStore


@dataclass
class _Attempt:
    index: int
    model_id: str | None
    verified: bool | None
    cost: float | None
    latency: float | None


def _attempts(events: list[Event]) -> list[_Attempt]:
    """Ordered attempt reconstruction for one run's event stream."""
    order: list[str] = []
    inv: dict[str, ModelInvocationFinished] = {}
    ver: dict[str, VerificationCompleted] = {}
    for e in events:
        if isinstance(e, ModelInvocationFinished) and e.attempt_id:
            if e.attempt_id not in inv:
                order.append(e.attempt_id)
                inv[e.attempt_id] = e
            else:  # multi-call attempt: fold cost into the first record
                first = inv[e.attempt_id]
                inv[e.attempt_id] = ModelInvocationFinished(
                    attempt_id=first.attempt_id,
                    model_id=first.model_id,
                    cost_usd=(first.cost_usd or 0) + (e.cost_usd or 0),
                    latency_ms=(first.latency_ms or 0) + (e.latency_ms or 0),
                )
        elif isinstance(e, VerificationCompleted) and e.attempt_id:
            ver.setdefault(e.attempt_id, e)  # first verdict per attempt
    out = []
    for i, aid in enumerate(order):
        v = ver.get(aid)
        out.append(
            _Attempt(
                index=i,
                model_id=inv[aid].model_id,
                verified=(v.status == VerificationStatus.PASSED) if v else None,
                cost=inv[aid].cost_usd,
                latency=inv[aid].latency_ms,
            )
        )
    return out


def _features(events: list[Event]) -> TaskFeatures | None:
    for e in events:
        if isinstance(e, TaskStarted) and isinstance(e.metadata, dict):
            raw = e.metadata.get("features")
            if isinstance(raw, dict):
                keys = ("category", "scope", "api_kind", "spec_clauses", "rule_markers")
                return TaskFeatures(**{k: str(raw.get(k, "unknown")) for k in keys})
    return None


@dataclass
class _Obs:
    weak: list[bool] = field(default_factory=list)          # per-feature-bucket later
    weak_by_task: dict[str, list[bool]] = field(default_factory=dict)
    strong_fresh: list[bool] = field(default_factory=list)
    strong_rescue: list[bool] = field(default_factory=list)
    c_weak: list[float] = field(default_factory=list)
    c_strong_fresh: list[float] = field(default_factory=list)
    c_strong_after: list[float] = field(default_factory=list)
    c_handoff: list[float] = field(default_factory=list)
    lat_weak: list[float] = field(default_factory=list)
    lat_strong: list[float] = field(default_factory=list)
    n_runs: int = 0


def collect(store_path: str | Path, weak_id: str, strong_id: str) -> _Obs:
    """Walk every task in the ledger; emit attempt-level observations."""
    store = SQLiteEventStore(store_path)
    try:
        events = store.all_events()
    finally:
        store.close()
    by_run: dict[str, list[Event]] = {}
    for e in events:
        if e.task_id:
            by_run.setdefault(e.task_id, []).append(e)

    obs = _Obs(n_runs=len(by_run))
    for run_events in by_run.values():
        atts = _attempts(run_events)
        feats = _features(run_events)
        prev_failed_weak = False
        for a in atts:
            if a.model_id == weak_id:
                if a.index == 0 and a.verified is not None:
                    obs.weak.append(a.verified)
                    if feats is not None:
                        obs.weak_by_task.setdefault(feats.signature(), []).append(
                            a.verified)
                    if a.cost is not None:
                        obs.c_weak.append(a.cost)
                    if a.latency is not None:
                        obs.lat_weak.append(a.latency)
                prev_failed_weak = a.verified is False
            elif a.model_id == strong_id:
                if a.index == 0:
                    if a.verified is not None:
                        obs.strong_fresh.append(a.verified)
                    if a.cost is not None:
                        obs.c_strong_fresh.append(a.cost)
                elif prev_failed_weak:
                    if a.verified is not None:
                        obs.strong_rescue.append(a.verified)
                    if a.cost is not None:
                        obs.c_strong_after.append(a.cost)
                if a.latency is not None:
                    obs.lat_strong.append(a.latency)
                prev_failed_weak = False
            else:
                prev_failed_weak = False
        # handoff cost: escalate decisions recorded their switch estimate;
        # use mean actual_switch_cost/escalation from finalized tasks instead
        for e in run_events:
            if e.event_type == "task_finalized":
                if (e.actual_switch_cost_usd or 0) and (e.escalation_count or 0):
                    obs.c_handoff.append(
                        e.actual_switch_cost_usd / e.escalation_count)
    return obs


def fit(
    store_path: str | Path,
    *,
    weak_id: str = "weak-coder",
    strong_id: str = "strong-coder",
    prior_strength: float = 3.0,
    quality_margin: float = 0.05,
    epsilon: float = 0.0,
    feature_version: str = "1",
) -> PolicySnapshot:
    obs = collect(store_path, weak_id, strong_id)

    # global Beta over ALL weak first-attempts
    g_s = sum(obs.weak)
    beta: dict[str, list[float]] = {"global": [float(g_s), float(len(obs.weak) - g_s)]}

    # need task->features mapping; collect() keys weak_by_task by signature,
    # so rebuild per-feature buckets by re-deriving keys from each signature
    for sig, outcomes in obs.weak_by_task.items():
        s = sum(outcomes)
        beta[f"sig:{sig}"] = [float(s), float(len(outcomes) - s)]
        for kv in sig.split("|"):
            fk = f"feat:{kv}"
            bucket = beta.setdefault(fk, [0.0, 0.0])
            bucket[0] += float(s)
            bucket[1] += float(len(outcomes) - s)

    def mean(xs: list[float], default: float) -> float:
        return statistics.mean(xs) if xs else default

    def rate(xs: list[bool], prior: float = 0.8, m: float = 3.0) -> float:
        n = len(xs)
        return (sum(xs) + m * prior) / (n + m) if n else prior

    cost_model = {
        "c_weak": mean(obs.c_weak, 0.001),
        "c_strong_fresh": mean(obs.c_strong_fresh, 0.01),
        "c_strong_after_fail": mean(obs.c_strong_after,
                                    mean(obs.c_strong_fresh, 0.01)),
        "c_handoff": mean(obs.c_handoff, 0.0),
        "q_recovery": rate(obs.strong_rescue),
        "q_fresh": rate(obs.strong_fresh),
        "lat_weak_ms": mean(obs.lat_weak, 0.0),
        "lat_strong_ms": mean(obs.lat_strong, 0.0),
    }
    return PolicySnapshot(
        version=SNAPSHOT_VERSION,
        feature_version=feature_version,
        prior_strength=prior_strength,
        beta=beta,
        cost_model=cost_model,
        quality_margin=quality_margin,
        epsilon=epsilon,
        trained_on_runs=obs.n_runs,
        trained_from_ledger=str(store_path),
    )


def fit_to_file(store_path, out_path, **kw) -> PolicySnapshot:
    snap = fit(store_path, **kw)
    Path(out_path).write_text(
        json.dumps(snap.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snap
