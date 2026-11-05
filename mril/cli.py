"""MRIL CLI — inspect why models were chosen, straight from the ledger."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mril.core.events import RouteDecided, TaskFinalized
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


def cmd_task(args) -> int:
    store = _store(args)
    events = store.events_for_task(args.task_id)
    if not events:
        print(f"no events for task {args.task_id!r}", file=sys.stderr)
        return 1
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
    models = dict(kv.split("=", 1) for kv in args.ollama_model)
    missing = [m.model_id for m in registry.models if not m.restricted and m.model_id not in models]
    if missing:
        print(f"no --ollama-model mapping for: {', '.join(missing)}", file=sys.stderr)
        return 1
    driver = OllamaDriver(models, host=args.ollama_host)
    runner = EvalRunner(
        registry=registry,
        driver=driver,
        verifier=CommandVerifier(corpus.root),
        default_constraints=RoutingConstraints(
            fallback_model_id=args.fallback, budget_usd=args.budget
        ),
        keep_workspaces=args.keep_workspaces,
    )
    wanted = {a.name: a for a in default_arms()}
    arms = tuple(wanted[n] for n in args.arms.split(",") if n in wanted)
    seeds = tuple(int(s) for s in args.seeds.split(","))
    results = run_matrix(
        corpus, registry, runner, args.out,
        seeds=seeds, arms=arms,
        store_factory=lambda p: SQLiteEventStore(p),
    )
    manifest = json.loads((Path(args.out) / "manifest.json").read_text())
    report = build_report(results, manifest)
    write_report(report, args.out)
    print(f"{len(results)} runs -> {args.out}/REPORT.md")
    return 0


def cmd_eval_report(args) -> int:
    from mril.eval.report import build_report, write_report
    from mril.eval.results import load_results

    out = Path(args.out_dir)
    manifest = json.loads((out / "manifest.json").read_text())
    report = build_report(load_results(out / "results.jsonl"), manifest, delta=args.delta)
    write_report(report, out)
    print((out / "REPORT.md").read_text())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mril", description="Model Routing Intelligence Layer")
    p.add_argument("--db", help="path to the MRIL SQLite ledger (default: mril.db or $MRIL_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("explain", help="explain a routing decision")
    e.add_argument("decision_id")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_explain)

    t = sub.add_parser("task", help="show the event timeline for a task")
    t.add_argument("task_id")
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
    er.add_argument("--ollama-model", action="append", default=[],
                    metavar="REG_ID=TAG", help="registry model_id -> ollama tag (repeatable)")
    er.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    er.set_defaults(fn=cmd_eval_run)

    ep = evsub.add_parser("report", help="rebuild the report from an eval output dir")
    ep.add_argument("out_dir")
    ep.add_argument("--delta", type=float, default=0.05)
    ep.set_defaults(fn=cmd_eval_report)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
