"""Contextual bandit learners.

Bandits are the right tool for the inter-run decision: a campaign only gets a few
dozen runs, so a sample-efficient, well-understood algorithm beats a deep RL
method.  All three learners here are O(d^2) per step and need no tuning to start.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from aiduvo.rl.base import Policy, register


@register
class LinUCBPolicy(Policy):
    """Disjoint linear UCB (Li et al., 2010).

    Each action keeps its own ridge-regression model of the reward as a linear
    function of the state vector, plus an exploration bonus that shrinks as the
    action is tried.  Ideal for seed/knob selection where rewards are smooth in
    the coverage state.
    """

    name = "linucb"
    learns = True

    def __init__(self, n_actions: int, state_dim: int, seed: int = 0, alpha: float = 0.6,
                 ridge: float = 1.0, **kwargs: Any):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.alpha = float(alpha)
        self.ridge = float(ridge)
        d = self.state_dim
        self.A = np.stack([np.eye(d) * self.ridge for _ in range(self.n_actions)])
        self.bvec = np.zeros((self.n_actions, d))
        self.theta = np.zeros((self.n_actions, d))
        self.counts = np.zeros(self.n_actions, dtype=int)
        self._cache: Dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------ select
    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        x = np.asarray(state, dtype=float).reshape(-1)
        if x.size != self.state_dim:
            x = np.resize(x, self.state_dim)
        scores = self.theta @ x
        if explore:
            for a in range(self.n_actions):
                if mask is not None and mask[a] <= 0:
                    scores[a] = -np.inf
                    continue
                try:
                    inv = np.linalg.solve(self.A[a], x)
                except np.linalg.LinAlgError:
                    inv = np.linalg.pinv(self.A[a]) @ x
                bonus = self.alpha * float(np.sqrt(max(0.0, x @ inv)))
                scores[a] += bonus
        elif mask is not None:
            scores = np.where(mask > 0, scores, -np.inf)
        a = int(np.argmax(scores))
        self._cache = {"x": x}
        return a

    # ----------------------------------------------------------------- observe
    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        x = np.asarray(state, dtype=float).reshape(-1)
        if x.size != self.state_dim:
            x = np.resize(x, self.state_dim)
        a = int(action) % self.n_actions
        self.A[a] += np.outer(x, x)
        self.bvec[a] += reward * x
        try:
            self.theta[a] = np.linalg.solve(self.A[a], self.bvec[a])
        except np.linalg.LinAlgError:
            self.theta[a] = np.linalg.pinv(self.A[a]) @ self.bvec[a]
        self.counts[a] += 1
        self.updates += 1
        pred = float(self.theta[a] @ x)
        return {"td_error": reward - pred}

    def action_values(self) -> Optional[np.ndarray]:
        return self.counts.astype(float)

    def _npz_items(self) -> Dict[str, np.ndarray]:
        return {"A": self.A, "bvec": self.bvec, "theta": self.theta, "counts": self.counts}

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        for k in ("A", "bvec", "theta", "counts"):
            if k in data:
                setattr(self, k, np.array(data[k]))


@register
class ThompsonPolicy(Policy):
    """Beta-Bernoulli Thompson sampling on a logistic squash of the reward.

    Cheap, self-tuning and very robust when rewards are noisy or the action set is
    small -- exactly the situation of "which knob profile next".
    """

    name = "thompson"
    learns = True

    def __init__(self, n_actions: int, state_dim: int, seed: int = 0, prior: float = 1.0,
                 temp: float = 1.0, **kwargs: Any):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.prior = float(prior)
        self.temp = float(temp)
        self.alpha = np.full(n_actions, self.prior)
        self.beta = np.full(n_actions, self.prior)
        self.counts = np.zeros(n_actions, dtype=int)
        self.reward_mean = np.zeros(n_actions)
        self.reward_scale = 1.0
        self._seen = 0

    def _squash(self, r: float) -> float:
        z = r / max(1e-9, self.reward_scale * self.temp)
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))))

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        samples = self.rng.beta(self.alpha, self.beta)
        if mask is not None:
            samples = np.where(mask > 0, samples, -np.inf)
        return int(np.argmax(samples))

    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        a = int(action) % self.n_actions
        self._seen += 1
        self.reward_mean[a] += (reward - self.reward_mean[a]) / max(1, self.counts[a] + 1)
        self.reward_scale = 0.98 * self.reward_scale + 0.02 * max(1e-6, abs(reward))
        p = self._squash(reward)
        self.alpha[a] += p
        self.beta[a] += 1.0 - p
        self.counts[a] += 1
        self.updates += 1
        return {"success_prob": p}

    def action_values(self) -> Optional[np.ndarray]:
        return self.alpha / np.maximum(1e-9, self.alpha + self.beta)

    def _npz_items(self) -> Dict[str, np.ndarray]:
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "counts": self.counts,
            "reward_mean": self.reward_mean,
        }

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        for k in ("alpha", "beta", "counts", "reward_mean"):
            if k in data:
                setattr(self, k, np.array(data[k]))


@register
class EpsilonGreedyPolicy(Policy):
    """Sample-average value estimate with decaying epsilon."""

    name = "epsilon_greedy"
    learns = True

    def __init__(self, n_actions: int, state_dim: int, seed: int = 0, epsilon: float = 0.2,
                 epsilon_min: float = 0.02, epsilon_decay: float = 0.97, **kwargs: Any):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.epsilon = float(epsilon)
        self.epsilon_min = float(epsilon_min)
        self.epsilon_decay = float(epsilon_decay)
        self.value = np.zeros(n_actions)
        self.counts = np.zeros(n_actions, dtype=int)

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        if explore and self.rng.random() < self.epsilon:
            candidates = np.arange(self.n_actions)
            if mask is not None:
                allowed = candidates[mask > 0]
                if allowed.size:
                    candidates = allowed
            return int(self.rng.choice(candidates))
        v = self.value.copy()
        if mask is not None:
            v = np.where(mask > 0, v, -np.inf)
        return int(np.argmax(v))

    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        a = int(action) % self.n_actions
        self.counts[a] += 1
        self.value[a] += (reward - self.value[a]) / self.counts[a]
        self.updates += 1
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return {"epsilon": self.epsilon}

    def action_values(self) -> Optional[np.ndarray]:
        return self.value

    def _npz_items(self) -> Dict[str, np.ndarray]:
        return {"value": self.value, "counts": self.counts, "epsilon": np.array([self.epsilon])}

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        for k in ("value", "counts"):
            if k in data:
                setattr(self, k, np.array(data[k]))
        if "epsilon" in data:
            self.epsilon = float(np.asarray(data["epsilon"]).reshape(-1)[0])
