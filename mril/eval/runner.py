"""Evaluation runner — one task, one arm, one seed, one ledger.

The runner owns the attempt lifecycle and nothing else: materialize a fresh
workspace, route -> drive -> verify -> next_action until pass, stop, or the
task's limits. It records everything through the Router so the ledger —
not runner bookkeeping — is the source of truth for the report.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from mril.core.decision import RecoveryType
from mril.core.events import VerificationStatus, new_event_id
from mril.core.models import ModelRegistry
from mril.core.task import RoutingConstraints, TaskContext
from mril.eval.arms import Arm, apply_recovery
from mril.eval.corpus import Corpus
from mril.eval.drivers import AgentDriver
from mril.eval.results import RunResult
from mril.eval.spec import TaskSpec
from mril.eval.verifier import CommandVerifier
from mril.eval.workspace import Workspace
from mril.sdk import Router
from mril.store.base import EventStore


@dataclass(frozen=True)
class EvalRunner:
    registry: ModelRegistry
    driver: AgentDriver
    verifier: CommandVerifier
    default_constraints: RoutingConstraints
    keep_workspaces: bool = False

    def run(
        self,
        spec: TaskSpec,
        arm: Arm,
        seed: int,
        store: EventStore,
        work_root: Path,
    ) -> RunResult:
        run_task_id = f"{spec.task_id}:{arm.name}:{seed}"
        router = Router(store, self.registry, arm.policy, self.default_constraints)
        constraints = RoutingConstraints(
            fallback_model_id=self.default_constraints.fallback_model_id,
            budget_usd=spec.budget_usd or self.default_constraints.budget_usd,
            max_attempts=spec.max_attempts,
            require_capabilities=self.default_constraints.require_capabilities,
        )
        ctx = TaskContext(
            task_id=run_task_id,
            language=spec.language,
            task_type=spec.category,
            scope=spec.scope,
            risk=spec.risk,
            harness="mril-eval",
            metadata={"base_task": spec.task_id, "arm": arm.name, "seed": seed},
        )
        ws = Workspace.materialize(spec, self.verifier.corpus_root, work_root, run_task_id.replace(":", "_"))
        t0, model_calls, feedback = time.monotonic(), 0, None
        try:
            for attempt_i in range(spec.max_attempts):
                if model_calls >= spec.max_model_calls:
                    break
                if (time.monotonic() - t0) > spec.max_wall_seconds:
                    break
                attempt_id = new_event_id()
                d = router.route(ctx, constraints,
                                 step_index=attempt_i, call_site="attempt")
                res = self.driver.generate(
                    model_id=d.model_id,
                    spec=spec,
                    workspace=ws,
                    attempt_index=attempt_i,
                    prior_feedback=feedback,
                )
                model_calls += 1
                router.observe_invocation(
                    d.decision_id, d.model_id,
                    task_id=run_task_id, attempt_id=attempt_id,
                    input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                    cached_input_tokens=res.cached_input_tokens,
                    latency_ms=res.latency_ms, api_error=res.api_error,
                    provider_request_id=res.provider_request_id,
                    step_index=attempt_i, call_site="attempt",
                )
                if res.api_error:
                    action = router.next_action(run_task_id, constraints)
                    if action.type == RecoveryType.STOP:
                        break
                    constraints = apply_recovery(constraints, action)
                    continue
                verdict = self.verifier.verify(spec, ws)
                status = (
                    VerificationStatus.PASSED if verdict.passed is True
                    else VerificationStatus.FAILED if verdict.passed is False
                    else VerificationStatus.INCONCLUSIVE
                )
                router.observe_verification(
                    attempt_id, status,
                    task_id=run_task_id, verifier_type="test",
                    failure_category=None if verdict.passed else "test_failure",
                    verification_run_id=verdict.run_id,
                )
                if verdict.passed:
                    break
                feedback = verdict.stdout[-2000:]
                action = router.next_action(run_task_id, constraints)
                if action.type == RecoveryType.STOP:
                    break
                constraints = apply_recovery(constraints, action)
        finally:
            if not self.keep_workspaces:
                ws.cleanup()
        fin = router.finalize(run_task_id)
        return RunResult.from_ledger(
            store, run_task_id, spec.task_id, arm, seed,
            wall_ms=(time.monotonic() - t0) * 1000, finalized=fin,
        )


def run_matrix(
    corpus: Corpus,
    registry: ModelRegistry,
    runner: EvalRunner,
    out_dir: Path,
    *,
    seeds: tuple[int, ...] = (0,),
    arms: tuple[Arm, ...],
    store_factory,
    run_order_seed: int = 0,
) -> list[RunResult]:
    """Controlled comparison: every task x arm x seed under identical limits.

    One ledger (eval.db) for the whole matrix; run_task_ids are namespaced
    task:arm:seed so `mril task` inspects any cell directly. Run order is
    deterministically interleaved (run_order_seed, recorded in the manifest)
    so warm model caches / thermal state can't systematically favor the arm
    that happens to run first or last.
    """
    import random

    out_dir = Path(out_dir)
    (out_dir / "work").mkdir(parents=True, exist_ok=True)
    store = store_factory(out_dir / "eval.db")
    combos = [
        (spec, arm, seed)
        for spec in corpus.tasks
        for arm in arms
        for seed in seeds
    ]
    random.Random(run_order_seed).shuffle(combos)
    results = [
        runner.run(spec, arm, seed, store, out_dir / "work")
        for spec, arm, seed in combos
    ]
    manifest = {
        "corpus_version": corpus.version,
        "registry_version": registry.version,
        "registry_hash": registry.hash,
        "arms": [{"name": a.name, "fingerprint": a.fingerprint} for a in arms],
        "seeds": list(seeds),
        "run_order_seed": run_order_seed,
        "interleaved": True,
        # registry model_id -> backend tag, when the driver exposes one —
        # the same logical tier can point at different weights across runs
        "model_map": getattr(runner.driver, "models", None),
        "cost_basis": "synthetic_token_price",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.to_dict()) + "\n")
    store.close()
    return results
