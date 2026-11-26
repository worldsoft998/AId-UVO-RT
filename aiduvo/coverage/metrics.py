"""Coverage metrics used for reward shaping, state encoding and reporting.

Every metric is derived purely from the coverage tree, so it applies unchanged
to any design, any HDL and any verification methodology.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from aiduvo.coverage.model import CoverageSnapshot


def closure(snap: CoverageSnapshot) -> float:
    """Fraction of bins covered (unweighted)."""
    total = snap.total_bins
    return snap.hit_bins / total if total else 0.0


def hardness_weights(snap: CoverageSnapshot, alpha: float = 1.0) -> Dict[str, float]:
    """Per-bin weights that emphasise hard-to-hit corners.

    A bin that has never been hit is the hardest possible target, so it gets the
    largest weight; a bin already hit hundreds of times is nearly saturated.
    Weights are normalised to mean 1.0 so reward magnitudes stay comparable
    between designs with different bin counts.
    """
    flat = snap.flat()
    if not flat:
        return {}
    raw = {p: 1.0 / ((1.0 + max(0, b.hits)) ** alpha) for p, b in flat.items() if not b.excluded}
    if not raw:
        return {}
    mean = sum(raw.values()) / len(raw)
    if mean <= 0:
        return raw
    return {p: w / mean for p, w in raw.items()}


def weighted_closure(snap: CoverageSnapshot, weights: Optional[Dict[str, float]] = None) -> float:
    """Coverage fraction where hard bins count more than easy ones."""
    if weights is None:
        weights = hardness_weights(snap)
    total = 0.0
    hit = 0.0
    for path, b in snap.flat().items():
        if b.excluded:
            continue
        w = weights.get(path, 1.0)
        total += w
        if b.covered:
            hit += w
    return hit / total if total else 0.0


def group_closures(snap: CoverageSnapshot) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for name, g in snap.groups.items():
        total = hit = 0
        for _, b in g.iter_bins():
            if b.excluded:
                continue
            total += 1
            hit += 1 if b.covered else 0
        out[name] = hit / total if total else 0.0
    return out


def entropy(snap: CoverageSnapshot) -> float:
    """Normalised Shannon entropy of the hit distribution in [0, 1].

    High entropy means hits are spread evenly (broad exploration); low entropy
    means a few bins absorb all the activity (the stimulus is stuck).
    """
    counts = [b.hits for b in snap.iter_bins() if not b.excluded and b.hits > 0]
    if len(counts) < 2:
        return 0.0
    total = float(sum(counts))
    probs = [c / total for c in counts]
    h = -sum(p * math.log(p) for p in probs if p > 0)
    return h / math.log(len(counts))


def novelty(prev: Optional[CoverageSnapshot], cur: CoverageSnapshot) -> float:
    """Fraction of the bin space that became covered since ``prev``."""
    total = cur.total_bins
    if total == 0:
        return 0.0
    return len(cur.new_bins_since(prev)) / total


def hardest_bins(snap: CoverageSnapshot, k: int = 10) -> List[Tuple[str, int]]:
    """Uncovered (then least-hit) bins, most urgent first."""
    items = [(p, b.hits) for p, b in snap.flat().items() if not b.excluded]
    items.sort(key=lambda t: (t[1], t[0]))
    return items[:k]


def zero_bin_ratio(snap: CoverageSnapshot) -> float:
    total = 0
    zero = 0
    for b in snap.iter_bins():
        if b.excluded:
            continue
        total += 1
        if b.hits == 0:
            zero += 1
    return zero / total if total else 0.0


def summarize(snap: CoverageSnapshot) -> Dict[str, float]:
    """One flat dict of every scalar metric, used by reports and state vectors."""
    gc = group_closures(snap)
    vals = list(gc.values()) or [0.0]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    flat_hits = [b.hits for b in snap.iter_bins() if not b.excluded]
    return {
        "closure": closure(snap),
        "weighted_closure": weighted_closure(snap),
        "total_bins": float(snap.total_bins),
        "hit_bins": float(snap.hit_bins),
        "zero_bin_ratio": zero_bin_ratio(snap),
        "entropy": entropy(snap),
        "groups": float(len(snap.groups)),
        "group_closure_min": min(vals),
        "group_closure_mean": mean,
        "group_closure_max": max(vals),
        "group_closure_std": math.sqrt(var),
        "mean_hits": (sum(flat_hits) / len(flat_hits)) if flat_hits else 0.0,
    }


def time_to_closure(curve: Sequence[Dict[str, float]], target: float, x_key: str = "cum_cycles") -> Optional[float]:
    """Linear interpolation of the effort needed to first reach ``target``.

    ``curve`` is a list of dicts as produced by the engine, each containing a
    closure value under ``"closure"`` and a cumulative effort under ``x_key``.
    Returns ``None`` when the target is never reached.
    """
    prev_x = 0.0
    prev_y = 0.0
    for point in curve:
        x = float(point.get(x_key, 0.0))
        y = float(point.get("closure", 0.0))
        if y >= target:
            if y <= prev_y:
                return x
            frac = (target - prev_y) / (y - prev_y)
            return prev_x + frac * (x - prev_x)
        prev_x, prev_y = x, y
    return None


def area_under_curve(curve: Sequence[Dict[str, float]], x_key: str = "cum_cycles") -> float:
    """Trapezoidal area under the closure curve, normalised by the x range.

    A higher value means coverage was reached earlier (better efficiency).
    """
    if len(curve) < 2:
        return 0.0
    xs = [float(p.get(x_key, 0.0)) for p in curve]
    ys = [float(p.get("closure", 0.0)) for p in curve]
    area = 0.0
    for i in range(1, len(xs)):
        area += 0.5 * (ys[i] + ys[i - 1]) * (xs[i] - xs[i - 1])
    span = xs[-1] - xs[0]
    return area / span if span > 0 else 0.0
