"""The blackbox knob space: everything a *closed* simulator can still be told.

In blackbox mode the optimizer may not look inside the simulator.  What it can do
is what any verification engineer does from a shell:

* choose the random seed (``-sv_seed``) -- universally available;
* choose how long each run may take (the ``run`` command in the do-file);
* pick a named *profile*: a set of plusargs and/or standard UVM config settings;
* choose which test / do-file to run.

None of that requires knowing a signal, a class or a covergroup name.  Plusarg
and ``uvm_set_config_*`` names live in a user-supplied inventory file -- the
framework never hard-codes them, and the inventory can be produced by
``aiduvo discover --inventory``.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

KNOB_KINDS = (
    "plusarg_int",
    "plusarg_flag",
    "plusarg_enum",
    "plusarg_string",
    "uvm_config_int",
    "uvm_config_string",
)

UVM_CONFIG_TEMPLATE = "+uvm_set_config_int={comp},{field},{value}"


@dataclass
class Knob:
    """One externally settable control of the simulation."""

    name: str
    kind: str = "plusarg_enum"
    values: List[str] = field(default_factory=list)
    lo: int = 0
    hi: int = 100
    step: int = 1
    template: str = ""
    weight: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KNOB_KINDS:
            raise ValueError(f"knob {self.name!r}: unknown kind {self.kind!r}")

    def sample(self, rng: np.random.Generator) -> str:
        if self.kind in ("plusarg_enum", "plusarg_string", "uvm_config_string") and self.values:
            return str(self.values[int(rng.integers(0, len(self.values)))])
        if self.kind in ("plusarg_int", "uvm_config_int"):
            steps = max(1, (self.hi - self.lo) // max(1, self.step))
            return str(self.lo + self.step * int(rng.integers(0, steps + 1)))
        if self.kind == "plusarg_flag":
            return "1" if int(rng.integers(0, 2)) else ""
        return str(self.values[0]) if self.values else ""

    def options(self, max_options: int = 8) -> List[str]:
        """Enumerate representative values (used to build knob profiles)."""
        if self.kind in ("plusarg_enum", "plusarg_string", "uvm_config_string"):
            return [str(v) for v in self.values][:max_options] or [""]
        if self.kind in ("plusarg_int", "uvm_config_int"):
            span = max(1, (self.hi - self.lo) // max(1, self.step))
            n = min(max_options, span + 1)
            return [str(self.lo + int(round(i * span / max(1, n - 1))) * self.step) for i in range(n)]
        return ["", "1"]

    def to_plusarg(self, value: Any) -> str:
        """Render one knob assignment as a simulator argument."""
        value = "" if value is None else str(value)
        if self.kind == "plusarg_flag":
            return f"+{self.name}" if value not in ("", "0", "false", "False") else ""
        if self.kind == "uvm_config_int":
            tpl = self.template or UVM_CONFIG_TEMPLATE
            comp, field_name = (self.name.split("::", 1) + [self.name])[:2]
            return tpl.format(comp=comp, field=field_name, value=value)
        if self.kind == "uvm_config_string":
            comp, field_name = (self.name.split("::", 1) + [self.name])[:2]
            tpl = self.template or "+uvm_set_config_string={comp},{field},{value}"
            return tpl.format(comp=comp, field=field_name, value=value)
        return f"+{self.name}={value}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "values": self.values,
            "lo": self.lo, "hi": self.hi, "step": self.step,
            "template": self.template, "weight": self.weight, "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Knob":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class KnobProfile:
    """A named, reusable assignment of the whole knob space."""

    name: str
    values: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "values": self.values, "description": self.description}


class KnobSpace:
    """Knob inventory plus the profile set the RL agent chooses from."""

    def __init__(self, knobs: Optional[Sequence[Knob]] = None,
                 profiles: Optional[Sequence[KnobProfile]] = None):
        self.knobs: List[Knob] = list(knobs or [])
        self.profiles: List[KnobProfile] = list(profiles or [])
        if not self.profiles:
            self.profiles = self.default_profiles()

    # ------------------------------------------------------------------ build
    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "KnobSpace":
        d = dict(d or {})
        knobs = [Knob.from_dict(k) for k in d.get("knobs") or []]
        profiles = [KnobProfile(**p) for p in d.get("profiles") or []]
        return cls(knobs, profiles)

    @classmethod
    def load(cls, path: str) -> "KnobSpace":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "knobs": [k.to_dict() for k in self.knobs],
            "profiles": [p.to_dict() for p in self.profiles],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    # --------------------------------------------------------------- profiles
    def default_profiles(self, n: int = 4, seed: int = 0) -> List[KnobProfile]:
        """Deterministic spread of profiles over the knob space.

        ``none`` is always first so that "AI off" is a genuine control group;
        the rest are latin-hypercube-ish spreads that differ in every knob.
        """
        profiles = [KnobProfile(name="none", values={}, description="no knob overrides")]
        if not self.knobs:
            return profiles
        rng = np.random.default_rng(seed)
        names = ["conservative", "balanced", "aggressive", "corner_heavy", "sweep"]
        for i in range(max(0, n - 1)):
            values = {}
            for j, knob in enumerate(self.knobs):
                opts = knob.options()
                idx = (i + j + int(rng.integers(0, max(1, len(opts))))) % max(1, len(opts))
                values[knob.name] = opts[idx]
            profiles.append(
                KnobProfile(
                    name=names[i] if i < len(names) else f"profile_{i}",
                    values=values,
                    description="auto-generated profile",
                )
            )
        return profiles

    def profile(self, name: str) -> KnobProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        return self.profiles[0]

    def profile_names(self) -> List[str]:
        return [p.name for p in self.profiles]

    # ------------------------------------------------------------------ apply
    def plusargs(self, profile: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Convert a profile (plus ad-hoc overrides) into plusarg/extra args."""
        values = dict(self.profile(profile).values)
        values.update(extra or {})
        out: Dict[str, Any] = {}
        for knob in self.knobs:
            if knob.name not in values:
                continue
            arg = knob.to_plusarg(values[knob.name])
            if not arg:
                continue
            if arg.startswith("+"):
                key, _, val = arg[1:].partition("=")
                out[key] = val if val else True
            else:
                out[arg] = True
        return out

    def describe(self) -> str:
        lines = [f"knob space: {len(self.knobs)} knobs, {len(self.profiles)} profiles"]
        for k in self.knobs:
            lines.append(f"  {k.name:<24s} {k.kind:<16s} {k.description}")
        for p in self.profiles:
            lines.append(f"  profile {p.name:<16s} {p.values}")
        return "\n".join(lines)


