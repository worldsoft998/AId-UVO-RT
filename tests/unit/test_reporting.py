import json
import os

import pytest

from aiduvo.core.types import CampaignResult, Mode
from aiduvo.reporting import build_report, compare, markdown_table, verdict
from aiduvo.reporting.compare import _closure_at


def make_result(mode, algorithm, ai, points, wall=10.0, groups=None):
    r = CampaignResult(mode=Mode(mode), algorithm=algorithm, ai_enabled=ai)
    r.curve = [
        {"run": i + 1, "closure": c, "weighted_closure": c, "cum_cycles": cyc,
         "cum_sim_time_ns": cyc * 10, "cum_wall_s": wall * (i + 1) / len(points), "reward": 0.0}
        for i, (cyc, c) in enumerate(points)
    ]
    r.final_closure = points[-1][1]
    r.total_cycles = points[-1][0]
    r.total_wall_s = wall
    r.runs_used = len(points)
    r.stopped_reason = "max_runs"
    r.metadata["group_closures"] = groups or {"grp_0": 0.8, "grp_1": 0.4}
    r.metadata["backend"] = "mock"
    return r


def campaigns():
    return {
        "baseline": make_result("baseline", "none", False,
                                [(1000, 0.3), (2000, 0.5), (3000, 0.6), (4000, 0.65)]),
        "blackbox": make_result("blackbox", "linucb", True,
                                [(1000, 0.45), (2000, 0.7), (3000, 0.85), (4000, 0.9)]),
        "runtime": make_result("runtime", "ppo", True,
                               [(1000, 0.55), (2000, 0.85), (3000, 0.95), (4000, 0.97)]),
    }


def test_compare_ranks_and_computes_speedups():
    cmp_ = compare(campaigns(), target=0.9)
    assert [r.key for r in cmp_.rows] == ["baseline", "blackbox", "runtime"]
    rt = cmp_.row("runtime")
    base = cmp_.row("baseline")
    assert base.ttc_cycles is None            # never reaches 90%
    assert rt.ttc_cycles is not None
    assert rt.closure_gain > 0
    assert rt.closure_at_baseline_budget is not None


def test_markdown_table_and_verdict():
    cmp_ = compare(campaigns(), target=0.9)
    table = markdown_table(cmp_)
    assert table.count("|") > 10
    assert "runtime" in table
    text = verdict(cmp_)
    assert "Baseline" in text


def test_closure_at_interpolates():
    curve = [{"cum_cycles": 0, "closure": 0.0}, {"cum_cycles": 100, "closure": 1.0}]
    assert _closure_at(curve, 50) == pytest.approx(0.5)
    assert _closure_at(curve, 500) == pytest.approx(1.0)


def test_build_report_writes_everything(tmp_path):
    out = str(tmp_path / "results")
    md = build_report(compare(campaigns(), target=0.9), out, title="unit test report")
    for name in ("report.md", "report.html", "closure_curve.svg", "final_closure.svg",
                 "comparison.json", "speedup.svg"):
        assert os.path.exists(os.path.join(out, name)), name
    assert "# unit test report" in md
    assert "<svg" in open(os.path.join(out, "closure_curve.svg")).read()
    html = open(os.path.join(out, "report.html")).read()
    assert "<table>" in html and "<svg" in html
    data = json.load(open(os.path.join(out, "comparison.json")))
    assert data["baseline_key"] == "baseline"
