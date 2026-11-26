"""Incremental transcript watching.

In blackbox mode the transcript is the only window into the run, so it is read
while the simulator is still writing it: a fatal error, an assertion or a
coverage plateau can cut a run short instead of waiting for the clock to run out.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PATTERNS = {
    "fatal": re.compile(r"\*\*\s*(?:Fatal|FATAL)|UVM_FATAL\s*:|FATAL ERROR", re.I),
    "error": re.compile(r"\*\*\s*Error|UVM_ERROR\s*:|Error(?:-\[|:)\s", re.I),
    "warning": re.compile(r"\*\*\s*Warning|UVM_WARNING\s*:", re.I),
    "assert": re.compile(r"assertion.*(?:failed|failure)|\bSVA\b.*fail", re.I),
    "finish": re.compile(r"\*\*\s*Note:\s*\$finish|simulation (?:finished|ended)", re.I),
    "coverage": re.compile(r"(?:total|overall)\s+coverage[^0-9]*(\d+(?:\.\d+)?)\s*%", re.I),
    "time": re.compile(r"(?:sim(?:ulation)?\s*time|at\s+time)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*(fs|ps|ns|us|ms|s)\b", re.I),
    "marker": re.compile(r"^\s*#?\s*AIDUVRUN\s+(\{.*\})\s*$"),
}

_UNIT_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}


@dataclass
class LogEvent:
    kind: str
    text: str
    line_no: int = 0
    value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "line_no": self.line_no, "value": self.value}


@dataclass
class TranscriptSummary:
    lines: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    first_error: str = ""
    sim_time_ns: float = 0.0
    finished: bool = False
    coverage_pct: Optional[float] = None
    markers: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lines": self.lines, "counts": self.counts, "first_error": self.first_error,
            "sim_time_ns": self.sim_time_ns, "finished": self.finished,
            "coverage_pct": self.coverage_pct, "markers": self.markers,
        }

    @property
    def errors(self) -> int:
        return self.counts.get("error", 0) + self.counts.get("fatal", 0)


class TranscriptWatcher:
    """Tails a transcript file and classifies new lines."""

    def __init__(self, path: str, patterns: Optional[Dict[str, re.Pattern]] = None,
                 max_events: int = 20000):
        self.path = path
        self.patterns = patterns or PATTERNS
        self.offset = 0
        self.summary = TranscriptSummary()
        self.events: List[LogEvent] = []
        self.max_events = max_events
        self._buffer = ""

    def poll(self) -> List[LogEvent]:
        """Return events found since the last call (never blocks)."""
        if not os.path.exists(self.path):
            return []
        try:
            size = os.path.getsize(self.path)
            if size < self.offset:  # file truncated / replaced
                self.offset = 0
                self._buffer = ""
            if size == self.offset:
                return []
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
                self.offset = fh.tell()
        except OSError:
            return []
        return self._consume(chunk)

    def flush(self) -> List[LogEvent]:
        """Classify a trailing line that was written without a newline.

        Simulators routinely end the transcript with `$finish` and no newline,
        so the last line is held back while tailing and released here.
        """
        if not self._buffer:
            return []
        text, self._buffer = self._buffer, ""
        return self._classify(text)

    def _consume(self, chunk: str) -> List[LogEvent]:
        new: List[LogEvent] = []
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split("\n")
        for raw in lines:
            new.extend(self._classify(raw))
        return new

    def _classify(self, raw: str) -> List[LogEvent]:
        line = raw.rstrip("\r")
        if not line.strip():
            return []
        out: List[LogEvent] = []
        self.summary.lines += 1
        for kind, rx in self.patterns.items():
            m = rx.search(line)
            if not m:
                continue
            value: Optional[float] = None
            if kind == "time":
                value = float(m.group(1)) * _UNIT_NS.get(m.group(2).lower(), 1.0)
                self.summary.sim_time_ns = max(self.summary.sim_time_ns, value)
            elif kind == "coverage":
                value = float(m.group(1))
                self.summary.coverage_pct = value
            elif kind == "marker":
                try:
                    self.summary.markers.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    pass
            elif kind == "finish":
                self.summary.finished = True
            if kind in ("error", "fatal") and not self.summary.first_error:
                self.summary.first_error = line.strip()
            self.summary.counts[kind] = self.summary.counts.get(kind, 0) + 1
            evt = LogEvent(kind=kind, text=line.strip(), line_no=self.summary.lines, value=value)
            out.append(evt)
            self.events.append(evt)
            if len(self.events) > self.max_events:
                self.events = self.events[-self.max_events :]
        return out

    def should_abort(self, abort_on_error: bool = True, abort_on_assert: bool = False) -> bool:
        if abort_on_error and (self.summary.counts.get("fatal", 0) or self.summary.counts.get("error", 0)):
            return True
        if abort_on_assert and self.summary.counts.get("assert", 0):
            return True
        return False

    def tail(self, n: int = 20) -> str:
        return "\n".join(e.text for e in self.events[-n:])


def scan_text(text: str) -> TranscriptSummary:
    """One-shot parse of a finished transcript (including a final line with no newline)."""
    watcher = TranscriptWatcher(path="")
    watcher._consume(text)
    watcher.flush()
    return watcher.summary


def wait_for_file(path: str, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True
        time.sleep(interval)
    return os.path.exists(path)