class SeedStrategy:
    """Turns the ``seed_mode`` action into a concrete seed."""

    MODES = ("fresh", "mutate_best", "sweep", "resume_best")

    def __init__(self, base_seed: int = 0, rng: Optional[np.random.Generator] = None,
                 seed_span: int = 2 ** 31 - 1):
        self.base_seed = int(base_seed)
        self.rng = rng or np.random.default_rng(base_seed)
        self.seed_span = int(seed_span)
        self.best_seed: Optional[int] = None
        self.best_score: float = -1e18
        self.used: List[int] = []

    def pick(self, mode: str, run_index: int) -> int:
        mode = (mode or "fresh").lower()
        if mode == "sweep":
            seed = self.base_seed + run_index
        elif mode == "resume_best" and self.best_seed is not None:
            seed = self.best_seed
        elif mode == "mutate_best" and self.best_seed is not None:
            delta = int(self.rng.integers(1, 1_000_000))
            seed = (self.best_seed + delta) % self.seed_span
        else:
            seed = int(self.rng.integers(0, self.seed_span))
        self.used.append(seed)
        return seed

    def report(self, seed: int, score: float) -> None:
        if score > self.best_score:
            self.best_score = score
            self.best_seed = seed

    def to_dict(self) -> Dict[str, Any]:
        return {"best_seed": self.best_seed, "best_score": self.best_score, "used": self.used}
