"""Local RL / ANN engine.

Everything here trains and infers on the local machine with numpy only -- no
network calls, no hosted model APIs.  Available policies:

====================  ==========================================================
``none``              AI disabled (always the default action)
``random``            uniform random (control group)
``round_robin``       deterministic sweep (control group)
``linucb``            contextual linear UCB bandit
``thompson``          Beta-Bernoulli Thompson sampling
``epsilon_greedy``    sample-average value bandit
``qlearning``         tabular Q-learning over a discretised coverage state
``dqn``               double deep Q-network (numpy MLP + replay + target net)
``ppo``               clipped-surrogate PPO actor-critic
``surrogate``         ANN coverage surrogate, model-based action choice
====================  ==========================================================
"""

from aiduvo.rl.ann import CoverageSurrogate, SurrogatePolicy
from aiduvo.rl.bandit import EpsilonGreedyPolicy, LinUCBPolicy, ThompsonPolicy
from aiduvo.rl.base import (
    NullPolicy,
    Policy,
    RandomPolicy,
    RoundRobinPolicy,
    available,
    make_policy,
    register,
)
from aiduvo.rl.dqn import DQNPolicy
from aiduvo.rl.nn import Adam, MLP, Standardizer
from aiduvo.rl.ppo import PPOPolicy
from aiduvo.rl.qlearning import QLearningPolicy
from aiduvo.rl.replay import ReplayBuffer

ALGORITHMS = [
    "none",
    "random",
    "round_robin",
    "linucb",
    "thompson",
    "epsilon_greedy",
    "qlearning",
    "dqn",
    "ppo",
    "surrogate",
]

__all__ = [
    "Policy",
    "NullPolicy",
    "RandomPolicy",
    "RoundRobinPolicy",
    "LinUCBPolicy",
    "ThompsonPolicy",
    "EpsilonGreedyPolicy",
    "QLearningPolicy",
    "DQNPolicy",
    "PPOPolicy",
    "SurrogatePolicy",
    "CoverageSurrogate",
    "ReplayBuffer",
    "MLP",
    "Adam",
    "Standardizer",
    "make_policy",
    "register",
    "available",
    "ALGORITHMS",
]
