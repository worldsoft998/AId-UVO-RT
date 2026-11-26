"""Synthetic run generator for the blackbox path.

Produces exactly the artifacts a real run produces -- a transcript and a UCIS
XML coverage database -- so the importer, the log watcher, the early-abort logic,
the reward and the reporting are all exercised end to end on a machine without a
simulator licence.

The synthetic design has a realistic shape for the purpose of the experiment:

* most bins are easy and any seed finds them;
* a few bins are corners that need a *stimulus profile* (a knob setting) to have
  any chance at all, which is exactly the structure a knob-selecting optimizer
  can exploit;
* different seeds explore different easy bins, so seed choice matters too.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

CORNERS_PER_CP = 2


@dataclass
class MockDesign:
    groups: int = 4
    coverpoints: int = 3
    bins: int = 8
    cycles_per_run: int = 2000
    period_ns: float = 10.0

    @property
    def total_bins(self) -> int:
        return self.groups * self.coverpoints * self.bins

    def bin_ids(self) -> List[str]:
        out = []
        for g in range(self.groups):
            for c in range(self.coverpoints):
                for b in range(self.bins):
                    out.append(f"grp_{g}|cp_{c}|b{b}")
        return out

    def is_corner(self, bin_id: str) -> bool:
        idx = int(bin_id.rsplit("b", 1)[1])
        return idx >= self.bins - CORNERS_PER_CP


class MockRunSimulator:
    """Deterministic fake run: (seed, quality) -> coverage."""

    def __init__(self, design: Optional[MockDesign] = None):
        self.design = design or MockDesign()

    def coverage(self, seed: int, quality: float, duration_factor: float = 1.0) -> Dict[str, int]:
        """Return ``{bin_id: hits}`` for one run.

        ``quality`` in [0, 1] models how aggressive the chosen knob profile is:
        easy bins get easier, and corner bins become reachable above ~0.5.
        """
        rng = random.Random(int(seed) * 7919 + int(quality * 1000))
        hits: Dict[str, int] = {}
        for bin_id in self.design.bin_ids():
            base = rng.random()
            if self.design.is_corner(bin_id):
                reach = max(0.0, quality - 0.45) * 1.4
                p = reach * duration_factor
            else:
                p = (0.30 + 0.45 * base) * (1.0 + 0.8 * quality) * duration_factor
            count = 0
            if rng.random() < min(1.0, p):
                count = 1 + int(rng.random() * 5 * max(0.2, duration_factor))
            hits[bin_id] = count
        return hits

    def write(self, hits: Dict[str, int], ucdb_path: str, log_path: str,
              seed: int, quality: float, duration_factor: float = 1.0,
              extra: Optional[Dict[str, Any]] = None) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(ucdb_path)) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
        with open(ucdb_path, "w", encoding="utf-8") as fh:
            fh.write(self.ucdb_xml(hits))
        cycles = int(self.design.cycles_per_run * duration_factor)
        total = len(hits)
        covered = sum(1 for v in hits.values() if v > 0)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("# AId-UVO-RT mock transcript\n")
            fh.write(f"# vsim -sv_seed {seed}\n")
            fh.write(f"# ** Note: seed={seed} quality={quality:.2f}\n")
            for kind, count in (("UVM_INFO", covered), ("UVM_WARNING", 0)):
                fh.write(f"# {kind} : {count}\n")
            fh.write(f"# Total coverage: {100.0 * covered / total:.2f}%\n")
            fh.write(f"# sim time = {cycles * self.design.period_ns:.0f} ns\n")
            fh.write("# ** Note: $finish\n")
            payload = {
                "seed": seed, "quality": quality, "cycles": cycles,
                "duration_factor": duration_factor, **(extra or {}),
            }
            fh.write(f"# AIDUVRUN {json.dumps(payload)}\n")

    def ucdb_xml(self, hits: Dict[str, int]) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ucis:coveragedata xmlns:ucis="http://www.accellera.org/XMLSchema/UCIS" '
            'writtenBy="aiduvo-mock">',
        ]
        tree: Dict[str, Dict[str, List[int]]] = {}
        for bin_id, count in hits.items():
            g, c, b = bin_id.split("|")
            tree.setdefault(g, {}).setdefault(c, []).append((int(b[1:]), count))  # type: ignore[arg-type]
        for g in sorted(tree):
            lines.append(f'  <ucis:covergroup name="{g}" weight="1">')
            for c in sorted(tree[g]):
                lines.append(f'    <ucis:coverpoint name="{c}" weight="1">')
                for idx, count in sorted(tree[g][c]):
                    lines.append(
                        f'      <ucis:bin name="b{idx}" weight="1"><ucis:count>{count}</ucis:count></ucis:bin>'
                    )
                lines.append("    </ucis:coverpoint>")
            lines.append("  </ucis:covergroup>")
        lines.append("</ucis:coveragedata>")
        return "\n".join(lines) + "\n"
