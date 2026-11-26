"""ANN coverage surrogate: a learned model of *where coverage comes from*.

Two uses:

* :class:`CoverageSurrogate` predicts the coverage gain of a candidate decision
  from (state, action).  The reporter uses it to explain "what the AI expected".
* :class:`SurrogatePolicy` is a model-based policy: it fits the surrogate
  online and picks the action with the best predicted gain, with epsilon
  exploration.  With very few runs it behaves like a bandit; with many runs it
  becomes a cheap forward model of the design's stimulus response.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aiduvo.rl.base import Policy, register
from aiduvo.rl.nn import Adam, MLP, Standardizer


class CoverageSurrogate:
    """MLP regressor over ``[state, one_hot(action)]`` -> expected reward."""

    def __init__(
        self,
        state_dim: int,
        n_actions: int,
        hidden: Tuple[int, ...] = (64, 32),
        seed: int = 0,
        lr: float = 3e-3,
        activation: str = "tanh",
    ):
        self.state_dim = int(state_dim)
        self.n_actions = int(n_actions)
        rng = np.random.default_rng(seed)
        self.net = MLP([state_dim + n_actions, *hidden, 1], rng=rng, activation=activation)
        self.opt = Adam(lr=lr)
        self.sx = Standardizer(state_dim + n_actions)
        self.sy = Standardizer(1)
        self.loss_history: List[float] = []
        self.trained = False

    def features(self, states: np.ndarray, actions: np.ndarray) -> np.ndarray:
        s = np.atleast_2d(np.asarray(states, dtype=float))
        a = np.asarray(actions, dtype=int).reshape(-1)
        oh = np.zeros((a.size, self.n_actions))
        oh[np.arange(a.size), a] = 1.0
        return np.concatenate([s, oh], axis=1)

    def fit(self, states: np.ndarray, actions: np.ndarray, targets: np.ndarray,
            epochs: int = 60, batch_size: int = 32, seed: int = 0) -> float:
        X = self.features(states, actions)
        y = np.asarray(targets, dtype=float).reshape(-1, 1)
        self.sx.update(X)
        self.sy.update(y)
        Xn = self.sx.transform(X)
        yn = self.sy.transform(y)
        rng = np.random.default_rng(seed)
        n = Xn.shape[0]
        last = 0.0
        for _ in range(epochs):
            perm = rng.permutation(n)
            for start in range(0, n, batch_size):
                mb = perm[start : start + batch_size]
                out, cache = self.net.forward(Xn[mb])
                err = out - yn[mb]
                grads = self.net.backward(cache, err / mb.size)
                self.opt.step(self.net.params(), grads)
            out, _ = self.net.forward(Xn)
            last = float(np.mean((out - yn) ** 2))
            self.loss_history.append(last)
        self.trained = True
        return last

    def predict(self, states: np.ndarray, actions: np.ndarray) -> np.ndarray:
        X = self.sx.transform(self.features(states, actions))
        out = self.net(X)
        return self.sy.inverse(out).reshape(-1)

    def rank_actions(self, state: np.ndarray, n_actions: Optional[int] = None) -> np.ndarray:
        n = int(n_actions or self.n_actions)
        s = np.repeat(np.asarray(state, dtype=float).reshape(1, -1), n, axis=0)
        return self.predict(s, np.arange(n))


@register
class SurrogatePolicy(Policy):
    """Model-based policy driven by the coverage surrogate."""

    name = "surrogate"
    learns = True

    def __init__(
        self,
        n_actions: int,
        state_dim: int,
        seed: int = 0,
        hidden: Tuple[int, ...] = (64, 32),
        min_samples: int = 12,
        refit_every: int = 4,
        epsilon: float = 0.2,
        epsilon_min: float = 0.03,
        epsilon_decay: float = 0.95,
        epochs: int = 60,
        **kwargs: Any,
    ):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.model = CoverageSurrogate(state_dim, n_actions, hidden=hidden, seed=seed)
        self.min_samples = int(min_samples)
        self.refit_every = int(refit_every)
        self.epsilon = float(epsilon)
        self.epsilon_min = float(epsilon_min)
        self.epsilon_decay = float(epsilon_decay)
        self.epochs = int(epochs)
        self.X: List[np.ndarray] = []
        self.A: List[int] = []
        self.Y: List[float] = []
        self._since_fit = 0
        self.last_loss = 0.0

    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        cand = np.arange(self.n_actions)
        if mask is not None and (mask > 0).any():
            cand = cand[mask > 0]
        if not self.model.trained or (explore and self.rng.random() < self.epsilon):
            return int(self.rng.choice(cand))
        scores = self.model.rank_actions(np.asarray(state, dtype=float).reshape(-1))
        if mask is not None:
            scores = np.where(mask > 0, scores, -np.inf)
        return int(np.argmax(scores))

    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        self.X.append(np.asarray(state, dtype=float).reshape(-1))
        self.A.append(int(action))
        self.Y.append(float(reward))
        self.updates += 1
        self._since_fit += 1
        out: Dict[str, float] = {}
        if len(self.X) >= self.min_samples and self._since_fit >= self.refit_every:
            self._refit()
            out = {"surrogate_mse": self.last_loss}
            self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return out

    def _refit(self) -> None:
        self.last_loss = self.model.fit(
            np.stack(self.X), np.array(self.A), np.array(self.Y),
            epochs=self.epochs, seed=self.seed + self.updates,
        )
        self._since_fit = 0

    def end_episode(self) -> None:
        if len(self.X) >= self.min_samples and self._since_fit > 0:
            self._refit()

    def action_values(self) -> Optional[np.ndarray]:
        if not self.X:
            return None
        return self.model.rank_actions(self.X[-1])

    def _npz_items(self) -> Dict[str, np.ndarray]:
        items: Dict[str, np.ndarray] = {
            "sx_mean": self.model.sx.mean,
            "sx_var": self.model.sx.var,
            "sy_mean": self.model.sy.mean,
            "sy_var": self.model.sy.var,
            "epsilon": np.array([self.epsilon]),
            "data_X": np.stack(self.X) if self.X else np.zeros((0, self.state_dim)),
            "data_A": np.array(self.A, dtype=np.int64),
            "data_Y": np.array(self.Y, dtype=float),
        }
        for i, (w, b) in enumerate(zip(self.model.net.W, self.model.net.b)):
            items[f"W{i}"] = w
            items[f"b{i}"] = b
        return items

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        net = self.model.net
        n = len(net.W)
        if all(f"W{i}" in data for i in range(n)):
            net.set_params([data[f"W{i}"] for i in range(n)] + [data[f"b{i}"] for i in range(n)])
            self.model.trained = True
        if "sx_mean" in data:
            self.model.sx.mean = np.array(data["sx_mean"])
            self.model.sx.var = np.array(data["sx_var"])
            self.model.sy.mean = np.array(data["sy_mean"])
            self.model.sy.var = np.array(data["sy_var"])
        if "epsilon" in data:
            self.epsilon = float(np.asarray(data["epsilon"]).reshape(-1)[0])
        if "data_X" in data and len(data["data_X"]):
            self.X = [np.array(r) for r in data["data_X"]]
            self.A = [int(x) for x in data["data_A"]]
            self.Y = [float(x) for x in data["data_Y"]]
