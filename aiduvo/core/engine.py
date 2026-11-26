"""The campaign engine: the loop that turns coverage into a learning signal.

One ``Campaign`` is one comparable experiment:

    baseline   seeds only, no AI, no adaptation
    blackbox   the same runner, but the AI chooses seed / profile / run length
    runtime    a live SRIE session, steered *inside* the run and across runs

The engine itself is backend-agnostic, which is what makes the three-way
comparison fair: identical reward, identical budget accounting, identical
storage, identical reporting.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from aiduvo.coverage import metrics as covmetrics
from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.coverage.store import CoverageStore
from aiduvo.core.backend import Backend, BackendInfo
from aiduvo.core.reward import RewardConfig, RewardFunction
from aiduvo.core.space import FactoredActionSpace, StateEncoder, build_action_space
from aiduvo.core.types import (
    Action,
    Budget,
    CampaignResult,
    EpisodeResult,
    Mode,
    Observation,
    Scope,
)
from aiduvo.rl import make_policy


@dataclass
class CampaignConfig:
    """Everything a campaign needs, serialisable to one JSON file."""

    mode: str = "baseline"
    ai: bool = False
    algorithm: str = "none"
    inner_algorithm: str = ""
    seed: int = 1
    outdir: str = "runs"
    name: str = ""
    budget: Dict[str, Any] = field(default_factory=dict)
    reward: Dict[str, Any] = field(default_factory=dict)
    knobs: Dict[str, Any] = field(default_factory=dict)
    srie: Dict[str, Any] = field(default_factory=dict)
    blackbox: Dict[str, Any] = field(default_factory=dict)
    focus_limit: int = 8
    policy_kwargs: Dict[str, Any] = field(default_factory=dict)
    inner_policy_kwargs: Dict[str, Any] = field(default_factory=dict)
    save_policy: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode, "ai": self.ai, "algorithm": self.algorithm,
            "inner_algorithm": self.inner_algorithm, "seed": self.seed,
            "outdir": self.outdir, "name": self.name, "budget": self.budget,
            "reward": self.reward, "knobs": self.knobs, "srie": self.srie,
            "blackbox": self.blackbox, "focus_limit": self.focus_limit,
            "policy_kwargs": self.policy_kwargs,
            "inner_policy_kwargs": self.inner_policy_kwargs,
            "save_policy": self.save_policy, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CampaignConfig":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})

    @classmethod
    def load(cls, path: str) -> "CampaignConfig":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)


def build_backend(cfg: CampaignConfig, log: Callable[[str], None]) -> Backend:
    """Instantiate the backend that matches the requested mode."""
    mode = Mode(cfg.mode)
    if mode == Mode.RUNTIME:
        from aiduvo.srie.optimizer import RuntimeBackend

        return RuntimeBackend(cfg, log=log)
    from aiduvo.blackbox.backend import BlackboxBackend, MockBlackboxBackend

    kind = str((cfg.blackbox or {}).get("kind", "questa")).lower()
    if kind == "mock":
        return MockBlackboxBackend(cfg, log=log)
    return BlackboxBackend(cfg, log=log)


class Campaign:
    """Runs one experiment and returns a comparable result object."""

    def __init__(self, config: CampaignConfig, log: Optional[Callable[[str], None]] = None):
        self.cfg = config
        self._log = log or (lambda m: print(m, flush=True))
        self.budget = Budget.from_dict(config.budget)
        self.reward_cfg = RewardConfig.from_dict(config.reward)
        self.mode = Mode(config.mode)
        self.encoder = StateEncoder()
        self.space: Optional[FactoredActionSpace] = None
        self.policy: Any = None
        self.backend: Optional[Backend] = None
        self.info = BackendInfo()
        self.outdir = self._make_outdir()
        self.store: Optional[CoverageStore] = None

    # ------------------------------------------------------------------ setup
    def _make_outdir(self) -> str:
        name = self.cfg.name or (
            f"{self.mode.value}_{self.cfg.algorithm if self.cfg.ai else 'noai'}_"
            f"{time.strftime('%Y%m%d-%H%M%S')}"
        )
        path = os.path.join(self.cfg.outdir, name)
        os.makedirs(path, exist_ok=True)
        return path

    def log(self, message: str) -> None:
        self._log(message)

    # -------------------------------------------------------------------- run
    def run(self) -> CampaignResult:
        cfg = self.cfg
        result = CampaignResult(
            mode=self.mode,
            algorithm=cfg.algorithm if cfg.ai else "none",
            ai_enabled=cfg.ai,
            budget=self.budget,
        )
        started = time.time()
        self.log(f"=== AId-UVO-RT campaign [{self.mode.value}] ===")
        self.log(f"output      : {self.outdir}")
        self.log(f"ai          : {'on (' + cfg.algorithm + ')' if cfg.ai else 'off'}")
        self.log(f"budget      : runs<={self.budget.max_runs} target_closure={self.budget.target_closure}")

        self.store = CoverageStore(os.path.join(self.outdir, "history.sqlite"))
        self.store.begin_campaign(
            result.campaign_id, self.mode.value, result.algorithm, cfg.ai, started,
            meta={"config": cfg.to_dict()},
        )
        cfg.save(os.path.join(self.outdir, "campaign_config.json"))

        try:
            self.backend = build_backend(cfg, self.log)
            self.info = self.backend.prepare()
            self.log(f"backend     : {self.backend.name}")
            if self.info.focus_groups:
                self.log(f"focus groups: {', '.join(self.info.focus_groups[:12])}")
            if self.info.notes:
                for note in self.info.notes:
                    self.log(f"  note: {note}")

            self.space = build_action_space(
                focus_groups=self.info.focus_groups[: self.cfg.focus_limit],
                knob_profiles=self.info.knob_profiles,
                runtime=(self.mode == Mode.RUNTIME),
            )
            self.backend.bind_space(self.space)
            self.log(self.space.describe())

            algo = cfg.algorithm if cfg.ai else "none"
            self.policy = make_policy(
                algo, self.space.size(), self.encoder.dim, seed=cfg.seed, **cfg.policy_kwargs
            )
            self.log(f"policy      : {self.policy.info()}")

            if self.mode == Mode.RUNTIME and hasattr(self.backend, "attach_inner_policy"):
                inner_algo = cfg.inner_algorithm or algo
                seed = cfg.seed + 7

                def factory(n_actions: int, state_dim: int, _algo: str = inner_algo, _seed: int = seed) -> Any:
                    return make_policy(
                        _algo, n_actions, state_dim, seed=_seed, **cfg.inner_policy_kwargs
                    )

                self.backend.attach_inner_policy(factory)  # type: ignore[attr-defined]

            self._loop(result, started)
        except Exception as exc:  # noqa: BLE001 - a campaign must always produce a report
            result.error = f"{type(exc).__name__}: {exc}"
            result.stopped_reason = "error"
            self.log(f"!! campaign error: {result.error}")
            raise
        finally:
            try:
                if self.backend is not None:
                    self.backend.close()
            finally:
                result.total_wall_s = time.time() - started
                self._finalize(result, started)
                if self.store is not None:
                    self.store.close()
        return result

    # ------------------------------------------------------------------- loop
    def _loop(self, result: CampaignResult, started: float) -> None:
        assert self.backend is not None and self.space is not None and self.policy is not None
        reward_fn = RewardFunction(self.reward_cfg, self.budget.target_closure)
        prev_cum: Optional[CoverageSnapshot] = None
        best_closure = 0.0
        plateau = 0
        run_index = 0
        last_wall = 0.0
        last_cycles = 0.0
        last_sim_ns = 0.0

        while run_index < max(1, self.budget.max_runs):
            obs = Observation(
                snapshot=prev_cum,
                run_index=run_index,
                wall_s=last_wall,
                cycles=last_cycles,
                sim_time_ns=last_sim_ns,
                info={"backend": self.backend.name},
            )
            ctx = self._encoder_ctx(best_closure, plateau, run_index)
            state = self.encoder.encode(obs, prev_cum, ctx)

            action = self._choose_action(state, run_index)
            self.log(f"--- run {run_index + 1}/{self.budget.max_runs} :: {action.label()}")
            t_run = time.time()
            episode = self.backend.run(action, run_index, self.budget)
            episode.mode = self.mode
            episode.algorithm = result.algorithm
            episode.run_index = run_index
            episode.action = action
            episode.wall_s = episode.wall_s or (time.time() - t_run)
            result.episodes.append(episode)

            cum = self.backend.cumulative
            if cum is None:
                cum = CoverageSnapshot(source="empty")
            closure = covmetrics.closure(cum)
            wclosure = covmetrics.weighted_closure(cum)
            episode.closure = closure
            episode.closure_unweighted = closure
            episode.total_bins = cum.total_bins
            episode.new_bins = len(cum.new_bins_since(prev_cum))

            dt_wall = max(0.0, episode.wall_s)
            dt_cycles = max(0.0, episode.cycles)
            breakdown = reward_fn(prev_cum, cum, dt_wall, dt_cycles)
            episode.reward_sum = breakdown.total

            next_obs = Observation(
                snapshot=cum, run_index=run_index + 1, wall_s=last_wall + dt_wall,
                cycles=last_cycles + dt_cycles, sim_time_ns=last_sim_ns + episode.sim_time_ns,
            )
            next_state = self.encoder.encode(next_obs, cum, self._encoder_ctx(
                max(best_closure, closure), plateau, run_index + 1))
            if self.cfg.ai:
                diag = self.policy.observe(state, self.space.decode(action.heads), breakdown.total, next_state)
                if diag:
                    episode.knobs.setdefault("_policy", {}).update(
                        {k: float(v) for k, v in diag.items() if isinstance(v, (int, float))}
                    )
            self.policy.end_episode()

            self.log(
                f"    coverage {closure * 100:6.2f}% (weighted {wclosure * 100:6.2f}%) "
                f"new_bins={episode.new_bins} reward={breakdown.total:+.3f} "
                f"cycles={episode.cycles:.0f} wall={episode.wall_s:.1f}s"
                + (f" ERROR={episode.error}" if episode.error else "")
            )

            if self.store is not None:
                self.store.record_episode(result.campaign_id, run_index, episode.to_dict())
                self.store.record_snapshot(result.campaign_id, run_index, cum, closure, wclosure)
                self.store.record_action(
                    result.campaign_id, run_index, 0,
                    {"action": action.to_dict(), "reward": breakdown.to_dict()},
                )

            last_wall += dt_wall
            last_cycles += dt_cycles
            last_sim_ns += episode.sim_time_ns
            result.curve.append(
                {
                    "run": float(run_index + 1),
                    "closure": closure,
                    "weighted_closure": wclosure,
                    "cum_cycles": last_cycles,
                    "cum_sim_time_ns": last_sim_ns,
                    "cum_wall_s": last_wall,
                    "reward": breakdown.total,
                }
            )
            result.runs_used = run_index + 1
            result.final_closure = closure
            result.final_closure_unweighted = closure
            result.total_cycles = last_cycles
            result.total_sim_time_ns = last_sim_ns

            if closure > best_closure + 1e-6:
                best_closure = closure
                plateau = 0
            else:
                plateau += 1
            prev_cum = cum
            run_index += 1

            reason = self._stop_reason(closure, plateau, run_index, time.time() - started, last_cycles)
            if reason:
                result.stopped_reason = reason
                self.log(f"=== stop: {reason} ===")
                break
        else:
            result.stopped_reason = "max_runs"

    def _choose_action(self, state: Any, run_index: int) -> Action:
        assert self.space is not None
        if not self.cfg.ai:
            heads = {h.name: h.options[0] for h in self.space.heads}
            if "seed_mode" in heads:
                heads["seed_mode"] = "sweep"
            return Action(heads=heads, rationale="baseline: sequential seeds, no adaptation")
        idx = self.policy.select(state, explore=True)
        return self.space.action(idx, rationale=f"policy={self.policy.name}")

    def _encoder_ctx(self, best: float, plateau: int, run_index: int) -> Any:
        from aiduvo.core.space import EncoderContext

        return EncoderContext(best_closure=best, plateau=plateau, run_index=run_index, budget=self.budget)

    def _stop_reason(self, closure: float, plateau: int, runs: int, wall: float,
                     cycles: float = 0.0) -> str:
        b = self.budget
        if runs < max(1, b.min_runs):
            return ""
        if b.target_closure > 0 and closure >= b.target_closure:
            return "target_closure"
        if b.max_wall_s > 0 and wall >= b.max_wall_s:
            return "max_wall_s"
        if b.max_cycles > 0 and cycles >= b.max_cycles:
            return "max_cycles"
        if b.plateau_runs > 0 and plateau >= b.plateau_runs:
            return "plateau"
        return ""

    # -------------------------------------------------------------- finalising
    def _finalize(self, result: CampaignResult, started: float) -> None:
        cum = self.backend.cumulative if self.backend is not None else None
        if cum is not None and not cum.is_empty():
            result.final_closure = covmetrics.closure(cum)
            result.final_closure_unweighted = covmetrics.closure(cum)
            result.metadata["final_summary"] = covmetrics.summarize(cum)
            result.metadata["hardest_bins"] = covmetrics.hardest_bins(cum, 15)
            result.metadata["group_closures"] = covmetrics.group_closures(cum)
        result.metadata["backend"] = self.backend.name if self.backend else None
        result.metadata["backend_info"] = self.info.to_dict()
        result.metadata["action_space"] = self.space.to_dict() if self.space else None
        result.metadata["policy"] = self.policy.info() if self.policy else None
        result.metadata["outdir"] = self.outdir
        result.metadata["config"] = self.cfg.to_dict()
        result.total_wall_s = time.time() - started
        result.save(os.path.join(self.outdir, "campaign_result.json"))
        if self.cfg.save_policy and self.policy is not None and self.cfg.ai:
            try:
                self.policy.save(os.path.join(self.outdir, "policy"))
            except Exception as exc:  # noqa: BLE001
                self.log(f"policy save skipped: {exc}")
        self.log(
            f"=== done [{result.stopped_reason}] final closure "
            f"{result.final_closure * 100:.2f}% in {result.runs_used} runs, "
            f"{result.total_wall_s:.1f}s wall ==="
        )


def run_campaign(config_path: Optional[str] = None, **overrides: Any) -> CampaignResult:
    """Convenience entry point used by the CLI and the batch files."""
    cfg = CampaignConfig.load(config_path) if config_path else CampaignConfig()
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return Campaign(cfg).run()
