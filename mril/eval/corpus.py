"""Corpus loading and validation.

A corpus is a directory of task dirs, each holding `task.json`, a `snapshot/`
(or archive), and verifier files. Loading validates digests eagerly — a
corrupt corpus fails before a single model call is spent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from mril.eval.spec import SpecError, TaskSpec


@dataclass(frozen=True)
class Corpus:
    root: Path
    tasks: tuple[TaskSpec, ...]

    @property
    def version(self) -> str:
        """Content digest over all task specs — the corpus's reproducibility id."""
        canonical = json.dumps(
            sorted(t.digest() for t in self.tasks), sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_corpus(root: str | Path, *, verify_digests: bool = True) -> Corpus:
    root = Path(root)
    if not root.is_dir():
        raise SpecError(f"corpus root not found: {root}")
    tasks, seen = [], set()
    for spec_path in sorted(root.glob("*/task.json")):
        spec = TaskSpec.load(spec_path)
        if spec.task_id in seen:
            raise SpecError(f"duplicate task id: {spec.task_id}")
        seen.add(spec.task_id)
        if verify_digests:
            spec.verify_snapshot(root)
            for vf in spec.verifier_files:
                if not (root / vf).is_file():
                    raise SpecError(f"{spec.task_id}: verifier file missing: {vf}")
        tasks.append(spec)
    if not tasks:
        raise SpecError(f"no tasks under {root}")
    return Corpus(root=root, tasks=tuple(tasks))
