import json
import os

import pytest

from aiduvo.blackbox.backend import MockBlackboxBackend, _profile_quality
from aiduvo.blackbox.knobs import Knob, KnobProfile, KnobSpace, SeedStrategy
from aiduvo.blackbox.logwatch import TranscriptWatcher, scan_text
from aiduvo.core.engine import CampaignConfig
from aiduvo.core.types import Action, Budget

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def test_transcript_scan_classifies_lines():
    summary = scan_text(open(os.path.join(FIXTURES, "transcript.log")).read())
    assert summary.counts.get("error") == 1
    assert summary.counts.get("warning") == 1
    assert summary.finished is True
    assert summary.sim_time_ns == pytest.approx(20000.0)
    assert summary.coverage_pct == pytest.approx(42.5)
    assert summary.markers and summary.markers[0]["seed"] == 1234


def test_transcript_watcher_is_incremental(tmp_path):
    path = tmp_path / "t.log"
    path.write_text("# first\n")
    w = TranscriptWatcher(str(path))
    assert len(w.poll()) == 0
    with open(path, "a") as fh:
        fh.write("# UVM_ERROR : boom\n")
    events = w.poll()
    assert any(e.kind == "error" for e in events)
    assert w.should_abort(abort_on_error=True)


def test_knob_to_plusarg_forms():
    k_int = Knob("NUM", kind="plusarg_int", lo=0, hi=10)
    assert k_int.to_plusarg("5") == "+NUM=5"
    k_flag = Knob("EN", kind="plusarg_flag")
    assert k_flag.to_plusarg("1") == "+EN"
    assert k_flag.to_plusarg("0") == ""
    k_uvm = Knob("env.agent::cnt", kind="uvm_config_int")
    assert k_uvm.to_plusarg("7").startswith("+uvm_set_config_int=")


def test_knobspace_profiles_and_plusargs():
    space = KnobSpace(knobs=[Knob("A", kind="plusarg_enum", values=["0", "1"])])
    names = space.profile_names()
    assert names[0] == "none"
    assert len(names) >= 2
    assert space.plusargs("none") == {}
    some = space.plusargs(names[1])
    assert "A" in some


def test_seed_strategy_modes():
    s = SeedStrategy(base_seed=100, rng=None)
    assert s.pick("sweep", 0) == 100
    assert s.pick("sweep", 3) == 103
    fresh = s.pick("fresh", 0)
    assert isinstance(fresh, int)
    s.report(5, 1.0)
    assert s.best_seed == 5
    assert s.pick("resume_best", 0) == 5
    mutated = s.pick("mutate_best", 0)
    assert mutated != 5


def make_cfg(tmp_path):
    return CampaignConfig.from_dict(
        {
            "mode": "blackbox",
            "ai": True,
            "algorithm": "linucb",
            "seed": 3,
            "outdir": str(tmp_path),
            "knobs": {
                "knobs": [{"name": "STIM", "kind": "plusarg_enum", "values": ["0", "100"]}],
                "profiles": [
                    {"name": "none", "values": {}},
                    {"name": "hot", "values": {"STIM": "100"}},
                ],
            },
            "blackbox": {"kind": "mock", "mock_cycles": 500},
            "budget": {"max_runs": 2, "target_closure": 0.99},
        }
    )


def test_mock_blackbox_backend_produces_coverage(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = MockBlackboxBackend(cfg)
    info = backend.prepare()
    assert info.focus_groups
    backend.bind_space(None)  # not used by this backend
    ep = backend.run(Action(heads={"seed_mode": "fresh", "knob_profile": "hot"}), 0,
                     Budget(max_runs=2))
    assert ep.total_bins == 96
    assert backend.cumulative is not None
    assert backend.cumulative.hit_bins > 0
    assert ep.cycles > 0
    assert os.path.exists(ep.artifacts["ucdb"])


def test_profile_quality_mapping():
    space = KnobSpace(knobs=[Knob("STIM", kind="plusarg_enum", values=["0", "100"])],
                      profiles=[KnobProfile("none", {}), KnobProfile("hot", {"STIM": "100"})])
    assert _profile_quality(space, "none") == 0.0
    assert _profile_quality(space, "hot") == pytest.approx(1.0)


def test_write_run_do_contains_save_and_quit(tmp_path):
    from aiduvo.blackbox.runner import write_run_do

    path = write_run_do(str(tmp_path / "run.do"), run_time="10us", ucdb=str(tmp_path / "c.ucdb"))
    text = open(path).read()
    assert "run 10us" in text
    assert "coverage save" in text
    assert "quit -f" in text
