"""EmpiricalCheapFirstPolicy — default cheap-first, evidence-based exceptions.

Study 02 reframed the routing question: not "which tier does this task need?"
but "is a cheap attempt worth buying?" A weak attempt costs ~1/30th of a
strong one, so trying cheap is nearly free *information* — the policy should
only bypass it when accumulated evidence says the attempt is unlikely to be
worth its cost, latency, or quality risk.

Design (study-03 spec):

  Estimator   hierarchical Beta-Binomial over TRANSFERABLE features (never
              task IDs). Sequential shrinkage: signature counts shrink toward
              a feature blend, feature rates toward the global rate, global
              toward uniform 0.5. Sparse tasks inherit; specific failure
              patterns still emerge as evidence accumulates.

  Decision    constrained choice over two candidate strategies:
                cheap-first:  E[C] = c_w + (1-p_w)·(c_handoff + c_strong_after_fail)
                              Q    = p_w + (1-p_w)·q_recovery
                strong-first: E[C] = c_strong_fresh
                              Q    = q_fresh
              Feasible = Q within `quality_margin` of the best Q; among
              feasible, pick lowest expected cost. Matches the eval's own
              objective: min expected cost s.t. completion within δ.

  Fallback    no usable evidence -> cheap-first (Study 02's baseline-to-beat;
              escalation preserves quality anyway). Configurable.

  Freeze      the policy is a pure function of a versioned PolicySnapshot —
              training writes one; evaluation loads it. Same snapshot file,
              same decisions, reproducible fingerprint.

  Recovery    inherits TieredPolicy's escalate-on-capability-failure — the
              empirical question lives entirely in initial routing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from mril.core.models import tier_index
from mril.core.task import RoutingConstraints, TaskContext
from mril.policy.base import PolicySelection, params_hash
from mril.policy.features import FEATURE_VERSION, features_from_context
from mril.policy.tiered import TieredPolicy, _blended_price

SNAPSHOT_VERSION = "1"


# ------------------------------------------------------------------ snapshot


@dataclass(frozen=True)
class PolicySnapshot:
    """The frozen, versioned artifact a PolicyTrainer emits and the policy
    consumes. `beta` maps bucket -> [successes+alpha, failures+beta] where
    bucket is "global", "feat:<k=v>" or "sig:<signature>"."""

    version: str
    feature_version: str
    prior_strength: float
    beta: dict[str, list[float]]
    cost_model: dict[str, float]
    quality_margin: float = 0.05
    fallback: str = "cheap"
    epsilon: float = 0.0
    trained_on_runs: int = 0
    trained_from_ledger: str = ""

    @property
    def hash(self) -> str:
        # Every decision-relevant knob is fingerprinted — snapshots that
        # differ only in fallback/epsilon/feature_version still diverge.
        # trained_on_runs / trained_from_ledger are provenance, not
        # decision inputs, and stay out.
        return params_hash({"version": self.version, "beta": self.beta,
                            "cost_model": self.cost_model,
                            "feature_version": self.feature_version,
                            "prior_strength": self.prior_strength,
                            "quality_margin": self.quality_margin,
                            "fallback": self.fallback, "epsilon": self.epsilon})

    # -- estimator -----------------------------------------------------------

    def _post_mean(self, bucket: str, prior_mean: float) -> tuple[float, float]:
        """(posterior mean, effective n) for a bucket shrunk toward prior."""
        a, b = self.beta.get(bucket, [0.0, 0.0])
        m = self.prior_strength
        return (a + m * prior_mean) / (a + b + m), a + b

    def estimate(self, features) -> tuple[float, float]:
        """(p_weak_success, effective evidence n) with hierarchical shrinkage.

        global: (k + m·0.5) / (n + m)
        feature f: (k_f + m·p_global) / (n_f + m)
        signature: (k_sig + m·p_feat) / (n_sig + m)
        """
        m = self.prior_strength
        p_global, n_global = self._post_mean("global", 0.5)

        keys = features.feature_keys()
        if keys:
            feat_means, feat_ns = [], []
            for k in keys:
                pm, n = self._post_mean(f"feat:{k}", p_global)
                feat_means.append(pm)
                feat_ns.append(n)
            # weight each feature's mean by its evidence — a feature seen
            # once shouldn't move the blend as much as one seen 30 times
            tot = sum(feat_ns) + m
            p_feat = (
                sum(p * n for p, n in zip(feat_means, feat_ns)) + m * p_global
            ) / tot if tot else p_global
        else:
            p_feat, feat_ns = p_global, []

        sig = f"sig:{features.signature()}"
        p_sig, n_sig = self._post_mean(sig, p_feat)
        evidence = n_sig + sum(feat_ns) + n_global
        return p_sig, evidence

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "feature_version": self.feature_version,
            "prior_strength": self.prior_strength,
            "beta": self.beta,
            "cost_model": self.cost_model,
            "quality_margin": self.quality_margin,
            "fallback": self.fallback,
            "epsilon": self.epsilon,
            "trained_on_runs": self.trained_on_runs,
            "trained_from_ledger": self.trained_from_ledger,
            "snapshot_hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolicySnapshot":
        if d.get("version") != SNAPSHOT_VERSION:
            raise ValueError(f"unsupported snapshot version: {d.get('version')}")
        return cls(
            version=d["version"],
            feature_version=d["feature_version"],
            prior_strength=float(d["prior_strength"]),
            beta={k: [float(x) for x in v] for k, v in d["beta"].items()},
            cost_model={k: float(v) for k, v in d["cost_model"].items()},
            quality_margin=float(d.get("quality_margin", 0.05)),
            fallback=d.get("fallback", "cheap"),
            epsilon=float(d.get("epsilon", 0.0)),
            trained_on_runs=int(d.get("trained_on_runs", 0)),
            trained_from_ledger=d.get("trained_from_ledger", ""),
        )


# -------------------------------------------------------------------- policy


@dataclass(frozen=True)
class EmpiricalCheapFirstPolicy(TieredPolicy):
    """Cheap-first by default; strong-first when the snapshot's evidence says
    the weak attempt isn't worth buying. Recovery is TieredPolicy's."""

    name: str = "empirical-cheap-first"
    version: str = "0.3.0"
    snapshot: PolicySnapshot = field(
        default_factory=lambda: PolicySnapshot(
            version=SNAPSHOT_VERSION, feature_version=FEATURE_VERSION,
            prior_strength=3.0, beta={}, cost_model={},
        )
    )
    epsilon: float = 0.0

    def __post_init__(self) -> None:
        # Feature extraction evolves across FEATURE_VERSIONs; a snapshot's
        # beta buckets are only meaningful under the version that produced
        # them. An empty beta carries no evidence, so version can't mislead.
        if self.snapshot.beta and self.snapshot.feature_version != FEATURE_VERSION:
            raise ValueError(
                f"snapshot trained under feature_version="
                f"{self.snapshot.feature_version!r}; current is "
                f"{FEATURE_VERSION!r} — retrain (mril eval train) before reuse"
            )

    @property
    def hash(self) -> str:
        return params_hash(
            {"name": self.name, "version": self.version,
             "snapshot": self.snapshot.hash, "epsilon": self.epsilon}
        )

    # -- the study-03 decision ------------------------------------------------

    def _strategies(self, p_w: float) -> dict[str, tuple[float, float]]:
        """strategy -> (expected_cost, expected_verified) for this task."""
        cm = self.snapshot.cost_model
        c_w = cm.get("c_weak", 0.001)
        c_sf = cm.get("c_strong_fresh", 0.01)
        c_sa = cm.get("c_strong_after_fail", c_sf)
        c_h = cm.get("c_handoff", 0.0)
        q_rec = cm.get("q_recovery", cm.get("q_fresh", 0.8))
        q_fresh = cm.get("q_fresh", 0.8)
        return {
            "cheap": (c_w + (1.0 - p_w) * (c_h + c_sa),
                      p_w + (1.0 - p_w) * q_rec),
            "strong": (c_sf, q_fresh),
        }

    def _choose(self, p_w: float) -> tuple[str, dict]:
        """Constrained pick: among strategies within `quality_margin` of the
        best expected verified rate, choose the lowest expected cost."""
        strat = self._strategies(p_w)
        best_q = max(q for _, q in strat.values())
        feasible = {
            k: v for k, v in strat.items()
            if v[1] >= best_q - self.snapshot.quality_margin
        }
        pick = min(feasible, key=lambda k: (feasible[k][0], k))
        return pick, strat

    # -- RoutingPolicy --------------------------------------------------------

    def select(
        self,
        ctx: TaskContext,
        constraints: RoutingConstraints,
        candidates: list,
        state,
        rng: random.Random,
    ) -> PolicySelection:
        if not candidates:
            raise ValueError("no eligible models after constraints")
        if len(candidates) == 1:
            m = candidates[0]
            return PolicySelection(
                model_id=m.model_id, probability=1.0,
                reason="single eligible model",
                estimated_cost_usd=self._estimate(m, ctx.scope),
            )

        cheap = min(candidates, key=lambda m: (_blended_price(m, ctx.scope), m.model_id))
        strong = max(
            candidates,
            key=lambda m: (tier_index(m.tier), _blended_price(m, ctx.scope), m.model_id),
        )

        feats = features_from_context(ctx)
        p_w, evidence = self.snapshot.estimate(feats)
        if evidence <= 0:
            pick_key = self.snapshot.fallback
            reason = f"no evidence; fallback={pick_key}"
        else:
            pick_key, strat = self._choose(p_w)
            reason = (
                f"p_weak={p_w:.2f} (n≈{evidence:.0f}) "
                f"E[cheap]=${strat['cheap'][0]:.4f}/Q={strat['cheap'][1]:.2f} "
                f"E[strong]=${strat['strong'][0]:.4f}/Q={strat['strong'][1]:.2f} "
                f"-> {pick_key}"
            )
        greedy = cheap if pick_key == "cheap" else strong

        n = len(candidates)
        if self.epsilon <= 0:
            return PolicySelection(
                model_id=greedy.model_id, probability=1.0, reason=reason,
                estimated_cost_usd=self._estimate(greedy, ctx.scope),
            )
        probs = {m.model_id: self.epsilon / n for m in candidates}
        probs[greedy.model_id] += 1.0 - self.epsilon
        pick, acc, r = greedy, 0.0, rng.random()
        for m in candidates:
            acc += probs[m.model_id]
            if r < acc:
                pick = m
                break
        if pick.model_id != greedy.model_id:
            reason = f"epsilon-exploration (eps={self.epsilon}); " + reason
        return PolicySelection(
            model_id=pick.model_id, probability=probs[pick.model_id],
            reason=reason, estimated_cost_usd=self._estimate(pick, ctx.scope),
        )
