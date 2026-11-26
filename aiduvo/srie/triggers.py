"""Asynchronous event plumbing.

A trigger installed with ``when`` runs a Tcl body inside the simulator the instant
a signal changes.  The body pushes one JSON line back over the SRIE channel, so
Python learns about the event *while the simulator is still running* -- this is
the mechanism behind "runtime / instantaneous" optimisation.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from aiduvo.srie.protocol import Event
from aiduvo.srie.transport import Transport


def trigger_body(kind: str, **fields: Any) -> str:
    """Build the Tcl body that emits one event.

    Values wrapped in ``[...]`` are left for Tcl to substitute, e.g.
    ``t="[now]"`` becomes the simulator's current time.
    """
    payload = {"kind": kind, **fields}
    text = json.dumps(payload)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'srie_evt "{escaped}"'


class EventBus:
    """Drains the transport's event queue and dispatches to subscribers."""

    def __init__(self, transport: Transport):
        self.transport = transport
        self.handlers: Dict[str, List[Callable[[Event], None]]] = {}
        self.history: List[Event] = []
        self.counts: Counter = Counter()
        self.max_history = 5000

    def on(self, kind: str, fn: Callable[[Event], None]) -> None:
        self.handlers.setdefault(kind, []).append(fn)

    def poll(self) -> List[Event]:
        events = self.transport.poll_events()
        for evt in events:
            self.counts[evt.kind] += 1
            self.history.append(evt)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history :]
            for fn in self.handlers.get(evt.kind, []):
                fn(evt)
            for fn in self.handlers.get("*", []):
                fn(evt)
        return events

    def wait(self, kind: Optional[str] = None, timeout: float = 30.0, poll_s: float = 0.01) -> Optional[Event]:
        """Block until an event arrives (optionally of a given kind)."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            for evt in self.poll():
                if kind is None or evt.kind == kind:
                    return evt
            time.sleep(poll_s)
        return None

    def stats(self) -> Dict[str, Any]:
        return {"total": sum(self.counts.values()), "by_kind": dict(self.counts)}
