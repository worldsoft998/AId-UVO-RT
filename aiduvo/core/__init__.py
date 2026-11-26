"""Core abstractions: types, spaces, rewards, and the campaign engine."""

from aiduvo.core.types import (
    Action,
    Budget,
    CampaignResult,
    EpisodeResult,
    Mode,
    Observation,
    Scope,
    Transition,
)
from aiduvo.core.space import FactoredActionSpace, Head, StateEncoder
from aiduvo.core.reward import RewardConfig, RewardFunction

__all__ = [
    "Action",
    "Budget",
    "CampaignResult",
    "EpisodeResult",
    "Mode",
    "Observation",
    "Scope",
    "Transition",
    "FactoredActionSpace",
    "Head",
    "StateEncoder",
    "RewardConfig",
    "RewardFunction",
]
