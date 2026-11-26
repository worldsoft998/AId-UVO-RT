"""Minimal, dependency-free neural network primitives (numpy only).

Deliberately small: a fully connected MLP with tanh/relu activations, an Adam
optimiser, and a feature standardiser.  That is everything DQN, PPO and the
coverage surrogate need, and it keeps the whole optimizer installable with a
single ``pip install numpy``.  No external model API is ever contacted.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def _activation(name: str):
    if name == "tanh":
        return np.tanh, lambda a: 1.0 - a * a
    if name == "relu":
        return (lambda z: np.maximum(z, 0.0)), (lambda a: (a > 0).astype(a.dtype))
    if name == "sigmoid":
        return (lambda z: 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))), (lambda a: a * (1.0 - a))
    if name == "linear":
        return (lambda z: z), (lambda a: np.ones_like(a))
    raise ValueError(f"unknown activation {name!r}")


class MLP:
    """Fully connected network; ``forward`` returns (output, cache)."""

    def __init__(
        self,
        sizes: Sequence[int],
        rng: Optional[np.random.Generator] = None,
        activation: str = "tanh",
        out_activation: str = "linear",
        out_gain: float = 0.01,
    ):
        if len(sizes) < 2:
            raise ValueError("MLP needs at least input and output sizes")
        self.sizes = list(sizes)
        self.activation = activation
        self.out_activation = out_activation
        rng = rng or np.random.default_rng(0)
        self.W: List[np.ndarray] = []
        self.b: List[np.ndarray] = []
        for i in range(len(sizes) - 1):
            fan_in = sizes[i]
            last = i == len(sizes) - 2
            gain = out_gain if last else math_sqrt2(fan_in)
            self.W.append(rng.normal(0.0, gain, size=(sizes[i], sizes[i + 1])))
            self.b.append(np.zeros(sizes[i + 1]))

    # ------------------------------------------------------------- parameters
    def params(self) -> List[np.ndarray]:
        return self.W + self.b

    def set_params(self, values: Sequence[np.ndarray]) -> None:
        n = len(self.W)
        self.W = [np.array(v, dtype=float) for v in values[:n]]
        self.b = [np.array(v, dtype=float) for v in values[n:]]

    def clone_from(self, other: "MLP") -> None:
        self.set_params([p.copy() for p in other.params()])

    def copy(self) -> "MLP":
        new = MLP(self.sizes, activation=self.activation, out_activation=self.out_activation)
        new.clone_from(self)
        return new

    def soft_update(self, other: "MLP", tau: float) -> None:
        for dst, src in zip(self.params(), other.params()):
            dst *= 1.0 - tau
            dst += tau * src

    # ---------------------------------------------------------------- forward
    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, Dict[str, List[np.ndarray]]]:
        x = np.atleast_2d(np.asarray(x, dtype=float))
        acts = [x]
        pres = []
        h = x
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            z = h @ W + b
            pres.append(z)
            last = i == len(self.W) - 1
            f, _ = _activation(self.out_activation if last else self.activation)
            h = f(z)
            acts.append(h)
        return h, {"acts": acts, "pres": pres}

    def __call__(self, x: np.ndarray) -> np.ndarray:
        out, _ = self.forward(x)
        return out

    # --------------------------------------------------------------- backward
    def backward(self, cache: Dict[str, List[np.ndarray]], dout: np.ndarray) -> List[np.ndarray]:
        acts = cache["acts"]
        n = len(self.W)
        grads_W: List[np.ndarray] = [None] * n  # type: ignore[list-item]
        grads_b: List[np.ndarray] = [None] * n  # type: ignore[list-item]
        delta = np.asarray(dout, dtype=float)
        for i in range(n - 1, -1, -1):
            fname = self.out_activation if i == n - 1 else self.activation
            _, dfun = _activation(fname)
            d = delta * dfun(acts[i + 1])
            grads_W[i] = acts[i].T @ d
            grads_b[i] = d.sum(axis=0)
            delta = d @ self.W[i].T
        return grads_W + grads_b


def math_sqrt2(fan_in: int) -> float:
    """He-style gain, safe for both tanh and relu trunks."""
    return float(np.sqrt(2.0 / max(1, fan_in)))


class Adam:
    """Adam optimiser with decoupled global gradient clipping."""

    def __init__(self, lr: float = 1e-3, beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8):
        self.lr = lr
        self.b1 = beta1
        self.b2 = beta2
        self.eps = eps
        self.t = 0
        self.m: List[np.ndarray] = []
        self.v: List[np.ndarray] = []

    def step(self, params: List[np.ndarray], grads: List[np.ndarray], clip_norm: float = 5.0) -> None:
        if not self.m:
            self.m = [np.zeros_like(p) for p in params]
            self.v = [np.zeros_like(p) for p in params]
        norm = float(np.sqrt(sum(float((g * g).sum()) for g in grads)))
        scale = 1.0 if norm <= clip_norm or norm == 0 else clip_norm / norm
        self.t += 1
        for i, (p, g) in enumerate(zip(params, grads)):
            g = g * scale
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            mhat = self.m[i] / (1 - self.b1 ** self.t)
            vhat = self.v[i] / (1 - self.b2 ** self.t)
            p -= self.lr * mhat / (np.sqrt(vhat) + self.eps)

    def state(self) -> Dict[str, object]:
        return {"t": self.t, "m": self.m, "v": self.v, "lr": self.lr}

    def load_state(self, st: Dict[str, object]) -> None:
        self.t = int(st["t"])  # type: ignore[arg-type]
        self.m = [np.array(a) for a in st["m"]]  # type: ignore[union-attr]
        self.v = [np.array(a) for a in st["v"]]  # type: ignore[union-attr]


class Standardizer:
    """Running mean/std normaliser for inputs and targets."""

    def __init__(self, dim: int, clip: float = 5.0):
        self.dim = dim
        self.clip = clip
        self.mean = np.zeros(dim)
        self.var = np.ones(dim)
        self.count = 1e-4

    def update(self, x: np.ndarray) -> None:
        x = np.atleast_2d(x)
        n = x.shape[0]
        if n == 0:
            return
        bmean = x.mean(axis=0)
        bvar = x.var(axis=0)
        delta = bmean - self.mean
        tot = self.count + n
        self.mean = self.mean + delta * n / tot
        m_a = self.var * self.count
        m_b = bvar * n
        self.var = (m_a + m_b + delta ** 2 * self.count * n / tot) / tot
        self.count = tot

    def transform(self, x: np.ndarray) -> np.ndarray:
        out = (np.asarray(x, dtype=float) - self.mean) / np.sqrt(self.var + 1e-8)
        return np.clip(out, -self.clip, self.clip)

    def inverse(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(x, dtype=float) * np.sqrt(self.var + 1e-8) + self.mean


def softmax(logits: np.ndarray) -> np.ndarray:
    z = np.asarray(logits, dtype=float)
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def masked_softmax(logits: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    p = softmax(logits)
    if mask is None:
        return p
    m = np.asarray(mask, dtype=float)
    p = p * m
    s = p.sum(axis=-1, keepdims=True)
    return np.where(s > 0, p / np.maximum(s, 1e-12), 1.0 / max(1, int(m.sum())))
