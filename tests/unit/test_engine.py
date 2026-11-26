import os

import pytest

from aiduvo.core.engine import Campaign, CampaignConfig
from aiduvo.core.types import Mode


def mock_cfg(tmp_path, mode, ai, algorithm, runs=4, steps=3):
    return CampaignConfig.from_dict(
        {
            "mode": mode,
            "ai": ai,
            "algorithm": algorithm,
            "inner_algorithm": "ppo" if mode == "runtime" else "",
            "seed": 11,
            "outdir": str(tmp_path),
            "name": f"c_{mode}",
            "knobs": {
                "knobs": [{"name": "STIM", "kind": "plusarg_enum", "values": ["0", "50", "100"]}],
                "profiles": [
                    {"name": "none", "values": {}},
                    {"name": "mid", "values": {"STIM": "50"}},
                    {"name": "hot", "values": {"STIM": "100"}},
                ],
            },
            "budget": {"max_runs": runs, "target_closure": 0.999, "max_steps_per_run": steps,
                       "min_runs": 1},
            "blackbox": {"kind": "mock", "mock_cycles": 400},
            "srie": {"transport": {"kind": "mock"}, "discover_depth": 4,
                     "quantum_cycles": 100, "intra_steps": steps, "max_forced": 4},
        }
    )


@pytest.mark.slow
def test_blackbox_campaign_produces_a_comparable_result(tmp_path):
    result = Campaign(mock_cfg(tmp_path, "blackbox", True, "linucb"), log=lambda m: None).run()
    assert result.runs_used >= 1
    assert result.final_closure > 0
    assert len(result.curve) == result.runs_used
    assert result.stopped_reason
    outdir = result.metadata["outdir"]
    assert os.path.exists(os.path.join(outdir, "campaign_result.json"))
    assert os.path.exists(os.path.join(outdir, "history.sqlite"))
    assert os.path.exists(os.path.join(outdir, "campaign_config.json"))
    assert os.path.exists(os.path.join(outdir, "policy.npz"))


@pytest.mark.slow
def test_baseline_campaign_uses_no_ai(tmp_path):
    result = Campaign(mock_cfg(tmp_path, "baseline", False, "none", runs=3), log=lambda m: None).run()
    assert result.ai_enabled is False
    assert result.algorithm == "none"
    assert result.runs_used == 3
    assert all(ep.action.heads.get("seed_mode") == "sweep" for ep in result.episodes)
    assert not os.path.exists(os.path.join(result.metadata["outdir"], "policy.npz"))


@pytest.mark.slow
def test_runtime_campaign_steers_inside_the_run(tmp_path):
    cfg = mock_cfg(tmp_path, "runtime", True, "linucb", runs=2, steps=3)
    result = Campaign(cfg, log=lambda m: None).run()
    assert result.mode == Mode.RUNTIME
    assert result.runs_used >= 1
    ep = result.episodes[0]
    assert ep.steps >= 1
    assert ep.intra_actions, "runtime mode must record intra-run decisions"
    assert all("force_bias" in a["action"] for a in ep.intra_actions)
    assert result.final_closure > 0


@pytest.mark.slow
def test_campaign_is_resumable_from_its_store(tmp_path):
    from aiduvo.coverage.store import CoverageStore

    result = Campaign(mock_cfg(tmp_path, "blackbox", True, "thompson", runs=3),
                      log=lambda m: None).run()
    outdir = result.metadata["outdir"]
    with CoverageStore(os.path.join(outdir, "history.sqlite")) as store:
        history = store.history(result.campaign_id)
        assert len(history) == result.runs_used
        merged = store.merged_snapshot(result.campaign_id)
        assert merged is not None and merged.total_bins == 96
        assert store.hardest_bins(result.campaign_id, 5)
