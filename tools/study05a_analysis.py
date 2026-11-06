"""Study-05A analysis — randomized recovery collection audit.

Reads the collect ledger and reports:
  1. Coverage: support counts per (prev_model, failure_category,
     attempt_count, action) — cells that were NOT IDENTIFIABLE before.
  2. Propensity integrity: draw distribution vs uniform, feasible-set
     correctness, forced-stop detection.
  3. Outcomes: next-attempt pass rate per cell (Wilson CIs, distinct tasks).
  4. Category informativeness: does category differentiate yield beyond
     prev_model + attempt_count?
  5. Challenger implications per the design doc's decision table.

Collection data is development data — these are sized hypotheses, not
policy rankings.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from study05_recovery_analysis import load_chains, wilson  # noqa: E402

DB = "eval/runs/study-05-collect/eval.db"


def main():
    tasks = load_chains(DB)
    print(f"loaded {len(tasks)} task-executions, "
          f"{len({t['task'] for t in tasks})} distinct tasks\n")

    cells = defaultdict(lambda: {"n": 0, "succ": 0, "tasks": set(),
                                 "costs": [], "lats": [], "feas_lens": []})
    for t in tasks:
        for i, a in enumerate(t["attempts"]):
            r = a.get("recovery")
            if not r or not a["model"]:
                continue
            nxt = t["attempts"][i + 1] if i + 1 < len(t["attempts"]) else None
            key = (a["model"], a["failcat"] or "inconclusive",
                   r["ctx"].get("attempt_count"),
                   r["action"], r["next_model"] or "-")
            v = cells[key]
            v["n"] += 1
            v["tasks"].add(t["task"])
            if nxt:
                v["costs"].append(nxt["cost"])
                v["lats"].append(nxt["latency"])
                if nxt["status"] == "passed":
                    v["succ"] += 1

    print("## 1-3. coverage + outcomes per (prev_model, category, attempt_count, action)")
    hdr = (f"{'prev':<12}{'category':<18}{'@att':<5}{'action':<10}{'next':<14}"
           f"{'tasks':<6}{'n':<4}{'pass CI95':<20}{'cost':<9}{'lat'}")
    print(hdr)
    for k, v in sorted(cells.items()):
        lo, hi = wilson(v["succ"], v["n"])
        succ = f"{v['succ']}/{v['n']} [{lo:.2f},{hi:.2f}]"
        mc = f"${sum(v['costs'])/len(v['costs']):.4f}" if v["costs"] else "-"
        ml = f"{sum(v['lats'])/len(v['lats']):.0f}ms" if v["lats"] else "-"
        print(f"{k[0]:<12}{k[1]:<18}{k[2]!s:<5}{k[3]:<10}{k[4]:<14}"
              f"{len(v['tasks']):<6}{v['n']:<4}{succ:<20}{mc:<9}{ml}")

    # propensity integrity: draws per feasible size should be ~uniform
    print("\n## 2. propensity integrity")
    c = sqlite3.connect(DB)
    draws = defaultdict(lambda: defaultdict(int))
    forced = 0
    for (p,) in c.execute("SELECT payload FROM events WHERE event_type='recovery_decided'"):
        d = json.loads(p)
        feas = d.get("feasible_actions") or []
        if len(feas) <= 1:
            forced += 1
            continue
        chosen = f"{d['action']}:{d['model_id'] or '-'}"
        chosen_norm = chosen.replace("escalate:", "switch:")
        draws[len(feas)][chosen_norm] += 1
    for size, d in sorted(draws.items()):
        tot = sum(d.values())
        exp = tot / size
        chi = sum((n - exp) ** 2 / exp for n in d.values())
        print(f"  |feas|={size}: draws={dict(d)} (chi2 vs uniform = {chi:.2f}, "
              f"crit@.05 ≈ {3.84 if size == 2 else 5.99 if size == 3 else 7.81:.2f})")
    print(f"  forced (|feas|=1, terminal): {forced} decisions")

    # pooled action yields at the primary state
    print("\n## 4. pooled yields, weak-fail @1 by action")
    agg = defaultdict(lambda: [0, 0, set()])
    for (pm, fc, ac, act, nm), v in cells.items():
        if pm == "weak-coder" and ac == 1 and act != "stop":
            g = agg[act]
            g[0] += v["succ"]
            g[1] += v["n"]
            g[2] |= v["tasks"]
    for act, (k, n, tk) in sorted(agg.items()):
        lo, hi = wilson(k, n)
        print(f"  {act:<10} {k}/{n} = {k/n:.2f} [{lo:.2f},{hi:.2f}] ({len(tk)} tasks)")
    print("\n## 4b. pooled yields, strong-fail @1 by action")
    agg = defaultdict(lambda: [0, 0, set()])
    for (pm, fc, ac, act, nm), v in cells.items():
        if pm == "strong-coder" and ac == 1 and act != "stop":
            g = agg[f"{act}:{nm}"]
            g[0] += v["succ"]
            g[1] += v["n"]
            g[2] |= v["tasks"]
    for act, (k, n, tk) in sorted(agg.items()):
        lo, hi = wilson(k, n)
        print(f"  {act:<22} {k}/{n} = {k/n:.2f} [{lo:.2f},{hi:.2f}] ({len(tk)} tasks)")

    print("\n## 5. category informativeness (weak-fail @1 -> escalate yield)")
    for (pm, fc, ac, act, nm), v in cells.items():
        if pm == "weak-coder" and ac == 1 and act == "escalate":
            lo, hi = wilson(v["succ"], v["n"])
            print(f"  {fc:<18} {v['succ']}/{v['n']} [{lo:.2f},{hi:.2f}]")

    # invalid-evidence audit
    print("\n## invalid evidence check")
    for row in c.execute(
        "SELECT json_extract(payload,'$.failure_category'), COUNT(*) "
        "FROM events WHERE event_type='verification_completed' GROUP BY 1"
    ):
        print(" ", row)


if __name__ == "__main__":
    sys.exit(main())
