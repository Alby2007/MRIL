"""Task specifications — the immutable contract every arm runs against.

A spec is declarative JSON (`task.json` in a corpus task dir). The snapshot
digest is mandatory: all arms must start from bit-identical state. Verifier
files are listed separately from the snapshot so the runner can keep them
out of the agent's reach — a model must never pass by editing the tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TASK_SCHEMA_VERSION = 1


class SpecError(ValueError):
    pass


def load_registry(path: str | Path) -> "ModelRegistry":
    """Model specification for an eval run — registry ids the arms route
    between. Prices are normalized API-equivalent estimates for local
    backends (see report.cost_basis), not billed amounts."""
    from mril.core.models import ModelRegistry, ModelSpec

    d = json.loads(Path(path).read_text())
    return ModelRegistry(
        version=d.get("version", "eval"),
        models=tuple(
            ModelSpec(
                model_id=m["model_id"],
                provider=m.get("provider", ""),
                tier=m.get("tier", "balanced"),
                input_price=m.get("input_price", 0.0),
                output_price=m.get("output_price", 0.0),
                cached_input_price=m.get("cached_input_price"),
                context_window=m.get("context_window", 0),
                capabilities=frozenset(m.get("capabilities", ())),
                restricted=m.get("restricted", False),
            )
            for m in d["models"]
        ),
    )


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _tree_sha256(root: Path) -> str:
    """Deterministic digest of a directory: sorted relpath:filehash lines."""
    h = hashlib.sha256()
    entries = sorted(
        p for p in root.rglob("*") if p.is_file() and ".mril-verify" not in p.parts
    )
    for p in entries:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(_file_sha256(p).encode())
        h.update(b"\n")
    return h.hexdigest()


def snapshot_sha256(snapshot: Path) -> str:
    if snapshot.is_dir():
        return _tree_sha256(snapshot)
    return _file_sha256(snapshot)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    snapshot: str  # path relative to corpus root: dir or .tar.gz/.tgz
    snapshot_sha256: str
    instruction: str
    verify_command: str  # run with cwd=workspace; {verify} -> staged verifier dir
    language: str | None = None
    category: str | None = None  # task_type
    scope: str | None = None
    risk: str | None = None
    target_file: str = "solution.py"  # where single-shot output materializes
    verifier_files: tuple[str, ...] = ()  # hidden files, corpus-relative
    verify_timeout_seconds: int = 60
    max_attempts: int = 3
    max_model_calls: int = 20
    max_wall_seconds: int = 300
    budget_usd: float | None = None  # token-priced budget, synthetic for local
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = TASK_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskSpec":
        if d.get("schema_version", TASK_SCHEMA_VERSION) != TASK_SCHEMA_VERSION:
            raise SpecError(f"unsupported schema_version: {d.get('schema_version')}")
        try:
            repo, task, ver, limits = (
                d["repository"], d["task"], d["verification"], d.get("limits", {})
            )
            return cls(
                task_id=d["id"],
                snapshot=repo["snapshot"],
                snapshot_sha256=repo["sha256"],
                instruction=task["instruction"],
                language=task.get("language"),
                category=task.get("category"),
                scope=task.get("scope"),
                risk=task.get("risk"),
                target_file=task.get("target_file", "solution.py"),
                verifier_files=tuple(ver.get("files", ())),
                verify_command=ver["command"],
                verify_timeout_seconds=ver.get("timeout_seconds", 60),
                max_attempts=limits.get("max_attempts", 3),
                max_model_calls=limits.get("max_model_calls", 20),
                max_wall_seconds=limits.get("max_wall_seconds", 300),
                budget_usd=limits.get("budget_usd"),
                metadata=dict(d.get("metadata", {})),
            )
        except KeyError as exc:
            raise SpecError(f"missing required key: {exc}") from exc

    @classmethod
    def load(cls, path: Path) -> "TaskSpec":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def verify_snapshot(self, corpus_root: Path) -> Path:
        """Resolve the snapshot and prove it matches the pinned digest."""
        snap = (corpus_root / self.snapshot).resolve()
        if not snap.exists():
            raise SpecError(f"{self.task_id}: snapshot not found: {snap}")
        actual = snapshot_sha256(snap)
        if actual != self.snapshot_sha256:
            raise SpecError(
                f"{self.task_id}: snapshot digest mismatch "
                f"(spec {self.snapshot_sha256[:12]}… != actual {actual[:12]}…)"
            )
        return snap
