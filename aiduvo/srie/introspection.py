"""Read-only introspection of a live simulation.

Two rules shape this module:

1. **Never assume a command exists.**  QuestaSim's Tcl surface varies by release,
   by licence bundle and by whether coverage was compiled in.  Every capability
   is probed once, the result is cached, and the framework degrades gracefully
   (``describe`` -> ``find`` -> user-supplied hierarchy dump -> give up loudly).
2. **Never assume a name.**  The hierarchy, the ports and the coverage groups are
   whatever the simulator reports.  No path literal appears in this file.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.coverage.ucis import load_coverage, parse_text_report
from aiduvo.srie import tcl
from aiduvo.srie.protocol import CapabilityError, CommandError, TransportError
from aiduvo.srie.transport import Transport

MAX_NODES = 200_000


@dataclass
class Hierarchy:
    """The slice of the design hierarchy the optimizer decided to look at."""

    nodes: Dict[str, tcl.NodeInfo] = field(default_factory=dict)
    root: str = "/"
    depth: int = 2

    def add(self, node: tcl.NodeInfo) -> None:
        if len(self.nodes) < MAX_NODES:
            self.nodes[node.path] = node

    # ------------------------------------------------------------------ views
    def inputs(self) -> List[tcl.NodeInfo]:
        return [n for n in self.nodes.values() if n.direction == "input"]

    def outputs(self) -> List[tcl.NodeInfo]:
        return [n for n in self.nodes.values() if n.direction == "output"]

    def inouts(self) -> List[tcl.NodeInfo]:
        return [n for n in self.nodes.values() if n.direction == "inout"]

    def signals(self) -> List[tcl.NodeInfo]:
        return [n for n in self.nodes.values() if n.kind == "signal"]

    def regions(self) -> List[tcl.NodeInfo]:
        return [n for n in self.nodes.values() if n.kind == "region"]

    def paths(self) -> List[str]:
        return sorted(self.nodes)

    def children(self, path: str) -> List[tcl.NodeInfo]:
        base = path.rstrip("/")
        return [n for n in self.nodes.values() if n.path.rsplit("/", 1)[0] == base]

    def depth_of(self, path: str) -> int:
        return path.count("/")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "depth": self.depth,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Hierarchy":
        h = cls(root=d.get("root", "/"), depth=int(d.get("depth", 2)))
        for nd in d.get("nodes") or []:
            h.add(
                tcl.NodeInfo(
                    path=nd["path"],
                    name=nd.get("name") or nd["path"].rsplit("/", 1)[-1],
                    direction=nd.get("direction", "unknown"),
                    width=nd.get("width"),
                    kind=nd.get("kind", "signal"),
                )
            )
        return h

    def describe(self, limit: int = 40) -> str:
        lines = [f"hierarchy root={self.root} nodes={len(self.nodes)} "
                 f"(inputs={len(self.inputs())} outputs={len(self.outputs())})"]
        for p in self.paths()[:limit]:
            n = self.nodes[p]
            lines.append(f"  {p:<50s} {n.direction:<9s} width={n.width}")
        if len(self.nodes) > limit:
            lines.append(f"  ... {len(self.nodes) - limit} more")
        return "\n".join(lines)


class Introspector:
    """Runtime, read-only access to hierarchy, values and coverage."""

    def __init__(
        self,
        transport: Transport,
        workdir: str = ".",
        coverage_cmd: Optional[str] = None,
        coverage_format: str = "auto",
        log: Optional[Any] = None,
    ):
        self.transport = transport
        self.workdir = workdir
        self.coverage_cmd = coverage_cmd or "coverage report -detail -xml -output {output}"
        self.coverage_format = coverage_format
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self.log = log
        os.makedirs(workdir, exist_ok=True)

    # ------------------------------------------------------------------ probe
    def probe(self) -> Dict[str, Dict[str, Any]]:
        """Discover which simulator features this build actually supports."""
        caps: Dict[str, Dict[str, Any]] = {}

        def record(name: str, ok: bool, detail: str = "") -> None:
            caps[name] = {"ok": ok, "detail": detail}
            if self.log:
                self.log(f"  capability {name:<14s} {'OK ' if ok else 'NO '} {detail}")

        try:
            r = self.transport.execute("version -short", timeout=30)
            record("version", r.ok, r.stdout.strip() or r.error)
        except (TransportError, CommandError) as exc:
            record("version", False, str(exc))

        try:
            r = self.transport.execute(tcl.describe("/", 1), timeout=30)
            record("describe", r.ok, f"{len(r.lines)} lines")
        except (TransportError, CommandError) as exc:
            record("describe", False, str(exc))

        try:
            r = self.transport.execute(tcl.find_in("/", "nets"), timeout=30)
            record("find", r.ok, f"{len(r.lines)} lines")
        except (TransportError, CommandError) as exc:
            record("find", False, str(exc))

        try:
            r = self.transport.execute(tcl.when("__aiduvo_probe", "0 = 1", "srie_evt {}"), timeout=30)
            ok = r.ok
            try:
                self.transport.execute(tcl.nowhen("__aiduvo_probe"), timeout=15)
            except (TransportError, CommandError):
                pass
            record("when", ok, "trigger install/remove")
        except (TransportError, CommandError) as exc:
            record("when", False, str(exc))

        try:
            r = self.transport.execute("coverage query", timeout=30)
            record("coverage", r.ok, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        except (TransportError, CommandError) as exc:
            record("coverage", False, str(exc))

        record("force", caps.get("describe", {}).get("ok", False), "requires a writable signal path")
        record("examine", caps.get("describe", {}).get("ok", False), "requires a readable signal path")
        self.capabilities = caps
        return caps

    def require(self, capability: str) -> None:
        cap = self.capabilities.get(capability)
        if cap is None or not cap.get("ok"):
            raise CapabilityError(
                f"simulator does not support {capability!r} "
                f"({(cap or {}).get('detail', 'not probed')}). "
                f"Run 'aiduvo srie probe' to see the capability matrix."
            )

    # -------------------------------------------------------------- hierarchy
    def discover(self, root: str = "/", depth: int = 2) -> Hierarchy:
        """Breadth-first hierarchy discovery using the best available command.

        ``depth`` is the maximum *path depth* to enumerate, in segments: with
        ``root="/"`` and ``depth=3`` the nodes ``/a``, ``/a/b`` and ``/a/b/c``
        are visited but ``/a/b/c/d`` is not.
        """
        hier = Hierarchy(root=root, depth=depth)
        use_find = self.capabilities.get("find", {}).get("ok", False) and not self.capabilities.get(
            "describe", {}
        ).get("ok", False)
        frontier: List[Tuple[str, int]] = [(root, 0)]
        seen = set()
        while frontier:
            path, level = frontier.pop(0)
            if path in seen or len(hier.nodes) >= MAX_NODES:
                continue
            seen.add(path)
            nodes = self._list_region(path, level, depth, use_find)
            if not nodes:
                continue
            for node in nodes:
                hier.add(node)
            if level + 1 <= depth:
                for node in nodes:
                    if node.kind == "region":
                        frontier.append((node.path, level + 1))
        if hier.nodes and depth > 1 and not any(n.kind == "region" for n in hier.nodes.values()):
            # Some releases do not label sub-regions in 'describe' output. Probe
            # one extra level per node so the hierarchy is still usable.
            for path in list(hier.nodes)[: min(200, MAX_NODES)]:
                for kid in self._list_region(path, 1, depth, use_find):
                    if kid.path not in hier.nodes:
                        hier.add(kid)
        if not hier.nodes:
            raise CapabilityError(
                "hierarchy discovery returned nothing: the simulator exposed neither "
                "'describe' nor 'find'. Provide a hierarchy dump via discovery.hierarchy_file."
            )
        return hier

    def _list_region(self, path: str, level: int, depth: int, use_find: bool) -> List[tcl.NodeInfo]:
        attempts = []
        if not use_find:
            attempts.append(tcl.describe(path, 1))
        attempts.append(tcl.find_in(path, "nets"))
        attempts.append(tcl.find_in(path, "signals"))
        attempts.append(tcl.describe(path, 1))
        for cmd in attempts:
            try:
                res = self.transport.execute(cmd, timeout=60)
            except (TransportError, CommandError):
                continue
            if not res.ok or not res.stdout.strip():
                continue
            nodes = tcl.parse_describe(res.stdout, parent=path)
            nodes = [n for n in nodes if n.path.rstrip("/") != path.rstrip("/")]
            if nodes:
                return nodes
        return []

    # ----------------------------------------------------------------- values
    def examine(self, paths: Sequence[str], batch: int = 64) -> Dict[str, Optional[int]]:
        """Read current values of many signals in as few round trips as possible."""
        out: Dict[str, Optional[int]] = {}
        plist = list(paths)
        for i in range(0, len(plist), batch):
            chunk = plist[i : i + batch]
            cmd = "; ".join(tcl.examine(p) for p in chunk)
            try:
                res = self.transport.execute(cmd, timeout=60)
            except (TransportError, CommandError):
                continue
            if not res.ok:
                # Fall back to one-by-one so one bad path cannot poison the batch.
                for p in chunk:
                    try:
                        single = self.transport.execute(tcl.examine(p), timeout=30)
                    except (TransportError, CommandError):
                        out[p] = None
                        continue
                    pairs = tcl.parse_examine(single.stdout)
                    out[p] = tcl.parse_value(pairs[0][1])[0] if pairs else None
                continue
            pairs = dict(tcl.parse_examine(res.stdout))
            for p in chunk:
                raw = pairs.get(p)
                out[p] = tcl.parse_value(raw)[0] if raw is not None else None
        return out

    def sample_raw(self, paths: Sequence[str]) -> Dict[str, str]:
        """Raw text values (useful for x/z detection and for logging)."""
        if not paths:
            return {}
        cmd = "; ".join(tcl.examine(p) for p in paths)
        try:
            res = self.transport.execute(cmd, timeout=60)
        except (TransportError, CommandError):
            return {}
        return {p: v for p, v in tcl.parse_examine(res.stdout)}

    # --------------------------------------------------------------- coverage
    def coverage(self, tag: str = "snap") -> CoverageSnapshot:
        """Take a coverage snapshot through the configured report command."""
        fd, path = tempfile.mkstemp(prefix=f"aiduvo_{tag}_", suffix=".xml", dir=self.workdir)
        os.close(fd)
        try:
            cmd = self.coverage_cmd.format(output=path)
            res = self.transport.execute(cmd, timeout=300)
            if res.ok and os.path.exists(path) and os.path.getsize(path) > 0:
                try:
                    snap = load_coverage(path, fmt=self.coverage_format)
                    if not snap.is_empty():
                        snap.cycles = snap.cycles or 0.0
                        return snap
                except Exception:  # noqa: BLE001 - fall through to text mode
                    pass
            res = self.transport.execute(tcl.coverage_report_text(), timeout=300)
            if res.ok and res.stdout.strip():
                snap = parse_text_report(res.stdout, source="live-text")
                if not snap.is_empty():
                    return snap
            return CoverageSnapshot(source="live-empty")
        finally:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:  # pragma: no cover
                pass

    # ------------------------------------------------------------------- time
    def now(self) -> Tuple[float, float]:
        """Return ``(sim_time_ns, cycle_estimate)`` from the simulator clock."""
        try:
            res = self.transport.execute("examine -time", timeout=30)
        except (TransportError, CommandError):
            return 0.0, 0.0
        if not res.ok or not res.stdout.strip():
            return 0.0, 0.0
        text = res.stdout.strip().splitlines()[-1]
        value = 0.0
        for token in text.replace("#", " ").split():
            num = tcl.parse_value(token)[0]
            if num is not None:
                value = float(num)
                break
        unit = 1.0
        low = text.lower()
        for name, scale in (("fs", 1e-6), ("ps", 1e-3), ("ns", 1.0), ("us", 1e3), ("ms", 1e6)):
            if name in low:
                unit = scale
                break
        return value * unit, 0.0
