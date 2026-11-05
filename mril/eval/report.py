"""Evaluation report — the constrained-comparison view.

Success is min cost subject to verified-completion within delta of the
quality ceiling arm; a policy that wins by abandoning hard tasks shows up
as a completion-rate violation, not a bargain. Costs are normalized
token-price estimates on local drivers — labeled, never billed money.
"""

from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

from mril.eval.results import RunResult


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round((q / 100) * (len(s) - 1))))
    return s[k]


def summarize_arm(results: list[RunResult]) -> dict:
    n = len(results)
    verified = [r for r in results if r.verified]
    walls = [r.wall_ms for r in results]
    return {
        "runs": n,
        "verified_completion_rate": len(verified) / n if n else None,
        "mean_total_cost_usd": statistics.mean(r.total_cost_usd for r in results) if n else None,
        "cost_per_verified_usd": (
            sum(r.total_cost_usd for r in results) / len(verified) if verified else None
        ),
        "median_wall_ms": statistics.median(walls) if walls else None,
        "p95_wall_ms": _pct(walls, 95),
        "mean_attempts": statistics.mean(r.attempts for r in results) if n else None,
        "mean_model_calls": statistics.mean(r.model_calls for r in results) if n else None,
        "escalation_rate": statistics.mean(r.escalations for r in results) if n else None,
        "estimated_switch_cost_usd": sum(r.estimated_switch_cost_usd or 0 for r in results),
        "actual_switch_cost_usd": sum(r.actual_switch_cost_usd or 0 for r in results),
    }


def _cluster_boot_ci(
    stats_fn,
    units: list[list[RunResult]],
    other: list[list[RunResult]],
    *,
    reps: int = 2000,
    rng_seed: int = 0,
) -> tuple[float, float] | None:
    """Percentile CI of `stats_fn(units_sample, other_sample)` under
    task-clustered resampling — runs sharing a task aren't independent,
    so the bootstrap resamples whole task clusters, not individual runs."""
    if not units or not other:
        return None
    rng, stats = random.Random(rng_seed), []
    nu, no = len(units), len(other)
    for _ in range(reps):
        su = [units[rng.randrange(nu)] for _ in range(nu)]
        so = [other[rng.randrange(no)] for _ in range(no)]
        stats.append(stats_fn(su, so))
    stats.sort()
    return stats[int(0.025 * reps)], stats[int(0.975 * reps)]


def _flat(clusters: list[list[RunResult]]) -> list[RunResult]:
    return [r for c in clusters for r in c]


def _per_task_consistency(results: list[RunResult]) -> dict:
    """task -> arm -> verified k/n + a stability label across seeds."""
    grid: dict[str, dict[str, list[RunResult]]] = {}
    for r in results:
        grid.setdefault(r.task_id, {}).setdefault(r.arm, []).append(r)
    out: dict[str, dict] = {}
    for tid, arms_ in sorted(grid.items()):
        entry = {}
        for arm, rs in sorted(arms_.items()):
            k, n = sum(1 for r in rs if r.verified), len(rs)
            label = "always" if k == n else "never" if k == 0 else "sometimes"
            entry[arm] = {"verified": k, "runs": n, "label": label}
        out[tid] = entry
    return out


