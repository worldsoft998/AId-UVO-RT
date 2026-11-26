"""Coverage importers: UCIS XML, CSV and Questa text reports.

UCIS (IEEE 1801) XML is the interchange format every serious coverage tool can
write: ``vcover report -xml``, ``coverage report -xml``, Verdi, VC SpyGlass and
others all emit it.  The parser below is namespace- and version-tolerant: it
walks the element tree looking for the three things that matter (a group, a
coverpoint, a bin with a hit count) and ignores everything else, so schema
additions do not break it.
"""

from __future__ import annotations

import csv
import io
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional

from aiduvo.coverage.model import Bin, CoverageSnapshot

_GROUP_TAGS = {"covergroup", "covergroupdef", "group", "covergroupinstance"}
_CP_TAGS = {"coverpoint", "coverpointdef", "cross", "crossdef", "point", "coverindex"}
_BIN_TAGS = {"bin", "ignorebin", "illegalbin", "crossbin", "binitem"}
_EXCLUDED_TAGS = {"ignorebin", "illegalbin"}
_COUNT_TAGS = {"count", "hits", "covercount", "hitcount", "ucis:count"}
_GOAL_ATTRS = ("goal", "atleast", "ucis:goal")
_HIT_ATTRS = ("hits", "count", "ucis:count", "covercount", "hitcount")


def _local(tag: str) -> str:
    return tag.split("}")[-1].split(":")[-1].lower()


def _as_int(text: Any, default: int = 0) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(text).strip()))
        except (TypeError, ValueError):
            return default


def _element_hits(elem: ET.Element) -> int:
    for attr in _HIT_ATTRS:
        for key in (attr, f"{{{elem.tag.split('}')[0][1:]}}}{attr}" if "}" in elem.tag else attr):
            if key in elem.attrib:
                return _as_int(elem.attrib[key])
    for child in elem:
        if _local(child.tag) in _COUNT_TAGS:
            if child.text is not None:
                return _as_int(child.text)
            return _as_int(child.attrib.get("value", 0))
    return 0


def _element_goal(elem: ET.Element) -> int:
    for attr in _GOAL_ATTRS:
        if attr in elem.attrib:
            return max(1, _as_int(elem.attrib[attr], 1))
    return 1


def _element_name(elem: ET.Element, fallback: str) -> str:
    for attr in ("name", "ucis:name", "alias", "instname"):
        if attr in elem.attrib:
            return str(elem.attrib[attr])
    for child in elem:
        if _local(child.tag) == "name" and child.text:
            return child.text.strip()
    return fallback


def parse_ucis_string(text: str, source: str = "ucis-xml") -> CoverageSnapshot:
    """Parse a UCIS XML document into a :class:`CoverageSnapshot`."""
    root = ET.fromstring(text)
    snap = CoverageSnapshot(source=source)
    counters = {"group": 0, "cp": 0, "bin": 0}

    def walk(elem: ET.Element, group: Optional[str], cp: Optional[str]) -> None:
        tag = _local(elem.tag)
        g, c = group, cp
        if tag in _GROUP_TAGS:
            counters["group"] += 1
            g = _element_name(elem, f"group_{counters['group']}")
            snap.group(g)
        elif tag in _CP_TAGS:
            counters["cp"] += 1
            c = _element_name(elem, f"cp_{counters['cp']}")
            if g is None:
                g = "default"
            snap.coverpoint(g, c)
        elif tag in _BIN_TAGS:
            counters["bin"] += 1
            name = _element_name(elem, f"bin_{counters['bin']}")
            if g is None:
                g = "default"
            if c is None:
                c = "default"
            snap.add_bin(
                g,
                c,
                Bin(
                    name=name,
                    hits=_element_hits(elem),
                    goal=_element_goal(elem),
                    kind="ignore" if tag in _EXCLUDED_TAGS else "coverpoint",
                    excluded=tag in _EXCLUDED_TAGS,
                ),
            )
        for child in elem:
            walk(child, g, c)

    walk(root, None, None)
    for attr in ("sim_time_ns", "simtime", "time"):
        if attr in root.attrib:
            snap.sim_time_ns = float(_as_int(root.attrib[attr]))
    if "writtenBy" in root.attrib:
        snap.meta["writtenBy"] = root.attrib["writtenBy"]
    return snap


def parse_ucis(path: str) -> CoverageSnapshot:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return parse_ucis_string(text, source=os.path.basename(path))


def parse_csv(
    path: str,
    group_col: str = "group",
    coverpoint_col: str = "coverpoint",
    bin_col: str = "bin",
    hits_col: str = "hits",
    goal_col: Optional[str] = "goal",
) -> CoverageSnapshot:
    """Parse a flat CSV export with configurable column names."""
    snap = CoverageSnapshot(source=os.path.basename(path))
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            g = row.get(group_col) or "default"
            c = row.get(coverpoint_col) or "default"
            b = row.get(bin_col) or "bin"
            hits = _as_int(row.get(hits_col, 0))
            goal = _as_int(row.get(goal_col, 1), 1) if goal_col else 1
            snap.add_bin(g, c, Bin(name=b, hits=hits, goal=max(1, goal)))
    return snap


def parse_text_report(text: str, source: str = "text-report") -> CoverageSnapshot:
    """Parse ``coverage report -detail`` style text (fallback importer)."""
    from aiduvo.srie.tcl import parse_text_coverage

    tree = parse_text_coverage(text)
    snap = CoverageSnapshot(source=source)
    for g, cps in tree.items():
        for c, bins in cps.items():
            for b, hits in bins.items():
                snap.add_bin(g, c, Bin(name=b, hits=hits))
    return snap


def load_coverage(path: str, fmt: str = "auto", **kwargs: Any) -> CoverageSnapshot:
    """Load any supported coverage artifact."""
    fmt = (fmt or "auto").lower()
    if fmt == "auto":
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xml", ".ucis"):
            fmt = "ucis"
        elif ext == ".csv":
            fmt = "csv"
        elif ext in (".txt", ".log", ".rpt"):
            fmt = "text"
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(4096)
            fmt = "ucis" if head.lstrip().startswith("<?xml") or "<ucis" in head else "text"
    if fmt == "ucis":
        return parse_ucis(path)
    if fmt == "csv":
        return parse_csv(path, **kwargs)
    if fmt == "text":
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return parse_text_report(fh.read(), source=os.path.basename(path))
    raise ValueError(f"unsupported coverage format {fmt!r}")
