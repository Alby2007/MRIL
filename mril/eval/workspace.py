"""Workspace isolation — every run gets a fresh, verified materialization.

The snapshot digest is checked at materialization time too (not just corpus
load), so a snapshot mutated between runs is caught rather than silently
compared across arms.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path

from mril.eval.spec import TaskSpec


class Workspace:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def materialize(
        cls, spec: TaskSpec, corpus_root: Path, work_root: Path, run_name: str
    ) -> "Workspace":
        snap = spec.verify_snapshot(corpus_root)
        dest = Path(tempfile.mkdtemp(prefix=f"{run_name}-", dir=work_root))
        if snap.is_dir():
            for item in snap.iterdir():
                tgt = dest / item.name
                shutil.copytree(item, tgt) if item.is_dir() else shutil.copy2(item, tgt)
        else:
            with tarfile.open(snap) as tf:
                try:
                    tf.extractall(dest, filter="data")
                except TypeError:  # older Python without filter=
                    tf.extractall(dest)
        return cls(dest)

    def read(self, relpath: str) -> str | None:
        p = self.path / relpath
        return (
            p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
        )

    def write(self, relpath: str, content: str) -> None:
        p = self.path / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def tree(self, max_files: int = 40) -> str:
        files = sorted(
            str(p.relative_to(self.path))
            for p in self.path.rglob("*")
            if p.is_file() and ".mril-verify" not in p.parts
        )
        return "\n".join(files[:max_files])

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
