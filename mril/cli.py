"""MRIL CLI — inspect why models were chosen, straight from the ledger."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mril.core.events import (
    Event,
    ModelInvocationFinished,
    RecoveryDecided,
    RouteDecided,
    TaskFinalized,
    TaskStarted,
    VerificationCompleted,
)
from mril.policy.state import rebuild_state
from mril.store.sqlite import SQLiteEventStore


def _store(args) -> SQLiteEventStore:
    return SQLiteEventStore(args.db or os.environ.get("MRIL_DB", "mril.db"))


def cmd_explain(args) -> int:
    store = _store(args)
    events = store.events_for_decision(args.decision_id)
    route = next((e for e in events if isinstance(e, RouteDecided)), None)
    if route is None:
        # maybe the argument was an event_id
        e = store.get(args.decision_id)
        route = e if isinstance(e, RouteDecided) else None
    if route is None:
        print(f"no routing decision found for {args.decision_id!r}", file=sys.stderr)
        return 1
    print(f"decision  {route.decision_id}")
    print(f"task      {route.task_id}   step={route.step_index} call_site={route.call_site}")
    print(f"model     {route.model_id}   (p={route.selection_probability})")
    print(f"policy    {route.policy_name}@{route.policy_version} #{route.policy_hash}")
    print(f"registry  v{route.registry_version} #{route.registry_hash}")
    print(f"seed      {route.decision_seed}")
    if route.degraded:
        print("MODE      DEGRADED (fallback path)")
    print(f"reason    {route.reason}")
    if route.estimated_cost_usd is not None:
        print(f"est cost  ${route.estimated_cost_usd:.4f}")
    print(f"candidates {', '.join(route.candidates)}")
    if args.json:
        print(json.dumps(route.to_dict(), indent=2, default=str))
    return 0


def _task_summary(task_id: str, events: list[Event]) -> dict:
    """Derive the per-attempt task summary from committed ledger events.

    Pure read-only projection: attempts are grouped by attempt_id (any
    route/invocation/verification event that carries it). RecoveryDecided
    carries no attempt_id, so it is attributed via the recorded
    recovery_context.last_attempt_id when present; ledger-order position is
    a fallback and is labeled "inferred" — concurrent attempts can
    interleave and make positional attribution wrong.
    """
    order: list[str] = []
    by_attempt: dict[str, dict] = {}
    recoveries: list[dict] = []
    orphan_decisions: list[RouteDecided] = []
    started: TaskStarted | None = None
    fin: TaskFinalized | None = None
    # RouteDecided doesn't carry attempt_id; invocations link it via
    # decision_id — build the map first, then bucket routes into attempts.
    dec_to_att = {
        e.decision_id: e.attempt_id
        for e in events
        if isinstance(e, ModelInvocationFinished) and e.decision_id and e.attempt_id
    }

    def att(aid: str) -> dict:
        if aid not in by_attempt:
            by_attempt[aid] = {"attempt_id": aid, "routes": [], "calls": [],
                               "verifications": []}
            order.append(aid)
        return by_attempt[aid]

    for e in events:
        if isinstance(e, TaskStarted):
            started = e
        elif isinstance(e, TaskFinalized):
            fin = e
        elif isinstance(e, RouteDecided):
            aid = e.attempt_id or dec_to_att.get(e.decision_id)
            if aid:
                att(aid)["routes"].append(e)
            else:
                # A decision that never produced an observed call is audit
                # evidence — surface it, never drop it.
                orphan_decisions.append(e)
        elif isinstance(e, ModelInvocationFinished):
            if e.attempt_id:
                att(e.attempt_id)["calls"].append(e)
        elif isinstance(e, VerificationCompleted):
            if e.attempt_id:
                att(e.attempt_id)["verifications"].append(e)
        elif isinstance(e, RecoveryDecided):
            # Prefer the recorded recovery_context.last_attempt_id — it's what
            # the policy actually saw. Ledger-order position only *infers* the
            # attempt and can be wrong when concurrent attempts interleave.
            recorded = (e.recovery_context or {}).get("last_attempt_id")
            if recorded:
                after, attribution = recorded, "recorded"
            elif order:
                after, attribution = order[-1], "inferred"
            else:
                after, attribution = None, "inferred"
            recoveries.append(
                {"event": e, "after_attempt_id": after, "attribution": attribution}
            )

    attempts: list[dict] = []
    for i, aid in enumerate(order):
        bucket = by_attempt[aid]
        calls: list[ModelInvocationFinished] = bucket["calls"]
        routes: list[RouteDecided] = bucket["routes"]
        vers: list[VerificationCompleted] = bucket["verifications"]
        last_v = vers[-1] if vers else None
        known_costs = [c.cost_usd for c in calls if c.cost_usd is not None]
        last_route = routes[-1] if routes else None
        attempts.append(
            {
                "attempt_id": aid,
                "index": i + 1,
                "model_id": (calls[-1].model_id if calls else None)
                or (last_route.model_id if last_route else None),
                "calls": len(calls),
                "cost_usd": sum(known_costs) if known_costs else None,
                "input_tokens": sum(c.input_tokens or 0 for c in calls) or None,
                "output_tokens": sum(c.output_tokens or 0 for c in calls) or None,
                "api_error": next(
                    (c.api_error for c in reversed(calls) if c.api_error), None
                ),
                "verification_status": last_v.status.value if last_v else None,
                "verifier_type": last_v.verifier_type if last_v else None,
                "failure_category": last_v.failure_category if last_v else None,
                "decision_ids": [r.decision_id for r in routes if r.decision_id],
                "route_reason": last_route.reason if last_route else None,
                "policy": (
                    f"{last_route.policy_name}@{last_route.policy_version}"
                    if last_route
                    else None
                ),
            }
        )

    recs = [
        {
            "action": r["event"].action,
            "model_id": r["event"].model_id,
            "reason": r["event"].reason,
            "estimated_cost_usd": r["event"].estimated_cost_usd,
            "estimated_switch_cost_usd": r["event"].estimated_switch_cost_usd,
            "after_attempt_id": r["after_attempt_id"],
            "attribution": r["attribution"],
            "feasible_actions": list(r["event"].feasible_actions),
        }
        for r in recoveries
    ]

    return {
        "task_id": task_id,
        "language": started.language if started else None,
        "task_type": started.task_type if started else None,
        "scope": started.scope if started else None,
        "risk": started.risk if started else None,
        "harness": started.harness if started else None,
        "attempts": attempts,
        "recoveries": recs,
        "finalized": fin is not None,
        "outcome": fin.task_outcome.value if fin else "open",
        "total_cost_usd": fin.total_cost_usd if fin else None,
        "elapsed_ms": fin.elapsed_ms if fin else None,
        "attempt_count": fin.attempt_count if fin else len(attempts),
        "escalation_count": fin.escalation_count if fin else sum(
            1 for r in recs if r["action"] == "escalate"
        ),
        "actual_switch_cost_usd": fin.actual_switch_cost_usd if fin else None,
        "switch_cost_basis": fin.switch_cost_basis if fin else None,
        "model_calls": sum(a["calls"] for a in attempts),
        "orphan_decisions": [
            {
                "decision_id": r.decision_id,
                "model_id": r.model_id,
                "step_index": r.step_index,
                "call_site": r.call_site,
                "reason": r.reason,
            }
            for r in orphan_decisions
        ],
    }


def _fmt_usd(v: float | None) -> str:
    return f"${v:.4f}" if v is not None else "n/a"


def _print_task_summary(s: dict) -> None:
    print(f"Task          {s['task_id']}")
    meta = [s[k] for k in ("task_type", "scope", "risk", "language", "harness") if s[k]]
    if meta:
        print(f"Context       {' / '.join(meta)}")
    print(f"Outcome       {s['outcome'].upper()}")
    print(f"Attempts      {s['attempt_count']}")
    print(f"Model calls   {s['model_calls']}")
    if s["finalized"]:
        print(f"Total cost    {_fmt_usd(s['total_cost_usd'])}")
        if s["elapsed_ms"] is not None:
            print(f"Elapsed       {s['elapsed_ms'] / 1000:.1f}s")
    else:
        state_cost = sum(
            a["cost_usd"] or 0.0 for a in s["attempts"]
        )
        print(f"Cost so far   ${state_cost:.4f}   (task not finalized)")

    rec_by_attempt = {a["attempt_id"]: a for a in s["attempts"]}
    for att in s["attempts"]:
        print(f"\nATTEMPT {att['index']} ({att['attempt_id'][:12]})")
        model_line = f"  Model       {att['model_id'] or 'unknown'}"
        if att["policy"]:
            model_line += f"   via {att['policy']}"
        print(model_line)
        if att["route_reason"]:
            print(f"  Reason      {att['route_reason']}")
        call_line = f"  Calls       {att['calls']}"
        call_line += f"   cost={_fmt_usd(att['cost_usd'])}"
        if att["input_tokens"] or att["output_tokens"]:
            call_line += (
                f"   tokens={att['input_tokens'] or 0}in/"
                f"{att['output_tokens'] or 0}out"
            )
        print(call_line)
        if att["api_error"]:
            print(f"  API error   {att['api_error']}")
        if att["verification_status"]:
            vline = f"  Verification {att['verification_status'].upper()}"
            if att["failure_category"]:
                vline += f" ({att['failure_category']})"
            if att["verifier_type"]:
                vline += f" via {att['verifier_type']}"
            print(vline)
        else:
            print("  Verification not reported")

        for r in s["recoveries"]:
            if r["after_attempt_id"] != att["attempt_id"]:
                continue
            print("\nRECOVERY")
            line = f"  Action      {r['action']}"
            if r["model_id"]:
                line += f" -> {r['model_id']}"
            if r["attribution"] == "inferred":
                line += "   (attempt link inferred from ledger order)"
            print(line)
            print(f"  Reason      {r['reason']}")
            if r["estimated_cost_usd"] is not None:
                sw = r["estimated_switch_cost_usd"]
                est = f"  Est. cost   {_fmt_usd(r['estimated_cost_usd'])}"
                if sw is not None:
                    est += f" (incl. switch {_fmt_usd(sw)})"
                print(est)
            if r["feasible_actions"]:
                print(f"  Feasible    {', '.join(r['feasible_actions'])}")

    unattributed = [r for r in s["recoveries"] if r["after_attempt_id"] is None]
    if unattributed or s["orphan_decisions"]:
        print("\nUNRESOLVED")
        for r in unattributed:
            print(f"  Recovery {r['action']} — no attempt link recorded")
        for d in s["orphan_decisions"]:
            print(
                f"  Route decided but never invoked: {d['model_id']}"
                f" (decision {d['decision_id'][:12]}, step {d['step_index']})"
            )

    print("\nFINAL")
    if s["finalized"]:
        print(f"  Outcome     {s['outcome']}")
        print(f"  Cost        {_fmt_usd(s['total_cost_usd'])}"
              f"   escalations={s['escalation_count']}")
        if s["actual_switch_cost_usd"] is not None:
            print(
                f"  Switch cost {_fmt_usd(s['actual_switch_cost_usd'])}"
                f" ({s['switch_cost_basis'] or 'unknown basis'})"
            )
    else:
        print("  Task still open — call router.finalize() when the task ends.")
    print("  Decisions:")
    for att in s["attempts"]:
        for did in att["decision_ids"]:
            print(f"    attempt {att['index']}: mril explain {did}")


def cmd_task(args) -> int:
    store = _store(args)
    events = store.events_for_task(args.task_id)
    if not events:
        print(f"no events for task {args.task_id!r}", file=sys.stderr)
        return 1
    if args.timeline:
        for e in events:
            line = f"{e.occurred_at}  {e.event_type}"
            if getattr(e, "model_id", None):
                line += f"  model={e.model_id}"
            if getattr(e, "action", None):
                line += f"  action={e.action}"
            print(line)
        state = rebuild_state(args.task_id, events)
        print(f"\nattempts={len(state.attempts)}  cost=${state.total_cost_usd:.4f}  "
              f"escalations={state.escalation_count}")
        return 0
    summary = _task_summary(args.task_id, events)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return 0
    _print_task_summary(summary)
    return 0


def cmd_tasks(args) -> int:
    store = _store(args)
    for tid in store.task_ids():
        events = store.events_for_task(tid)
        fin = next((e for e in events if isinstance(e, TaskFinalized)), None)
        state = rebuild_state(tid, events)
        outcome = fin.task_outcome.value if fin else "open"
        print(f"{tid}  attempts={len(state.attempts)}  "
              f"cost=${state.total_cost_usd:.4f}  outcome={outcome}")
    return 0


def cmd_eval_run(args) -> int:
    from mril.eval import (
        CommandVerifier, EvalRunner, OllamaDriver, default_arms, load_corpus,
        run_matrix,
    )
    from mril.eval.report import build_report, write_report
    from mril.eval.spec import load_registry
    from mril.core.task import RoutingConstraints

    corpus = load_corpus(args.corpus)
    registry = load_registry(args.registry)

    from mril.eval.arms import collection_arms

    wanted = {a.name: a for a in default_arms()}
    wanted.update({a.name: a for a in collection_arms(args.collection_seed)})
    if args.empirical_policy:
        from mril.eval.arms import Arm
        from mril.policy.empirical import EmpiricalCheapFirstPolicy, PolicySnapshot

        snap = PolicySnapshot.from_dict(
            json.loads(Path(args.empirical_policy).read_text(encoding="utf-8"))
        )
        wanted["empirical-cheap-first"] = Arm(
            "empirical-cheap-first",
            EmpiricalCheapFirstPolicy(snapshot=snap, epsilon=snap.epsilon),
        )
    requested = args.arms.split(",")
    unknown = [n for n in requested if n not in wanted]
    if unknown:
        print(
            f"unknown arms: {', '.join(unknown)} "
            f"(available: {', '.join(sorted(wanted))})",
            file=sys.stderr,
        )
        return 1
    arms = tuple(wanted[n] for n in requested)

    models = dict(kv.split("=", 1) for kv in args.ollama_model)
    missing = [m.model_id for m in registry.models if not m.restricted and m.model_id not in models]
    if missing:
        print(f"no --ollama-model mapping for: {', '.join(missing)}", file=sys.stderr)
        return 1
    driver = OllamaDriver(
        models, host=args.ollama_host,
        temperature=args.temperature, top_p=args.top_p, num_ctx=args.num_ctx,
    )
    runner = EvalRunner(
        registry=registry,
        driver=driver,
        verifier=CommandVerifier(corpus.root),
        default_constraints=RoutingConstraints(
            fallback_model_id=args.fallback, budget_usd=args.budget
        ),
        keep_workspaces=args.keep_workspaces,
        capture_dir=Path(args.capture_failures) if args.capture_failures else None,
    )
    seeds = tuple(int(s) for s in args.seeds.split(","))
    results = run_matrix(
        corpus, registry, runner, args.out,
        seeds=seeds, arms=arms,
        store_factory=lambda p: SQLiteEventStore(p),
    )
    manifest = json.loads(
        (Path(args.out) / "manifest.json").read_text(encoding="utf-8")
    )
    report = build_report(results, manifest)
    write_report(report, args.out)
    print(f"{len(results)} runs -> {args.out}/REPORT.md")
    return 0


def cmd_eval_train(args) -> int:
    from mril.eval.train import fit_to_file

    snap = fit_to_file(
        args.ledger, args.out,
        weak_id=args.weak, strong_id=args.strong,
        prior_strength=args.prior_strength,
        quality_margin=args.quality_margin, epsilon=args.epsilon,
    )
    print(f"snapshot {snap.hash} -> {args.out} "
          f"({snap.trained_on_runs} runs, "
          f"global weak rate {snap.beta.get('global')})")
    return 0


def cmd_eval_report(args) -> int:
    from mril.eval.report import build_report, write_report
    from mril.eval.results import load_results

    out = Path(args.out_dir)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    report = build_report(load_results(out / "results.jsonl"), manifest, delta=args.delta)
    write_report(report, out)
    print((out / "REPORT.md").read_text(encoding="utf-8"))
    return 0


def cmd_eval_probe(args) -> int:
    """Study-05B: replay captured failure checkpoints under both handoff arms."""
    from mril.eval import CommandVerifier, OllamaDriver, load_corpus  # noqa: F401
    from mril.eval.probe import paired_report, run_probe
    from mril.eval.spec import load_registry

    registry = load_registry(args.registry)
    models = dict(kv.split("=", 1) for kv in args.ollama_model)
    driver = OllamaDriver(
        models, host=args.ollama_host,
        temperature=args.temperature, top_p=args.top_p, num_ctx=args.num_ctx,
    )
    results = run_probe(
        checkpoints_dir=Path(args.checkpoints),
        corpus_root=Path(args.corpus),
        registry=registry,
        driver=driver,
        verifier=CommandVerifier(Path(args.corpus)),
        model_id=args.model,
        out_dir=Path(args.out),
        probe_seed=args.probe_seed,
        failed_model=args.failed_model,
    )
    rep = paired_report(results)
    (Path(args.out) / "PROBE-REPORT.txt").write_text(rep + "\n", encoding="utf-8")
    print(rep)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mril", description="Model Routing Intelligence Layer")
    p.add_argument("--db", help="path to the MRIL SQLite ledger (default: mril.db or $MRIL_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("explain", help="explain a routing decision")
    e.add_argument("decision_id")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_explain)

    t = sub.add_parser("task", help="summarize a task's attempts, verification and recovery")
    t.add_argument("task_id")
    t.add_argument("--json", action="store_true", help="machine-readable summary")
    t.add_argument("--timeline", action="store_true",
                   help="raw per-event timeline (the old view)")
    t.set_defaults(fn=cmd_task)

    sub.add_parser("tasks", help="list tasks in the ledger").set_defaults(fn=cmd_tasks)

    ev = sub.add_parser("eval", help="evaluation harness: run a corpus matrix or build a report")
    evsub = ev.add_subparsers(dest="eval_cmd", required=True)

    er = evsub.add_parser("run", help="run task x arm x seed matrix")
    er.add_argument("--corpus", required=True, help="corpus root (task dirs with task.json)")
    er.add_argument("--registry", required=True, help="model registry JSON")
    er.add_argument("--out", required=True, help="output dir (ledger, manifest, results, report)")
    er.add_argument("--arms", default="strongest-only,cheap-first,mril-tiered")
    er.add_argument("--seeds", default="0")
    er.add_argument("--budget", type=float, default=1.0, help="token-priced budget per task")
    er.add_argument("--fallback", help="fallback model_id for degraded path")
    er.add_argument("--keep-workspaces", action="store_true")
    er.add_argument("--capture-failures", metavar="DIR",
                    help="snapshot workspace+feedback at each failed attempt (Study-05B)")
    er.add_argument("--ollama-model", action="append", default=[],
                    metavar="REG_ID=TAG", help="registry model_id -> ollama tag (repeatable)")
    er.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    er.add_argument("--temperature", type=float, default=0.2)
    er.add_argument("--top-p", type=float, default=0.9)
    er.add_argument("--num-ctx", type=int, default=8192)
    er.add_argument("--collection-seed", type=int, default=0,
                    help="seed for randomized recovery draws on collect-* arms")
    er.add_argument("--empirical-policy", metavar="SNAPSHOT.json",
                    help="add an empirical-cheap-first arm from a trained snapshot")
    er.set_defaults(fn=cmd_eval_run)

    et = evsub.add_parser("train", help="fit an empirical-routing snapshot from a ledger")
    et.add_argument("--ledger", required=True, help="path to an eval eval.db")
    et.add_argument("--out", required=True, help="snapshot JSON out path")
    et.add_argument("--weak", default="weak-coder", help="weak model_id")
    et.add_argument("--strong", default="strong-coder", help="strong model_id")
    et.add_argument("--prior-strength", type=float, default=3.0)
    et.add_argument("--quality-margin", type=float, default=0.05)
    et.add_argument("--epsilon", type=float, default=0.0)
    et.set_defaults(fn=cmd_eval_train)

    ep = evsub.add_parser("report", help="rebuild the report from an eval output dir")
    ep.add_argument("out_dir")
    ep.add_argument("--delta", type=float, default=0.05)
    ep.set_defaults(fn=cmd_eval_report)

    pr = evsub.add_parser("probe", help="Study-05B paired handoff probe on captured checkpoints")
    pr.add_argument("--checkpoints", required=True)
    pr.add_argument("--corpus", required=True)
    pr.add_argument("--registry", required=True)
    pr.add_argument("--out", required=True)
    pr.add_argument("--model", default="strong-coder")
    pr.add_argument("--failed-model", default="weak-coder",
                    help="only probe checkpoints whose failed attempt used this model_id")
    pr.add_argument("--probe-seed", type=int, default=0)
    pr.add_argument("--ollama-model", action="append", default=[],
                    metavar="REG_ID=TAG")
    pr.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    pr.add_argument("--temperature", type=float, default=0.2)
    pr.add_argument("--top-p", type=float, default=0.9)
    pr.add_argument("--num-ctx", type=int, default=8192)
    pr.set_defaults(fn=cmd_eval_probe)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
