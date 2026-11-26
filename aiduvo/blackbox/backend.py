"""Blackbox backends: the simulator as a closed box.

``BlackboxBackend``
    Real QuestaSim: launches ``vsim`` per run with a chosen seed and knob
    profile, bounds the run with a generated do-file, watches the transcript,
    and imports the coverage database afterwards.

``MockBlackboxBackend``
    Same control flow against the synthetic run generator, so the blackbox path
    can be demonstrated and unit-tested without a licence.

Neither can see inside the simulator: their entire action space is
"seed, profile, run length, test", and their entire observation space is
"transcript + coverage database".  That restriction is exactly what makes them a
meaningful baseline against the runtime optimizer.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from aiduvo.blackbox.knobs import KnobSpace, SeedStrategy
from aiduvo.blackbox.logwatch import TranscriptWatcher
from aiduvo.blackbox.mock import MockDesign, MockRunSimulator
from aiduvo.blackbox.runner import RunArtifacts, SimRunner, write_run_do
from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.coverage.ucis import load_coverage
from aiduvo.core.backend import Backend, BackendInfo
from aiduvo.core.types import Action, Budget, EpisodeResult, Mode
from aiduvo.srie.launcher import SimLaunch, find_executable


def _profile_quality(knobs: KnobSpace, profile: str) -> float:
    """Map a knob profile to a [0,1] "stimulus aggressiveness" for the mock.

    Real simulators do not need this: their response is the response.  The mock
    needs a defined relationship between knob values and reachable coverage.
    """
    values = knobs.profile(profile).values
    nums: List[float] = []
    for v in values.values():
        try:
            nums.append(float(str(v)))
        except (TypeError, ValueError):
            continue
    if not nums:
        return 0.0
    return max(0.0, min(1.0, sum(nums) / len(nums) / 100.0))


class _BlackboxBase(Backend):
    mode = Mode.BLACKBOX

    def __init__(self, cfg: Any, log: Optional[Callable[[str], None]] = None):
        super().__init__(log=log)
        self.cfg = cfg
        self.bb: Dict[str, Any] = dict(cfg.blackbox or {})
        self.knobs = KnobSpace.from_dict(cfg.knobs)
        self.seed_strategy = SeedStrategy(base_seed=int(cfg.seed))
        self.budget = Budget.from_dict(cfg.budget)
        self.artifacts_dir = os.path.join(cfg.outdir, "_artifacts")
        os.makedirs(self.artifacts_dir, exist_ok=True)
        self.run_time = str(self.bb.get("run_time", "1000 us"))
        self.period_ns = float(self.bb.get("period_ns", 10.0))
        self.timeout_s = float(self.bb.get("timeout_s", 3600.0))
        self.abort_on_error = bool(self.bb.get("abort_on_error", True))
        self.stall_seconds = float(self.bb.get("stall_seconds", 0.0))
        self.tests: List[str] = list(self.bb.get("tests") or [])
        self.coverage_format = str(self.bb.get("coverage_format", "auto"))
        self.run_index = 0

    # ------------------------------------------------------------------ helpers
    def _run_paths(self, run_index: int) -> Dict[str, str]:
        d = os.path.join(self.artifacts_dir, f"run_{run_index:04d}")
        os.makedirs(d, exist_ok=True)
        return {
            "dir": d,
            "log": os.path.join(d, "transcript.log"),
            "ucdb": os.path.join(d, "coverage.ucdb"),
            "xml": os.path.join(d, "coverage.xml"),
            "do": os.path.join(d, "run.do"),
        }

    def _episode_shell(self, action: Action, run_index: int, seed: int,
                       profile: str) -> EpisodeResult:
        return EpisodeResult(
            run_index=run_index,
            mode=self.mode,
            seed=seed,
            test=self.tests[0] if self.tests else "",
            knobs={"profile": profile, "run_time": self.run_time,
                   **self.knobs.plusargs(profile)},
        )


class BlackboxBackend(_BlackboxBase):
    """Drives a real QuestaSim through seeds, plusargs and coverage databases."""

    name = "blackbox-questa"

    def __init__(self, cfg: Any, log: Optional[Callable[[str], None]] = None):
        super().__init__(cfg, log)
        self.launch = SimLaunch.from_dict(self.bb.get("launch"))
        self.launch.exe = self.launch.exe or (find_executable("vsim") or "vsim")
        self.vcover = str(self.bb.get("vcover") or find_executable("vcover") or "vcover")
        self.seed_file = str(self.bb.get("coverage_seed_file", ""))

    def prepare(self) -> BackendInfo:
        notes: List[str] = []
        exe_ok = find_executable(self.launch.exe) is not None
        notes.append(f"vsim: {self.launch.exe} ({'found' if exe_ok else 'NOT FOUND'})")
        notes.append(f"vcover: {self.vcover}")
        groups: List[str] = []
        if self.seed_file and os.path.exists(self.seed_file):
            try:
                snap = load_coverage(self.seed_file, fmt=self.coverage_format)
                groups = snap.group_names
                self.merge(snap)
                notes.append(f"seeded focus groups from {self.seed_file}: {len(groups)}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"could not read coverage_seed_file: {exc}")
        if not groups:
            notes.append(
                "focus groups will be limited to 'all'/'hardest' until the first run "
                "(point blackbox.coverage_seed_file at an existing UCDB to pre-seed them)"
            )
        return BackendInfo(
            focus_groups=groups,
            knob_profiles=self.knobs.profile_names(),
            tests=self.tests,
            capabilities={"vsim": exe_ok, "vcover": bool(self.vcover)},
            notes=notes,
        )

    def run(self, action: Action, run_index: int, budget: Budget) -> EpisodeResult:
        mode = action.heads.get("seed_mode", "fresh")
        seed = self.seed_strategy.pick(mode, run_index)
        profile = action.heads.get("knob_profile", "none")
        plusargs = self.knobs.plusargs(profile)
        paths = self._run_paths(run_index)
        episode = self._episode_shell(action, run_index, seed, profile)
        t0 = time.time()

        write_run_do(
            paths["do"], run_time=self.run_time, ucdb=paths["ucdb"],
            user_do=str(self.bb.get("user_do", "")),
        )
        launch = SimLaunch.from_dict(self.launch.to_dict())
        launch.seed = seed
        launch.do_file = paths["do"]
        launch.plusargs = {**launch.plusargs, **plusargs}
        launch.log_file = paths["log"]
        launch.coverage = True
        if self.tests:
            launch.top = self.tests[run_index % len(self.tests)]
        runner = SimRunner(
            launch,
            log_path=paths["log"],
            ucdb_path=paths["ucdb"],
            timeout_s=self.timeout_s,
            abort_on_error=self.abort_on_error,
            stall_seconds=self.stall_seconds,
        )
        art: RunArtifacts = runner.run()
        episode.wall_s = art.wall_s
        episode.aborted = art.aborted or art.timed_out
        episode.error = art.error
        episode.artifacts = {"log": paths["log"], "ucdb": paths["ucdb"], "do": paths["do"]}
        episode.sim_time_ns = art.summary.sim_time_ns
        episode.cycles = art.summary.sim_time_ns / self.period_ns if self.period_ns else 0.0

        snap = self._read_coverage(paths, episode)
        if snap is not None and not snap.is_empty():
            snap.cycles = episode.cycles
            snap.sim_time_ns = episode.sim_time_ns
            snap.wall_s = episode.wall_s
            self.merge(snap)
            episode.total_bins = snap.total_bins
        elif not episode.error:
            episode.error = "no coverage database produced"
        self.seed_strategy.report(seed, art.summary.coverage_pct or 0.0)
        episode.wall_s = episode.wall_s or (time.time() - t0)
        return episode

    def _read_coverage(self, paths: Dict[str, str], episode: EpisodeResult) -> Optional[CoverageSnapshot]:
        ucdb = paths["ucdb"]
        if not os.path.exists(ucdb) or os.path.getsize(ucdb) == 0:
            return None
        try:
            head = open(ucdb, "rb").read(5)
            if head.startswith(b"<?xml") or b"<ucis" in open(ucdb, "rb").read(4096):
                return load_coverage(ucdb, fmt="ucis")
        except OSError:
            pass
        xml_out = paths["xml"]
        argv = [self.vcover, "report", "-xml", "-output", xml_out, ucdb]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout_s)
            if proc.returncode != 0:
                episode.artifacts["vcover_error"] = (proc.stderr or proc.stdout)[-800:]
                return None
            return load_coverage(xml_out, fmt="ucis")
        except (OSError, subprocess.SubprocessError) as exc:
            episode.artifacts["vcover_error"] = str(exc)
            return None


class MockBlackboxBackend(_BlackboxBase):
    """The same control flow against the synthetic run generator."""

    name = "blackbox-mock"

    def __init__(self, cfg: Any, log: Optional[Callable[[str], None]] = None):
        super().__init__(cfg, log)
        design = MockDesign(
            groups=int(self.bb.get("mock_groups", 4)),
            coverpoints=int(self.bb.get("mock_coverpoints", 3)),
            bins=int(self.bb.get("mock_bins", 8)),
            cycles_per_run=int(self.bb.get("mock_cycles", 2000)),
            period_ns=self.period_ns,
        )
        self.sim = MockRunSimulator(design)
        self.duration_factor = float(self.bb.get("mock_duration_factor", 1.0))

    def prepare(self) -> BackendInfo:
        design = self.sim.design
        groups = [f"grp_{g}" for g in range(design.groups)]
        self.log(
            f"mock design: {design.groups} groups x {design.coverpoints} coverpoints "
            f"x {design.bins} bins = {design.total_bins} bins"
        )
        return BackendInfo(
            focus_groups=groups,
            knob_profiles=self.knobs.profile_names(),
            capabilities={"simulator": "mock"},
            notes=["synthetic backend: numbers are illustrative, not simulator measurements"],
        )

    def run(self, action: Action, run_index: int, budget: Budget) -> EpisodeResult:
        t0 = time.time()
        mode = action.heads.get("seed_mode", "fresh")
        seed = self.seed_strategy.pick(mode, run_index)
        profile = action.heads.get("knob_profile", "none")
        quality = _profile_quality(self.knobs, profile)
        paths = self._run_paths(run_index)
        episode = self._episode_shell(action, run_index, seed, profile)
        hits = self.sim.coverage(seed, quality, self.duration_factor)
        self.sim.write(
            hits, paths["ucdb"], paths["log"], seed=seed, quality=quality,
            duration_factor=self.duration_factor, extra={"profile": profile},
        )
        snap = load_coverage(paths["ucdb"], fmt="ucis")
        watcher = TranscriptWatcher(paths["log"])
        watcher.poll()
        episode.sim_time_ns = watcher.summary.sim_time_ns
        episode.cycles = episode.sim_time_ns / self.period_ns if self.period_ns else 0.0
        episode.wall_s = time.time() - t0
        episode.artifacts = {"log": paths["log"], "ucdb": paths["ucdb"]}
        episode.total_bins = snap.total_bins
        snap.cycles = episode.cycles
        snap.sim_time_ns = episode.sim_time_ns
        self.merge(snap)
        self.seed_strategy.report(seed, sum(1 for v in hits.values() if v > 0))
        return episode
