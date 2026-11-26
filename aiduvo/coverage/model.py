"""The project-agnostic coverage model.

A snapshot is a three level tree -- group -> coverpoint -> bin -- which mirrors
the structure every IEEE-1801 / UCIS database exposes, without ever naming a
signal, class or covergroup from the user's project.  Identifiers are opaque
strings copied verbatim from the database the simulator wrote.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple


@dataclass
class Bin:
    """A single coverage bin (a.k.a. ``ucis:bin``)."""

    name: str
    hits: int = 0
    goal: int = 1
    weight: float = 1.0
    kind: str = "coverpoint"
    excluded: bool = False

    @property
    def covered(self) -> bool:
        return (not self.excluded) and self.hits >= max(1, self.goal)

    @property
    def path(self) -> str:
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "hits": self.hits,
            "goal": self.goal,
            "weight": self.weight,
            "kind": self.kind,
            "excluded": self.excluded,
        }


@dataclass
class Coverpoint:
    """A coverpoint: a named collection of bins."""

    name: str
    bins: Dict[str, Bin] = field(default_factory=dict)
    weight: float = 1.0
    kind: str = "coverpoint"

    def add(self, bin_: Bin) -> None:
        self.bins[bin_.name] = bin_

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "kind": self.kind,
            "bins": [b.to_dict() for b in self.bins.values()],
        }


@dataclass
class CoverGroup:
    """A covergroup (or an assertion / FSM group, depending on ``kind``)."""

    name: str
    coverpoints: Dict[str, Coverpoint] = field(default_factory=dict)
    weight: float = 1.0
    kind: str = "covergroup"

    def add(self, cp: Coverpoint) -> None:
        self.coverpoints[cp.name] = cp

    def iter_bins(self) -> Iterator[Tuple[str, Bin]]:
        for cp in self.coverpoints.values():
            for b in cp.bins.values():
                yield f"{self.name}.{cp.name}.{b.name}", b

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "kind": self.kind,
            "coverpoints": [cp.to_dict() for cp in self.coverpoints.values()],
        }


@dataclass
class CoverageSnapshot:
    """A point-in-time coverage state (post-run, or mid-run in runtime mode)."""

    groups: Dict[str, CoverGroup] = field(default_factory=dict)
    sim_time_ns: float = 0.0
    cycles: float = 0.0
    wall_s: float = 0.0
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ tree
    def group(self, name: str) -> CoverGroup:
        if name not in self.groups:
            self.groups[name] = CoverGroup(name=name)
        return self.groups[name]

    def coverpoint(self, group: str, cp: str) -> Coverpoint:
        g = self.group(group)
        if cp not in g.coverpoints:
            g.coverpoints[cp] = Coverpoint(name=cp)
        return g.coverpoints[cp]

    def add_bin(self, group: str, cp: str, bin_: Bin) -> None:
        self.coverpoint(group, cp).add(bin_)

    # -------------------------------------------------------------- flat view
    def flat(self) -> Dict[str, Bin]:
        out: Dict[str, Bin] = {}
        for g in self.groups.values():
            for path, b in g.iter_bins():
                out[path] = b
        return out

    def iter_bins(self) -> Iterable[Bin]:
        for g in self.groups.values():
            for _, b in g.iter_bins():
                yield b

    # ---------------------------------------------------------------- numbers
    @property
    def total_bins(self) -> int:
        return sum(1 for b in self.iter_bins() if not b.excluded)

    @property
    def hit_bins(self) -> int:
        return sum(1 for b in self.iter_bins() if b.covered)

    @property
    def group_names(self) -> List[str]:
        return sorted(self.groups.keys())

    def is_empty(self) -> bool:
        return self.total_bins == 0

    # ------------------------------------------------------------------ merge
    def merged_with(self, other: "CoverageSnapshot", how: str = "max") -> "CoverageSnapshot":
        """Union of two snapshots.

        ``how="max"`` (default) treats coverage as a set: a bin is covered if it
        was covered in any contributing run, and its hit count is the maximum
        observed.  ``how="sum"`` accumulates counts instead (matches
        ``vcover merge`` semantics for counters).
        """
        out = CoverageSnapshot(
            sim_time_ns=self.sim_time_ns + other.sim_time_ns,
            cycles=self.cycles + other.cycles,
            wall_s=self.wall_s + other.wall_s,
            source=f"merge({self.source},{other.source})",
            meta={**self.meta, **{k: v for k, v in other.meta.items() if k not in self.meta}},
        )
        for src in (self, other):
            for gname, g in src.groups.items():
                tg = out.group(gname)
                tg.weight = max(tg.weight, g.weight)
                for cpname, cp in g.coverpoints.items():
                    tcp = out.coverpoint(gname, cpname)
                    tcp.weight = max(tcp.weight, cp.weight)
                    for bname, b in cp.bins.items():
                        if bname not in tcp.bins:
                            tcp.bins[bname] = Bin(**b.to_dict())
                        else:
                            tgt = tcp.bins[bname]
                            tgt.hits = (
                                tgt.hits + b.hits if how == "sum" else max(tgt.hits, b.hits)
                            )
                            tgt.goal = max(tgt.goal, b.goal)
                            tgt.weight = max(tgt.weight, b.weight)
                            tgt.excluded = tgt.excluded or b.excluded
        return out

    def new_bins_since(self, prev: Optional["CoverageSnapshot"]) -> List[str]:
        """Bin paths that are covered now but were not covered in ``prev``."""
        if prev is None:
            return [p for p, b in self.flat().items() if b.covered]
        cur = self.flat()
        old = prev.flat()
        return [p for p, b in cur.items() if b.covered and not (p in old and old[p].covered)]

    # ------------------------------------------------------------ (de)serialise
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sim_time_ns": self.sim_time_ns,
            "cycles": self.cycles,
            "wall_s": self.wall_s,
            "source": self.source,
            "timestamp": self.timestamp,
            "meta": self.meta,
            "groups": [g.to_dict() for g in self.groups.values()],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CoverageSnapshot":
        snap = cls(
            sim_time_ns=float(d.get("sim_time_ns", 0.0)),
            cycles=float(d.get("cycles", 0.0)),
            wall_s=float(d.get("wall_s", 0.0)),
            source=str(d.get("source", "unknown")),
            timestamp=float(d.get("timestamp", time.time())),
            meta=dict(d.get("meta") or {}),
        )
        for gd in d.get("groups") or []:
            g = snap.group(gd.get("name", "?"))
            g.weight = float(gd.get("weight", 1.0))
            g.kind = gd.get("kind", "covergroup")
            for cpd in gd.get("coverpoints") or []:
                cp = snap.coverpoint(g.name, cpd.get("name", "?"))
                cp.weight = float(cpd.get("weight", 1.0))
                cp.kind = cpd.get("kind", "coverpoint")
                for bd in cpd.get("bins") or []:
                    cp.add(
                        Bin(
                            name=bd.get("name", "?"),
                            hits=int(bd.get("hits", 0)),
                            goal=int(bd.get("goal", 1)),
                            weight=float(bd.get("weight", 1.0)),
                            kind=bd.get("kind", "coverpoint"),
                            excluded=bool(bd.get("excluded", False)),
                        )
                    )
        return snap

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "CoverageSnapshot":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # ------------------------------------------------------------------ report
    def describe(self) -> str:
        lines = [
            f"coverage snapshot [{self.source}] "
            f"bins={self.hit_bins}/{self.total_bins} "
            f"groups={len(self.groups)} cycles={self.cycles:.0f}"
        ]
        for name in self.group_names:
            g = self.groups[name]
            total = sum(1 for _, b in g.iter_bins() if not b.excluded)
            hit = sum(1 for _, b in g.iter_bins() if b.covered)
            pct = 100.0 * hit / total if total else 0.0
            lines.append(f"  {name:<40s} {hit:>5d}/{total:<5d} {pct:6.2f}%")
        return "\n".join(lines)
