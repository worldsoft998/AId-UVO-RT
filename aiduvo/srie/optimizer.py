"""The runtime optimizer: SRIE inside the simulation loop.

Two nested control loops, both learned:

**Outer (inter-run)** -- after each simulation run, decide the next seed mode,
which coverage group to focus on, and which knob profile to launch with.  This is
where a bandit shines: only a handful of decisions per campaign.

**Inner (intra-run)** -- inside a single simulation, every ``quantum_cycles`` the
agent looks at the coverage snapshot and the sampled signals, then steers the
stimulus by driving discovered input ports (hold / low / high / toggle / random
walk), and decides how long to run before looking again.  This is the
"instantaneous" part: the decision happens while the simulator is paused at a
prompt, with no restart and no recompilation.

Both loops share the reward function, the encoder and the storage, so the whole
thing behaves like one hybrid framework rather than two bolted-on tools.
"""

from __future__ import annotations

import os
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from aiduvo.coverage import metrics as covmetrics
from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.core.backend import Backend, BackendInfo, InnerPolicyFactory
from aiduvo.core.reward import RewardConfig, RewardFunction
from aiduvo.core.space import (
    EncoderContext,
    FactoredActionSpace,
    StateEncoder,
    build_action_space,
)
from aiduvo.core.types import Action, Budget, EpisodeResult, Mode
from aiduvo.blackbox.knobs import KnobSpace, SeedStrategy
from aiduvo.srie.bootstrap import bootstrap_do_file
from aiduvo.srie.launcher import SimLaunch, find_executable
from aiduvo.srie.protocol import SRIEError
from aiduvo.srie.session import SRIEConfig, SRIESession

QUANTUM_SCALE = {"short": 1, "medium": 4, "long": 12}


@dataclass
class RuntimeSettings:
    """The ``srie`` block of a campaign config, with runtime-only extras."""

    config: SRIEConfig = field(default_factory=SRIEConfig)
    reuse_prepare_session: bool = False
    intra_steps: int = 8
    coverage_every: int = 1
    max_steps_per_run: int = 0
    trigger_specs: List[Dict[str, str]] = field(default_factory=list)
    log_events: bool = True

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]], launch: Optional[Dict[str, Any]] = None) -> "RuntimeSettings":
        d = dict(d or {})
        cfg = SRIEConfig.from_dict(d)
        if launch and not cfg.launch:
            cfg.launch = dict(launch)
        return cls(
            config=cfg,
            reuse_prepare_session=bool(d.get("reuse_prepare_session", False)),
            intra_steps=int(d.get("intra_steps", 8)),
            coverage_every=max(1, int(d.get("coverage_every", 1))),
            max_steps_per_run=int(d.get("max_steps_per_run", 0)),
            trigger_specs=list(d.get("trigger_specs") or []),
            log_events=bool(d.get("log_events", True)),
        )


