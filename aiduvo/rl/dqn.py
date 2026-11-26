"""Deep Q-Network (double DQN) with a numpy MLP.

Used when the state space is too rich for a table: continuous closure/entropy/
plateau features drive a small MLP that scores joint actions.  Experience replay
plus a periodically synced target network keep the bootstrap stable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

from aiduvo.rl.base import Policy, register
from aiduvo.rl.nn import Adam, MLP
from aiduvo.rl.replay import ReplayBuffer


@register
class DQNPolicy(Policy):
    """Double DQN with epsilon-greedy exploration and Huber loss."""

    name = "dqn"
    learns = True

    def __init__(
        self,
        n_actions: int,
        state_dim: int,
        seed: int = 0,
        hidden: Tuple[int, ...] = (64, 64),
        lr: float = 1e-3,
        gamma: float = 0.95,
        batch_size: int = 32,
        buffer_size: int = 4096,
        target_sync: int = 100,
        epsilon: float = 0.9,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        warmup: int = 64,
        double: bool = True,
        train_every: int = 1,
        activation: str = "tanh",
        **kwargs: Any,
    ):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.gamma = float(gamma)
        self.batch_size = int(batch_size)
        self.target_sync = int(target_sync)
        self.epsilon = float(epsilon)
        self.epsilon_min = float(epsilon_min)
        self.epsilon_decay = float(epsilon_decay)
        self.warmup = int(warmup)
        self.double = bool(double)
        self.train_every = max(1, int(train_every))
        sizes = [state_dim, *hidden, n_actions]
        self.online = MLP(sizes, rng=self.rng, activation=activation)
        self.target = self.online.copy()
        self.opt = Adam(lr=lr)
        self.buffer = ReplayBuffer(buffer_size, state_dim, seed=seed + 1)
        self.last_loss = 0.0

    # ------------------------------------------------------------------ select
    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        if explore and self.rng.random() < self.epsilon:
            cand = np.arange(self.n_actions)
            if mask is not None:
                allowed = cand[mask > 0]
                if allowed.size:
                    cand = allowed
            return int(self.rng.choice(cand))
        q = self.online(np.asarray(state, dtype=float).reshape(1, -1))[0]
        if mask is not None:
            q = np.where(mask > 0, q, -np.inf)
        return int(np.argmax(q))

    # ----------------------------------------------------------------- observe
    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        self.buffer.push(state, action, reward, next_state, done)
        self.updates += 1
        out: Dict[str, float] = {}
        if len(self.buffer) >= max(self.warmup, self.batch_size) and self.updates % self.train_every == 0:
            out = self._train_step()
        if self.updates % max(1, self.target_sync // 4) == 0:
            self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return out

    def _train_step(self) -> Dict[str, float]:
        b = self.buffer.sample(self.batch_size)
        n = b.state.shape[0]
        q_all, cache = self.online.forward(b.state)
        idx = np.arange(n)
        q_sa = q_all[idx, b.action]

        q_next_target = self.target(b.next_state)
        if self.double:
            q_next_online = self.online(b.next_state)
            best = np.argmax(q_next_online, axis=1)
            q_next = q_next_target[idx, best]
        else:
            q_next = q_next_target.max(axis=1)
        target = b.reward + self.gamma * (1.0 - b.done) * q_next

        td = q_sa - target
        huber = np.where(np.abs(td) <= 1.0, td, np.sign(td))
        dout = np.zeros_like(q_all)
        dout[idx, b.action] = huber / n
        grads = self.online.backward(cache, dout)
        self.opt.step(self.online.params(), grads)
        if self.updates % max(1, self.target_sync) == 0:
            self.target.clone_from(self.online)
        self.last_loss = float(np.mean(0.5 * np.minimum(np.abs(td), 1.0) ** 2 + 0.5 * np.abs(np.clip(np.abs(td) - 1, 0, None))))
        return {"loss": self.last_loss, "q_mean": float(q_sa.mean()), "epsilon": self.epsilon}

    def end_episode(self) -> None:
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def action_values(self) -> Optional[np.ndarray]:
        return None

    def _npz_items(self) -> Dict[str, np.ndarray]:
        items: Dict[str, np.ndarray] = {"epsilon": np.array([self.epsilon])}
        for i, (w, b) in enumerate(zip(self.online.W, self.online.b)):
            items[f"W{i}"] = w
            items[f"b{i}"] = b
        for i, (w, b) in enumerate(zip(self.target.W, self.target.b)):
            items[f"tW{i}"] = w
            items[f"tb{i}"] = b
        return items

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        n = len(self.online.W)
        self.online.set_params([data[f"W{i}"] for i in range(n)] + [data[f"b{i}"] for i in range(n)])
        if all(f"tW{i}" in data for i in range(n)):
            self.target.set_params([data[f"tW{i}"] for i in range(n)] + [data[f"tb{i}"] for i in range(n)])
        if "epsilon" in data:
            self.epsilon = float(np.asarray(data["epsilon"]).reshape(-1)[0])
