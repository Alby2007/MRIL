# Hand-written fallback vs MRIL — requirements coverage

The question every evaluator asks first: *why not just write `try cheap →
verify → retry strong` myself?* `tools/compare_fallback.py` runs the same
scenario suite through both implementations.

**What this is:** a requirements-coverage demonstration. The baseline
deliberately doesn't implement most operational requirements, so the N/A
rows are missing features, not comparison losses. **What this isn't:**
evidence that MRIL outperforms an equally capable handwritten
implementation — building one of those is exactly the engineering the
N/A rows represent.

```bash
.venv/Scripts/python tools/compare_fallback.py
```

## The baseline

~15 lines, zero dependencies, correct for the trivial case:

```python
def hw_run_task(prompt, workdir, verify):
    sol = workdir / "solution.py"
    for model_id in ("cheap", "strong"):
        sol.write_text(generate(model_id, prompt))
        shutil.rmtree(workdir / "__pycache__", ignore_errors=True)
        if verify():
            return "success"
    return "failure"
```

(Yes, even this needs the `__pycache__` line — a same-size rewrite within
one mtime tick makes Python reuse stale bytecode and verify the *previous*
attempt's artifact. The first version of this baseline skipped it and
reported `failure` on fixed code.)

## Results

| Scenario | handwritten | MRIL |
| --- | --- | --- |
| cheap model fails verification → escalate | PASS — but nothing recorded | PASS + recovery provenance |
| agent makes multiple model calls in a run | N/A — "attempts" are retries; calls untracked | PASS — one attempt, steps 0..n |
| two concurrent agent sessions | N/A — stateless by accident; nothing recorded either | PASS — distinct task/attempt ids (real `ainvoke` covered by `tests/test_langchain_integration.py`) |
| driver double-reports an observation | N/A — no observation layer to dedupe | PASS — logical dedupe keys |
| verification never ran | PARTIAL — falsy verdict fails *conservatively*, but mislabels inconclusive as verified failure | PASS — `inconclusive`, never upgraded |
| process interrupted mid-task | N/A — in-memory only; a crash leaves nothing to resume | PASS — ledger replay reconstructs state |
| restricted model in the candidate set | N/A — no registry/policy concept to violate | PASS — restricted skipped on every path incl. fallback |

Measured decision-path overhead: ~100 µs per route + observe + finalize
cycle — in-process MemoryEventStore, 200 sequential synthetic decisions,
single machine. That is bookkeeping cost only, not agent runtime
overhead; SQLite adds a constant commit cost.

## The honest verdict

The baseline is the right answer for one-shot scripts. Every N/A and
PARTIAL row above is engineering a production deployment would otherwise
have to build, test, and maintain itself: attempt/call separation,
idempotent accounting, run isolation, honest outcome labels, resumable
state, restricted-model enforcement, and per-decision explainability.

That is MRIL's v0.3 positioning: **not** "smarter routing than your
if-statement", but a verified, replayable, explainable recovery lifecycle
that a `pip install` buys instead of a build-maintain-debug cycle.

## What MRIL adds on top

- **Ledger**: every decision, invocation, verdict, recovery, and outcome
  in an append-only SQLite event store — inspect with `mril task` /
  `mril explain`.
- **Cost accounting**: decision-time price snapshots, KV-cache switch-cost
  estimates, per-attempt and total spend.
- **Recovery policy**: escalate / retry / stop with budget checks and
  recorded reasons, replayable offline (`recovery_context` snapshot).
- **Evaluation harness**: reproducible policy comparison against the same
  corpora, guardrailed reports — see `docs/` and `mril eval`.
