"""Coarse role inference for discovered signals.

The patterns below are *conventions*, not project knowledge: almost every design
in existence calls its clock something containing ``clk`` and its reset
something containing ``rst``.  If a project deviates, the patterns are
configurable and nothing breaks -- worst case a signal is classified
``unknown`` and treated conservatively (observe only, never drive).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence

from aiduvo.srie.introspection import Hierarchy


class SemanticRole(str, Enum):
    CLOCK = "clock"
    RESET = "reset"
    DATA = "data"
    CONTROL = "control"
    HANDSHAKE = "handshake"
    STATUS = "status"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


DEFAULT_RULES: Sequence[tuple] = (
    (SemanticRole.CLOCK, r"(^|[_/])(clk|clock|ck|cclk|aclk|hclk|sclk|clk_i|sys_clk)($|[_/])"),
    (SemanticRole.RESET, r"(^|[_/])(rst|reset|resetn|rstn|nrst|rst_n|reset_n|arst|srst)($|[_/])"),
    (SemanticRole.HANDSHAKE, r"(^|[_/])(valid|vld|ready|rdy|ack|req|grant|vld_i|vld_o|handshake)($|[_/])"),
    (SemanticRole.CONTROL, r"(^|[_/])(en|enable|mode|sel|start|stop|last|first|err|error|irq|int)($|[_/])"),
    (SemanticRole.DATA, r"(^|[_/])(data|dat|din|dout|payload|addr|address|wdata|rdata|be|strb)($|[_/])"),
    (SemanticRole.STATUS, r"(^|[_/])(out|status|state|q|cnt|count|full|empty|flags?)($|[_/])"),
)


@dataclass
class SignalRole:
    path: str
    role: SemanticRole
    direction: str = "unknown"
    width: Optional[int] = None
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path, "role": str(self.role), "direction": self.direction,
            "width": self.width, "confidence": self.confidence,
        }


class SemanticLayer:
    """Annotates a discovered hierarchy with coarse roles."""

    def __init__(self, rules: Optional[Sequence[tuple]] = None):
        self.rules = [
            (role, re.compile(rx, re.I)) for role, rx in (rules or DEFAULT_RULES)
        ]

    def classify(self, path: str, direction: str = "unknown", width: Optional[int] = None) -> SignalRole:
        leaf = path.rstrip("/").split("/")[-1]
        for role, rx in self.rules:
            if rx.search(leaf) or rx.search(path):
                conf = 0.9 if rx.search(leaf) else 0.6
                return SignalRole(path=path, role=role, direction=direction, width=width, confidence=conf)
        if direction == "output":
            return SignalRole(path=path, role=SemanticRole.STATUS, direction=direction,
                              width=width, confidence=0.3)
        if width and width > 1:
            return SignalRole(path=path, role=SemanticRole.DATA, direction=direction,
                              width=width, confidence=0.3)
        return SignalRole(path=path, role=SemanticRole.UNKNOWN, direction=direction, width=width)

    def annotate(self, hierarchy: Hierarchy) -> List[SignalRole]:
        return [
            self.classify(n.path, n.direction, n.width) for n in hierarchy.nodes.values()
        ]

    def by_role(self, roles: Iterable[SignalRole]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for r in roles:
            out.setdefault(str(r.role), []).append(r.path)
        return out

    def drive_order(self, roles: Iterable[SignalRole]) -> List[str]:
        """Order force targets: data first, control next, never clock/reset."""
        priority = {
            SemanticRole.DATA: 0,
            SemanticRole.CONTROL: 1,
            SemanticRole.HANDSHAKE: 2,
            SemanticRole.STATUS: 3,
            SemanticRole.UNKNOWN: 4,
            SemanticRole.CLOCK: 90,
            SemanticRole.RESET: 91,
        }
        ordered = sorted(roles, key=lambda r: (priority.get(r.role, 50), r.path))
        return [r.path for r in ordered if r.role not in (SemanticRole.CLOCK, SemanticRole.RESET)]

    def summary(self, roles: Sequence[SignalRole]) -> str:
        groups = self.by_role(roles)
        lines = [f"semantic roles for {len(roles)} discovered signals"]
        for role in SemanticRole:
            paths = groups.get(str(role), [])
            if paths:
                lines.append(f"  {str(role):<10s} {len(paths):>4d}  {', '.join(paths[:4])}"
                             + (" ..." if len(paths) > 4 else ""))
        return "\n".join(lines)
