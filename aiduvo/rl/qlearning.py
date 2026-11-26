"""Tabular Q-learning over a discretised coverage state.

Small, fast, and easy to explain to a verification engineer: the state is the
coarse "shape" of the coverage situation, the action is a joint decision index.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aiduvo.rl.base import Policy, register

# Feature indices in aiduvo.core.space.FEATURE_NAMES
_CLOSURE, _DELTA, _NOVELTY, _ZERO, _PLATEAU = 0, 2, 4, 6, 13


def _bucket(value: float, edges: List[float]) -> int:
    for i, e in enumerate(edges):
        if value < e:
            return i
    return len(edges)


@register
class QLearningPolicy(Policy):
    """Epsilon-greedy tabular Q-learning with optimistic initialisation."""

    name = "qlearning"
    learns = True

    def __init__(self, n_actions: int, state_dim: int, seed: int = 0, alpha: float = 0.25,
                 gamma: float = 0.95, epsilon: float = 0.25, epsilon_min: float = 0.03,
                 epsilon_decay: float = 0.98, optimistic: float = 0.5, **kwargs: Any):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.alpha = float(alpha)
        self.gamma = float(gamma)
        self.epsilon = float(epsilon)
        self.epsilon_min = float(epsilon_min)
        self.epsilon_decay = float(epsilon_decay)
        self.optimistic = float(optimistic)
        self.Q: Dict[Tuple[int, ...], np.ndarray] = {}

    # ------------------------------------------------------------ discretising
    def _key(self, state: np.ndarray) -> Tuple[int, ...]:
        s = np.asarray(state, dtype=float).reshape(-1)
        get = lambda i: float(s[i]) if i < s.size else 0.0
        return (
            _bucket(get(_CLOSURE), [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.98]),
            _bucket(get(_DELTA), [0.0, 0.15]),
            _bucket(get(_NOVELTY), [0.0, 0.1, 0.4]),
            _bucket(get(_ZERO), [0.1, 0.3, 0.6]),
            _bucket(get(_PLATEAU), [0.05, 0.2]),
        )

    def _row(self, key: Tuple[int, ...]) -> np.ndarray:
        row = self.Q.get(key)
        if row is None:
            row = np.full(self.n_actions, self.optimistic)
            self.Q[key] = row
        return row

    # ------------------------------------------------------------------ select
    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        row = self._row(self._key(state))
        if explore and self.rng.random() < self.epsilon:
            cand = np.arange(self.n_actions)
            if mask is not None:
                allowed = cand[mask > 0]
                if allowed.size:
                    cand = allowed
            return int(self.rng.choice(cand))
        v = row.copy()
        if mask is not None:
            v = np.where(mask > 0, v, -np.inf)
        return int(np.argmax(v))

    # ----------------------------------------------------------------- observe
    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        k = self._key(state)
        row = self._row(k)
        a = int(action) % self.n_actions
        if next_state is None or done:
            target = reward
        else:
            target = reward + self.gamma * float(np.max(self._row(self._key(next_state))))
        td = target - row[a]
        row[a] += self.alpha * td
        self.updates += 1
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return {"td_error": float(td), "states": float(len(self.Q))}

    def end_episode(self) -> None:
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def action_values(self) -> Optional[np.ndarray]:
        if not self.Q:
            return None
        return np.mean(np.stack(list(self.Q.values())), axis=0)

    def _npz_items(self) -> Dict[str, np.ndarray]:
        keys = sorted(self.Q.keys())
        return {
            "keys": np.array(keys, dtype=np.int64) if keys else np.zeros((0, 5), dtype=np.int64),
            "values": np.stack([self.Q[k] for k in keys]) if keys else np.zeros((0, self.n_actions)),
            "epsilon": np.array([self.epsilon]),
        }

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        if "keys" in data and "values" in data and len(data["keys"]):
            self.Q = {tuple(int(x) for x in k): np.array(v, dtype=float)
                      for k, v in zip(data["keys"], data["values"])}
        if "epsilon" in data:
            self.epsilon = float(np.asarray(data["epsilon"]).reshape(-1)[0])
