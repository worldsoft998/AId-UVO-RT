"""Core value objects shared by every layer of AId-UVO-RT.

These types are deliberately free of any project-specific vocabulary.  A
"signal", a "coverpoint" or a "knob" is only ever an opaque identifier that the
framework learned at run time from the simulator.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence


class Mode(str, Enum):
    """Which optimizer flavour is running."""

    BASELINE = "baseline"      # plain constrained-random, no AI
    BLACKBOX = "blackbox"      # post-run logs / databases only, no simulator internals
    RUNTIME = "runtime"        # SRIE: live simulator introspection & reflection

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class Scope(str, Enum):
    """Where in the control hierarchy a decision is taken."""

    INTER_RUN = "inter_run"    # choose seed / knob profile / test for the next run
    INTRA_RUN = "intra_run"    # steer a running simulation (runtime mode only)


@dataclass
class Budget:
    """Global effort limits for a campaign."""

    max_runs: int = 20
    max_wall_s: float = 0.0            # 0 => unlimited
    max_cycles: float = 0.0            # 0 => unlimited
    target_closure: float = 0.95       # stop when weighted closure >= this
    max_steps_per_run: int = 0         # 0 => unlimited intra-run steps
    min_runs: int = 1                  # never stop before this many runs
    plateau_runs: int = 0              # 0 => disabled; else stop after N flat runs

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[Mapping[str, Any]]) -> "Budget":
        return cls(**{k: v for k, v in dict(d or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class Action:
    """A factored decision: one symbolic option per action head.

    ``heads`` maps a head name (``"seed_mode"``, ``"focus"``, ``"knob_profile"``,
    ``"force_bias"`` ...) to the chosen option label.  The concrete meaning of an
    option is resolved by the backend, never hard-coded in the policy.
    """

    heads: Dict[str, str] = field(default_factory=dict)
    rationale: str = ""

    def label(self) -> str:
        if not self.heads:
            return "<empty>"
        return "|".join(f"{k}={v}" for k, v in sorted(self.heads.items()))

    def to_dict(self) -> Dict[str, Any]:
        return {"heads": dict(self.heads), "rationale": self.rationale}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Action":
        return cls(heads=dict(d.get("heads") or {}), rationale=str(d.get("rationale") or ""))


@dataclass
class Observation:
    """What the optimizer is allowed to know at a decision point.

    ``snapshot`` is a :class:`aiduvo.coverage.model.CoverageSnapshot` (kept as
    ``Any`` to avoid an import cycle); ``signals`` holds sampled values from the
    live hierarchy in runtime mode and is empty in blackbox mode.
    """

    snapshot: Any = None
    signals: Dict[str, str] = field(default_factory=dict)
    sim_time_ns: float = 0.0
    cycles: float = 0.0
    wall_s: float = 0.0
    run_index: int = 0
    step_index: int = 0
    info: Dict[str, Any] = field(default_factory=dict)

    def signal_vector(self, order: Sequence[str]) -> List[str]:
        return [self.signals.get(k, "") for k in order]


@dataclass
class Transition:
    """One (state, action, reward, next-state) tuple handed to a learner."""

    state: Any
    action_index: int
    reward: float
    next_state: Any
    done: bool = False
    scope: Scope = Scope.INTER_RUN
    info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeResult:
    """Outcome of one simulation run (one seed / one test invocation)."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_index: int = 0
    mode: Mode = Mode.BASELINE
    algorithm: str = "none"
    action: Action = field(default_factory=Action)
    seed: Optional[int] = None
    test: str = ""
    knobs: Dict[str, Any] = field(default_factory=dict)
    closure: float = 0.0
    closure_unweighted: float = 0.0
    new_bins: int = 0
    total_bins: int = 0
    sim_time_ns: float = 0.0
    cycles: float = 0.0
    wall_s: float = 0.0
    steps: int = 0
    reward_sum: float = 0.0
    aborted: bool = False
    artifacts: Dict[str, str] = field(default_factory=dict)
    intra_actions: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "EpisodeResult":
        d = dict(d)
        d["mode"] = Mode(d.get("mode", "baseline"))
        d["action"] = Action.from_dict(d.get("action") or {})
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CampaignResult:
    """Full record of a campaign: config, episodes, final coverage, timings."""

    campaign_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))
    mode: Mode = Mode.BASELINE
    algorithm: str = "none"
    ai_enabled: bool = False
    budget: Budget = field(default_factory=Budget)
    episodes: List[EpisodeResult] = field(default_factory=list)
    final_closure: float = 0.0
    final_closure_unweighted: float = 0.0
    total_wall_s: float = 0.0
    total_sim_time_ns: float = 0.0
    total_cycles: float = 0.0
    runs_used: int = 0
    stopped_reason: str = ""
    curve: List[Dict[str, float]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "mode": self.mode.value,
            "algorithm": self.algorithm,
            "ai_enabled": self.ai_enabled,
            "budget": self.budget.to_dict(),
            "episodes": [e.to_dict() for e in self.episodes],
            "final_closure": self.final_closure,
            "final_closure_unweighted": self.final_closure_unweighted,
            "total_wall_s": self.total_wall_s,
            "total_sim_time_ns": self.total_sim_time_ns,
            "total_cycles": self.total_cycles,
            "runs_used": self.runs_used,
            "stopped_reason": self.stopped_reason,
            "curve": self.curve,
            "metadata": self.metadata,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CampaignResult":
        d = dict(d)
        return cls(
            campaign_id=d.get("campaign_id", ""),
            mode=Mode(d.get("mode", "baseline")),
            algorithm=d.get("algorithm", "none"),
            ai_enabled=bool(d.get("ai_enabled", False)),
            budget=Budget.from_dict(d.get("budget")),
            episodes=[EpisodeResult.from_dict(e) for e in d.get("episodes") or []],
            final_closure=float(d.get("final_closure", 0.0)),
            final_closure_unweighted=float(d.get("final_closure_unweighted", 0.0)),
            total_wall_s=float(d.get("total_wall_s", 0.0)),
            total_sim_time_ns=float(d.get("total_sim_time_ns", 0.0)),
            total_cycles=float(d.get("total_cycles", 0.0)),
            runs_used=int(d.get("runs_used", 0)),
            stopped_reason=d.get("stopped_reason", ""),
            curve=list(d.get("curve") or []),
            metadata=dict(d.get("metadata") or {}),
            error=d.get("error", ""),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "CampaignResult":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
