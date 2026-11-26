"""The backend contract: how a campaign actually runs simulations.

Two families implement it:

* :class:`aiduvo.srie.optimizer.RuntimeBackend` -- drives a *live* simulator
  through SRIE and can steer it mid-run.
* :class:`aiduvo.blackbox.backend.BlackboxBackend` -- drives the simulator as a
  closed box: seeds, plusargs, run length, transcript and coverage database.

Both return the same :class:`EpisodeResult`, so rewards, policies, storage and
reporting are shared and the three-way comparison is apples-to-apples.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from aiduvo.coverage.model import CoverageSnapshot
from aiduvo.core.space import FactoredActionSpace
from aiduvo.core.types import Action, Budget, EpisodeResult, Mode


@dataclass
class BackendInfo:
    """What the backend learned before the campaign starts."""

    focus_groups: List[str] = field(default_factory=list)
    knob_profiles: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "focus_groups": self.focus_groups, "knob_profiles": self.knob_profiles,
            "tests": self.tests, "capabilities": self.capabilities, "notes": self.notes,
        }


InnerPolicyFactory = Callable[[int, int], Any]


class Backend(ABC):
    """One way of obtaining coverage from a design."""

    name: str = "backend"
    mode: Mode = Mode.BASELINE

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda _m: None)
        self.space: Optional[FactoredActionSpace] = None
        self._cumulative: Optional[CoverageSnapshot] = None

    # ---------------------------------------------------------------- lifecycle
    @abstractmethod
    def prepare(self) -> BackendInfo: ...

    def bind_space(self, space: FactoredActionSpace) -> None:
        self.space = space

    @abstractmethod
    def run(self, action: Action, run_index: int, budget: Budget) -> EpisodeResult: ...

    def close(self) -> None: ...

    # ---------------------------------------------------------------- coverage
    @property
    def cumulative(self) -> Optional[CoverageSnapshot]:
        return self._cumulative

    def merge(self, snap: CoverageSnapshot) -> CoverageSnapshot:
        if self._cumulative is None or self._cumulative.is_empty():
            self._cumulative = snap
        else:
            self._cumulative = self._cumulative.merged_with(snap)
        return self._cumulative