def _paired(results: list[RunResult], baseline: str) -> dict:
    """Arm-vs-baseline deltas clustered by task. Point differences are
    honest observations; the CI shows whether the gap survives task-level
    resampling — a flag inside delta isn't proof of inferiority."""
    by_task_arm: dict[tuple[str, str], list[RunResult]] = {}
    for r in results:
        by_task_arm.setdefault((r.task_id, r.arm), []).append(r)
    tasks = sorted({t for t, _ in by_task_arm})
    arm_names = sorted({a for _, a in by_task_arm})

    def clusters(arm: str) -> list[list[RunResult]]:
        return [by_task_arm.get((t, arm), []) for t in tasks]

    def d_verified(a, b):
        va = statistics.mean(r.verified for r in _flat(a))
        vb = statistics.mean(r.verified for r in _flat(b))
        return va - vb

    def d_cost(a, b):
        return statistics.mean(r.total_cost_usd for r in _flat(a)) - statistics.mean(
            r.total_cost_usd for r in _flat(b))

    def d_wall(a, b):
        return statistics.mean(r.wall_ms for r in _flat(a)) - statistics.mean(
            r.wall_ms for r in _flat(b))

    base = clusters(baseline)
    out = {}
    for arm in arm_names:
        if arm == baseline:
            continue
        a = clusters(arm)
        out[arm] = {
            "verified_delta": d_verified(a, base),
            "verified_delta_ci95": _cluster_boot_ci(d_verified, a, base),
            "cost_delta_usd": d_cost(a, base),
            "cost_delta_ci95": _cluster_boot_ci(d_cost, a, base),
            "wall_delta_ms": d_wall(a, base),
            "wall_delta_ci95": _cluster_boot_ci(d_wall, a, base),
        }
    return {"baseline": baseline, "comparisons": out,
            "note": "task-clustered bootstrap; run-level pairing by (task, seed)"}


def _missed_opportunities(results: list[RunResult]) -> dict:
    """Per-task observed missed opportunities — NOT counterfactual regret.

    Generation is stochastic and policies produce different recovery
    states, so these flag decisions that were costly under the outcomes
    observed, not decisions that provably should have differed."""
    by_task_arm: dict[str, dict[str, list[RunResult]]] = {}
    for r in results:
        by_task_arm.setdefault(r.task_id, {}).setdefault(r.arm, []).append(r)
    out: dict[str, list[str]] = {}
    for tid, arms_ in sorted(by_task_arm.items()):
        notes = []
        cheap = arms_.get("cheap-first", [])
        tiered = arms_.get("mril-tiered", [])
        strong = arms_.get("strongest-only", [])
        weak_first_pass = sum(
            1 for r in cheap if r.verified and r.escalations == 0
        )
        escalations = [r for r in cheap if r.escalations > 0]
        recovered = [r for r in escalations if r.verified]
        # tiered used strong where weak proved it can pass
        tiered_strong = [r for r in tiered if "weak-coder" not in r.models_used]
        if tiered_strong and weak_first_pass:
            notes.append(
                f"tiered_conservative: routed strong but weak verified "
                f"{weak_first_pass}/{len(cheap)} cheap-first runs")
        # cheap burned a weak attempt then still needed strong
        wasted = len(escalations) - len(recovered)
        if wasted:
            notes.append(
                f"weak_attempt_wasted: {wasted}/{len(cheap)} cheap-first runs "
                "burned a weak attempt without recovering")
        if recovered:
            notes.append(
                f"escalation_recovered: {len(recovered)}/{len(escalations)} "
                "escalations verified")
        for arm, rs in arms_.items():
            ks = {r.verified for r in rs}
            if len(ks) > 1:
                notes.append(
                    f"flaky[{arm}]: {sum(ks)}/{len(rs)} seeds verified — "
                    "generation-sensitive, not a hard capability bound")
        if strong and not any(r.verified for r in strong):
            notes.append("ceiling: strongest-only never verified — "
                         "shared failure, not routing-relevant")
        if notes:
            out[tid] = notes
    return out


def build_report(
    results: list[RunResult],
    manifest: dict,
    *,
    quality_baseline: str = "strongest-only",
    delta: float = 0.05,
) -> dict:
    by_arm: dict[str, list[RunResult]] = {}
    for r in results:
        by_arm.setdefault(r.arm, []).append(r)
    arms = {name: summarize_arm(rs) for name, rs in sorted(by_arm.items())}
    base_rate = (arms.get(quality_baseline) or {}).get("verified_completion_rate")
    paired = _paired(results, quality_baseline)
    guardrail = {
        "quality_baseline": quality_baseline,
        "delta": delta,
        "violations": [
            {
                "arm": name,
                "completion_gap": (base_rate or 0) - (s["verified_completion_rate"] or 0),
                "delta_ci95": (paired["comparisons"].get(name) or {}).get("verified_delta_ci95"),
            }
            for name, s in arms.items()
            if base_rate is not None
            and s["verified_completion_rate"] is not None
            and s["verified_completion_rate"] < base_rate - delta
        ],
    }
    return {
        "manifest": manifest,
        "arms": arms,
        "guardrail": guardrail,
        "per_task_consistency": _per_task_consistency(results),
        "paired": paired,
        "missed_opportunities": _missed_opportunities(results),
    }


