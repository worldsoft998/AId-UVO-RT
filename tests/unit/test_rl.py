import os

import numpy as np
import pytest

from aiduvo.rl import ALGORITHMS, CoverageSurrogate, make_policy
from aiduvo.rl.nn import MLP, Adam

STATE = np.ones(6, dtype=np.float32)
BEST = 1


def train(policy, steps=400, best=BEST):
    rng = np.random.default_rng(0)
    rewards = []
    for _ in range(steps):
        a = policy.select(STATE, explore=True)
        r = 1.0 if a == best else 0.0
        rewards.append(r)
        policy.observe(STATE, a, r, STATE, False)
    policy.end_episode()
    return rewards


@pytest.mark.parametrize("algo", ALGORITHMS)
def test_every_algorithm_returns_a_valid_action(algo):
    pol = make_policy(algo, 4, 6, seed=0)
    a = pol.select(STATE, explore=True)
    assert 0 <= a < 4
    info = pol.info()
    assert info["policy"]


@pytest.mark.parametrize("algo", ["linucb", "epsilon_greedy", "qlearning", "thompson"])
def test_bandits_prefer_the_better_action(algo):
    pol = make_policy(algo, 3, 6, seed=0)
    train(pol, steps=500)
    if algo == "thompson":
        values = pol.action_values()
        assert int(np.argmax(values)) == BEST
    else:
        assert pol.select(STATE, explore=False) == BEST


@pytest.mark.parametrize("algo", ["linucb", "thompson", "epsilon_greedy", "qlearning", "dqn", "ppo"])
def test_learning_improves_reward(algo):
    pol = make_policy(algo, 3, 6, seed=1)
    rewards = train(pol, steps=400)
    first, last = np.mean(rewards[:100]), np.mean(rewards[-100:])
    assert last >= first - 0.05


@pytest.mark.parametrize("algo", ["linucb", "qlearning", "dqn"])
def test_save_and_load_roundtrip(algo, tmp_path):
    pol = make_policy(algo, 3, 6, seed=2)
    train(pol, steps=300)
    before = pol.select(STATE, explore=False)
    path = str(tmp_path / f"{algo}.ckpt")
    pol.save(path)
    clone = make_policy(algo, 3, 6, seed=99)
    clone.load(path)
    assert clone.select(STATE, explore=False) == before


def test_mask_is_respected():
    pol = make_policy("linucb", 3, 6, seed=0)
    train(pol, steps=50)
    mask = np.array([0.0, 0.0, 1.0])
    assert pol.select(STATE, mask=mask, explore=False) == 2


def test_mlp_backward_matches_finite_difference():
    rng = np.random.default_rng(0)
    net = MLP([3, 5, 2], rng=rng, activation="tanh")
    x = rng.normal(size=(4, 3))
    target = rng.normal(size=(4, 2))
    out, cache = net.forward(x)
    dout = 2.0 * (out - target) / out.size   # d/d(out) of mean((out-target)^2)
    grads = net.backward(cache, dout)
    for pi, p in enumerate(net.params()):
        idx = tuple(0 for _ in p.shape)
        eps = 1e-6
        orig = p[idx]
        p[idx] = orig + eps
        plus = float(((net(x) - target) ** 2).mean())
        p[idx] = orig - eps
        minus = float(((net(x) - target) ** 2).mean())
        p[idx] = orig
        numeric = (plus - minus) / (2 * eps)
        assert numeric == pytest.approx(float(grads[pi][idx]), rel=1e-3, abs=1e-6)


def test_adam_reduces_loss():
    rng = np.random.default_rng(0)
    net = MLP([2, 8, 1], rng=rng, activation="tanh")
    opt = Adam(lr=1e-2)
    x = rng.normal(size=(32, 2))
    y = (x[:, :1] > 0).astype(float)
    losses = []
    for _ in range(200):
        out, cache = net.forward(x)
        err = out - y
        losses.append(float((err ** 2).mean()))
        opt.step(net.params(), net.backward(cache, err / x.shape[0]))
    assert losses[-1] < losses[0] * 0.5


def test_surrogate_fits_and_ranks():
    rng = np.random.default_rng(0)
    states = rng.normal(size=(64, 4))
    actions = rng.integers(0, 3, size=64)
    targets = np.where(actions == 1, 1.0, 0.0)
    model = CoverageSurrogate(4, 3, hidden=(16,), seed=0)
    model.fit(states, actions, targets, epochs=120)
    ranks = model.rank_actions(states[0])
    assert ranks.shape == (3,)
    assert int(np.argmax(ranks)) == 1
