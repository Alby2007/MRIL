"""Model capability registry.

The registry pins model capabilities *and* prices. Decisions snapshot prices at
decision time so cost accounting stays reproducible when providers re-price.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

TIER_ORDER = ("cheap", "balanced", "frontier")


def tier_index(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return len(TIER_ORDER) - 1


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    provider: str = ""
    tier: str = "balanced"
    input_price: float = 0.0  # USD per 1M input tokens
    output_price: float = 0.0  # USD per 1M output tokens
    cached_input_price: float | None = None  # discounted price on cache hit
    context_window: int = 0
    capabilities: frozenset[str] = frozenset()
    restricted: bool = False  # customer flag: never auto-select
    metadata: dict[str, Any] = field(default_factory=dict)

    def cost_usd(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float:
        cached = min(cached_input_tokens, input_tokens)
        fresh = input_tokens - cached
        cached_price = self.cached_input_price if self.cached_input_price is not None else self.input_price
        return (
            fresh * self.input_price + cached * cached_price + output_tokens * self.output_price
        ) / 1_000_000

    def switch_cost_usd(self, context_tokens: int) -> float:
        """Estimated cost of moving a warm session to this model.

        A different model cannot reuse the KV cache, so the entire context must
        be re-ingested at full input price. This is the cost that naive routing
        ignores and that can exceed the savings of picking a cheaper model.
        """
        return context_tokens * self.input_price / 1_000_000

    def price_snapshot(self) -> dict[str, float | None]:
        return {
            "input_price": self.input_price,
            "output_price": self.output_price,
            "cached_input_price": self.cached_input_price,
        }


@dataclass(frozen=True)
class ModelRegistry:
    models: tuple[ModelSpec, ...]
    version: str = "1"

    def get(self, model_id: str) -> ModelSpec | None:
        for m in self.models:
            if m.model_id == model_id:
                return m
        return None

    def __contains__(self, model_id: str) -> bool:
        return self.get(model_id) is not None

    @property
    def hash(self) -> str:
        canonical = json.dumps(
            {
                "version": self.version,
                "models": [
                    {
                        "model_id": m.model_id,
                        "provider": m.provider,
                        "tier": m.tier,
                        "input_price": m.input_price,
                        "output_price": m.output_price,
                        "cached_input_price": m.cached_input_price,
                        "context_window": m.context_window,
                        "capabilities": sorted(m.capabilities),
                        "restricted": m.restricted,
                    }
                    for m in sorted(self.models, key=lambda m: m.model_id)
                ],
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def candidates(
        self,
        allowed: tuple[str, ...] | None = None,
        require_capabilities: frozenset[str] = frozenset(),
    ) -> list[ModelSpec]:
        out = []
        for m in self.models:
            if m.restricted:
                continue
            if allowed is not None and m.model_id not in allowed:
                continue
            if not require_capabilities.issubset(m.capabilities):
                continue
            out.append(m)
        return out
