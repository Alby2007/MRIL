"""Study 05 offline recovery diagnostics — reconstruction of attempt chains
from existing eval ledgers. Read-only; no model calls.

Analyses:
  A. Failure-to-recovery transition table (observed cells only; unobserved
     actions are "unsupported", not zero-probability)
  B. Sensitivity by attempts used / attempts remaining (from RecoveryContext)
  C. Strong-retry-after-strong-fail vs strong-rescue-after-weak-fail
  D. Recoverability vs capability ceilings (per task, by feature cell)
  E. Action/failure-category coverage audit -> evidence classification

Every figure is tagged: OBSERVED (directly measured), ESTIMATED (predicted
from observed transitions with uncertainty), or NOT IDENTIFIABLE (no
propensity support for the alternative action).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

LEDDERS = [
    "study-01",  # uncontrolled generation — development data
    "study-02",
    "study-03-train",
    "study-03-dev",
    "study-04",
]


def load_chains(db_path: str):
    """Reconstruct per-task attempt chains ordered by ledger seq.

    Returns list of tasks: {task_id, task, arm, seed, attempts:[...], final}
    attempt: {model, cost, latency, status, failcat}
    between attempts: recovery decision linking prev attempt to next.
    """
    c = sqlite3.connect(db_path)
    rows = c.execute(
        "SELECT seq, task_id, event_type, payload FROM events WHERE task_id IS NOT NULL ORDER BY task_id, seq"
    ).fetchall()
    tasks = defaultdict(list)
    for seq, tid, et, p in rows:
        tasks[tid].append((seq, et, json.loads(p)))

    out = []
    for tid, evs in tasks.items():
        parts = tid.split(":")
        if len(parts) < 3:
            continue
        attempts = {}   # attempt_id -> dict
        order = []      # attempt_ids in seq order
        recovs = []     # (after_attempt_id, action, next_model, ctx)
        inv_by_aid = {}
        ver_by_aid = {}
        final = None
        for seq, et, p in evs:
            if et == "model_invocation_finished":
                aid = p.get("attempt_id") or f"inv{len(order)}"
                inv_by_aid[aid] = p
                order.append(aid)
            elif et == "verification_completed":
                ver_by_aid[p.get("attempt_id") or (order[-1] if order else "?")] = p
            elif et == "recovery_decided":
                ctx = p.get("recovery_context") or {}
                recovs.append({
                    "after": ctx.get("last_attempt_id"),
                    "action": p.get("action"),
                    "next_model": p.get("model_id"),
                    "ctx": ctx,
                })
            elif et == "task_finalized":
                final = p
        atts = []
        for aid in order:
            inv, ver = inv_by_aid.get(aid, {}), ver_by_aid.get(aid, {})
            atts.append({
                "aid": aid,
                "model": inv.get("model_id"),
                "cost": inv.get("cost_usd") or 0.0,
                "latency": inv.get("latency_ms") or 0,
                "status": ver.get("status"),
                "failcat": ver.get("failure_category"),
            })
        # link recovery to the attempt it follows (by last_attempt_id, else previous)
        for i, r in enumerate(recovs):
            idx = next((j for j, a in enumerate(atts) if a["aid"] == r["after"]), i)
            if idx < len(atts):
                atts[idx]["recovery"] = r
        out.append({
            "task_id": tid, "task": parts[0], "arm": parts[1],
            "seed": parts[2] if len(parts) > 2 else "?",
            "attempts": atts, "final": final,
        })
    return out


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def main():
    all_tasks = []
    for name in LEDDERS:
        p = Path(f"eval/runs/{name}/eval.db")
        if p.exists():
            all_tasks += load_chains(str(p))
    print(f"attempt chains loaded: {len(all_tasks)} task-executions "
          f"({len({t['task'] for t in all_tasks})} distinct tasks, {len({t['task_id'].rsplit(':',1)[0] for t in all_tasks})} task×arm cells)\n")

    # ---------- A: transition table ----------
    trans = defaultdict(lambda: {"n": 0, "succ": 0, "tasks": set(), "costs": [], "lats": []})
    for t in all_tasks:
        for i, a in enumerate(t["attempts"]):
            r = a.get("recovery")
            if not r or not a["model"]:
                continue
            next_att = t["attempts"][i + 1] if i + 1 < len(t["attempts"]) else None
            key = (a["model"], a["failcat"] or a["status"], r["action"], r["next_model"])
            cell = trans[key]
            cell["n"] += 1
            cell["tasks"].add(t["task"])
            if next_att is not None:
                cell["costs"].append(next_att["cost"])
                cell["lats"].append(next_att["latency"])
                if next_att["status"] == "passed":
                    cell["succ"] += 1
            else:
                cell["succ"] += 0  # terminal — no next attempt

    print("## A. failure-to-recovery transition table (OBSERVED cells only)")
    print(f"{'prev model':<12}{'fail type':<14}{'action':<10}{'next model':<13}{'distinct tasks':<15}{'transitions':<12}{'next-att succ':<22}{'mean next cost':<15}{'mean next lat'}")
    for (pm, fc, act, nm), v in sorted(trans.items()):
        k, n = v["succ"], v["n"]
        lo, hi = wilson(k, n)
        succ = f"{k}/{n} [{lo:.2f},{hi:.2f}]" if n else "—"
        mc = f"${sum(v['costs'])/len(v['costs']):.4f}" if v["costs"] else "—"
        ml = f"{sum(v['lats'])/len(v['lats']):.0f}ms" if v["lats"] else "—"
        print(f"{pm:<12}{fc:<14}{act:<10}{str(nm):<13}{len(v['tasks']):<15}{n:<12}{succ:<22}{mc:<15}{ml}")
    print("\nUNOBSERVED (unsupported, not p=0): weak→retry-weak, weak→stop, "
          "any action on a failure category other than test_failure, any 3rd attempt.")

    # ---------- B: attempts-used sensitivity ----------
    print("\n## B. recovery decisions by attempts used (OBSERVED)")
    by_used = defaultdict(lambda: defaultdict(int))
    for t in all_tasks:
        for a in t["attempts"]:
            r = a.get("recovery")
            if r:
                ctx = r["ctx"]
                by_used[(ctx.get("attempt_count"), ctx.get("max_attempts"))][r["action"]] += 1
    for k, acts in sorted(by_used.items()):
        print(f"  attempt_count={k[0]}/{k[1]}: {dict(acts)}")
    print("  -> policy deterministically maps (model, attempt_count) to action; "
          "remaining-attempt sensitivity is unobservable beyond this boundary.")

    # ---------- C: strong retry vs strong rescue ----------
    print("\n## C. strong retry-after-strong-fail vs strong rescue-after-weak-fail")
    for label, pred in [("rescue (weak failed -> strong)", lambda pm: pm == "weak-coder"),
                        ("retry  (strong failed -> strong)", lambda pm: pm == "strong-coder")]:
        k = n = 0
        tasks = set()
        costs, lats = [], []
        for t in all_tasks:
            for i, a in enumerate(t["attempts"]):
                r = a.get("recovery")
                if r and r["next_model"] == "strong-coder" and a["failcat"] == "test_failure" and pred(a["model"]):
                    n += 1
                    tasks.add(t["task"])
                    if i + 1 < len(t["attempts"]):
                        na = t["attempts"][i + 1]
                        costs.append(na["cost"])
                        lats.append(na["latency"])
                        if na["status"] == "passed":
                            k += 1
        lo, hi = wilson(k, n)
        print(f"  {label}: {k}/{n} = {k/n:.2f} CI95[{lo:.2f},{hi:.2f}] over {len(tasks)} distinct tasks; "
              f"mean next-att cost ${sum(costs)/len(costs):.4f}, lat {sum(lats)/len(lats):.0f}ms")
    print("  OBSERVED rates; comparison is NOT causal (different task mixes/histories).")

    # ---------- D: recoverability vs ceilings ----------
    print("\n## D. task-level recoverability (OBSERVED; 3 seeds is not proof of permanent ceiling)")
    taskrec = defaultdict(lambda: {"weak_fail_then_strong": [0, 0], "strong_ever": [0, 0],
                                   "weak_ever": [0, 0], "strong_runs": 0})
    for t in all_tasks:
        rec = taskrec[t["task"]]
        for i, a in enumerate(t["attempts"]):
            if a["model"] == "strong-coder":
                rec["strong_runs"] += 1
                rec["strong_ever"][1] += 1
                if a["status"] == "passed":
                    rec["strong_ever"][0] += 1
            if a["model"] == "weak-coder":
                rec["weak_ever"][1] += 1
                if a["status"] == "passed":
                    rec["weak_ever"][0] += 1
            r = a.get("recovery")
            if r and a["model"] == "weak-coder" and r["action"] == "escalate" and i + 1 < len(t["attempts"]):
                rec["weak_fail_then_strong"][1] += 1
                if t["attempts"][i + 1]["status"] == "passed":
                    rec["weak_fail_then_strong"][0] += 1
    print(f"  {'task':<26}{'weak pass':<12}{'strong pass':<13}{'rescue after weak fail'}")
    for task, r in sorted(taskrec.items()):
        wp = f"{r['weak_ever'][0]}/{r['weak_ever'][1]}"
        sp = f"{r['strong_ever'][0]}/{r['strong_ever'][1]}"
        resc = f"{r['weak_fail_then_strong'][0]}/{r['weak_fail_then_strong'][1]}" if r["weak_fail_then_strong"][1] else "—"
        ceil = "  <- ceiling candidate (strong never verified)" if r["strong_ever"][1] and r["strong_ever"][0] == 0 else ""
        print(f"  {task:<26}{wp:<12}{sp:<13}{resc}{ceil}")

    # ---------- E: coverage / identifiability ----------
    print("\n## E. evidence classification")
    print("  OBSERVED: weak-fail→escalate→strong transitions; strong-fail→retry→strong;")
    print("            strong-fail@2→stop; next-attempt cost/latency/outcome for each.")
    print("  ESTIMATED (only via model): per-task weak/strong pass rates above.")
    print("  NOT IDENTIFIABLE from this ledger:")
    print("    - weak retry after weak failure (0 propensity across all ledgers)")
    print("    - stop after first weak failure (never observed)")
    print("    - any recovery action on failure categories other than test_failure")
    print("      (no contract/syntax/api-error/timeout failures were ever recorded)")
    print("    - any 3rd attempt (policy stops at attempt_count=2; max_attempts=3 unused)")
    print("    - retry vs escalate *choice* under identical context (policy is deterministic:")
    print("      weak-fail@1→escalate, strong-fail@1→retry — no within-cell action variation)")
    print("\n  SAFEGUARD: no 'recovery policy X would save Y%' claim is supportable")
    print("  from these data — the alternative arms lack propensity coverage.")


if __name__ == "__main__":
    sys.exit(main())
