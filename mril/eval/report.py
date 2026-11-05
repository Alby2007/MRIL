"""Evaluation report — the constrained-comparison view.

Success is min cost subject to verified-completion within delta of the
quality ceiling arm; a policy that wins by abandoning hard tasks shows up
as a completion-rate violation, not a bargain. Costs are normalized
token-price estimates on local drivers — labeled, never billed money.
"""

from __future__ import annotations

import json
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
    guardrail = {
        "quality_baseline": quality_baseline,
        "delta": delta,
        "violations": [
            {
                "arm": name,
                "completion_gap": (base_rate or 0) - (s["verified_completion_rate"] or 0),
            }
            for name, s in arms.items()
            if base_rate is not None
            and s["verified_completion_rate"] is not None
            and s["verified_completion_rate"] < base_rate - delta
        ],
    }
    return {"manifest": manifest, "arms": arms, "guardrail": guardrail}


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
        "",
        "switch spend (re-ingest, not counterfactual): "
        + " | ".join(
            f"{n}: est ${s['estimated_switch_cost_usd']:.4f} → obs ${s['actual_switch_cost_usd']:.4f}"
            for n, s in report["arms"].items()
        ),
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
