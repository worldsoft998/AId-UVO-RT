"""Hierarchical discovery and config generation.

The optimizer is project-agnostic because it *learns* the project at run time:

1. ask the simulator for the hierarchy under a root instance;
2. ask the coverage database for groups / coverpoints / bins;
3. classify the discovered signals into coarse roles (optional);
4. emit a campaign config whose action space is derived from what was found.

Nothing in this file mentions a signal, class, module or covergroup name.  The
output config is a *starting point* that the user can inspect and edit; every
value in it came from the simulator, not from the repository.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from aiduvo.blackbox.knobs import Knob, KnobProfile, KnobSpace
from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.coverage.ucis import load_coverage
from aiduvo.semantics.layer import SemanticLayer
from aiduvo.srie.session import SRIEConfig, SRIESession


@dataclass
class DiscoveryReport:
    """Everything discovery learned, in a serialisable form."""

    root: str = "/"
    depth: int = 2
    regions: List[str] = field(default_factory=list)
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    roles: List[Dict[str, Any]] = field(default_factory=list)
    coverage_groups: List[str] = field(default_factory=list)
    coverage_bins: int = 0
    coverage_source: str = ""
    capabilities: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root, "depth": self.depth, "regions": self.regions,
            "inputs": self.inputs, "outputs": self.outputs, "roles": self.roles,
            "coverage_groups": self.coverage_groups, "coverage_bins": self.coverage_bins,
            "coverage_source": self.coverage_source, "capabilities": self.capabilities,
            "notes": self.notes,
        }

    def summary(self) -> str:
        lines = [
            f"discovery report: root={self.root} depth={self.depth}",
            f"  regions  : {len(self.regions)}",
            f"  inputs   : {len(self.inputs)}",
            f"  outputs  : {len(self.outputs)}",
            f"  coverage : {self.coverage_bins} bins in {len(self.coverage_groups)} groups"
            + (f" ({self.coverage_source})" if self.coverage_source else ""),
        ]
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


class HierarchicalDiscovery:
    """Breadth-first discovery over a live session or a coverage database."""

    def __init__(self, depth: int = 2, root: str = "/", semantic: bool = True,
                 max_signals: int = 64):
        self.depth = depth
        self.root = root
        self.semantic = semantic
        self.max_signals = max_signals
        self.layer = SemanticLayer()

    # ------------------------------------------------------------------ live
    def from_session(self, session: SRIESession) -> DiscoveryReport:
        hier = session.hierarchy or session.discover()
        report = DiscoveryReport(
            root=hier.root, depth=hier.depth,
            regions=[n.path for n in hier.regions()],
            inputs=[n.to_dict() for n in hier.inputs()][: self.max_signals],
            outputs=[n.to_dict() for n in hier.outputs()][: self.max_signals],
            capabilities=session.capabilities,
        )
        if self.semantic:
            roles = self.layer.annotate(hier)
            report.roles = [r.to_dict() for r in roles][: self.max_signals * 2]
            report.notes.append(self.layer.summary(roles).replace("\n", " | "))
        snap = session.coverage("discover")
        report.coverage_groups = snap.group_names
        report.coverage_bins = snap.total_bins
        report.coverage_source = "live"
        if snap.is_empty():
            report.notes.append("no coverage reported: was the design compiled with coverage?")
        return report

    # ------------------------------------------------------------- from files
    def from_coverage(self, path: str, fmt: str = "auto") -> DiscoveryReport:
        snap: CoverageSnapshot = load_coverage(path, fmt=fmt)
        return DiscoveryReport(
            coverage_groups=snap.group_names,
            coverage_bins=snap.total_bins,
            coverage_source=os.path.basename(path),
        )

    # ---------------------------------------------------------------- config
    def build_config(
        self,
        report: DiscoveryReport,
        mode: str = "runtime",
        ai: bool = True,
        algorithm: str = "linucb",
        srie: Optional[Dict[str, Any]] = None,
        blackbox: Optional[Dict[str, Any]] = None,
        knobs: Optional[Dict[str, Any]] = None,
        budget: Optional[Dict[str, Any]] = None,
        outdir: str = "runs",
        seed: int = 1,
    ) -> Dict[str, Any]:
        """Assemble a campaign config from a discovery report."""
        knob_space = KnobSpace.from_dict(knobs or {})
        cfg: Dict[str, Any] = {
            "mode": mode,
            "ai": bool(ai),
            "algorithm": algorithm if ai else "none",
            "inner_algorithm": algorithm if ai else "none",
            "seed": seed,
            "outdir": outdir,
            "focus_limit": max(2, min(10, len(report.coverage_groups))),
            "budget": {
                "max_runs": 20,
                "target_closure": 0.95,
                "min_runs": 1,
                "plateau_runs": 0,
                "max_steps_per_run": 8,
                **(budget or {}),
            },
            "reward": {},
            "knobs": knob_space.to_dict(),
            "srie": {
                "transport": {"kind": "pipe"},
                "discover_root": report.root,
                "discover_depth": report.depth,
                "max_forced": 8,
                "quantum_cycles": 500,
                "period_ns": 10.0,
                "intra_steps": 8,
                **(srie or {}),
            },
            "blackbox": {
                "kind": "questa",
                "run_time": "1000 us",
                "period_ns": 10.0,
                "abort_on_error": True,
                **(blackbox or {}),
            },
            "notes": "generated by aiduvo discover from runtime introspection",
        }
        return cfg


def discover_campaign_config(
    out_path: str,
    transport: Optional[Dict[str, Any]] = None,
    launch: Optional[Dict[str, Any]] = None,
    coverage_file: str = "",
    mode: str = "runtime",
    algorithm: str = "linucb",
    depth: int = 2,
    root: str = "/",
    semantic: bool = True,
    knobs: Optional[Dict[str, Any]] = None,
    workdir: str = ".",
) -> Dict[str, Any]:
    """Discover from a live simulator (or a coverage file) and write a config."""
    disc = HierarchicalDiscovery(depth=depth, root=root, semantic=semantic)
    if coverage_file:
        report = disc.from_coverage(coverage_file)
        report.notes.append("hierarchy not discovered (coverage file only)")
    else:
        cfg = SRIEConfig.from_dict(
            {"transport": transport or {"kind": "mock"}, "launch": launch or {},
             "workdir": workdir, "discover_root": root, "discover_depth": depth}
        )
        with SRIESession(cfg, log=lambda m: None) as session:
            report = disc.from_session(session)
    config = disc.build_config(report, mode=mode, algorithm=algorithm, knobs=knobs)
    config["discovery"] = report.to_dict()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    return config


def knob_inventory_template(path: str) -> Dict[str, Any]:
    """Write an empty, documented knob inventory for the user to fill in.

    The framework cannot invent plusargs: they are declared inside the testbench,
    which it is not allowed to read.  What it can do is give the user a schema and
    turn whatever they provide into a profile space the RL agent can explore.
    """
    template = {
        "_comment": (
            "Fill in the plusargs / UVM config settings your testbench understands. "
            "AId-UVO-RT treats them as opaque knobs; it never inspects the source. "
            "Profiles are generated automatically from this inventory."
        ),
        "knobs": [
            {
                "name": "KNOB_NAME",
                "kind": "plusarg_enum",
                "values": ["0", "50", "100"],
                "description": "example: stimulus intensity in percent",
            },
            {
                "name": "ANOTHER_KNOB",
                "kind": "plusarg_int",
                "lo": 1,
                "hi": 1000,
                "step": 10,
                "description": "example: number of transactions",
            },
        ],
        "profiles": [],
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)
    return template
