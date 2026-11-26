"""SRIESession: one live simulator, introspected and steered.

A session owns the transport, the introspector (read), the reflection controller
(write) and the event bus (async).  The runtime optimizer builds one session per
simulation run; the ``aiduvo srie`` sub-commands use it interactively.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.srie import tcl
from aiduvo.srie.introspection import Hierarchy, Introspector
from aiduvo.srie.launcher import SimLaunch
from aiduvo.srie.protocol import CommandError, SRIEError, TransportError
from aiduvo.srie.reflection import DEFAULT_DENY_PATTERNS, ReflectionController
from aiduvo.srie.transport import Transport, make_transport
from aiduvo.srie.triggers import EventBus


@dataclass
class SRIEConfig:
    """Serialisable SRIE settings (the ``srie`` block of a campaign config)."""

    transport: Dict[str, Any] = field(default_factory=lambda: {"kind": "mock", "seed": 1})
    workdir: str = "."
    discover_root: str = "/"
    discover_depth: int = 2
    coverage_cmd: str = "coverage report -detail -xml -output {output}"
    coverage_format: str = "auto"
    max_forced: int = 8
    allow_outputs: bool = False
    deny_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_DENY_PATTERNS))
    value_base: str = "dec"
    quantum_cycles: int = 500
    period_ns: float = 10.0
    dry_run: bool = False
    probe: bool = True
    launch: Dict[str, Any] = field(default_factory=dict)
    max_introspect_signals: int = 32

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "SRIEConfig":
        d = dict(d or {})
        cfg = cls()
        for k, v in d.items():
            if k in cls.__dataclass_fields__:
                setattr(cfg, k, v)
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transport": self.transport, "workdir": self.workdir,
            "discover_root": self.discover_root, "discover_depth": self.discover_depth,
            "coverage_cmd": self.coverage_cmd, "coverage_format": self.coverage_format,
            "max_forced": self.max_forced, "allow_outputs": self.allow_outputs,
            "deny_patterns": self.deny_patterns, "value_base": self.value_base,
            "quantum_cycles": self.quantum_cycles, "period_ns": self.period_ns,
            "dry_run": self.dry_run, "probe": self.probe, "launch": self.launch,
            "max_introspect_signals": self.max_introspect_signals,
        }


class SRIESession:
    """Context manager around a live introspection/reflection session."""

    def __init__(self, config: SRIEConfig, log: Optional[Any] = None):
        self.config = config
        self.log = log or (lambda _m: None)
        self.transport: Optional[Transport] = None
        self.introspector: Optional[Introspector] = None
        self.reflection: Optional[ReflectionController] = None
        self.bus: Optional[EventBus] = None
        self.hierarchy: Optional[Hierarchy] = None
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self._t0 = 0.0
        self._samples = 0

    # ------------------------------------------------------------- lifecycle
    def open(self, discover: bool = True) -> "SRIESession":
        spec = dict(self.config.transport)
        if not spec.get("argv") and self.config.launch:
            spec["argv"] = SimLaunch.from_dict(self.config.launch).argv()
        self.transport = make_transport(spec)
        self.log(f"starting transport {self.transport.name} ...")
        self.transport.start()
        self.log(f"simulator ready: {self.transport.version or '(no version)'}")
        self.introspector = Introspector(
            self.transport,
            workdir=self.config.workdir,
            coverage_cmd=self.config.coverage_cmd,
            coverage_format=self.config.coverage_format,
            log=self.log,
        )
        if self.config.probe:
            self.capabilities = self.introspector.probe()
        self.bus = EventBus(self.transport)
        self.reflection = ReflectionController(
            self.transport,
            dry_run=self.config.dry_run,
            max_forced=self.config.max_forced,
            allow_outputs=self.config.allow_outputs,
            deny_patterns=self.config.deny_patterns,
            value_base=self.config.value_base,
            log=self.log,
        )
        if discover:
            self.discover()
        self._t0 = time.time()
        return self

    def discover(self) -> Hierarchy:
        assert self.introspector is not None
        self.hierarchy = self.introspector.discover(
            root=self.config.discover_root, depth=self.config.discover_depth
        )
        if self.reflection is not None:
            self.reflection.set_hierarchy(self.hierarchy)
        self.log(self.hierarchy.describe())
        return self.hierarchy

    def close(self) -> None:
        if self.reflection is not None:
            try:
                self.reflection.restore()
            except Exception:  # noqa: BLE001 - cleanup must never raise
                pass
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:  # noqa: BLE001
                pass
        self.log("session closed")

    def __enter__(self) -> "SRIESession":
        return self.open()

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ read
    def sample(self, paths: Sequence[str]) -> Dict[str, Optional[int]]:
        assert self.introspector is not None
        self._samples += 1
        return self.introspector.examine(paths)

    def observation_paths(self, limit: Optional[int] = None) -> List[str]:
        """Signals worth sampling: outputs first, then inputs, capped."""
        if self.hierarchy is None:
            return []
        limit = limit or self.config.max_introspect_signals
        ordered = [n.path for n in self.hierarchy.outputs()] + [n.path for n in self.hierarchy.inputs()]
        return ordered[:limit]

    def coverage(self, tag: str = "snap") -> CoverageSnapshot:
        assert self.introspector is not None
        snap = self.introspector.coverage(tag=tag)
        snap.wall_s = time.time() - self._t0
        return snap

    def sim_time_ns(self) -> float:
        assert self.introspector is not None
        t, _ = self.introspector.now()
        return t

    # ----------------------------------------------------------------- write
    def run_quantum(self, cycles: Optional[int] = None) -> bool:
        assert self.reflection is not None
        n = cycles if cycles is not None else self.config.quantum_cycles
        return self.reflection.run_quantum(n, period_ns=self.config.period_ns)

    def bias(self, mode: str, **kwargs: Any) -> List[Dict[str, Any]]:
        assert self.reflection is not None
        return self.reflection.apply_bias(mode, **kwargs)

    def install_trigger(self, label: str, expression: str, **fields: Any) -> bool:
        assert self.reflection is not None
        return self.reflection.install_trigger(label, expression, **fields)

    def pump_events(self) -> int:
        assert self.bus is not None
        return len(self.bus.poll())

    # ------------------------------------------------------------------ misc
    def capability_report(self) -> str:
        lines = [f"transport: {self.transport.name if self.transport else '-'}",
                 f"version  : {self.transport.version if self.transport else '-'}"]
        for name, cap in sorted(self.capabilities.items()):
            lines.append(f"  {name:<10s} {'OK' if cap.get('ok') else 'NO':<3s} {cap.get('detail', '')}")
        if self.hierarchy is not None:
            lines.append(self.hierarchy.describe(limit=20))
        return "\n".join(lines)

    def selftest(self) -> Dict[str, Any]:
        """Exercise every capability once and report what worked."""
        report: Dict[str, Any] = {"transport": self.transport.name if self.transport else None}
        try:
            report["probe"] = self.capabilities or (self.introspector.probe() if self.introspector else {})
            hier = self.hierarchy or self.discover()
            report["hierarchy_nodes"] = len(hier.nodes)
            report["inputs"] = [n.path for n in hier.inputs()][:10]
            report["outputs"] = [n.path for n in hier.outputs()][:10]
            vals = self.sample(self.observation_paths(4))
            report["sample"] = {k: v for k, v in vals.items()}
            if self.reflection and self.reflection.candidates():
                first = self.reflection.candidates()[0]
                ok = self.reflection.force(first, 1, reason="selftest")
                report["force"] = {"path": first, "ok": ok}
                self.reflection.release(first)
            snap = self.coverage("selftest")
            report["coverage_bins"] = snap.total_bins
            report["coverage_groups"] = snap.group_names
            report["run"] = self.run_quantum(50)
            report["sim_time_ns"] = self.sim_time_ns()
            report["events"] = self.pump_events()
        except (SRIEError, CommandError, TransportError) as exc:
            report["error"] = str(exc)
        return report
