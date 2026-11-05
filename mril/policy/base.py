"""Routing policy interface.

A policy is a pure, deterministic decision function: given the same context,
candidate set, task state, and RNG seed it must produce the same output. This
is what makes recorded decisions replayable.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Protocol

from mril.core.decision import RecoveryAction
from mril.core.models import ModelRegistry, ModelSpec
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.state import TaskState


@dataclass(frozen=True)
class PolicySelection:
    model_id: str
    probability: float
    reason: str
    estimated_cost_usd: float | None = None


class RoutingPolicy(Protocol):
    name: str
    version: str

    @property
    def hash(self) -> str: ...

    def select(
        self,
        ctx: TaskContext,
        constraints: RoutingConstraints,
        candidates: list[ModelSpec],
        state: TaskState | None,
        rng: random.Random,
    ) -> PolicySelection: ...

    def recover(
        self,
        state: TaskState,
        constraints: RoutingConstraints,
        registry: ModelRegistry,
    ) -> RecoveryAction: ...


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
