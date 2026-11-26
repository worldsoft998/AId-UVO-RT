import json

import pytest

from aiduvo.coverage import metrics
from aiduvo.coverage.model import Bin, CoverageSnapshot
from aiduvo.coverage.store import CoverageStore


def make_snapshot(hits_a=1, hits_b=0):
    snap = CoverageSnapshot(source="test")
    snap.add_bin("g1", "cp1", Bin("a", hits=hits_a))
    snap.add_bin("g1", "cp1", Bin("b", hits=hits_b))
    snap.add_bin("g2", "cp2", Bin("c", hits=0))
    return snap


def test_counts_and_closure():
    snap = make_snapshot()
    assert snap.total_bins == 3
    assert snap.hit_bins == 1
    assert metrics.closure(snap) == pytest.approx(1 / 3)


def test_merge_is_a_union():
    a = make_snapshot(hits_a=1, hits_b=0)
    b = make_snapshot(hits_a=0, hits_b=2)
    merged = a.merged_with(b)
    # bin c is never hit, so the union covers 2 of 3
    assert metrics.closure(merged) == pytest.approx(2 / 3)
    assert merged.flat()["g1.cp1.a"].hits == 1
    assert merged.flat()["g1.cp1.b"].hits == 2


def test_new_bins_since():
    a = make_snapshot(hits_a=1, hits_b=0)
    b = make_snapshot(hits_a=1, hits_b=1)
    new = b.new_bins_since(a)
    assert "g1.cp1.b" in new
    assert "g1.cp1.a" not in new


def test_hardness_weights_favour_uncovered():
    snap = make_snapshot(hits_a=50, hits_b=0)
    w = metrics.hardness_weights(snap)
    assert w["g1.cp1.b"] > w["g1.cp1.a"]


def test_summary_keys():
    summary = metrics.summarize(make_snapshot())
    for key in ("closure", "weighted_closure", "entropy", "zero_bin_ratio", "groups"):
        assert key in summary


def test_snapshot_roundtrip(tmp_path):
    snap = make_snapshot()
    path = str(tmp_path / "snap.json")
    snap.save(path)
    loaded = CoverageSnapshot.load(path)
    assert loaded.total_bins == snap.total_bins
    assert loaded.flat().keys() == snap.flat().keys()


def test_store_merges_runs(tmp_path):
    store = CoverageStore(str(tmp_path / "history.sqlite"))
    store.begin_campaign("c1", "baseline", "none", False, 0.0)
    store.record_snapshot("c1", 0, make_snapshot(hits_a=1, hits_b=0), 0.33, 0.3)
    store.record_snapshot("c1", 1, make_snapshot(hits_a=0, hits_b=1), 0.33, 0.3)
    merged = store.merged_snapshot("c1")
    assert merged is not None
    assert merged.hit_bins == 2
    history = store.history("c1")
    assert len(history) == 2
    store.close()


def test_time_to_closure_interpolates():
    curve = [
        {"cum_cycles": 0, "closure": 0.0},
        {"cum_cycles": 100, "closure": 0.5},
        {"cum_cycles": 200, "closure": 1.0},
    ]
    assert metrics.time_to_closure(curve, 0.75, "cum_cycles") == pytest.approx(150.0)
    assert metrics.time_to_closure(curve, 1.1, "cum_cycles") is None
