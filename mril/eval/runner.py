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
from mril.core.events import (
    RouteDecided,
    TaskFinalized,
    VerificationStatus,
    new_event_id,
)
from mril.core.models import ModelRegistry
from mril.core.task import RoutingConstraints, TaskContext
from mril.eval.arms import Arm, apply_recovery
from mril.eval.corpus import Corpus
from mril.eval.drivers import AgentDriver
from mril.eval.failures import (
    check_counts,
    classify_failure,
    sanitize_feedback,
    structured_feedback,
)
from mril.eval.results import RunResult
from mril.eval.spec import SpecError, TaskSpec
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
    # Study-05B: when set, every failed attempt's full workspace + sanitized
    # feedback is snapshotted here for later paired handoff probes.
    capture_dir: Path | None = None

    def _capture_checkpoint(
        self, spec: TaskSpec, ws: Workspace, run_task_id: str,
        attempt_i: int, model_id: str, verdict, category: str | None,
    ) -> None:
        import shutil

        cid = f"{run_task_id.replace(':', '_')}__a{attempt_i}"
        dest = self.capture_dir / cid
        (dest / "workspace").mkdir(parents=True, exist_ok=True)
        shutil.copytree(ws.path, dest / "workspace", dirs_exist_ok=True)
        meta = {
            "checkpoint_id": cid,
            "task_id": spec.task_id,
            "run_task_id": run_task_id,
            "attempt_index": attempt_i,
            "model_id": model_id,
            "failure_category": category,
            "corpus_root": str(self.verifier.corpus_root),
            "counts": check_counts(verdict.stdout),
            "feedback_raw": verdict.stdout[-2000:],
            "feedback_sanitized": sanitize_feedback(verdict, category or "test_failure"),
            "feedback_structured": structured_feedback(verdict, category or "test_failure"),
        }
        (dest / "checkpoint.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

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
            budget_usd=(spec.budget_usd if spec.budget_usd is not None
                        else self.default_constraints.budget_usd),
            max_attempts=spec.max_attempts,
            require_capabilities=self.default_constraints.require_capabilities,
        )
        # transferable features travel to policies via ctx.metadata — the
        # empirical arm reads them there; the ledger persists them on
        # TaskStarted so PolicyTrainer can re-derive buckets post-hoc.
        from mril.eval.features import extract_features

        feats = extract_features(
            spec, snapshot_dir=self.verifier.corpus_root / spec.snapshot
        ).as_dict()
        ctx = TaskContext(
            task_id=run_task_id,
            language=spec.language,
            task_type=spec.category,
            scope=spec.scope,
            risk=spec.risk,
            harness="mril-eval",
            metadata={
                "base_task": spec.task_id,
                "arm": arm.name,
                "seed": seed,
                "features": feats,
            },
        )
        ws = Workspace.materialize(spec, self.verifier.corpus_root, work_root, run_task_id.replace(":", "_"))
        t0, model_calls, feedback = time.monotonic(), 0, None
        route_constraints = constraints
        try:
            for attempt_i in range(spec.max_attempts):
                if model_calls >= spec.max_model_calls:
                    break
                if (time.monotonic() - t0) > spec.max_wall_seconds:
                    break
                attempt_id = new_event_id()
                d = router.route(ctx, route_constraints,
                                 step_index=attempt_i, call_site="attempt")
                res = self.driver.generate(
                    model_id=d.model_id,
                    spec=spec,
                    workspace=ws,
                    attempt_index=attempt_i,
                    prior_feedback=feedback,
                    seed=seed,
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
                    route_constraints = apply_recovery(route_constraints, action)
                    continue
                verdict = self.verifier.verify(spec, ws)
                status = (
                    VerificationStatus.PASSED if verdict.passed is True
                    else VerificationStatus.FAILED if verdict.passed is False
                    else VerificationStatus.INCONCLUSIVE
                )
                category = classify_failure(verdict)
                router.observe_verification(
                    attempt_id, status,
                    task_id=run_task_id, verifier_type="test",
                    failure_category=category,
                    verification_run_id=verdict.run_id,
                )
                if verdict.passed:
                    break
                if self.capture_dir is not None:
                    self._capture_checkpoint(
                        spec, ws, run_task_id, attempt_i, d.model_id,
                        verdict, category,
                    )
                # Sanitized feedback only — raw verifier output leaks hidden
                # test source/expected values into the agent's context.
                feedback = sanitize_feedback(verdict, category)
                action = router.next_action(run_task_id, constraints)
                if action.type == RecoveryType.STOP:
                    break
                route_constraints = apply_recovery(route_constraints, action)
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

    Re-running into an existing out_dir RESUMES rather than corrupts: cells
    whose run_task_id already carries a TaskFinalized are skipped and their
    results rebuilt from the ledger, so a crashed or extended matrix never
    silently drops new events behind stale dedupe keys. results.jsonl is
    appended per completed cell (crash-safe progress) and rewritten
    canonically at the end.
    """
    import random

    out_dir = Path(out_dir)
    (out_dir / "work").mkdir(parents=True, exist_ok=True)
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
        # pinned sampling params — routing is seeded, but seeded routing
        # means nothing if generation itself is uncontrolled
        "generation": getattr(runner.driver, "generation_options", None),
        "cost_basis": "synthetic_token_price",
        # recovery feedback shape is part of comparability: raw-traceback
        # runs (pre-sanitization studies) must never be pooled with
        # sanitized-feedback runs
        "feedback_contract": "sanitized-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    store = store_factory(out_dir / "eval.db")
    try:
        prior_events = store.all_events()
        if prior_events:
            # a populated ledger proves this dir already belongs to a matrix;
            # only a compatible config may extend it — never silently mix
            _assert_resume_compatible(
                out_dir, corpus, registry, runner, arms, prior_events
            )
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        done = {
            e.task_id
            for e in prior_events
            if isinstance(e, TaskFinalized)
        }

        def run_id(spec, arm, seed) -> str:
            return f"{spec.task_id}:{arm.name}:{seed}"

        combos = [
            (spec, arm, seed)
            for spec in corpus.tasks
            for arm in arms
            for seed in seeds
        ]
        random.Random(run_order_seed).shuffle(combos)
        results = []
        for spec, arm, seed in combos:
            if run_id(spec, arm, seed) in done:
                # previously completed cell — rebuild, never re-run
                results.append(_result_from_ledger(store, spec, arm, seed))
        results_path = out_dir / "results.jsonl"
        with results_path.open("a", encoding="utf-8") as fh:
            for spec, arm, seed in combos:
                if run_id(spec, arm, seed) in done:
                    continue
                r = runner.run(spec, arm, seed, store, out_dir / "work")
                results.append(r)
                fh.write(json.dumps(r.to_dict()) + "\n")
                fh.flush()
        # canonical results file: exactly this matrix's cells
        with results_path.open("w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps(r.to_dict()) + "\n")
    finally:
        store.close()
    return results


def _assert_resume_compatible(
    out_dir: Path,
    corpus: Corpus,
    registry: ModelRegistry,
    runner: "EvalRunner",
    arms: tuple[Arm, ...],
    prior_events: list,
) -> None:
    """Fail closed when an existing out dir isn't a resume of THIS matrix.

    Resuming is legitimate only under an identical experimental config —
    same corpus digest, registry identity, backend model map, generation
    options, and (for arms that already have cells) policy fingerprints.
    The manifest is checked first; the ledger's own recorded hashes are
    checked per cell, because the ledger — not the manifest — is truth.
    """
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SpecError(
            f"{out_dir} contains a ledger but no manifest.json — cannot "
            "prove it belongs to this matrix; use a fresh --out dir"
        )
    old = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    if old.get("corpus_version") != corpus.version:
        mismatches.append(
            f"corpus {old.get('corpus_version')} != {corpus.version}"
        )
    if (
        old.get("registry_version") != registry.version
        or old.get("registry_hash") != registry.hash
    ):
        mismatches.append(
            f"registry {old.get('registry_version')}#{old.get('registry_hash')} "
            f"!= {registry.version}#{registry.hash}"
        )
    if old.get("feedback_contract") != "sanitized-v1":
        # pre-sanitization ledgers fed raw tracebacks to the model — their
        # cells aren't comparable with sanitized-feedback runs
        mismatches.append("feedback contract differs (pre-sanitized ledger)")
    if old.get("model_map") != getattr(runner.driver, "models", None):
        mismatches.append("model_map changed")
    if old.get("generation") != getattr(runner.driver, "generation_options", None):
        mismatches.append("generation options changed")
    old_arms = {a["name"]: a["fingerprint"] for a in old.get("arms", [])}
    for a in arms:
        if a.name in old_arms and old_arms[a.name] != a.fingerprint:
            mismatches.append(f"arm {a.name!r} fingerprint changed")
    wanted = {a.name: a for a in arms}
    for e in prior_events:
        if not isinstance(e, RouteDecided) or e.task_id is None:
            continue
        parts = e.task_id.rsplit(":", 2)
        arm = wanted.get(parts[1]) if len(parts) == 3 else None
        if arm is None:
            continue  # cell from an arm not being re-run — outside this matrix
        if e.policy_hash != arm.policy.hash:
            mismatches.append(
                f"cell {e.task_id}: recorded policy #{e.policy_hash} "
                f"!= {arm.policy.hash}"
            )
            break
        if e.registry_hash and e.registry_hash != registry.hash:
            mismatches.append(
                f"cell {e.task_id}: recorded registry #{e.registry_hash} "
                f"!= {registry.hash}"
            )
            break
    if mismatches:
        raise SpecError(
            f"refusing to resume into an incompatible eval dir ({out_dir}):\n  - "
            + "\n  - ".join(mismatches)
            + "\nuse a fresh --out dir or delete this one"
        )


def _result_from_ledger(store, spec, arm, seed) -> RunResult:
    """Reconstruct a RunResult for a cell completed in an earlier process —
    the ledger is the source of truth; wall time comes from TaskFinalized."""
    rid = f"{spec.task_id}:{arm.name}:{seed}"
    events = store.events_for_task(rid)
    fin = next(e for e in reversed(events) if isinstance(e, TaskFinalized))
    return RunResult.from_ledger(
        store, rid, spec.task_id, arm, seed,
        wall_ms=fin.elapsed_ms or 0.0, finalized=fin,
    )
