"""Three-way comparison: baseline vs blackbox vs runtime.

The comparison is deliberately blunt: how much coverage, how fast, at what cost.
Every number is derived from the same fields in :class:`CampaignResult`, so the
three campaigns are always measured the same way.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aiduvo.coverage import metrics as covmetrics
from aiduvo.core.types import CampaignResult, Mode

DISCLAIMER = (
    "Numbers produced by the synthetic (mock) backend are illustrative only: they "
    "demonstrate that the pipeline learns and that the three modes are measured "
    "identically. They are not simulator measurements and must not be quoted as "
    "coverage-closure speedups for any real design."
)


@dataclass
class Row:
    key: str
    label: str
    mode: str = "baseline"
    algorithm: str = "none"
    ai: bool = False
    runs: int = 0
    final_closure: float = 0.0
    final_wclosure: float = 0.0
    total_cycles: float = 0.0
    total_sim_ns: float = 0.0
    total_wall_s: float = 0.0
    ttc_cycles: Optional[float] = None
    ttc_wall: Optional[float] = None
    auc: float = 0.0
    closure_at_baseline_budget: Optional[float] = None
    speedup_cycles: Optional[float] = None
    speedup_wall: Optional[float] = None
    closure_gain: float = 0.0
    stopped_reason: str = ""
    curve_cycles: List[Tuple[float, float]] = field(default_factory=list)
    curve_wall: List[Tuple[float, float]] = field(default_factory=list)
    group_closures: Dict[str, float] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "key": self.key, "label": self.label, "mode": self.mode,
            "algorithm": self.algorithm, "ai": self.ai, "runs": self.runs,
            "final_closure": self.final_closure, "final_wclosure": self.final_wclosure,
            "total_cycles": self.total_cycles, "total_sim_ns": self.total_sim_ns,
            "total_wall_s": self.total_wall_s, "ttc_cycles": self.ttc_cycles,
            "ttc_wall": self.ttc_wall, "auc": self.auc,
            "closure_at_baseline_budget": self.closure_at_baseline_budget,
            "speedup_cycles": self.speedup_cycles, "speedup_wall": self.speedup_wall,
            "closure_gain": self.closure_gain, "stopped_reason": self.stopped_reason,
            "group_closures": self.group_closures, "error": self.error,
        }
        return d


@dataclass
class Comparison:
    rows: List[Row] = field(default_factory=list)
    target: float = 0.9
    baseline_key: str = ""
    generated: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    notes: List[str] = field(default_factory=list)

    def row(self, key: str) -> Optional[Row]:
        for r in self.rows:
            if r.key == key:
                return r
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated": self.generated, "target": self.target,
            "baseline_key": self.baseline_key,
            "rows": [r.to_dict() for r in self.rows], "notes": self.notes,
        }

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        return path


def load_campaign(path: str) -> CampaignResult:
    """Load a campaign result from a file or a campaign directory."""
    if os.path.isdir(path):
        candidate = os.path.join(path, "campaign_result.json")
        if not os.path.exists(candidate):
            raise FileNotFoundError(f"no campaign_result.json in {path}")
        path = candidate
    return CampaignResult.load(path)


def _closure_at(curve: Sequence[Dict[str, float]], x: float, x_key: str = "cum_cycles") -> Optional[float]:
    if not curve:
        return None
    prev = (0.0, float(curve[0].get("closure", 0.0)))
    for point in curve:
        px = float(point.get(x_key, 0.0))
        py = float(point.get("closure", 0.0))
        if px >= x:
            if px <= prev[0]:
                return py
            frac = (x - prev[0]) / (px - prev[0])
            return prev[1] + frac * (py - prev[1])
        prev = (px, py)
    return float(curve[-1].get("closure", 0.0))


def make_row(key: str, label: str, campaign: CampaignResult, target: float) -> Row:
    row = Row(
        key=key,
        label=label,
        mode=campaign.mode.value,
        algorithm=campaign.algorithm,
        ai=campaign.ai_enabled,
        runs=campaign.runs_used or len(campaign.episodes),
        final_closure=campaign.final_closure,
        final_wclosure=float(campaign.metadata.get("final_summary", {}).get("weighted_closure", 0.0)),
        total_cycles=campaign.total_cycles,
        total_sim_ns=campaign.total_sim_time_ns,
        total_wall_s=campaign.total_wall_s,
        stopped_reason=campaign.stopped_reason,
        error=campaign.error,
    )
    curve = campaign.curve or []
    row.curve_cycles = [(float(p.get("cum_cycles", 0.0)), float(p.get("closure", 0.0))) for p in curve]
    row.curve_wall = [(float(p.get("cum_wall_s", 0.0)), float(p.get("closure", 0.0))) for p in curve]
    row.ttc_cycles = covmetrics.time_to_closure(curve, target, "cum_cycles")
    row.ttc_wall = covmetrics.time_to_closure(curve, target, "cum_wall_s")
    row.auc = covmetrics.area_under_curve(curve, "cum_cycles")
    row.group_closures = dict(campaign.metadata.get("group_closures") or {})
    return row


def compare(
    campaigns: Dict[str, CampaignResult],
    labels: Optional[Dict[str, str]] = None,
    target: float = 0.9,
    baseline_key: Optional[str] = None,
) -> Comparison:
    """Build a comparison from ``{key: CampaignResult}``."""
    labels = labels or {}
    cmp_ = Comparison(target=target)
    for key, campaign in campaigns.items():
        cmp_.rows.append(make_row(key, labels.get(key, key), campaign, target))
    if baseline_key is None:
        for r in cmp_.rows:
            if r.mode == Mode.BASELINE.value:
                baseline_key = r.key
                break
        baseline_key = baseline_key or cmp_.rows[0].key if cmp_.rows else ""
    cmp_.baseline_key = baseline_key or ""
    base = cmp_.row(cmp_.baseline_key)
    if base is not None:
        for r in cmp_.rows:
            r.closure_gain = r.final_closure - base.final_closure
            if base.total_cycles > 0:
                r.closure_at_baseline_budget = _closure_at(
                    [{"cum_cycles": x, "closure": y} for x, y in r.curve_cycles], base.total_cycles
                )
            if r.ttc_cycles and base.ttc_cycles:
                r.speedup_cycles = base.ttc_cycles / r.ttc_cycles if r.ttc_cycles > 0 else None
            if r.ttc_wall and base.ttc_wall:
                r.speedup_wall = base.ttc_wall / r.ttc_wall if r.ttc_wall > 0 else None
    cmp_.notes.append(f"target closure for time-to-closure: {target * 100:.0f}%")
    cmp_.notes.append(f"baseline for speedups: {cmp_.baseline_key}")
    if any("mock" in (r.mode + r.key) for r in cmp_.rows) or any(
        "mock" in str(c.metadata.get("backend", "")) for c in campaigns.values()
    ):
        cmp_.notes.append(DISCLAIMER)
    return cmp_


def markdown_table(cmp_: Comparison) -> str:
    """Compact markdown table of the headline numbers."""
    header = (
        "| Campaign | Mode | AI | Runs | Final closure | Closure @ baseline budget | "
        "Cycles to target | Speedup (cycles) | Sim time (ns) | Wall (s) |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in cmp_.rows:
        ttc = f"{r.ttc_cycles:,.0f}" if r.ttc_cycles is not None else "not reached"
        sp = f"{r.speedup_cycles:.2f}x" if r.speedup_cycles else "-"
        cab = f"{r.closure_at_baseline_budget * 100:.2f}%" if r.closure_at_baseline_budget is not None else "-"
        lines.append(
            f"| {r.label} | {r.mode} | {'yes' if r.ai else 'no'} | {r.runs} | "
            f"{r.final_closure * 100:.2f}% | {cab} | {ttc} | {sp} | "
            f"{r.total_sim_ns:,.0f} | {r.total_wall_s:,.1f} |"
        )
    return "\n".join(lines)


def verdict(cmp_: Comparison) -> str:
    """One paragraph a human can read without the table."""
    base = cmp_.row(cmp_.baseline_key)
    if base is None or not cmp_.rows:
        return "No campaigns to compare."
    best = max(cmp_.rows, key=lambda r: r.final_closure)
    parts = [
        f"Baseline reached {base.final_closure * 100:.2f}% closure in {base.runs} runs "
        f"({base.total_cycles:,.0f} cycles)."
    ]
    if best.key != base.key:
        parts.append(
            f"{best.label} reached {best.final_closure * 100:.2f}% "
            f"({(best.final_closure - base.final_closure) * 100:+.2f} points) "
            f"in {best.runs} runs."
        )
        if best.speedup_cycles:
            parts.append(
                f"It hit the {cmp_.target * 100:.0f}% mark {best.speedup_cycles:.2f}x sooner "
                f"in simulated cycles."
            )
        if best.closure_at_baseline_budget is not None:
            parts.append(
                f"Given the baseline's total cycle budget it would have reached "
                f"{best.closure_at_baseline_budget * 100:.2f}%."
            )
    return " ".join(parts)
