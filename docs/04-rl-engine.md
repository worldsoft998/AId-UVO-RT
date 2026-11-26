# The RL / ANN engine

Everything here is numpy only, trains and infers on your machine, and is
deterministic given a seed. No network calls, no hosted model.

## Algorithms

| Name | Class | Best for | Notes |
|---|---|---|---|
| `none` | — | the AI-off control group | always returns the default action |
| `random` | `RandomPolicy` | a second control group | uniform over the joint action space |
| `round_robin` | `RoundRobinPolicy` | reproducible sweeps | deterministic cycle through actions |
| `linucb` | `LinUCBPolicy` | **inter-run default** | contextual linear UCB; O(d²) per step, no tuning |
| `thompson` | `ThompsonPolicy` | small action sets, noisy reward | Beta-Bernoulli on a logistic squash |
| `epsilon_greedy` | `EpsilonGreedyPolicy` | a cheap baseline | sample-average values, decaying ε |
| `qlearning` | `QLearningPolicy` | interpretable tabular learning | discretised coverage state, optimistic init |
| `dqn` | `DQNPolicy` | **intra-run alternative** | double DQN, replay, target net, Huber loss |
| `ppo` | `PPOPolicy` | **intra-run default** | clipped surrogate, GAE, entropy bonus |
| `surrogate` | `SurrogatePolicy` | model-based exploration | fits an ANN of (state, action) → reward |

Rule of thumb: **bandits outside the run, PPO inside the run.** A campaign makes
a few dozen decisions, which is too few for a deep method to learn anything; a
single run makes dozens to hundreds of decisions, which is exactly what PPO
needs.

## The action space is factored

Instead of one flat set of joint actions, a decision is a tuple:

```
inter-run :  seed_mode  x  focus       x  knob_profile
             4 options     2 + N groups   2 + N profiles

intra-run :  force_bias  x  quantum
             6 options      3 options
```

`FactoredActionSpace` maps a joint index to head values (row-major) and back. The
space is built from *discovered* facts: `focus` options are the coverage groups
the simulator reported, `knob_profile` options come from your inventory.

```python
space.size()          # 4 * (2+groups) * profiles
space.encode(37)      # {"seed_mode": "sweep", "focus": "cg_ops", ...}
space.decode({...})   # 37
```

## State vector (24 features)

`StateEncoder` maps an `Observation` to a fixed vector, independent of the design:

```
closure · weighted_closure · Δclosure · Δweighted · novelty · entropy ·
zero_bin_ratio · groups_at_goal · elapsed_wall_frac · elapsed_cycles_frac ·
runs_frac · best_closure · regret · plateau_frac · log_cycles · log_mean_hits ·
group_closure_{min,mean,max,std} · steps_frac · sim_time_frac · efficiency · bias
```

Everything is clipped to [-1, 1] so a 200-bin block and a 200 000-bin SoC produce
vectors of the same scale. Add a feature by appending to `FEATURE_NAMES` and to
`StateEncoder.encode` — nothing else needs to change, and old checkpoints simply
refuse to load (`state_dim` mismatch).

## Reward

```python
total = hard_bin_weight   * Δweighted_closure * 10
      + new_bin_weight    * min(1, novelty * 10)
      + efficiency_weight * 10 * Δclosure / (1 + log1p(Δcycles / 1e4))
      - time_penalty      * min(1, Δwall / time_ref_s)
      - cycle_penalty     * min(1, log1p(Δcycles) / log1p(cycle_ref))
      - plateau_penalty   (when nothing new was covered)
      + goal_bonus        (once, when the target closure is reached)
```

Design notes:

* **hardness weighting** is what makes the agent chase corners: a never-hit bin
  carries a much larger weight than a bin already hit 50 times, so closing the
  last 5% is worth more than re-covering the easy 60%;
* the **efficiency** term is incremental, so a step that finds nothing earns
  nothing and the plateau penalty dominates;
* the **goal bonus** is paid once per campaign (latched), so it cannot be farmed.

Tune in `reward` in the campaign config; the defaults work for most designs.

## Hyperparameters

Every learner takes `**kwargs` from the config:

```json
"policy_kwargs": { "alpha": 0.8, "ridge": 1.0 },
"inner_policy_kwargs": { "lr": 0.002, "hidden": [64, 64], "rollout": 256 }
```

| Algorithm | Useful knobs |
|---|---|
| linucb | `alpha` (exploration), `ridge` |
| thompson | `prior`, `temp` |
| epsilon_greedy | `epsilon`, `epsilon_decay`, `epsilon_min` |
| qlearning | `alpha`, `gamma`, `epsilon`, `optimistic` |
| dqn | `lr`, `gamma`, `hidden`, `batch_size`, `buffer_size`, `target_sync`, `epsilon_decay` |
| ppo | `lr`, `gamma`, `lam`, `clip`, `epochs`, `rollout`, `ent_coef` |
| surrogate | `hidden`, `min_samples`, `refit_every`, `epochs` |

## Persistence

`policy.save(path)` writes `path.npz` (weights, tables, standardisers) and
`path.json` (class, config, counters). Every campaign saves its final policy to
`runs/<campaign>/policy.*`.

To warm-start a new campaign from an old one, load it explicitly:

```python
from aiduvo.rl import make_policy
pol = make_policy("ppo", n_actions, state_dim, seed=1)
pol.load("runs/old_campaign/policy")
```

The campaign engine does not auto-load checkpoints: silently inheriting an old
policy would make a comparison unfair.

## Numerical hygiene

* `Adam` with global gradient-norm clipping (5.0);
* Huber loss in DQN so a single large reward cannot blow up the value function;
* advantage normalisation in PPO;
* target network with hard sync (DQN);
* all RNGs are `numpy.random.Generator` seeded from the campaign seed, so a
  campaign is reproducible run-for-run.

## The ANN surrogate

`CoverageSurrogate` fits `(state, one_hot(action)) → reward` with a small MLP and
a standardised target. Two uses:

1. `SurrogatePolicy` uses it directly for model-based action choice (with ε
   exploration), which is useful when runs are expensive and you want to
   extrapolate from few samples;
2. the reporter can show "what the model expected" for each action, which makes
   the agent's behaviour explainable to a verification engineer.

## What it is not

This is not a general-purpose deep-RL library. There is no GPU support, no
distributed training, no offline RL, no reward learning. It is a small,
auditable set of learners sized for the decision problems this framework
actually has.
