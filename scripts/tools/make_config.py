#!/usr/bin/env python3
"""Build a campaign config JSON from command-line switches.

The Windows batch menu calls this, so all JSON assembly lives in Python instead
of in fragile batch string concatenation.

Example
-------
    python scripts/tools/make_config.py --out config/campaign.json ^
        --mode runtime --ai on --algorithm ppo --runs 10 --seed 1 ^
        --target 0.95 --top tb_top --lib work --mock
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from aiduvo.blackbox.knobs import KnobSpace  # noqa: E402
from aiduvo.config import (  # noqa: E402
    deep_merge,
    default_config,
    load_config_dict,
    mode_preset,
    save_config_dict,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="generate an AId-UVO-RT campaign config")
    ap.add_argument("--out", "-o", default="config/campaign.json")
    ap.add_argument("--base", default="", help="existing config to merge into")
    ap.add_argument("--mode", choices=["baseline", "blackbox", "runtime"], default="runtime")
    ap.add_argument("--ai", choices=["on", "off"], default="on")
    ap.add_argument("--algorithm", "-a", default="linucb")
    ap.add_argument("--inner-algorithm", default="")
    ap.add_argument("--runs", "-n", type=int, default=10)
    ap.add_argument("--seed", "-s", type=int, default=1)
    ap.add_argument("--target", "-t", type=float, default=0.95)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--max-wall", type=float, default=0.0)
    ap.add_argument("--max-cycles", type=float, default=0.0)
    ap.add_argument("--plateau", type=int, default=0)
    ap.add_argument("--top", default="")
    ap.add_argument("--lib", default="work")
    ap.add_argument("--outdir", default="runs")
    ap.add_argument("--tag", default="")
    ap.add_argument("--knobs", default="", help="knob inventory JSON")
    ap.add_argument("--run-time", default="1000us", help="blackbox run length per simulation")
    ap.add_argument("--transport", default="", choices=["", "pipe", "socket", "mock", "fli"])
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--quantum", type=int, default=0, help="SRIE run quantum in cycles")
    ap.add_argument("--max-forced", type=int, default=0)
    ap.add_argument("--coverage-seed-file", default="")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args(argv)

    data = load_config_dict(args.base) if args.base else default_config()
    data = deep_merge(data, mode_preset(args.mode, mock=args.mock))
    data["ai"] = args.ai == "on"
    if data["ai"]:
        data["algorithm"] = args.algorithm
        data["inner_algorithm"] = args.inner_algorithm or args.algorithm
    else:
        data["algorithm"] = "none"
        data["inner_algorithm"] = "none"
    data["seed"] = args.seed
    data["outdir"] = args.outdir
    data["name"] = args.tag or ""
    data.setdefault("budget", {}).update(
        {
            "max_runs": args.runs,
            "target_closure": args.target,
            "max_steps_per_run": args.max_steps,
            "max_wall_s": args.max_wall,
            "max_cycles": args.max_cycles,
            "plateau_runs": args.plateau,
            "min_runs": 1,
        }
    )
    if args.top:
        data.setdefault("srie", {}).setdefault("launch", {})["top"] = args.top
        data.setdefault("blackbox", {}).setdefault("launch", {})["top"] = args.top
    if args.lib:
        data.setdefault("srie", {}).setdefault("launch", {})["lib"] = args.lib
        data.setdefault("blackbox", {}).setdefault("launch", {})["lib"] = args.lib
    if args.transport:
        data.setdefault("srie", {})["transport"] = (
            {"kind": "socket", "port": args.port} if args.transport == "socket"
            else {"kind": args.transport}
        )
    if args.quantum:
        data.setdefault("srie", {})["quantum_cycles"] = args.quantum
    if args.max_forced:
        data.setdefault("srie", {})["max_forced"] = args.max_forced
    data.setdefault("blackbox", {})["run_time"] = args.run_time
    if args.coverage_seed_file:
        data["blackbox"]["coverage_seed_file"] = args.coverage_seed_file
    if args.knobs and os.path.exists(args.knobs):
        data["knobs"] = KnobSpace.load(args.knobs).to_dict()
    if args.mock:
        data["blackbox"]["kind"] = "mock"
        data["srie"]["transport"] = {"kind": "mock"}

    save_config_dict(data, args.out)
    if args.print:
        print(json.dumps(data, indent=2))
    else:
        print(f"config written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
