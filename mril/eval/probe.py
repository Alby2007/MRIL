"""Study-05B rescue probe — paired handoff evaluation over captured
failure checkpoints.

Each checkpoint (workspace at failure + sanitized/structured feedback) is
replayed under both handoff arms against the same recovery model with an
identical generation seed — the only difference is the feedback string.
Results land in probe-results.jsonl; pairing key is checkpoint_id.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zlib
from pathlib import Path

from mril.eval.corpus import load_corpus
from mril.eval.workspace import Workspace

ARMS = ("handoff-current", "handoff-structured")

# Patterns that must never reach a probe prompt — hidden-verifier content.
# They match verifier-output shapes (test defs, tracebacks, pytest's 'E '
# failure lines), never the legitimate category names — "test_failure" and
# "verifier_error" are part of the frozen feedback contract and must pass.
_LEAK_PATTERNS = (
    r"def test_\w+",      # verifier source lines
    r"test_\w*\.py",      # verifier filenames
    r"verifiers/",        # corpus-relative verifier paths
    r"(?m)^\s*E\s",       # pytest 'E  assert ...' failure detail lines
    r"\.py:\d+",          # traceback file:line refs
    r"==",                # expected-vs-actual comparisons
)


def audit_checkpoint(meta: dict) -> list[str]:
    """Return leak findings in a checkpoint's two feedback variants."""
    hits = []
    for arm in ARMS:
        fb = meta["feedback_sanitized" if arm == "handoff-current" else "feedback_structured"]
        for pat in _LEAK_PATTERNS:
            if re.search(pat, fb):
                hits.append(f"{meta['checkpoint_id']}:{arm} contains {pat!r}")
    return hits


def run_probe(
    checkpoints_dir: Path,
    corpus_root: Path,
    registry,
    driver,
    verifier,
    model_id: str,
    out_dir: Path,
    probe_seed: int = 0,
    failed_model: str | None = "weak-coder",
    max_checkpoints: int | None = None,
) -> list[dict]:
    corpus = load_corpus(corpus_root)
    specs = {t.task_id: t for t in corpus.tasks}
    checkpoints = sorted(
        p for p in Path(checkpoints_dir).iterdir()
        if (p / "checkpoint.json").is_file()
    )
    leaks = []
    metas = []
    for cdir in checkpoints:
        meta = json.loads((cdir / "checkpoint.json").read_text(encoding="utf-8"))
        # Only checkpoints whose failed attempt used the entry model, and only
        # valid failure evidence (verifier_error carries no code signal).
        if failed_model and meta["model_id"] != failed_model:
            continue
        if meta["failure_category"] == "verifier_error":
            continue
        leaks += audit_checkpoint(meta)
        metas.append((cdir, meta))
    if max_checkpoints:
        metas = metas[:max_checkpoints]
    if leaks:
        raise RuntimeError("leakage audit failed:\n" + "\n".join(leaks[:20]))

    out_dir.mkdir(parents=True, exist_ok=True)
    model = registry.get(model_id)
    results = []
    for cdir, meta in metas:
        spec = specs[meta["task_id"]]
        for arm, fb in (
            ("handoff-current", meta["feedback_sanitized"]),
            ("handoff-structured", meta["feedback_structured"]),
        ):
            ws_dir = Path(tempfile.mkdtemp(prefix="probe-"))
            shutil.copytree(cdir / "workspace", ws_dir, dirs_exist_ok=True)
            ws = Workspace(ws_dir)
            try:
                seed = zlib.crc32(f"{meta['checkpoint_id']}:{probe_seed}".encode())
                res = driver.generate(
                    model_id=model_id, spec=spec, workspace=ws,
                    attempt_index=0, prior_feedback=fb, seed=seed,
                )
                if res.api_error:
                    verdict_passed, cat = None, "api_error"
                else:
                    v = verifier.verify(spec, ws)
                    verdict_passed, cat = v.passed, None
                cost = (
                    model.cost_usd(res.input_tokens or 0, res.output_tokens or 0)
                    if model else None
                )
                results.append({
                    "checkpoint_id": meta["checkpoint_id"],
                    "task_id": meta["task_id"],
                    "arm": arm,
                    "model_id": model_id,
                    "failure_category": meta["failure_category"],
                    "verified": verdict_passed,
                    "cost_usd": cost,
                    "latency_ms": res.latency_ms,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "api_error": res.api_error,
                })
            finally:
                shutil.rmtree(ws_dir, ignore_errors=True)
        print(f"  {meta['checkpoint_id']}: "
              + ", ".join(f"{r['arm']}={'ok' if r['verified'] else 'fail' if r['verified'] is False else 'err'}"
                          for r in results[-2:]))
    (out_dir / "probe-results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8"
    )
    return results


def paired_report(results: list[dict]) -> str:
    """McNemar-style paired comparison by checkpoint_id."""
    by_cp: dict[str, dict[str, dict]] = {}
    for r in results:
        by_cp.setdefault(r["checkpoint_id"], {})[r["arm"]] = r
    both = only_cur = only_str = neither = 0
    for cp, arms in by_cp.items():
        a = arms.get("handoff-current", {}).get("verified") is True
        b = arms.get("handoff-structured", {}).get("verified") is True
        both += a and b
        only_cur += a and not b
        only_str += b and not a
        neither += not a and not b
    n = len(by_cp)
    lines = [
        f"pairs: {n}",
        f"both verified: {both} | only current: {only_cur} | "
        f"only structured: {only_str} | neither: {neither}",
        f"current rescue rate: {(both + only_cur) / max(n, 1):.3f}",
        f"structured rescue rate: {(both + only_str) / max(n, 1):.3f}",
        f"discordant pairs (decisive evidence): {only_cur + only_str}",
    ]
    return "\n".join(lines)
