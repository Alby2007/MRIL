"""Verification — run the hidden verifier against a COPY of the workspace.

The agent never coexists with the tests: verifier files live in the corpus,
each execution copies the workspace into a throwaway dir (agent-created
`.mril-verify/` content excluded), injects the pinned verifier files there,
and runs the command in the copy. A shell-capable agent can neither read
nor edit the tests that grade it, and test side effects never touch the
real workspace. `passed=None` means the verifier itself couldn't produce a
verdict (timeout, crash) — never treated as success.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from mril.core.events import new_event_id
from mril.eval.spec import TaskSpec
from mril.eval.workspace import Workspace

VERIFY_DIR = ".mril-verify"


def _command_argv(command: str) -> list[str]:
    """Build argv from a spec verify_command template.

    Split the template BEFORE substitution: placeholders expand to real
    paths that may contain spaces (sys.executable under e.g. "C:\\Program
    Files\\") — splitting after substitution would shred them, and quoting
    keeps them single-argument on every platform.
    """
    return [
        tok.replace("{verify}", f"{VERIFY_DIR}/").replace("{python}", sys.executable)
        for tok in shlex.split(command, posix=True)
    ]


@dataclass(frozen=True)
class Verdict:
    run_id: str  # one per verifier execution — feeds verification_run_id
    passed: bool | None
    returncode: int | None
    stdout: str
    duration_ms: float
    timed_out: bool = False


class CommandVerifier:
    def __init__(self, corpus_root: Path) -> None:
        self.corpus_root = Path(corpus_root)

    def _make_verify_env(self, spec: TaskSpec, workspace: Workspace) -> Path:
        """Snapshot the agent's workspace, minus any agent-planted verify
        dir, then inject the pinned verifier files."""
        env = Path(tempfile.mkdtemp(prefix="mril-verify-"))
        shutil.copytree(
            workspace.path, env, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(VERIFY_DIR),
        )
        stage = env / VERIFY_DIR
        stage.mkdir(parents=True, exist_ok=True)
        for vf in spec.verifier_files:
            shutil.copy2(self.corpus_root / vf, stage / Path(vf).name)
        return env

    def verify(self, spec: TaskSpec, workspace: Workspace) -> Verdict:
        run_id = new_event_id()
        env = self._make_verify_env(spec, workspace)
        argv = _command_argv(spec.verify_command)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=spec.verify_timeout_seconds,
            )
            return Verdict(
                run_id=run_id,
                passed=proc.returncode == 0,
                returncode=proc.returncode,
                stdout=(proc.stdout or "") + (proc.stderr or ""),
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return Verdict(
                run_id=run_id,
                passed=None,
                returncode=None,
                stdout=str(exc),
                duration_ms=(time.monotonic() - started) * 1000,
                timed_out=isinstance(exc, subprocess.TimeoutExpired),
            )
        finally:
            shutil.rmtree(env, ignore_errors=True)
