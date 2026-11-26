"""Configuration loading, defaults and CLI-to-config mapping.

One JSON file describes one campaign.  The batch files generate that JSON from
their interactive menu and then call ``python -m aiduvo run --config ...``, so
the same experiment can be reproduced from the command line, from CI, or from
Python.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

from aiduvo.core.engine import CampaignConfig

CONFIG_VERSION = 1


DEFAULT_CONFIG: Dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "mode": "baseline",
    "ai": False,
    "algorithm": "none",
    "inner_algorithm": "",
    "seed": 1,
    "outdir": "runs",
    "name": "",
    "focus_limit": 8,
    "save_policy": True,
    "notes": "",
    "budget": {
        "max_runs": 12,
        "max_wall_s": 0,
        "max_cycles": 0,
        "target_closure": 0.95,
        "max_steps_per_run": 8,
        "min_runs": 1,
        "plateau_runs": 0,
    },
    "reward": {
        "hard_bin_weight": 1.0,
        "new_bin_weight": 0.8,
        "efficiency_weight": 0.2,
        "time_penalty": 0.25,
        "cycle_penalty": 0.1,
        "plateau_penalty": 0.15,
        "goal_bonus": 5.0,
        "time_ref_s": 60.0,
        "cycle_ref": 1000000.0,
        "reward_scale": 1.0,
        "clip": 10.0,
    },
    "knobs": {"knobs": [], "profiles": []},
    "srie": {
        "transport": {"kind": "pipe"},
        "discover_root": "/",
        "discover_depth": 2,
        "coverage_cmd": "coverage report -detail -xml -output {output}",
        "coverage_format": "auto",
        "max_forced": 8,
        "allow_outputs": False,
        "value_base": "dec",
        "quantum_cycles": 500,
        "period_ns": 10.0,
        "intra_steps": 8,
        "coverage_every": 1,
        "dry_run": False,
        "probe": True,
        "reuse_prepare_session": False,
        "trigger_specs": [],
        "launch": {
            "exe": "vsim",
            "lib": "work",
            "top": "",
            "do_file": "",
            "coverage": True,
            "plusargs": {},
            "extra": [],
        },
    },
    "blackbox": {
        "kind": "questa",
        "run_time": "1000 us",
        "period_ns": 10.0,
        "timeout_s": 3600,
        "abort_on_error": True,
        "abort_on_assert": False,
        "stall_seconds": 0,
        "tests": [],
        "user_do": "",
        "coverage_seed_file": "",
        "coverage_format": "auto",
        "mock_groups": 4,
        "mock_coverpoints": 3,
        "mock_bins": 8,
        "mock_cycles": 2000,
    },
    "policy_kwargs": {},
    "inner_policy_kwargs": {},
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def default_config(**overrides: Any) -> Dict[str, Any]:
    return deep_merge(DEFAULT_CONFIG, overrides)


def load_config_dict(path: str) -> Dict[str, Any]:
    if not path:
        return default_config()
    if not os.path.exists(path):
        raise FileNotFoundError(f"config file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".toml":
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - py<3.11
            raise RuntimeError("TOML configs need Python 3.11+ (tomllib)") from exc
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    else:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    return deep_merge(DEFAULT_CONFIG, data)


def load_campaign_config(path: str = "", **overrides: Any) -> CampaignConfig:
    data = load_config_dict(path)
    cfg = CampaignConfig.from_dict(data)
    for key, value in overrides.items():
        if value is None:
            continue
        if key in ("budget", "reward", "knobs", "srie", "blackbox", "policy_kwargs", "inner_policy_kwargs"):
            merged = deep_merge(getattr(cfg, key) or {}, value)
            setattr(cfg, key, merged)
        elif hasattr(cfg, key):
            setattr(cfg, key, value)
    if not cfg.ai:
        cfg.algorithm = "none"
    return cfg


def save_config_dict(data: Dict[str, Any], path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def mode_preset(mode: str, mock: bool = False) -> Dict[str, Any]:
    """Sensible defaults per mode, so the batch menu can offer one-click setups."""
    mode = (mode or "baseline").lower()
    if mode == "baseline":
        return {
            "mode": "baseline",
            "ai": False,
            "algorithm": "none",
            "blackbox": {"kind": "mock" if mock else "questa"},
            "budget": {"max_runs": 12, "max_steps_per_run": 0},
        }
    if mode == "blackbox":
        return {
            "mode": "blackbox",
            "ai": True,
            "algorithm": "linucb",
            "blackbox": {"kind": "mock" if mock else "questa"},
            "budget": {"max_runs": 12},
        }
    if mode == "runtime":
        return {
            "mode": "runtime",
            "ai": True,
            "algorithm": "linucb",
            "inner_algorithm": "ppo",
            "srie": {
                "transport": {"kind": "mock"} if mock else {"kind": "pipe"},
                "discover_depth": 4 if mock else 3,
            },
            "budget": {"max_runs": 6, "max_steps_per_run": 8},
        }
    raise ValueError(f"unknown mode {mode!r}")


def describe_config(cfg: CampaignConfig) -> str:
    lines = [
        f"mode        : {cfg.mode}",
        f"ai          : {'on' if cfg.ai else 'off'} ({cfg.algorithm}"
        + (f" / inner {cfg.inner_algorithm}" if cfg.inner_algorithm else "") + ")",
        f"seed        : {cfg.seed}",
        f"outdir      : {cfg.outdir}",
        f"budget      : {json.dumps(cfg.budget)}",
    ]
    if cfg.mode == "runtime":
        lines.append(f"srie        : {json.dumps(cfg.srie.get('transport', {}))}")
    else:
        lines.append(f"blackbox    : kind={cfg.blackbox.get('kind')} run_time={cfg.blackbox.get('run_time')}")
    knobs = (cfg.knobs or {}).get("knobs") or []
    lines.append(f"knobs       : {len(knobs)} declared")
    return "\n".join(lines)
