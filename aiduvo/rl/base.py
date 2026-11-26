"""Policy interface, registry and the non-learning baselines.

A policy only ever sees a fixed-size state vector and an action count.  It has no
idea what the actions mean, which is what makes every learner in this package
reusable across designs, simulators and HDLs.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

import numpy as np


class Policy(ABC):
    """Common contract for every learner and baseline."""

    name: str = "base"
    learns: bool = True

    def __init__(self, n_actions: int, state_dim: int, seed: int = 0, **kwargs: Any):
        if n_actions < 1:
            raise ValueError("n_actions must be >= 1")
        self.n_actions = int(n_actions)
        self.state_dim = int(state_dim)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.updates = 0
        self.config = dict(kwargs)

    # ---------------------------------------------------------------- decision
    @abstractmethod
    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        """Return an action index."""

    # ---------------------------------------------------------------- learning
    def observe(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: Optional[np.ndarray] = None,
        done: bool = False,
    ) -> Dict[str, float]:
        """Learn from one transition.  Returns diagnostics (losses etc.)."""
        return {}

    def end_episode(self) -> None:
        """Hook called when a simulation run ends."""

    # -------------------------------------------------------------- inspection
    def info(self) -> Dict[str, Any]:
        return {
            "policy": self.name,
            "n_actions": self.n_actions,
            "state_dim": self.state_dim,
            "seed": self.seed,
            "updates": self.updates,
            "learns": self.learns,
            **{k: v for k, v in self.config.items() if isinstance(v, (int, float, str, bool))},
        }

    def action_values(self) -> Optional[np.ndarray]:
        """Optional per-action score, used by the reporter for explanations."""
        return None

    # ------------------------------------------------------------ persistence
    def _npz_items(self) -> Dict[str, np.ndarray]:
        return {}

    def _extra_state(self) -> Dict[str, Any]:
        return {}

    def save(self, path: str) -> None:
        """Persist to ``<path>.npz`` + ``<path>.json`` (path may omit extension)."""
        base = path[:-4] if path.endswith(".npz") else path
        parent = os.path.dirname(os.path.abspath(base))
        os.makedirs(parent, exist_ok=True)
        np.savez(base + ".npz", **self._npz_items())
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump(
                {"class": type(self).__name__, "info": self.info(), "extra": self._extra_state()},
                fh,
                indent=2,
                default=str,
            )

    def load(self, path: str) -> None:
        base = path[:-4] if path.endswith(".npz") else path
        if not os.path.exists(base + ".npz"):
            return
        with np.load(base + ".npz", allow_pickle=True) as data:
            self._load_npz(dict(data))
        if os.path.exists(base + ".json"):
            with open(base + ".json", "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            self.updates = int(meta.get("info", {}).get("updates", 0))

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        pass


# ---------------------------------------------------------------------------
# Non-learning baselines
# ---------------------------------------------------------------------------


class NullPolicy(Policy):
    """Always picks the default action (AI disabled)."""

    name = "none"
    learns = False

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        return 0


class RandomPolicy(Policy):
    """Uniform random action -- the honest 'no intelligence' control group."""

    name = "random"
    learns = False

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        return int(self.rng.integers(0, self.n_actions))


class RoundRobinPolicy(Policy):
    """Deterministic sweep -- reproducible control group."""

    name = "round_robin"
    learns = False

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._i = 0

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        a = self._i % self.n_actions
        self._i += 1
        return a

    def end_episode(self) -> None:
        self._i = (self._i + 1) % self.n_actions


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Type[Policy]] = {}


def register(cls: Type[Policy]) -> Type[Policy]:
    _REGISTRY[cls.name] = cls
    return cls


def available() -> List[str]:
    _ensure_loaded()
    return sorted(_REGISTRY)


_LOADED = False


def _ensure_loaded() -> None:
    """Import the learners (registration side effect) and the control policies.

    Guarded by an explicit flag rather than by ``_REGISTRY``: importing any
    learner module registers a class, so a non-empty registry does not mean the
    control policies were registered.
    """
    global _LOADED
    if _LOADED:
        return
    from aiduvo.rl import ann, bandit, dqn, ppo, qlearning  # noqa: F401  (registration side effects)

    for cls in (NullPolicy, RandomPolicy, RoundRobinPolicy):
        _REGISTRY.setdefault(cls.name, cls)
    _LOADED = True


def make_policy(
    name: str,
    n_actions: int,
    state_dim: int,
    seed: int = 0,
    **kwargs: Any,
) -> Policy:
    """Instantiate a policy by name (case/alias tolerant)."""
    _ensure_loaded()
    key = (name or "none").strip().lower().replace("-", "_")
    aliases = {
        "off": "none",
        "no_ai": "none",
        "baseline": "none",
        "lin_ucb": "linucb",
        "ucb": "linucb",
        "thompson_sampling": "thompson",
        "q_learning": "qlearning",
        "q": "qlearning",
        "deep_q": "dqn",
        "double_dqn": "dqn",
        "ann": "surrogate",
        "mlp": "surrogate",
    }
    key = aliases.get(key, key)
    if key not in _REGISTRY:
        raise KeyError(f"unknown policy {name!r}; available: {', '.join(sorted(_REGISTRY))}")
    cls = _REGISTRY[key]
    return cls(n_actions=n_actions, state_dim=state_dim, seed=seed, **kwargs)
