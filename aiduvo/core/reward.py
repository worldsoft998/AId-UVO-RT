"""Reward shaping for coverage-driven optimisation.

The reward answers one question: *did this decision buy coverage cheaply?*
It rewards hard-bin closure and novel bins, penalises wasted simulated time and
plateaus, and pays a one-off bonus for reaching the campaign goal.  All terms are
normalised so the same numbers work for a 200-bin block and a 200 000-bin SoC.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from aiduvo.coverage import metrics as covmetrics
from aiduvo.coverage.model import CoverageSnapshot


@dataclass
class RewardConfig:
    hard_bin_weight: float = 1.0       # weight on hardness-weighted closure gain
    new_bin_weight: float = 0.8        # weight on the fraction of newly covered bins
    efficiency_weight: float = 0.2     # weight on coverage-per-cycle efficiency
    time_penalty: float = 0.25         # cost of wall-clock time
    cycle_penalty: float = 0.10        # cost of simulated cycles
    plateau_penalty: float = 0.15      # cost of a step that found nothing
    goal_bonus: float = 5.0            # one-off reward for hitting the goal
    time_ref_s: float = 60.0           # wall seconds that map to a penalty of 1.0
    cycle_ref: float = 1.0e6           # cycles that map to a penalty of 1.0
    reward_scale: float = 1.0
    clip: float = 10.0
    time_budget_fraction_weight: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RewardConfig":
        d = dict(d or {})
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RewardBreakdown:
    total: float = 0.0
    hard_gain: float = 0.0
    new_bins: float = 0.0
    efficiency: float = 0.0
    time_cost: float = 0.0
    cycle_cost: float = 0.0
    plateau_cost: float = 0.0
    goal_bonus: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


class RewardFunction:
    """Stateful reward function (remembers the goal latch)."""

    def __init__(self, cfg: Optional[RewardConfig] = None, target_closure: float = 0.0):
        self.cfg = cfg or RewardConfig()
        self.target_closure = float(target_closure)
        self._goal_paid = False

    def reset(self) -> None:
        self._goal_paid = False

    def __call__(
        self,
        prev: Optional[CoverageSnapshot],
        cur: CoverageSnapshot,
        dt_wall_s: float = 0.0,
        dt_cycles: float = 0.0,
        weights: Optional[Dict[str, float]] = None,
    ) -> RewardBreakdown:
        cfg = self.cfg
        cur_m = covmetrics.summarize(cur)
        if prev is None or prev.is_empty():
            prev_m = {
                "weighted_closure": 0.0,
                "closure": 0.0,
                "mean_hits": 0.0,
                "group_closure_mean": 0.0,
                "group_closure_std": 0.0,
            }
        else:
            prev_m = covmetrics.summarize(prev)

        # --- coverage gains -------------------------------------------------
        d_hard = max(0.0, cur_m["weighted_closure"] - prev_m["weighted_closure"])
        hard_gain = cfg.hard_bin_weight * d_hard * 10.0
        new_ratio = covmetrics.novelty(prev, cur)
        new_bins = cfg.new_bin_weight * min(1.0, new_ratio * 10.0)
        # Efficiency is *incremental*: coverage gained per unit of simulated
        # effort. A step that finds nothing earns nothing, which is what makes
        # the plateau penalty meaningful.
        d_closure = max(0.0, cur_m["closure"] - prev_m["closure"])
        eff = d_closure / (1.0 + math.log1p(max(0.0, dt_cycles) / 1.0e4))
        efficiency = cfg.efficiency_weight * 10.0 * eff

        # --- costs ----------------------------------------------------------
        time_cost = cfg.time_penalty * min(1.0, max(0.0, dt_wall_s) / max(1e-9, cfg.time_ref_s))
        cycle_cost = cfg.cycle_penalty * min(1.0, math.log1p(max(0.0, dt_cycles)) / math.log1p(cfg.cycle_ref))
        plateau_cost = 0.0
        if new_ratio <= 1e-9 and d_hard <= 1e-9:
            plateau_cost = cfg.plateau_penalty

        # --- goal -----------------------------------------------------------
        bonus = 0.0
        if (
            self.target_closure > 0
            and cur_m["closure"] >= self.target_closure
            and not self._goal_paid
        ):
            bonus = cfg.goal_bonus
            self._goal_paid = True

        total = hard_gain + new_bins + efficiency - time_cost - cycle_cost - plateau_cost + bonus
        total = max(-cfg.clip, min(cfg.clip, total * cfg.reward_scale))
        return RewardBreakdown(
            total=total,
            hard_gain=hard_gain,
            new_bins=new_bins,
            efficiency=efficiency,
            time_cost=-time_cost,
            cycle_cost=-cycle_cost,
            plateau_cost=-plateau_cost,
            goal_bonus=bonus,
        )
