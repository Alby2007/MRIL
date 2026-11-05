"""MRIL evaluation harness — reproducible controlled comparisons.

Corpus (immutable task specs + pinned snapshots) x arms (interchangeable
routing strategies) x seeds, all recorded through the Router ledger.
"""

from mril.eval.arms import Arm, apply_recovery, default_arms
from mril.eval.corpus import Corpus, load_corpus
from mril.eval.drivers import AgentDriver, DriverResult, OllamaDriver
from mril.eval.results import RunResult, load_results
from mril.eval.runner import EvalRunner, run_matrix
from mril.eval.spec import SpecError, TaskSpec
from mril.eval.verifier import CommandVerifier, Verdict
from mril.eval.workspace import Workspace

__all__ = [
    "AgentDriver",
    "Arm",
    "CommandVerifier",
    "Corpus",
    "DriverResult",
    "EvalRunner",
    "OllamaDriver",
    "RunResult",
    "SpecError",
    "TaskSpec",
    "Verdict",
    "Workspace",
    "apply_recovery",
    "default_arms",
    "load_corpus",
    "load_results",
    "run_matrix",
]