def write_report(report: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# MRIL evaluation report",
        "",
        f"corpus {report['manifest'].get('corpus_version')} · "
        f"registry {report['manifest'].get('registry_version')} "
        f"#{report['manifest'].get('registry_hash')} · "
        f"cost basis: {report['manifest'].get('cost_basis')}",
        "",
        "| arm | verified | cost/task | cost/verified | p50 ms | p95 ms | attempts | escalations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, s in report["arms"].items():
        def f(v, nd=4):
            return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))
        lines.append(
            f"| {name} | {f(s['verified_completion_rate'], 2)} | "
            f"${f(s['mean_total_cost_usd'])} | ${f(s['cost_per_verified_usd'])} | "
            f"{f(s['median_wall_ms'], 0)} | {f(s['p95_wall_ms'], 0)} | "
            f"{f(s['mean_attempts'], 2)} | {f(s['escalation_rate'], 2)} |"
        )
    g = report["guardrail"]
    lines += [
        "",
        f"guardrail: completion within δ={g['delta']} of {g['quality_baseline']} — "
        + ("PASS" if not g["violations"] else f"VIOLATED by {[v['arm'] for v in g['violations']]}"),
    ]
    for v in g["violations"]:
        ci = v.get("delta_ci95")
        ci_s = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else "n/a"
        lines.append(
            f"  {v['arm']}: gap {v['completion_gap']:+.3f}, CI95 {ci_s} — observed "
            "difference, not proof of inferiority (task-clustered CI)")
    lines += [
        "",
        "switch spend (re-ingest, not counterfactual): "
        + " | ".join(
            f"{n}: est ${s['estimated_switch_cost_usd']:.4f} → obs ${s['actual_switch_cost_usd']:.4f}"
            for n, s in report["arms"].items()
        ),
    ]
    if "paired" in report:
        p = report["paired"]
        lines += [
            "",
            f"## paired vs {p['baseline']} (task-clustered bootstrap CI95)",
            "",
            "| arm | Δverified | CI95 | Δcost/task | CI95 | Δwall ms |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for arm, c in p["comparisons"].items():
            ci_v = c["verified_delta_ci95"] or (float("nan"),) * 2
            ci_c = c["cost_delta_ci95"] or (float("nan"),) * 2
            lines.append(
                f"| {arm} | {c['verified_delta']:+.3f} | "
                f"[{ci_v[0]:+.3f}, {ci_v[1]:+.3f}] | "
                f"${c['cost_delta_usd']:+.4f} | "
                f"[{ci_c[0]:+.4f}, {ci_c[1]:+.4f}] | {c['wall_delta_ms']:+.0f} |"
            )
    if "per_task_consistency" in report:
        grid = report["per_task_consistency"]
        arm_names = sorted({a for t in grid.values() for a in t})
        lines += [
            "",
            "## per-task consistency (verified k/n per arm)",
            "",
            "| task | " + " | ".join(arm_names) + " |",
            "| --- | " + " | ".join("---" for _ in arm_names) + " |",
        ]
        mark = {"always": "✓", "never": "✗", "sometimes": "~"}
        for tid, arms_ in grid.items():
            cells = [
                f"{mark.get(e['label'], '?')}{e['verified']}/{e['runs']}"
                for a in arm_names
                for e in [arms_.get(a, {"verified": "-", "runs": "-", "label": ""})]
            ]
            lines.append(f"| {tid} | " + " | ".join(cells) + " |")
    if "missed_opportunities" in report:
        lines += ["", "## observed missed opportunities (not counterfactual regret)", ""]
        for tid, notes in report["missed_opportunities"].items():
            lines.append(f"- **{tid}**")
            lines += [f"  - {n}" for n in notes]
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