class RuntimeBackend(Backend):
    """Live, in-simulation optimization through SRIE."""

    name = "srie-runtime"
    mode = Mode.RUNTIME

    def __init__(self, cfg: Any, log: Optional[Callable[[str], None]] = None):
        super().__init__(log=log)
        self.cfg = cfg
        self.settings = RuntimeSettings.from_dict(cfg.srie)
        self.knobs = KnobSpace.from_dict(cfg.knobs)
        self.seed_strategy = SeedStrategy(base_seed=int(cfg.seed), rng=None)
        self.reward_cfg = RewardConfig.from_dict(cfg.reward)
        self.budget = Budget.from_dict(cfg.budget)
        self.encoder = StateEncoder()
        self.inner_space: Optional[FactoredActionSpace] = None
        self.inner_policy: Any = None
        self._inner_factory: Optional[InnerPolicyFactory] = None
        self._prepared: Optional[SRIESession] = None
        self._groups: List[str] = []
        self.capabilities: Dict[str, Any] = {}
        self.workdir = os.path.abspath(os.path.join(cfg.outdir, "_srie_work"))
        os.makedirs(self.workdir, exist_ok=True)

    # ------------------------------------------------------------------ setup
    def attach_inner_policy(self, factory: InnerPolicyFactory) -> None:
        self._inner_factory = factory

    def prepare(self) -> BackendInfo:
        """Discover the hierarchy and the coverage structure once, up front."""
        session = self._open_session(seed=int(self.cfg.seed), plusargs={})
        try:
            self.capabilities = session.capabilities
            snap = session.coverage("prepare")
            self._groups = snap.group_names
            self.log(f"discovered {snap.total_bins} coverage bins in {len(self._groups)} groups")
            info = BackendInfo(
                focus_groups=self._groups,
                knob_profiles=self.knobs.profile_names(),
                capabilities={"transport": session.transport.name if session.transport else "",
                              "capabilities": self.capabilities,
                              "inputs": [n.path for n in session.hierarchy.inputs()][:32]
                              if session.hierarchy else []},
                notes=[f"coverage bins: {snap.total_bins}"],
            )
            if snap.is_empty():
                info.notes.append("WARNING: no coverage found; check that coverage was compiled in")
            self.merge(snap)
            if self.settings.reuse_prepare_session:
                self._prepared = session
                session = None
            return info
        finally:
            if session is not None:
                session.close()

    # --------------------------------------------------------------- sessions
    def _transport_spec(self, seed: int, plusargs: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.settings.config
        spec = dict(cfg.transport)
        kind = str(spec.get("kind", "mock")).lower()
        if kind in ("pipe", "questa", "vsim"):
            launch = SimLaunch.from_dict(cfg.launch)
            launch.exe = launch.exe or (find_executable("vsim") or "vsim")
            launch.seed = seed
            launch.coverage = True
            merged = dict(launch.plusargs)
            merged.update(plusargs)
            launch.plusargs = merged
            if not launch.do_file:
                launch.do_file = bootstrap_do_file(self.workdir, seed=seed)
            launch.cwd = launch.cwd or self.workdir
            launch.log_file = launch.log_file or os.path.join(
                self.workdir, f"vsim_{int(time.time() * 1000) % 1000000}.log"
            )
            spec = {"kind": "pipe", "argv": launch.argv(), "cwd": launch.cwd}
        elif kind in ("socket", "tcl"):
            launch = SimLaunch.from_dict(cfg.launch)
            launch.exe = launch.exe or (find_executable("vsim") or "vsim")
            launch.seed = seed
            launch.plusargs = {**launch.plusargs, **plusargs}
            port = int(spec.get("port") or _free_port())
            launch.do_file = bootstrap_do_file(self.workdir, seed=seed, port=port)
            launch.cwd = launch.cwd or self.workdir
            import subprocess

            subprocess.Popen(launch.argv(), cwd=launch.cwd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.STDOUT)
            spec = {"kind": "socket", "host": spec.get("host", "127.0.0.1"), "port": port}
        else:
            spec = {"kind": "mock", "seed": seed}
        return spec

    def _open_session(self, seed: int, plusargs: Dict[str, Any]) -> SRIESession:
        cfg = self.settings.config
        spec = self._transport_spec(seed, plusargs)
        sub = SRIEConfig.from_dict(cfg.to_dict())
        sub.transport = spec
        sub.workdir = self.workdir
        session = SRIESession(sub, log=self.log)
        session.open(discover=True)
        if self.settings.trigger_specs and session.hierarchy is not None:
            self._install_triggers(session)
        return session

    def _install_triggers(self, session: SRIESession) -> None:
        hier = session.hierarchy
        if hier is None:
            return
        ins = [n.path for n in hier.inputs()]
        outs = [n.path for n in hier.outputs()]
        for i, spec in enumerate(self.settings.trigger_specs):
            expr = str(spec.get("expr", ""))
            for j, p in enumerate(ins):
                expr = expr.replace(f"{{in{j}}}", p)
            for j, p in enumerate(outs):
                expr = expr.replace(f"{{out{j}}}", p)
            label = str(spec.get("label", f"trig_{i}"))
            ok = session.install_trigger(label, expr, kind=str(spec.get("kind", "trigger")))
            self.log(f"trigger {label}: {'installed' if ok else 'FAILED'} ({expr})")

    # -------------------------------------------------------------------- run
    def run(self, action: Action, run_index: int, budget: Budget) -> EpisodeResult:
        mode = action.heads.get("seed_mode", "fresh")
        seed = self.seed_strategy.pick(mode, run_index)
        profile = action.heads.get("knob_profile", "none")
        plusargs = self.knobs.plusargs(profile)
        focus = action.heads.get("focus", "all")

        episode = EpisodeResult(mode=Mode.RUNTIME, seed=seed, knobs={"profile": profile, **plusargs})
        t0 = time.time()
        session: Optional[SRIESession] = None
        if self._prepared is not None:
            session = self._prepared
            self._prepared = None
        else:
            session = self._open_session(seed, plusargs)
        try:
            episode.artifacts["transport"] = session.transport.name if session.transport else ""
            episode.artifacts["capabilities"] = session.capabilities
            targets = self._bias_targets(session, focus)
            episode.knobs["bias_targets"] = targets

            inner = self._ensure_inner_policy()
            reward_fn = RewardFunction(self.reward_cfg, self.budget.target_closure)
            prev = session.coverage(f"r{run_index}_init")
            cycles_total = 0.0
            last_wall = 0.0
            steps = 0
            max_steps = self.settings.max_steps_per_run or self.settings.intra_steps
            if budget.max_steps_per_run:
                max_steps = min(max_steps, budget.max_steps_per_run) if max_steps else budget.max_steps_per_run

            while steps < max_steps:
                obs_snapshot = prev
                ctx = EncoderContext(
                    best_closure=covmetrics.closure(prev), plateau=0, step_index=steps, budget=budget
                )
                from aiduvo.core.types import Observation

                obs = Observation(snapshot=obs_snapshot, run_index=run_index, step_index=steps,
                                  cycles=cycles_total, wall_s=last_wall)
                state = self.encoder.encode(obs, prev, ctx)
                idx = inner.select(state, explore=True) if self.cfg.ai else inner.select(state, explore=False)
                inner_action = self.inner_space.action(idx) if self.inner_space else Action({})
                bias = inner_action.heads.get("force_bias", "hold")
                quantum = QUANTUM_SCALE.get(inner_action.heads.get("quantum", "medium"), 4)

                current = session.sample(targets) if targets else {}
                applied = session.bias(bias, paths=targets, cycle=cycles_total, current=current)
                t_step = time.time()
                ran = session.run_quantum(self.settings.config.quantum_cycles * quantum)
                dt_wall = time.time() - t_step
                events = session.pump_events()

                snap = session.coverage(f"r{run_index}_s{steps}")
                sim_ns = session.sim_time_ns()
                dt_cycles = max(0.0, sim_ns - cycles_total * self.settings.config.period_ns)
                dt_cycles = dt_cycles / self.settings.config.period_ns if self.settings.config.period_ns else 0.0
                cycles_total += dt_cycles
                breakdown = reward_fn(prev, snap, dt_wall, dt_cycles)

                record = {
                    "step": steps,
                    "action": inner_action.heads,
                    "bias_ops": len(applied),
                    "closure": covmetrics.closure(snap),
                    "weighted_closure": covmetrics.weighted_closure(snap),
                    "new_bins": len(snap.new_bins_since(prev)),
                    "reward": breakdown.total,
                    "cycles": cycles_total,
                    "events": events,
                    "ran": ran,
                }
                episode.intra_actions.append(record)
                self.log(
                    f"    step {steps:>2d} {bias:<11s} q={quantum:<2d} "
                    f"closure={record['closure'] * 100:6.2f}% new={record['new_bins']:<3d} "
                    f"r={breakdown.total:+.3f}"
                )

                if self.cfg.ai:
                    from aiduvo.core.types import Scope, Transition

                    next_obs = Observation(snapshot=snap, run_index=run_index, step_index=steps + 1,
                                           cycles=cycles_total, wall_s=last_wall + dt_wall)
                    next_state = self.encoder.encode(next_obs, snap, ctx)
                    inner.observe(state, idx, breakdown.total, next_state, done=False)
                prev = snap
                last_wall += dt_wall
                steps += 1
                if self.budget.target_closure > 0 and covmetrics.closure(snap) >= self.budget.target_closure:
                    self.log("    intra-run target closure reached; stopping run early")
                    break
            inner.end_episode()

            final = session.coverage(f"r{run_index}_final")
            self.merge(final)
            episode.sim_time_ns = session.sim_time_ns()
            episode.cycles = cycles_total
            episode.steps = steps
            episode.reward_sum = sum(r["reward"] for r in episode.intra_actions)
            episode.aborted = False
        except SRIEError as exc:
            episode.error = f"{type(exc).__name__}: {exc}"
            self.log(f"!! runtime error: {episode.error}")
        finally:
            episode.wall_s = time.time() - t0
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass
        self.seed_strategy.report(seed, episode.reward_sum)
        return episode

    # ----------------------------------------------------------------- helpers
    def _ensure_inner_policy(self) -> Any:
        if self.inner_policy is not None:
            return self.inner_policy
        self.inner_space = build_action_space(
            focus_groups=[],
            knob_profiles=["none"],
            runtime=True,
            include_seed=False,
            include_focus=False,
            include_knobs=False,
        )
        if self._inner_factory is not None:
            self.inner_policy = self._inner_factory(self.inner_space.size(), self.encoder.dim)
        else:
            from aiduvo.rl import make_policy

            self.inner_policy = make_policy("none", self.inner_space.size(), self.encoder.dim)
        self.log(f"inner action space: {self.inner_space.size()} actions "
                 f"({', '.join(self.inner_space.names)})")
        return self.inner_policy

    def _bias_targets(self, session: SRIESession, focus: str) -> List[str]:
        if session.reflection is None:
            return []
        cands = session.reflection.candidates(limit=256)
        if not cands:
            return []
        n = max(1, min(len(cands), self.settings.config.max_forced))
        if focus in ("", "all", "hardest"):
            return cands[:n]
        # Deterministic rotation keyed by the coverage group name (crc32 keeps it
        # stable across processes, unlike hash()).
        k = zlib.crc32(focus.encode()) % len(cands)
        return [cands[(k + i) % len(cands)] for i in range(n)]

    def close(self) -> None:
        if self._prepared is not None:
            try:
                self._prepared.close()
            except Exception:  # noqa: BLE001
                pass
            self._prepared = None


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
