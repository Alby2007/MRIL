"""MRIL — Model Routing Intelligence Layer.

Local-first, verified-outcome-aware model routing for coding agents.
"""

from mril.core.decision import RecoveryAction, RecoveryType, RoutingDecision
from mril.core.models import ModelRegistry, ModelSpec
from mril.core.task import RoutingConstraints, TaskContext
from mril.sdk import Router

__all__ = [
    "ModelRegistry",
    "ModelSpec",
    "RecoveryAction",
    "RecoveryType",
    "Router",
    "RoutingConstraints",
    "RoutingDecision",
    "TaskContext",
]

__version__ = "0.3.0"
