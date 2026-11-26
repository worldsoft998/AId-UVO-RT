"""Fixed-size experience replay buffer backed by numpy arrays."""

from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np


class Batch(NamedTuple):
    state: np.ndarray
    action: np.ndarray
    reward: np.ndarray
    next_state: np.ndarray
    done: np.ndarray


class ReplayBuffer:
    """Ring buffer of transitions; O(1) insert, O(batch) sample."""

    def __init__(self, capacity: int, state_dim: int, seed: int = 0):
        self.capacity = int(max(1, capacity))
        self.state_dim = int(state_dim)
        self.s = np.zeros((self.capacity, self.state_dim), dtype=np.float32)
        self.s2 = np.zeros((self.capacity, self.state_dim), dtype=np.float32)
        self.a = np.zeros(self.capacity, dtype=np.int64)
        self.r = np.zeros(self.capacity, dtype=np.float32)
        self.d = np.zeros(self.capacity, dtype=np.float32)
        self._idx = 0
        self._size = 0
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return self._size

    def push(self, s: np.ndarray, a: int, r: float, s2: Optional[np.ndarray], done: bool) -> None:
        i = self._idx
        self.s[i] = np.asarray(s, dtype=np.float32).reshape(-1)[: self.state_dim]
        s2 = s if s2 is None else s2
        self.s2[i] = np.asarray(s2, dtype=np.float32).reshape(-1)[: self.state_dim]
        self.a[i] = int(a)
        self.r[i] = float(r)
        self.d[i] = 1.0 if done else 0.0
        self._idx = (self._idx + 1) % self.capacity
        self._size = min(self._size + 1, self.capacity)

    def sample(self, batch_size: int) -> Batch:
        n = min(batch_size, self._size)
        idx = self.rng.integers(0, self._size, size=n)
        return Batch(self.s[idx], self.a[idx], self.r[idx], self.s2[idx], self.d[idx])

    def all(self) -> Batch:
        return Batch(self.s[: self._size], self.a[: self._size], self.r[: self._size],
                     self.s2[: self._size], self.d[: self._size])
