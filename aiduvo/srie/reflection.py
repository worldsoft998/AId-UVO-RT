"""Reflection: steering a running simulation without touching its source.

Everything here is a *simulator control* action: ``force``/``release`` on
existing DUT ports, ``when`` triggers, and ``run``/``stop``.  No HDL, testbench
or UVM file is read, parsed, generated or modified, and nothing is recompiled.

Safety is not an afterthought:

* only signals the simulator reported as **inputs** may be driven;
* clock- and reset-like paths are excluded by default (generic name conventions,
  configurable, and never required to match a particular project);
* a hard cap limits how many signals can be forced at once;
* every force is recorded in a ledger and released on exit, including on error
  and on simulator death.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

from aiduvo.srie import tcl
from aiduvo.srie.introspection import Hierarchy
from aiduvo.srie.protocol import CommandError, TransportError
from aiduvo.srie.transport import Transport
from aiduvo.srie.triggers import trigger_body

DEFAULT_DENY_PATTERNS = (
    r"(^|/)(clk|clock|ck|clk_i|sys_clk)$",
    r"(^|/)(rst|reset|reset_n|rst_n|nrst|resetn)$",
    r"(^|/)(scan_en|test_mode|dft_.*)$",
)

BIAS_MODES = ("hold", "low", "high", "toggle", "random_walk", "release")


@dataclass
class ForceRecord:
    path: str
    value: int
    freeze: bool = True
    cycle: float = 0.0
    original: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "value": self.value,
            "freeze": self.freeze,
            "cycle": self.cycle,
            "original": self.original,
            "reason": self.reason,
        }


class ReflectionController:
    """Writes to the simulation through the simulator's own control commands."""

    def __init__(
        self,
        transport: Transport,
        hierarchy: Optional[Hierarchy] = None,
        dry_run: bool = False,
        max_forced: int = 8,
        allow_outputs: bool = False,
        deny_patterns: Sequence[str] = DEFAULT_DENY_PATTERNS,
        value_base: str = "dec",
        log: Optional[Callable[[str], None]] = None,
    ):
        self.transport = transport
        self.hierarchy = hierarchy
        self.dry_run = dry_run
        self.max_forced = int(max_forced)
        self.allow_outputs = allow_outputs
        self.deny = [re.compile(p, re.I) for p in deny_patterns]
        self.value_base = value_base
        self.log = log or (lambda _m: None)
        self._ledger: List[ForceRecord] = []
        self._triggers: Dict[str, str] = {}
        self._widths: Dict[str, Optional[int]] = {}
        self._allowed: Optional[set] = None
        self.applied: List[Dict[str, Any]] = []
        if hierarchy is not None:
            self.set_hierarchy(hierarchy)

    # ------------------------------------------------------------------ setup
    def set_hierarchy(self, hierarchy: Hierarchy) -> None:
        self.hierarchy = hierarchy
        self._allowed = {n.path for n in hierarchy.inputs()}
        if self.allow_outputs:
            self._allowed |= {n.path for n in hierarchy.outputs()}
            self._allowed |= {n.path for n in hierarchy.inouts()}
        self._widths = {n.path: n.width for n in hierarchy.nodes.values()}

    def candidates(self, limit: int = 64) -> List[str]:
        """Force-eligible paths (inputs, not clock/reset, discovered order)."""
        if self._allowed is None:
            return []
        out = []
        for p in sorted(self._allowed):
            if any(rx.search(p) for rx in self.deny):
                continue
            out.append(p)
        return out[:limit]

    def check_path(self, path: str) -> None:
        if self._allowed is not None and path not in self._allowed:
            raise ValueError(
                f"{path!r} is not an input port discovered in the hierarchy; "
                "refusing to drive it"
            )
        if any(rx.search(path) for rx in self.deny):
            raise ValueError(f"{path!r} matches the clock/reset deny list; refusing to drive it")

    # ------------------------------------------------------------------ forces
    def force(self, path: str, value: int, freeze: bool = True, cycle: float = 0.0,
              reason: str = "") -> bool:
        self.check_path(path)
        if len(self._ledger) >= self.max_forced and path not in {r.path for r in self._ledger}:
            self.log(f"force limit reached ({self.max_forced}); skipping {path}")
            return False
        literal = tcl.to_sv_literal(value, self._widths.get(path), self.value_base)
        if self.dry_run:
            self.log(f"[dry-run] {tcl.force(path, literal, freeze)}")
        else:
            res = self.transport.execute(tcl.force(path, literal, freeze), timeout=30)
            if not res.ok:
                self.log(f"force failed on {path}: {res.error}")
                return False
        self._ledger.append(ForceRecord(path=path, value=int(value), freeze=freeze, cycle=cycle, reason=reason))
        self.applied.append({"op": "force", "path": path, "value": int(value), "cycle": cycle, "reason": reason})
        return True

    def release(self, path: str) -> bool:
        if self.dry_run:
            self.log(f"[dry-run] {tcl.release(path)}")
        else:
            try:
                res = self.transport.execute(tcl.release(path), timeout=30)
                if not res.ok:
                    self.log(f"release failed on {path}: {res.error}")
            except (TransportError, CommandError) as exc:
                self.log(f"release failed on {path}: {exc}")
        self._ledger = [r for r in self._ledger if r.path != path]
        self.applied.append({"op": "release", "path": path})
        return True

    def release_all(self) -> int:
        paths = [r.path for r in self._ledger]
        for p in paths:
            self.release(p)
        self._ledger.clear()
        return len(paths)

    @property
    def ledger(self) -> List[ForceRecord]:
        return list(self._ledger)

    def restore(self) -> None:
        """Full cleanup: release every force and remove every trigger."""
        try:
            self.release_all()
        finally:
            for label in list(self._triggers):
                self.remove_trigger(label)

    # ------------------------------------------------------------------- bias
    def apply_bias(
        self,
        bias: str,
        paths: Optional[Sequence[str]] = None,
        rng: Optional[np.random.Generator] = None,
        cycle: float = 0.0,
        max_paths: Optional[int] = None,
        current: Optional[Dict[str, Optional[int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Drive a group of inputs according to a coarse stimulus bias."""
        bias = (bias or "hold").lower()
        if bias not in BIAS_MODES:
            raise ValueError(f"unknown bias {bias!r}; expected one of {BIAS_MODES}")
        targets = list(paths if paths is not None else self.candidates())
        cap = max_paths if max_paths is not None else self.max_forced
        targets = targets[:cap]
        rng = rng or np.random.default_rng(0)
        current = current or {}

        if bias == "release":
            n = self.release_all()
            return [{"op": "release_all", "count": n}]

        actions: List[Dict[str, Any]] = []
        for path in targets:
            cur = current.get(path)
            if bias == "hold":
                value = 1 if cur is None else int(cur)
            elif bias == "low":
                value = 0
            elif bias == "high":
                value = 1
            elif bias == "toggle":
                value = 0 if (cur is None or int(cur) == 1) else 1
            else:  # random_walk
                value = int(rng.integers(0, 2))
            if self.force(path, value, freeze=True, cycle=cycle, reason=bias):
                actions.append({"op": "force", "path": path, "value": value, "bias": bias})
        return actions

    def pattern_bias(self, pattern: str, paths: Optional[Sequence[str]] = None,
                     cycle: float = 0.0) -> List[Dict[str, Any]]:
        """Drive inputs to an explicit bit pattern (``"1010"``); leftovers untouched."""
        targets = list(paths if paths is not None else self.candidates())
        bits = [c for c in pattern if c in "01"]
        actions = []
        for path, bit in zip(targets, bits):
            if self.force(path, int(bit), freeze=True, cycle=cycle, reason="pattern"):
                actions.append({"op": "force", "path": path, "value": int(bit), "bias": "pattern"})
        return actions

    # --------------------------------------------------------------- triggers
    def install_trigger(self, label: str, expression: str, kind: str = "trigger",
                        **fields: Any) -> bool:
        body = trigger_body(kind, label=label, **fields)
        if self.dry_run:
            self.log(f"[dry-run] {tcl.when(label, expression, body)}")
            self._triggers[label] = expression
            return True
        res = self.transport.execute(tcl.when(label, expression, body), timeout=30)
        if res.ok:
            self._triggers[label] = expression
        else:
            self.log(f"trigger install failed ({label}): {res.error}")
        return res.ok

    def remove_trigger(self, label: str) -> None:
        self._triggers.pop(label, None)
        if self.dry_run:
            self.log(f"[dry-run] {tcl.nowhen(label)}")
            return
        try:
            self.transport.execute(tcl.nowhen(label), timeout=15)
        except (TransportError, CommandError):
            pass

    @property
    def triggers(self) -> Dict[str, str]:
        return dict(self._triggers)

    # ------------------------------------------------------------------ control
    def run_for(self, spec: str = "1000 ns") -> bool:
        if self.dry_run:
            self.log(f"[dry-run] {tcl.run(spec)}")
            return True
        res = self.transport.execute(tcl.run(spec), timeout=24 * 3600)
        return res.ok

    def run_quantum(self, cycles: int, period_ns: float = 10.0) -> bool:
        return self.run_for(f"{int(max(1, cycles) * period_ns)} ns")

    def stop(self) -> bool:
        try:
            return self.transport.execute(tcl.stop(), timeout=30).ok
        except (TransportError, CommandError):
            return False

    def quit(self) -> None:
        try:
            self.transport.execute(tcl.quit_sim(), timeout=30)
        except (TransportError, CommandError):
            pass
