import numpy as np
import pytest

from aiduvo.coverage.model import Bin, CoverageSnapshot
from aiduvo.core.reward import RewardConfig, RewardFunction
from aiduvo.core.space import (
    FEATURE_NAMES,
    FactoredActionSpace,
    Head,
    StateEncoder,
    build_action_space,
)
from aiduvo.core.types import Action, Budget, Observation


def test_encode_decode_roundtrip():
    space = FactoredActionSpace(heads=[Head("a", ("x", "y")), Head("b", ("p", "q", "r"))])
    assert space.size() == 6
    for idx in range(6):
        heads = space.encode(idx)
        assert space.decode(heads) == idx


def test_action_labels():
    space = build_action_space(focus_groups=["g1", "g2"], knob_profiles=["none", "agg"],
                               runtime=True)
    assert "seed_mode" in space.names
    assert "force_bias" in space.names
    action = space.action(0)
    assert isinstance(action, Action)
    assert "=" in action.label()
    assert "g1" in space.describe()
    assert "force_bias" in space.describe()


def test_runtime_space_adds_heads():
    base = build_action_space()
    runtime = build_action_space(runtime=True)
    assert set(runtime.names) - set(base.names) == {"force_bias", "quantum"}


def test_inner_space_has_only_intra_run_heads():
    inner = build_action_space(runtime=True, include_seed=False, include_focus=False,
                               include_knobs=False)
    assert inner.names == ["force_bias", "quantum"]
    assert inner.size() == 6 * 3


def test_encoder_shape_and_range():
    snap = CoverageSnapshot()
    for i in range(8):
        snap.add_bin("g", "cp", Bin(f"b{i}", hits=i % 3))
    enc = StateEncoder()
    vec = enc.encode(Observation(snapshot=snap), None, None)
    assert vec.shape == (len(FEATURE_NAMES),)
    assert np.all(np.isfinite(vec))
    assert np.all(np.abs(vec) <= 1.0001)


def test_encoder_handles_missing_snapshot():
    vec = StateEncoder().encode(Observation(), None, None)
    assert vec.shape == (len(FEATURE_NAMES),)
    assert vec[-1] == 1.0


def test_reward_rewards_new_coverage():
    fn = RewardFunction(RewardConfig(), target_closure=0.9)
    before = CoverageSnapshot()
    before.add_bin("g", "cp", Bin("a", hits=1))
    before.add_bin("g", "cp", Bin("b", hits=0))
    after = CoverageSnapshot()
    after.add_bin("g", "cp", Bin("a", hits=1))
    after.add_bin("g", "cp", Bin("b", hits=1))
    r = fn(before, after, dt_wall_s=1.0, dt_cycles=100)
    assert r.new_bins > 0
    assert r.hard_gain > 0
    assert r.total > 0


def test_reward_penalises_plateau():
    fn = RewardFunction(RewardConfig(), target_closure=0.0)
    snap = CoverageSnapshot()
    snap.add_bin("g", "cp", Bin("a", hits=1))
    flat = fn(snap, snap, dt_wall_s=1.0, dt_cycles=100)
    assert flat.plateau_cost < 0
    assert flat.total < 0


def test_goal_bonus_is_paid_once():
    fn = RewardFunction(RewardConfig(goal_bonus=5.0), target_closure=0.5)
    snap = CoverageSnapshot()
    snap.add_bin("g", "cp", Bin("a", hits=1))
    first = fn(None, snap, 1.0, 10)
    second = fn(snap, snap, 1.0, 10)
    assert first.goal_bonus == 5.0
    assert second.goal_bonus == 0.0


def test_budget_roundtrip():
    b = Budget.from_dict({"max_runs": 3, "unknown_key": 1})
    assert b.max_runs == 3
    assert b.to_dict()["max_runs"] == 3
