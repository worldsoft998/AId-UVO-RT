"""Wire protocol shared by every SRIE transport.

The simulator side runs a handful of tiny Tcl helper procs (see
``scripts/questa/srie_bootstrap.do``).  Python writes one command per line; the
simulator answers with free-form text terminated by a sentinel line.  Events
pushed *from* the simulator (value-change triggers, ``onbreak`` hooks) arrive on
the same channel as ``@@SRIE_EVT {...}@@`` lines, which is what makes the
optimizer instantaneous: it can react in the middle of a ``run`` command.

    python  ->  <tcl command>\n
    sim     ->  ... output lines ...
    sim     ->  @@SRIE_END <id> rc=<0|1>@@
    sim     ->  @@SRIE_EVT {"kind": "...", ...}@@      (asynchronous, any time)
    sim     ->  @@SRIE_READY <version>@@               (once, at startup)
    sim     ->  @@SRIE_FATAL <message>@@               (fatal simulator error)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PROMPT_PREFIX = "@@SRIE_END"
EVT_PREFIX = "@@SRIE_EVT"
READY_PREFIX = "@@SRIE_READY"
FATAL_PREFIX = "@@SRIE_FATAL"

_END_RE = re.compile(r"^@@SRIE_END\s+(\d+)\s+rc=(\d+)@@\s*$")
_NOISE_RE = re.compile(r"^(VSIM\(?\d*\)?>\s*|VSIM\s+\d+>\s*|>\s*)$")


class SRIEError(RuntimeError):
    """Base class for every SRIE failure."""


class TransportError(SRIEError):
    """The channel to the simulator died or timed out."""


class CommandError(SRIEError):
    """The simulator rejected a command."""

    def __init__(self, command: str, message: str):
        super().__init__(f"{command!r} failed: {message}")
        self.command = command
        self.message = message


class CapabilityError(SRIEError):
    """A required introspection/reflection capability is missing."""


@dataclass
class CommandResult:
    ok: bool
    stdout: str = ""
    error: str = ""
    elapsed: float = 0.0
    command: str = ""

    @property
    def lines(self) -> List[str]:
        return [ln for ln in self.stdout.splitlines() if ln.strip()]

    def require_ok(self) -> "CommandResult":
        if not self.ok:
            raise CommandError(self.command, self.error or "unknown error")
        return self


@dataclass
class Event:
    """An asynchronous notification pushed by the simulator."""

    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    recv_time: float = field(default_factory=time.time)

    def __getitem__(self, key: str) -> Any:
        return self.payload.get(key)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "payload": self.payload, "recv_time": self.recv_time}


def encode_event(kind: str, **payload: Any) -> str:
    """Simulator-side helper: build the line a Tcl proc should print."""
    return f"{EVT_PREFIX} {json.dumps({'kind': kind, **payload})}@@"


def parse_event_line(line: str) -> Optional[Event]:
    if not line.startswith(EVT_PREFIX):
        return None
    body = line[len(EVT_PREFIX) :].rstrip()
    if body.endswith("@@"):
        body = body[:-2]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return Event(kind="malformed", payload={"raw": line})
    kind = str(data.pop("kind", "event"))
    return Event(kind=kind, payload=data)


def is_noise(line: str) -> bool:
    """Simulator chatter that must not pollute command output."""
    return bool(_NOISE_RE.match(line))


def parse_end_line(line: str) -> Optional[tuple]:
    m = _END_RE.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)) == 0
