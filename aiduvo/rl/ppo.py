"""Proximal Policy Optimisation (clipped surrogate) with numpy actor-critic.

PPO is the right choice for *intra-run* steering, where the agent takes many
decisions inside one simulation (change stimulus bias, extend the run quantum,
or cut the run short).  Rollouts are collected across steps and episodes, so a
single long run already provides enough signal to learn from.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aiduvo.rl.base import Policy, register
from aiduvo.rl.nn import Adam, MLP, masked_softmax, softmax


@register
class PPOPolicy(Policy):
    name = "ppo"
    learns = True

    def __init__(
        self,
        n_actions: int,
        state_dim: int,
        seed: int = 0,
        hidden: Tuple[int, ...] = (64, 64),
        lr: float = 3e-3,
        gamma: float = 0.97,
        lam: float = 0.95,
        clip: float = 0.2,
        epochs: int = 4,
        minibatch: int = 32,
        rollout: int = 128,
        ent_coef: float = 0.01,
        vf_coef: float = 0.5,
        activation: str = "tanh",
        **kwargs: Any,
    ):
        super().__init__(n_actions, state_dim, seed, **kwargs)
        self.gamma = float(gamma)
        self.lam = float(lam)
        self.clip = float(clip)
        self.epochs = int(epochs)
        self.minibatch = int(minibatch)
        self.rollout = int(rollout)
        self.ent_coef = float(ent_coef)
        self.vf_coef = float(vf_coef)
        self.actor = MLP([state_dim, *hidden, n_actions], rng=self.rng, activation=activation)
        self.critic = MLP([state_dim, *hidden, 1], rng=self.rng, activation=activation)
        self.opt_a = Adam(lr=lr)
        self.opt_c = Adam(lr=lr)
        self.buf: List[Dict[str, Any]] = []
        self._last_logp = 0.0
        self._last_value = 0.0
        self.last_loss = 0.0

    # ------------------------------------------------------------------ select
    def select(self, state: np.ndarray, mask: Optional[np.ndarray] = None, explore: bool = True) -> int:
        x = np.asarray(state, dtype=float).reshape(1, -1)
        logits, _ = self.actor.forward(x)
        p = masked_softmax(logits[0], mask)
        v = float(self.critic(x)[0, 0])
        if explore:
            a = int(self.rng.choice(self.n_actions, p=p / max(1e-12, p.sum())))
        else:
            a = int(np.argmax(p))
        self._last_logp = float(np.log(max(1e-12, p[a])))
        self._last_value = v
        return a

    # ----------------------------------------------------------------- observe
    def observe(self, state: np.ndarray, action: int, reward: float,
                next_state: Optional[np.ndarray] = None, done: bool = False) -> Dict[str, float]:
        self.buf.append(
            {
                "s": np.asarray(state, dtype=float).reshape(-1),
                "a": int(action),
                "r": float(reward),
                "d": float(done),
                "logp": self._last_logp,
                "v": self._last_value,
            }
        )
        self.updates += 1
        if len(self.buf) >= self.rollout:
            return self._update()
        return {}

    def end_episode(self) -> None:
        if len(self.buf) >= max(8, self.minibatch):
            self._update()

    # ------------------------------------------------------------------ update
    def _update(self) -> Dict[str, float]:
        if not self.buf:
            return {}
        n = len(self.buf)
        s = np.stack([b["s"] for b in self.buf])
        a = np.array([b["a"] for b in self.buf], dtype=np.int64)
        r = np.array([b["r"] for b in self.buf], dtype=float)
        d = np.array([b["d"] for b in self.buf], dtype=float)
        old_logp = np.array([b["logp"] for b in self.buf], dtype=float)
        v_old = np.array([b["v"] for b in self.buf], dtype=float)

        adv = np.zeros(n)
        last = 0.0
        for t in range(n - 1, -1, -1):
            nonterm = 1.0 - d[t]
            next_v = v_old[t + 1] if t + 1 < n else 0.0
            delta = r[t] + self.gamma * next_v * nonterm - v_old[t]
            last = delta + self.gamma * self.lam * nonterm * last
            adv[t] = last
        ret = adv + v_old
        adv_norm = (adv - adv.mean()) / (adv.std() + 1e-8)

        pi_losses: List[float] = []
        v_losses: List[float] = []
        ent_vals: List[float] = []
        idx = np.arange(n)
        for _ in range(self.epochs):
            self.rng.shuffle(idx)
            for start in range(0, n, self.minibatch):
                mb = idx[start : start + self.minibatch]
                if mb.size == 0:
                    continue
                xb, ab, advb = s[mb], a[mb], adv_norm[mb]
                logits, cache_a = self.actor.forward(xb)
                p = softmax(logits)
                logp_all = np.log(np.clip(p, 1e-12, 1.0))
                logp = logp_all[np.arange(mb.size), ab]
                ratio = np.exp(logp - old_logp[mb])
                surr1 = ratio * advb
                surr2 = np.clip(ratio, 1.0 - self.clip, 1.0 + self.clip) * advb
                active = (surr1 <= surr2).astype(float)
                onehot = np.zeros_like(p)
                onehot[np.arange(mb.size), ab] = 1.0
                dlogits = -(active * advb * ratio)[:, None] * (onehot - p)
                ent = -np.sum(p * logp_all, axis=1)
                dlogits += self.ent_coef * p * (logp_all + ent[:, None])
                grads_a = self.actor.backward(cache_a, dlogits / mb.size)
                self.opt_a.step(self.actor.params(), grads_a)

                vb, cache_c = self.critic.forward(xb)
                vb = vb.reshape(-1)
                d_adv = self.vf_coef * (vb - ret[mb]) / mb.size
                grads_c = self.critic.backward(cache_c, d_adv.reshape(-1, 1))
                self.opt_c.step(self.critic.params(), grads_c)

                pi_losses.append(float(np.mean(-np.minimum(surr1, surr2))))
                v_losses.append(float(np.mean(0.5 * (vb - ret[mb]) ** 2)))
                ent_vals.append(float(np.mean(ent)))

        self.buf.clear()
        self.last_loss = float(np.mean(pi_losses)) if pi_losses else 0.0
        return {
            "pi_loss": self.last_loss,
            "v_loss": float(np.mean(v_losses)) if v_losses else 0.0,
            "entropy": float(np.mean(ent_vals)) if ent_vals else 0.0,
        }

    def action_values(self) -> Optional[np.ndarray]:
        return None

    def _npz_items(self) -> Dict[str, np.ndarray]:
        items: Dict[str, np.ndarray] = {}
        for tag, net in (("a", self.actor), ("c", self.critic)):
            for i, (w, b) in enumerate(zip(net.W, net.b)):
                items[f"{tag}W{i}"] = w
                items[f"{tag}b{i}"] = b
        return items

    def _load_npz(self, data: Dict[str, np.ndarray]) -> None:
        for tag, net in (("a", self.actor), ("c", self.critic)):
            n = len(net.W)
            if all(f"{tag}W{i}" in data for i in range(n)):
                net.set_params([data[f"{tag}W{i}"] for i in range(n)] + [data[f"{tag}b{i}"] for i in range(n)])
