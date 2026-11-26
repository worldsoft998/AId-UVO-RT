"""A synthetic simulator that speaks the real SRIE wire protocol.

Why it exists:

* the framework must be testable and demonstrable on a machine with no QuestaSim
  licence (CI, laptops, code review);
* it exercises the *entire* stack -- Tcl parsing, trigger events, coverage
  export, force/release bookkeeping, the RL loop -- not just mocked-out stubs.

It is clearly synthetic: the design is a four-input toy block with 4 covergroups
of 3 coverpoints x 8 bins, and two of those bins are genuine corners that random
stimulus almost never reaches but a targeted force does.  Every number it emits
is generated locally; it never pretends to be a real simulator measurement.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

_CYCLE_NS = 10.0
_UNIT_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9, "": 1.0}


class MockQuestaSim:
    """Minimal Questa-like Tcl surface over a toy design."""

    version = "mock-questa/2024.1 (synthetic, AId-UVO-RT)"

    def __init__(self, seed: int = 1, groups: int = 4, coverpoints: int = 3, bins: int = 8):
        import random

        self.rng = random.Random(seed)
        self.cycles = 0
        self.sim_time_ns = 0.0
        self.finished = False
        self.forces: Dict[str, int] = {}
        self.triggers: Dict[str, Tuple[str, str]] = {}
        self.pending: List[str] = []
        self._prev_all_zero = True
        self.ucdb_path: Optional[str] = None
        self.log: List[str] = []
        self.groups: Dict[str, Dict[str, List[int]]] = {}
        for g in range(groups):
            cps: Dict[str, List[int]] = {}
            for c in range(coverpoints):
                cps[f"cp_{c}"] = [0] * bins
            self.groups[f"grp_{g}"] = cps
        self.nodes: Dict[str, Dict[str, Any]] = {
            "/tb": {"kind": "region", "dir": "internal", "width": None},
            "/tb/top": {"kind": "region", "dir": "internal", "width": None},
            "/tb/top/clk": {"kind": "signal", "dir": "input", "width": 1},
            "/tb/top/rst_n": {"kind": "signal", "dir": "input", "width": 1},
            "/tb/top/u_dut": {"kind": "region", "dir": "internal", "width": None},
        }
        for i in range(4):
            self.nodes[f"/tb/top/u_dut/in_{i:02d}"] = {"kind": "signal", "dir": "input", "width": 1}
        for i in range(3):
            self.nodes[f"/tb/top/u_dut/out_{i:02d}"] = {"kind": "signal", "dir": "output", "width": 8}
        self.nodes["/tb/top/u_dut/state"] = {"kind": "signal", "dir": "internal", "width": 4}

    # ------------------------------------------------------------------ helpers
    def describe_design(self) -> Dict[str, Any]:
        return {
            "nodes": len(self.nodes),
            "groups": len(self.groups),
            "coverpoints": sum(len(c) for c in self.groups.values()),
            "bins": sum(len(b) for c in self.groups.values() for b in c.values()),
            "cycles": self.cycles,
        }

    def value(self, path: str) -> int:
        if path in self.forces:
            return self.forces[path]
        if path.endswith("/clk"):
            return int((self.cycles // 1) % 2 == 0)
        if path.endswith("/rst_n"):
            return 1
        if "/in_" in path:
            return self.rng.getrandbits(1)
        if "/out_" in path:
            return self.rng.getrandbits(8)
        if path.endswith("/state"):
            return self.cycles % 16
        return 0

    def set_force(self, path: str, value: int) -> None:
        self.forces[path] = int(value)

    def release(self, path: str) -> bool:
        return self.forces.pop(path, None) is not None

    # -------------------------------------------------------------------- run
    def _step(self) -> None:
        self.cycles += 1
        self.sim_time_ns += _CYCLE_NS
        vals = [self.value(f"/tb/top/u_dut/in_{i:02d}") for i in range(4)]
        all_one = all(vals)
        for gi, (gname, cps) in enumerate(self.groups.items()):
            for ci, (cpname, hits) in enumerate(cps.items()):
                idx = (gi * 37 + ci * 11 + sum(v * (i + 1) for i, v in enumerate(vals))) % 6
                hits[idx] += 1
                if vals[0] and vals[1]:
                    hits[6] += 1
                if all_one and self._prev_all_zero:
                    hits[7] += 1
        self._prev_all_zero = not any(vals)
        self._fire_triggers(vals)

    def _fire_triggers(self, vals: List[int]) -> None:
        for label, (expr, body) in list(self.triggers.items()):
            m = re.match(r"^\s*(/\S+)\s*(?:==|=)\s*'?[bdh]?([0-9a-fA-F]+)\s*$", expr)
            if not m:
                continue
            path, want = m.group(1), int(m.group(2), 0)
            if self.value(path) == want:
                evt = {"kind": "trigger", "label": label, "path": path, "value": want,
                       "cycle": self.cycles, "sim_time_ns": self.sim_time_ns}
                self.pending.append(f"@@SRIE_EVT {json.dumps(evt)}@@")
                if "stop" in body:
                    self.pending.append("@@SRIE_NOTE halted by trigger@@")
                    self.triggers.pop(label, None)

    def _run_cycles(self, n: int) -> Iterator[str]:
        for _ in range(n):
            if self.finished:
                break
            self._step()
            while self.pending:
                yield self.pending.pop(0)

    # --------------------------------------------------------------- coverage
    def coverage_xml(self) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ucis:coveragedata xmlns:ucis="http://www.accellera.org/XMLSchema/UCIS" '
            f'writtenBy="{self.version}">',
        ]
        for gname, cps in self.groups.items():
            lines.append(f'  <ucis:covergroup name="{gname}" weight="1">')
            for cpname, hits in cps.items():
                lines.append(f'    <ucis:coverpoint name="{cpname}" weight="1">')
                for i, h in enumerate(hits):
                    lines.append(
                        f'      <ucis:bin name="b{i}" weight="1"><ucis:count>{h}</ucis:count></ucis:bin>'
                    )
                lines.append("    </ucis:coverpoint>")
            lines.append("  </ucis:covergroup>")
        lines.append("</ucis:coveragedata>")
        return "\n".join(lines) + "\n"

    def coverage_text(self) -> str:
        lines = ["# Coverage Report"]
        for gname, cps in self.groups.items():
            total = sum(len(h) for h in cps.values())
            hit = sum(1 for h in cps.values() for x in h if x > 0)
            lines.append(f"{gname}  {100.0 * hit / total:.2f}%")
            for cpname, hits in cps.items():
                lines.append(f"  {cpname}  {100.0 * sum(1 for x in hits if x > 0) / len(hits):.2f}%")
                for i, h in enumerate(hits):
                    lines.append(f"    b{i}  {h}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------- tcl
    def execute_lines(self, command: str, cid: int) -> Iterator[str]:
        """Execute one Tcl-ish command, yielding output lines then the sentinel."""
        self.log.append(command)
        rc = 0
        try:
            for line in self._dispatch(command.strip()):
                yield line
        except Exception as exc:  # emulate a Tcl error
            rc = 1
            yield f"@@SRIE_ERR {exc}@@"
        yield f"@@SRIE_END {cid} rc={rc}@@"

    def _dispatch(self, cmd: str) -> Iterator[str]:
        # ``when`` carries brace-quoted Tcl bodies, so it is parsed by regex
        # before the generic tokeniser.
        if cmd.startswith("when "):
            m = re.match(
                r"^when(?:\s+-label\s+(\S+))?\s*\{(.*?)\}\s*\{(.*)\}\s*$", cmd, re.S
            )
            if not m:
                raise RuntimeError("when: usage: when ?-label <l>? {<expr>} {<body>}")
            label = _strip_braces(m.group(1) or f"when_{len(self.triggers)}")
            self.triggers[label] = (m.group(2).strip(), m.group(3))
            yield f"# when {label}: {m.group(2).strip()}"
            return
        if cmd.startswith("puts "):
            yield cmd[5:].strip().strip('"')
            return
        try:
            parts = [_strip_braces(p) for p in shlex.split(cmd, posix=True)]
        except ValueError as exc:
            raise RuntimeError(f"parse error: {exc}")
        if not parts:
            return
        head = parts[0]

        if head == "describe":
            path = "/"
            depth = 1
            i = 1
            while i < len(parts):
                if parts[i] == "-depth":
                    depth = int(parts[i + 1]); i += 2
                else:
                    path = parts[i]; i += 1
            yield from self._describe(path, depth)
            return

        if head == "version":
            yield f"# {self.version}"
            return

        if head == "examine":
            if "-time" in parts:
                yield f"# {self.sim_time_ns:.0f} ns"
                return
            args = [p for p in parts[1:] if not p.startswith("-")]
            if not args:
                raise RuntimeError("examine: missing path")
            for p in args:
                if p not in self.nodes:
                    raise RuntimeError(f"examine: no object named {p}")
                yield f"# {p} = {self.value(p)}"
            return

        if head == "force":
            freeze = True
            args = []
            for p in parts[1:]:
                if p == "-freeze":
                    freeze = True
                elif p == "-deposit":
                    freeze = False
                else:
                    args.append(p)
            if len(args) < 2:
                raise RuntimeError("force: usage: force [-freeze|-deposit] <path> <value>")
            path, raw = args[0], args[1]
            if path not in self.nodes:
                raise RuntimeError(f"force: no object named {path}")
            self.set_force(path, _to_int(raw))
            yield f"# force {'-freeze' if freeze else '-deposit'} {path} {raw}"
            return

        if head == "release":
            if len(parts) < 2:
                raise RuntimeError("release: missing path")
            ok = self.release(parts[1])
            yield f"# release {parts[1]}: {'done' if ok else 'not forced'}"
            return

        if head == "when":
            label = f"when_{len(self.triggers)}"
            expr = body = ""
            i = 1
            while i < len(parts):
                if parts[i] == "-label":
                    label = parts[i + 1]; i += 2
                elif not expr:
                    expr = parts[i]; i += 1
                else:
                    body = " ".join(parts[i:]); break
            self.triggers[label] = (expr, body)
            yield f"# when {label}: {expr}"
            return

        if head == "nowhen":
            if len(parts) > 1:
                self.triggers.pop(parts[1], None)
            else:
                self.triggers.clear()
            yield "# nowhen done"
            return

        if head == "run":
            if len(parts) < 2:
                raise RuntimeError("run: missing time")
            spec = parts[1]
            if spec == "-all":
                n = 100_000
            else:
                m = re.match(r"^(\d+)\s*([a-z]*)$", spec)
                if not m:
                    raise RuntimeError(f"run: bad time {spec!r}")
                n = int(m.group(1))
                unit = m.group(2)
                if unit in _UNIT_NS and unit not in ("", "ns"):
                    n = max(1, int(round(n * _UNIT_NS[unit] / _CYCLE_NS)))
            yield from self._run_cycles(n)
            yield f"# run {spec} -> cycle {self.cycles}"
            return

        if head == "stop":
            yield f"# stopped at cycle {self.cycles}"
            return

        if head == "coverage":
            yield from self._coverage(parts)
            return

        if head == "quit":
            self.finished = True
            yield "# quitting"
            return

        if head == "puts":
            yield " ".join(parts[1:]).strip('"')
            return

        if head == "set":
            yield ""
            return

        raise RuntimeError(f"invalid command name \"{head}\"")

    def _describe(self, path: str, depth: int) -> Iterator[str]:
        if path in self.nodes and self.nodes[path]["kind"] == "signal":
            yield f"# Region: {path}"
            n = self.nodes[path]
            yield f"#   {path}   {n['dir']}  wire  width={n['width']}"
            return
        base = path.rstrip("/") or "/"
        if base == "/":
            children = sorted(p for p in self.nodes if p.count("/") == 1)
        else:
            children = sorted(
                p for p in self.nodes
                if p != base and p.rsplit("/", 1)[0] == base
            )
        yield f"# Region: {base}"
        for p in children:
            n = self.nodes[p]
            if n["kind"] == "region":
                yield f"#   {p}   internal  region"
            else:
                yield f"#   {p}   {n['dir']}  wire  width={n['width']}"
        if depth > 1:
            for p in children:
                if self.nodes[p]["kind"] == "region":
                    yield from self._describe(p, depth - 1)

    def _coverage(self, parts: List[str]) -> Iterator[str]:
        sub = parts[1] if len(parts) > 1 else "report"
        if sub == "report":
            out = None
            xml = False
            i = 2
            while i < len(parts):
                if parts[i] == "-output":
                    out = parts[i + 1]; i += 2
                elif parts[i] == "-xml":
                    xml = True; i += 1
                else:
                    i += 1
            payload = self.coverage_xml() if xml else self.coverage_text()
            if out:
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                yield f"# coverage report written to {out}"
            else:
                for line in payload.splitlines():
                    yield line
            return
        if sub == "save":
            args = [p for p in parts[2:] if not p.startswith("-")]
            if args:
                self.ucdb_path = args[0]
                with open(args[0], "w", encoding="utf-8") as fh:
                    fh.write(self.coverage_xml())
                yield f"# coverage saved to {args[0]}"
            else:
                yield "# coverage save: no file given"
            return
        if sub in ("query", "attribute"):
            total = sum(len(h) for c in self.groups.values() for h in c.values())
            hit = sum(1 for c in self.groups.values() for h in c.values() for x in h if x > 0)
            yield f"# coverage: {hit}/{total} bins"
            return
        raise RuntimeError(f"coverage: unknown subcommand {sub!r}")

    # ------------------------------------------------------------- blackbox API
    def write_ucdb(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.coverage_xml())
        self.ucdb_path = path

    def write_transcript(self, path: str, extra: Optional[Dict[str, Any]] = None) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# mock questa transcript\n")
            for line in self.log:
                fh.write(f"# {line}\n")
            fh.write(f"# ** Note: simulation finished at cycle {self.cycles}\n")
            fh.write(f"# ** Note: sim time = {self.sim_time_ns:.0f} ns\n")
            if extra:
                fh.write(f"# AIDUVRUN {json.dumps(extra)}\n")


def _strip_braces(token: str) -> str:
    t = token
    while len(t) >= 2 and t.startswith("{") and t.endswith("}"):
        t = t[1:-1]
    return t


def _to_int(raw: str) -> int:
    text = raw.strip().strip('"').replace("_", "")
    if text.startswith("'h") or text.startswith("'H"):
        return int(text[2:], 16)
    if text.startswith("'b") or text.startswith("'B"):
        return int(text[2:], 2)
    if "'" in text:  # e.g. 8'h0f
        _, rest = text.split("'", 1)
        base = {"h": 16, "b": 2, "d": 10, "o": 8}.get(rest[0].lower(), 10)
        return int(rest[1:], base)
    return int(text, 0)
