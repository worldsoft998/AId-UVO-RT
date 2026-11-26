"""Tcl command builders and tolerant output parsers.

Every simulator interaction the framework ever performs is expressed here as a
plain Tcl string.  Nothing in this file knows anything about the design under
verification: paths, values and labels are all supplied by the caller after
runtime discovery.

Why Tcl: QuestaSim's command language *is* its introspection API.  Driving it
from Python over stdin/stdout or a socket gives full read/write access to the
live simulation (hierarchy, signal values, forces, breakpoints, coverage) with
zero edits to RTL, testbench or UVM code, and zero recompilation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def tcl_quote(text: str) -> str:
    """Quote a string as a Tcl brace-quoted word (safe for paths/labels)."""
    if "{" in text or "}" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "{" + text + "}"


def describe(path: str = "/", depth: int = 1) -> str:
    return f"describe -depth {int(depth)} {tcl_quote(path)}"


def find_in(region: str, kind: str = "nets") -> str:
    """Alternative hierarchy enumeration on simulators that support ``find``."""
    return f"find {kind} -in {tcl_quote(region)}"


def examine(path: str) -> str:
    return f"examine -value {tcl_quote(path)}"


def examine_bin(path: str) -> str:
    return f"examine -bin -value {tcl_quote(path)}"


def force(path: str, value: str, freeze: bool = True) -> str:
    mode = "-freeze" if freeze else "-deposit"
    return f"force {mode} {tcl_quote(path)} {value}"


def release(path: str) -> str:
    return f"release {tcl_quote(path)}"


def when(label: str, expression: str, body: str) -> str:
    """Install a value-change trigger; ``body`` runs inside the simulator."""
    return f"when -label {tcl_quote(label)} {{{expression}}} {{{body}}}"


def nowhen(label: str = "") -> str:
    return f"nowhen {tcl_quote(label)}" if label else "nowhen"


def run(time_spec: str) -> str:
    return f"run {time_spec}"


def run_all() -> str:
    return "run -all"


def stop() -> str:
    return "stop"


def coverage_report_xml(output: str, detail: bool = True) -> str:
    detail_flag = "-detail " if detail else ""
    return f"coverage report {detail_flag}-xml -output {tcl_quote(output)}"


def coverage_report_text() -> str:
    return "coverage report -detail"


def coverage_save(ucdb: str) -> str:
    return f"coverage save -onexit {tcl_quote(ucdb)}"


def coverage_attribute(cmd: str = "query") -> str:
    return f"coverage {cmd}"


def quit_sim() -> str:
    return "quit -f"


def echo(message: str) -> str:
    return f'puts "@@SRIE_NOTE {message}@@"'


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

_HEX = re.compile(r"^'?[hH]([0-9a-fA-FxXzZ_]+)$")
_BIN = re.compile(r"^'?[bB]([0-9a-fA-FxXzZ_]+)$")
_DEC = re.compile(r"^-?\d+$")


def parse_value(raw: str) -> Tuple[Optional[int], str]:
    """Parse a simulator value into ``(int_or_None, original_text)``.

    Handles Questa's ``'h1f``/``'b1010``/plain-decimal forms and marks x/z as
    unparsable (``None``) so the optimizer never acts on an unknown value.
    """
    text = (raw or "").strip().strip('"')
    if "=" in text:
        text = text.split("=", 1)[1].strip()
    token = text.split()[0] if text.split() else ""
    if not token:
        return None, raw
    if re.search(r"[xXzZ]", token):
        return None, token
    m = _HEX.match(token)
    if m:
        try:
            return int(m.group(1).replace("_", ""), 16), token
        except ValueError:
            return None, token
    m = _BIN.match(token)
    if m:
        try:
            return int(m.group(1).replace("_", ""), 2), token
        except ValueError:
            return None, token
    if _DEC.match(token):
        return int(token), token
    return None, token


def to_sv_literal(value: int, width: Optional[int] = None, base: str = "dec") -> str:
    """Format an integer as a Verilog literal that ``force`` accepts."""
    if base == "hex":
        return f"{width or 32}'h{int(value) & ((1 << (width or 32)) - 1):x}"
    if base == "bin":
        return f"{width or 32}'b{int(value) & ((1 << (width or 32)) - 1):b}"
    return str(int(value))


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_DIRECTION_TOKENS = {
    "in": "input",
    "input": "input",
    "out": "output",
    "output": "output",
    "inout": "inout",
    "internal": "internal",
    "net": "internal",
    "signal": "internal",
    "variable": "internal",
    "port": "internal",
}

_PATH_RE = re.compile(r"(/[A-Za-z_0-9$\[\]\.\-/]*)")
_DIR_RE = re.compile(r"\b(inout|input|output|in|out|internal|net|signal|variable|port)\b", re.I)
_WIDTH_RE = re.compile(r"(?:width\s*=\s*|\(|\s)(\d+)\s*\)?\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class NodeInfo:
    """One hierarchy node discovered from the simulator."""

    path: str
    name: str = ""
    direction: str = "unknown"
    width: Optional[int] = None
    kind: str = "signal"

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "direction": self.direction,
            "width": self.width,
            "kind": self.kind,
        }

    @property
    def is_input(self) -> bool:
        return self.direction == "input"

    @property
    def is_output(self) -> bool:
        return self.direction == "output"


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def parse_describe(text: str, parent: str = "") -> List[NodeInfo]:
    """Parse ``describe`` output into nodes.

    Questa's formatting differs between versions and between ``describe`` and
    ``describe -depth``, so the parser is deliberately tolerant: any token that
    looks like an absolute hierarchical path becomes a node, and direction/width
    are recovered from nearby tokens when present.  Lines that only describe a
    region header are used as the parent for relative names.
    """
    nodes: List[NodeInfo] = []
    seen = set()
    region = parent.rstrip("/")
    for raw in _strip_ansi(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        low = line.lower()
        if low.startswith("region") or "region:" in low:
            m = _PATH_RE.search(line)
            if m:
                region = m.group(1).rstrip("/")
            continue
        m = _PATH_RE.search(line)
        if m:
            path = m.group(1)
            rest = line[m.end() :]
        else:
            # relative member name, e.g. "  clk  input  wire"
            token = line.split()[0]
            if token in {"#", "-", "="} or not re.match(r"^[A-Za-z_][\w$\[\]]*$", token):
                continue
            path = f"{region}/{token}" if region else token
            rest = line[len(token) :]
        if path in seen:
            continue
        seen.add(path)
        direction = "unknown"
        dm = _DIR_RE.search(rest)
        if dm:
            direction = _DIRECTION_TOKENS.get(dm.group(1).lower(), "unknown")
        width = None
        wm = _WIDTH_RE.search(rest.strip())
        if wm:
            try:
                width = int(wm.group(1))
            except ValueError:
                width = None
        low_rest = rest.lower()
        is_region = (
            "region" in low_rest
            or "instance" in low_rest
            or "(module" in low_rest
            or low_rest.strip().endswith("(region)")
        )
        nodes.append(
            NodeInfo(
                path=path,
                name=path.rstrip("/").split("/")[-1],
                direction=direction,
                width=width,
                kind="region" if is_region else "signal",
            )
        )
    return nodes


def parse_examine(text: str) -> List[Tuple[str, str]]:
    """Parse ``examine`` output into ``[(path, raw_value), ...]``."""
    out: List[Tuple[str, str]] = []
    for raw in _strip_ansi(text).splitlines():
        line = raw.strip()
        if not line or is_header(line):
            continue
        if "=" in line:
            left, right = line.split("=", 1)
            m = _PATH_RE.search(left)
            path = m.group(1) if m else left.strip()
            out.append((path, right.strip()))
        else:
            m = _PATH_RE.search(line)
            if m:
                out.append((m.group(1), line[m.end() :].strip()))
    return out


def is_header(line: str) -> bool:
    low = line.lower().lstrip("# ").strip()
    return low.startswith(("region", "signals", "variables", "nets", "coverage")) or low.endswith(":")


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BIN_LINE_RE = re.compile(r"^\s*(?:#\s*)?(\S.*?)\s{2,}(\d+)\s*$")


def parse_text_coverage(text: str) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Parse ``coverage report -detail`` text into ``{group: {coverpoint: {bin: hits}}}``.

    The text report is a fallback for simulator builds without XML export.  The
    parser keys off indentation depth: a section line ends with ``%``; a deeper
    line with a trailing integer is a bin with its hit count.
    """
    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    group = coverpoint = None
    for raw in _strip_ansi(text).splitlines():
        if not raw.strip() or raw.strip().startswith(("---", "===")):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        pct = _PCT_RE.search(line)
        if pct and not _BIN_LINE_RE.match(raw):
            name = line.split()[0]
            if indent <= 2 or group is None:
                group = name
                coverpoint = None
                result.setdefault(group, {})
            else:
                coverpoint = name
                result[group].setdefault(coverpoint, {})
            continue
        m = _BIN_LINE_RE.match(raw)
        if m and group is not None:
            bin_name, hits = m.group(1).strip(), int(m.group(2))
            cp = coverpoint or "default"
            result[group].setdefault(cp, {})[bin_name] = hits
    return result
