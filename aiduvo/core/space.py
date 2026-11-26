"""Abstract action space and state encoder.

The action space is *factored*: instead of one huge flat set of joint actions, a
decision is a tuple of symbolic options, one per head.  This keeps the learning
problem small and interpretable, and it lets the framework swap a head (for
example adding a ``force_bias`` head only in runtime mode) without retraining
anything.

Nothing here names a signal or a coverpoint: ``focus`` options are built from
whatever coverage groups the simulator reported, and ``knob_profile`` options
are built from whatever plusargs the discovery step found.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from aiduvo.coverage import metrics as covmetrics
from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.core.types import Action, Budget, Observation

# ---------------------------------------------------------------------------
# Action space
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Head:
    """One dimension of a factored action."""

    name: str
    options: Tuple[str, ...]
    weights: Optional[Tuple[float, ...]] = None

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError(f"action head {self.name!r} has no options")
        if self.weights is not None and len(self.weights) != len(self.options):
            raise ValueError(f"head {self.name!r}: weights/options length mismatch")

    def index(self, option: str) -> int:
        try:
            return self.options.index(option)
        except ValueError:
            return 0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "options": list(self.options)}


@dataclass
class FactoredActionSpace:
    """Product of independent action heads."""

    heads: List[Head] = field(default_factory=list)
    max_joint: int = 4096

    # ------------------------------------------------------------------ shape
    @property
    def names(self) -> List[str]:
        return [h.name for h in self.heads]

    def head(self, name: str) -> Head:
        for h in self.heads:
            if h.name == name:
                return h
        raise KeyError(f"unknown action head {name!r}")

    def size(self) -> int:
        n = 1
        for h in self.heads:
            n *= len(h.options)
        return min(n, self.max_joint)

    def head_sizes(self) -> List[int]:
        return [len(h.options) for h in self.heads]

    # --------------------------------------------------------------- encoding
    def encode(self, joint_index: int) -> Dict[str, str]:
        """Joint index -> per-head option labels (row-major, last head fastest)."""
        out: Dict[str, str] = {}
        idx = int(joint_index) % max(1, self.size())
        for h in reversed(self.heads):
            idx, rem = divmod(idx, len(h.options))
            out[h.name] = h.options[rem]
        return out

    def decode(self, heads: Mapping[str, str]) -> int:
        idx = 0
        for h in self.heads:
            idx = idx * len(h.options) + h.index(str(heads.get(h.name, h.options[0])))
        return idx

    def action(self, joint_index: int, rationale: str = "") -> Action:
        return Action(heads=self.encode(joint_index), rationale=rationale)

    def sample(self, rng: np.random.Generator) -> int:
        return int(rng.integers(0, max(1, self.size())))

    def default_index(self) -> int:
        return self.decode({h.name: h.options[0] for h in self.heads})

    def iter_actions(self) -> List[Dict[str, str]]:
        return [dict(zip(self.names, combo)) for combo in itertools.product(*[h.options for h in self.heads])]

    def to_dict(self) -> Dict[str, Any]:
        return {"heads": [h.to_dict() for h in self.heads], "max_joint": self.max_joint}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FactoredActionSpace":
        heads = [Head(name=h["name"], options=tuple(h["options"])) for h in d.get("heads") or []]
        return cls(heads=heads, max_joint=int(d.get("max_joint", 4096)))

    def describe(self) -> str:
        lines = [f"action space: {self.size()} joint actions"]
        for h in self.heads:
            lines.append(f"  {h.name:<14s} {len(h.options):>3d} options: {', '.join(h.options)}")
        return "\n".join(lines)


SEED_MODES = ("fresh", "mutate_best", "sweep", "resume_best")
KNOB_PROFILES_DEFAULT = ("none", "conservative", "balanced", "aggressive")
FORCE_BIASES = ("hold", "low", "high", "toggle", "random_walk", "release")
QUANTA = ("short", "medium", "long")
MAX_FOCUS_GROUPS = 10


def build_action_space(
    focus_groups: Sequence[str] = (),
    knob_profiles: Sequence[str] = KNOB_PROFILES_DEFAULT,
    runtime: bool = False,
    include_seed: bool = True,
    include_quantum: bool = True,
    include_focus: bool = True,
    include_knobs: bool = True,
) -> FactoredActionSpace:
    """Assemble a space from discovered facts.

    ``focus_groups`` should be a (possibly truncated) list of coverage group
    names reported by the simulator.  ``"all"`` and ``"hardest"`` are always
    available so the policy can always fall back to a project-agnostic choice.
    """
    heads: List[Head] = []
    if include_seed:
        heads.append(Head("seed_mode", SEED_MODES))
    if include_focus:
        focus = ["all", "hardest"] + [g for g in focus_groups if g not in ("all", "hardest")]
        focus = focus[: MAX_FOCUS_GROUPS + 2]
        heads.append(Head("focus", tuple(focus)))
    if include_knobs:
        heads.append(Head("knob_profile", tuple(knob_profiles) or ("none",)))
    if runtime:
        heads.append(Head("force_bias", FORCE_BIASES))
        if include_quantum:
            heads.append(Head("quantum", QUANTA))
    return FactoredActionSpace(heads=heads)


# ---------------------------------------------------------------------------
# State encoder
# ---------------------------------------------------------------------------

FEATURE_NAMES: Tuple[str, ...] = (
    "closure",
    "weighted_closure",
    "delta_closure",
    "delta_weighted",
    "novelty",
    "entropy",
    "zero_bin_ratio",
    "groups_at_goal",
    "elapsed_wall_frac",
    "elapsed_cycles_frac",
    "runs_frac",
    "best_closure",
    "regret",
    "plateau_frac",
    "log_cycles",
    "log_mean_hits",
    "group_closure_min",
    "group_closure_mean",
    "group_closure_max",
    "group_closure_std",
    "steps_frac",
    "sim_time_frac",
    "efficiency",
    "bias",
)


@dataclass
class EncoderContext:
    """Non-coverage bookkeeping the policy needs to see."""

    best_closure: float = 0.0
    plateau: int = 0
    run_index: int = 0
    step_index: int = 0
    budget: Budget = field(default_factory=Budget)
    cycles_scale: float = 1.0e6
    sim_time_scale: float = 1.0e6


class StateEncoder:
    """Maps an :class:`Observation` to a fixed-size, design-agnostic vector."""

    def __init__(self, dim: Optional[int] = None):
        self.dim = dim or len(FEATURE_NAMES)
        if self.dim != len(FEATURE_NAMES):
            raise ValueError("custom state dims are not supported; use FEATURE_NAMES")

    @staticmethod
    def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return float(max(lo, min(hi, x)))

    def encode(
        self,
        obs: Observation,
        prev: Optional[CoverageSnapshot] = None,
        ctx: Optional[EncoderContext] = None,
    ) -> np.ndarray:
        ctx = ctx or EncoderContext()
        snap: Optional[CoverageSnapshot] = obs.snapshot
        if snap is None or snap.is_empty():
            vec = np.zeros(self.dim, dtype=np.float32)
            vec[-1] = 1.0
            return vec

        m = covmetrics.summarize(snap)
        pm = covmetrics.summarize(prev) if prev is not None else None
        delta = m["closure"] - (pm["closure"] if pm else 0.0)
        delta_w = m["weighted_closure"] - (pm["weighted_closure"] if pm else 0.0)
        nov = covmetrics.novelty(prev, snap)
        gc = covmetrics.group_closures(snap)
        at_goal = sum(1 for v in gc.values() if v >= 0.999)
        groups = max(1, len(gc))
        wall_frac = (obs.wall_s / ctx.budget.max_wall_s) if ctx.budget.max_wall_s > 0 else 0.0
        cyc_frac = (obs.cycles / ctx.budget.max_cycles) if ctx.budget.max_cycles > 0 else 0.0
        runs_frac = (ctx.run_index / ctx.budget.max_runs) if ctx.budget.max_runs > 0 else 0.0
        steps_frac = (
            ctx.step_index / ctx.budget.max_steps_per_run if ctx.budget.max_steps_per_run > 0 else 0.0
        )
        best = max(ctx.best_closure, m["closure"])
        eff = m["closure"] / (1.0 + math.log1p(obs.cycles / max(1.0, ctx.cycles_scale)))

        vec = np.array(
            [
                self._clip(m["closure"], 0, 1),
                self._clip(m["weighted_closure"], 0, 1),
                self._clip(delta * 10.0),
                self._clip(delta_w * 10.0),
                self._clip(nov * 10.0),
                self._clip(m["entropy"], 0, 1),
                self._clip(m["zero_bin_ratio"], 0, 1),
                self._clip(at_goal / groups, 0, 1),
                self._clip(wall_frac, 0, 1),
                self._clip(cyc_frac, 0, 1),
                self._clip(runs_frac, 0, 1),
                self._clip(best, 0, 1),
                self._clip(best - m["closure"], 0, 1),
                self._clip(ctx.plateau / 10.0, 0, 1),
                self._clip(math.log1p(obs.cycles) / 20.0, 0, 1),
                self._clip(math.log1p(m["mean_hits"]) / 10.0, 0, 1),
                self._clip(m["group_closure_min"], 0, 1),
                self._clip(m["group_closure_mean"], 0, 1),
                self._clip(m["group_closure_max"], 0, 1),
                self._clip(m["group_closure_std"] * 3.0, 0, 1),
                self._clip(steps_frac, 0, 1),
                self._clip(
                    (obs.sim_time_ns / ctx.sim_time_scale) if ctx.sim_time_scale > 0 else 0.0, 0, 1
                ),
                self._clip(eff, 0, 1),
                1.0,
            ],
            dtype=np.float32,
        )
        return vec

    def encode_many(self, obs_list: Sequence[Observation]) -> np.ndarray:
        return np.stack([self.encode(o) for o in obs_list]) if obs_list else np.zeros((0, self.dim))
