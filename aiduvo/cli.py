"""Command-line interface.

    python -m aiduvo <command> [options]

Commands
--------
``init``       write a starter campaign config (+ knob inventory template)
``run``        run one campaign (baseline | blackbox | runtime)
``sweep``      run baseline + blackbox + runtime and produce the comparison report
``compare``    compare existing campaign results
``discover``   introspect a design and generate a config from what was found
``srie``       probe / selftest / discover against a live simulator
``lint``       non-intrusiveness compliance check
``selftest``   end-to-end framework check on the synthetic backend
``algorithms`` list available RL/ANN algorithms
``info``       environment and version information
``zip``        package the repository into a single downloadable ZIP
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from aiduvo import __version__
from aiduvo.config import (
    DEFAULT_CONFIG,
    deep_merge,
    default_config,
    describe_config,
    load_campaign_config,
    load_config_dict,
    mode_preset,
    save_config_dict,
)
from aiduvo.core.engine import Campaign, CampaignConfig
from aiduvo.logging_utils import banner, human_time, make_logger

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _apply_mode_preset(data: Dict[str, Any], mode: str, mock: bool) -> Dict[str, Any]:
    preset = mode_preset(mode, mock=mock)
    merged = deep_merge(data, preset)
    if mock:
        merged = deep_merge(merged, {"blackbox": {"kind": "mock"},
                                     "srie": {"transport": {"kind": "mock"}}})
    return merged


def _config_from_args(args: argparse.Namespace) -> CampaignConfig:
    data = load_config_dict(getattr(args, "config", "") or "")
    mode = getattr(args, "mode", None)
    mock = bool(getattr(args, "mock", False))
    if mode:
        data = _apply_mode_preset(data, mode, mock)
    elif mock:
        data = _apply_mode_preset(data, data.get("mode", "baseline"), mock)
    ai = getattr(args, "ai", None)
    if ai is not None:
        data["ai"] = str(ai).lower() in ("1", "on", "yes", "true", "y")
        if not data["ai"]:
            data["algorithm"] = "none"
    if getattr(args, "algorithm", None):
        data["algorithm"] = args.algorithm
        if not data.get("inner_algorithm"):
            data["inner_algorithm"] = args.algorithm
    if getattr(args, "inner_algorithm", None):
        data["inner_algorithm"] = args.inner_algorithm
    if getattr(args, "runs", None):
        data.setdefault("budget", {})["max_runs"] = int(args.runs)
    if getattr(args, "target", None):
        data.setdefault("budget", {})["target_closure"] = float(args.target)
    if getattr(args, "seed", None) is not None:
        data["seed"] = int(args.seed)
    if getattr(args, "outdir", None):
        data["outdir"] = args.outdir
    if getattr(args, "tag", None):
        data["name"] = args.tag
    if getattr(args, "max_steps", None) is not None:
        data.setdefault("budget", {})["max_steps_per_run"] = int(args.max_steps)
    if getattr(args, "knobs", None):
        from aiduvo.blackbox.knobs import KnobSpace

        data["knobs"] = KnobSpace.load(args.knobs).to_dict()
    cfg = CampaignConfig.from_dict(data)
    if not cfg.ai:
        cfg.algorithm = "none"
    return cfg


def _print_summary(result: Any) -> None:
    print("")
    print(banner(f"campaign finished: {result.stopped_reason}"))
    print(f"  mode            : {result.mode.value}")
    print(f"  algorithm       : {result.algorithm} (ai={'on' if result.ai_enabled else 'off'})")
    print(f"  runs            : {result.runs_used}")
    print(f"  final closure   : {result.final_closure * 100:.2f}%")
    print(f"  simulated cycles: {result.total_cycles:,.0f}")
    print(f"  wall time       : {human_time(result.total_wall_s)}")
    if result.error:
        print(f"  error           : {result.error}")
    print(f"  artifacts       : {result.metadata.get('outdir', '')}")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    from aiduvo.discovery.discover import knob_inventory_template

    data = default_config()
    if args.mode:
        data = _apply_mode_preset(data, args.mode, args.mock)
    if args.top:
        data["srie"]["launch"]["top"] = args.top
    if args.lib:
        data["srie"]["launch"]["lib"] = args.lib
        data["blackbox"]["launch"] = {"lib": args.lib, "top": args.top or ""}
    out = args.out or "config/campaign.json"
    save_config_dict(data, out)
    print(f"wrote campaign config : {out}")
    if args.knobs_out:
        knob_inventory_template(args.knobs_out)
        print(f"wrote knob inventory  : {args.knobs_out}")
    print("")
    print(describe_config(CampaignConfig.from_dict(data)))
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    logfile = args.log or os.path.join(cfg.outdir, "last_run.log")
    log = make_logger(logfile=logfile, quiet=args.quiet)
    if args.print_config:
        print(json.dumps(cfg.to_dict(), indent=2))
        if args.dry_run:
            return EXIT_OK
    log(describe_config(cfg))
    campaign = Campaign(cfg, log=log)
    try:
        result = campaign.run()
    except Exception as exc:  # noqa: BLE001
        log(f"campaign failed: {type(exc).__name__}: {exc}")
        return EXIT_FAIL
    _print_summary(result)
    print(json.dumps({"result": result.metadata.get("outdir", ""),
                      "closure": result.final_closure,
                      "runs": result.runs_used}, indent=2))
    return EXIT_OK if not result.error else EXIT_FAIL


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run baseline, blackbox and runtime, then compare them."""
    from aiduvo.reporting import build_report, compare, load_campaign, markdown_table

    base_data = load_config_dict(args.config or "")
    outroot = args.outdir or os.path.join("results", f"sweep_{args.tag or 'run'}")
    os.makedirs(outroot, exist_ok=True)
    log = make_logger(logfile=os.path.join(outroot, "sweep.log"), quiet=args.quiet)
    modes = args.modes.split(",") if args.modes else ["baseline", "blackbox", "runtime"]
    keys: List[str] = []
    paths: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    for mode in modes:
        mode = mode.strip()
        if not mode:
            continue
        data = _apply_mode_preset(base_data, mode, args.mock)
        if args.algorithm:
            data["algorithm"] = args.algorithm
            data["inner_algorithm"] = args.algorithm
        if mode == "baseline":
            data["ai"] = False
            data["algorithm"] = "none"
        else:
            data["ai"] = True
        data["outdir"] = outroot
        data["name"] = f"{mode}_{args.tag or 'sweep'}"
        if args.runs:
            data.setdefault("budget", {})["max_runs"] = int(args.runs)
        if args.target:
            data.setdefault("budget", {})["target_closure"] = float(args.target)
        data["seed"] = int(args.seed or 1)
        cfg = CampaignConfig.from_dict(data)
        log(f"### running {mode} ({cfg.algorithm}) ###")
        result = Campaign(cfg, log=log).run()
        key = mode
        keys.append(key)
        paths[key] = result.metadata.get("outdir", "")
        labels[key] = f"{mode} ({cfg.algorithm if cfg.ai else 'no ai'})"
        log(f"    -> {result.final_closure * 100:.2f}% in {result.runs_used} runs")
    campaigns = {k: load_campaign(paths[k]) for k in keys if paths.get(k)}
    cmp_ = compare(campaigns, labels=labels, target=float(args.target or 0.9),
                   baseline_key="baseline" if "baseline" in campaigns else None)
    md = build_report(
        cmp_, outroot,
        title=f"AId-UVO-RT sweep: {' vs '.join(keys)}",
        repro=[f"python -m aiduvo sweep --outdir {outroot}"
               + (" --mock" if args.mock else "")],
    )
    print("")
    print(banner("comparison"))
    print(markdown_table(cmp_))
    print("")
    print(f"report: {os.path.join(outroot, 'report.md')}")
    print(f"html  : {os.path.join(outroot, 'report.html')}")
    return EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    from aiduvo.reporting import build_report, compare, load_campaign, markdown_table

    campaigns: Dict[str, Any] = {}
    labels: Dict[str, str] = {}
    for spec in args.campaign:
        if "=" in spec:
            key, path = spec.split("=", 1)
        else:
            key, path = os.path.basename(spec.rstrip("/\\")) or spec, spec
        campaigns[key] = load_campaign(path)
        labels[key] = args.label_map.get(key, key)
    if not campaigns:
        print("no campaigns given (use --campaign key=path)", file=sys.stderr)
        return EXIT_USAGE
    cmp_ = compare(campaigns, labels=labels, target=args.target, baseline_key=args.baseline)
    outdir = args.outdir or "results/comparison"
    build_report(cmp_, outdir, title=args.title, repro=args.repro or None)
    print(markdown_table(cmp_))
    print("")
    print(f"report: {os.path.join(outdir, 'report.md')}")
    print(f"html  : {os.path.join(outdir, 'report.html')}")
    return EXIT_OK


def cmd_discover(args: argparse.Namespace) -> int:
    from aiduvo.discovery.discover import discover_campaign_config, knob_inventory_template

    data = load_config_dict(args.config or "")
    transport = data.get("srie", {}).get("transport")
    launch = data.get("srie", {}).get("launch")
    if args.mock:
        transport = {"kind": "mock"}
    config = discover_campaign_config(
        args.out or "config/discovered.json",
        transport=transport,
        launch=launch,
        coverage_file=args.coverage_file or "",
        mode=args.mode or data.get("mode", "runtime"),
        algorithm=args.algorithm or data.get("algorithm", "linucb"),
        depth=args.depth,
        root=args.root,
        knobs=data.get("knobs"),
        workdir=args.workdir or ".",
    )
    report = config.get("discovery", {})
    print(f"discovered {report.get('coverage_bins', 0)} coverage bins in "
          f"{len(report.get('coverage_groups', []))} groups")
    for note in report.get("notes", []):
        print(f"  note: {note}")
    print(f"config written to {args.out or 'config/discovered.json'}")
    if args.knobs_out:
        knob_inventory_template(args.knobs_out)
        print(f"knob inventory template: {args.knobs_out}")
    return EXIT_OK


def cmd_srie(args: argparse.Namespace) -> int:
    from aiduvo.srie.session import SRIEConfig, SRIESession

    data = load_config_dict(args.config or "")
    srie = dict(data.get("srie") or {})
    if args.mock:
        srie["transport"] = {"kind": "mock"}
    cfg = SRIEConfig.from_dict(srie)
    log = make_logger(quiet=args.quiet)
    if args.action == "tcl":
        print(args.command)
        return EXIT_OK
    session = SRIESession(cfg, log=log)
    try:
        session.open(discover=(args.action != "probe"))
        if args.action == "probe":
            print(session.capability_report())
        elif args.action == "selftest":
            print(json.dumps(session.selftest(), indent=2, default=str))
        elif args.action == "discover":
            print(session.hierarchy.describe() if session.hierarchy else "no hierarchy")
            snap = session.coverage("discover")
            print(snap.describe())
        else:
            print(session.capability_report())
    finally:
        session.close()
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    from aiduvo.lint import check_files, check_repo

    report = check_files(args.files) if args.files else check_repo(args.root)
    print(report.render())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    return EXIT_OK if report.ok else EXIT_FAIL


def cmd_selftest(args: argparse.Namespace) -> int:
    """End-to-end check on the synthetic backend (no simulator needed)."""
    from aiduvo.reporting import build_report, compare, load_campaign

    outroot = args.outdir or os.path.join("runs", "_selftest")
    os.makedirs(outroot, exist_ok=True)
    log = make_logger(logfile=os.path.join(outroot, "selftest.log"), quiet=args.quiet)
    checks: List[tuple] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        log(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")

    log(banner(f"AId-UVO-RT selftest v{__version__}"))
    # 1. coverage importers
    try:
        from aiduvo.blackbox.mock import MockRunSimulator

        sim = MockRunSimulator()
        hits = sim.coverage(1234, 0.8)
        tmp = os.path.join(outroot, "selftest_ucdb.xml")
        sim.write(hits, tmp, os.path.join(outroot, "selftest_transcript.log"), 1234, 0.8)
        from aiduvo.coverage.ucis import load_coverage

        snap = load_coverage(tmp)
        record("coverage import", snap.total_bins == sim.design.total_bins,
               f"{snap.total_bins} bins")
    except Exception as exc:  # noqa: BLE001
        record("coverage import", False, str(exc))

    # 2. RL smoke: every algorithm learns a toy preference
    try:
        from aiduvo.rl import ALGORITHMS, make_policy
        import numpy as np

        best = []
        for algo in ALGORITHMS:
            pol = make_policy(algo, 4, 8, seed=0)
            rng = np.random.default_rng(0)
            for _ in range(200):
                s = rng.normal(size=8).astype(np.float32)
                a = pol.select(s, explore=True)
                r = 1.0 if a == 2 else 0.0
                pol.observe(s, a, r, s, False)
            pick = int(np.argmax([pol.select(np.zeros(8), explore=False) for _ in range(1)]))
            best.append((algo, pick))
        record("rl smoke", True, f"{len(best)} algorithms exercised")
    except Exception as exc:  # noqa: BLE001
        record("rl smoke", False, str(exc))

    # 3. campaigns on the mock backend
    keys: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    for mode, ai, algo in (("baseline", False, "none"), ("blackbox", True, "linucb")):
        try:
            data = _apply_mode_preset(default_config(), mode, mock=True)
            data.update({"outdir": outroot, "name": f"selftest_{mode}", "seed": 7,
                         "ai": ai, "algorithm": algo})
            data["budget"] = {"max_runs": 8, "target_closure": 0.95, "min_runs": 1}
            cfg = CampaignConfig.from_dict(data)
            res = Campaign(cfg, log=log).run()
            keys[mode] = res.metadata.get("outdir", "")
            labels[mode] = f"{mode} (mock)"
            record(f"{mode} campaign", res.final_closure > 0,
                   f"{res.final_closure * 100:.1f}% in {res.runs_used} runs")
        except Exception as exc:  # noqa: BLE001
            record(f"{mode} campaign", False, str(exc))

    # 4. runtime campaign on the mock SRIE session
    try:
        data = _apply_mode_preset(default_config(), "runtime", mock=True)
        data.update({"outdir": outroot, "name": "selftest_runtime", "seed": 7,
                     "ai": True, "algorithm": "linucb", "inner_algorithm": "ppo"})
        data["budget"] = {"max_runs": 3, "max_steps_per_run": 6, "target_closure": 0.99}
        cfg = CampaignConfig.from_dict(data)
        res = Campaign(cfg, log=log).run()
        keys["runtime"] = res.metadata.get("outdir", "")
        labels["runtime"] = "runtime (mock SRIE)"
        record("runtime campaign", res.final_closure > 0,
               f"{res.final_closure * 100:.1f}% in {res.runs_used} runs")
    except Exception as exc:  # noqa: BLE001
        record("runtime campaign", False, f"{type(exc).__name__}: {exc}")

    # 5. report generation
    try:
        campaigns = {k: load_campaign(v) for k, v in keys.items() if v}
        cmp_ = compare(campaigns, labels=labels, target=0.9,
                       baseline_key="baseline" if "baseline" in campaigns else None)
        build_report(cmp_, os.path.join(outroot, "report"),
                     title="AId-UVO-RT selftest report")
        record("report generation", True, "report.md + report.html")
    except Exception as exc:  # noqa: BLE001
        record("report generation", False, str(exc))

    # 6. compliance
    try:
        from aiduvo.lint import check_repo

        rep = check_repo(".")
        record("non-intrusiveness lint", rep.ok, f"{len(rep.violations)} violation(s)")
    except Exception as exc:  # noqa: BLE001
        record("non-intrusiveness lint", False, str(exc))

    failed = [c for c in checks if not c[1]]
    print("")
    print(banner(f"selftest: {len(checks) - len(failed)}/{len(checks)} passed"))
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<26s} {detail}")
    return EXIT_OK if not failed else EXIT_FAIL


def cmd_algorithms(args: argparse.Namespace) -> int:
    from aiduvo.rl import ALGORITHMS

    print("available algorithms:")
    for a in ALGORITHMS:
        print(f"  {a}")
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    import platform

    from aiduvo.srie.launcher import find_executable

    print(f"AId-UVO-RT {__version__}")
    print(f"python      : {platform.python_version()} ({platform.system()} {platform.machine()})")
    try:
        import numpy

        print(f"numpy       : {numpy.__version__}")
    except ImportError:  # pragma: no cover
        print("numpy       : NOT INSTALLED")
    for exe in ("vsim", "vlog", "vopt", "vcover", "vlib"):
        found = find_executable(exe)
        print(f"{exe:<12s}: {found or 'not found'}")
    print(f"cwd         : {os.getcwd()}")
    return EXIT_OK


def cmd_zip(args: argparse.Namespace) -> int:
    from scripts.tools.package_zip import build_zip

    out = build_zip(args.out or "", root=args.root or ".")
    print(f"wrote {out}")
    return EXIT_OK


def cmd_knobs(args: argparse.Namespace) -> int:
    from aiduvo.discovery.discover import knob_inventory_template

    knob_inventory_template(args.out or "config/knobs.json")
    print(f"knob inventory template: {args.out or 'config/knobs.json'}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aiduvo",
        description="AId-UVO-RT - AI-driven universal verification optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--version", action="version", version=f"AId-UVO-RT {__version__}")
    sub = p.add_subparsers(dest="command")

    def add_common(sp: argparse.ArgumentParser, config: bool = True) -> None:
        if config:
            sp.add_argument("--config", "-c", default="", help="campaign config JSON")
        sp.add_argument("--quiet", "-q", action="store_true")

    # init
    sp = sub.add_parser("init", help="write a starter config")
    sp.add_argument("--out", "-o", default="config/campaign.json")
    sp.add_argument("--mode", choices=["baseline", "blackbox", "runtime"])
    sp.add_argument("--mock", action="store_true", help="target the synthetic backend")
    sp.add_argument("--top", default="", help="top-level testbench unit (e.g. tb_top)")
    sp.add_argument("--lib", default="work")
    sp.add_argument("--knobs-out", default="config/knobs.json")
    sp.set_defaults(func=cmd_init)

    # run
    sp = sub.add_parser("run", help="run one campaign")
    add_common(sp)
    sp.add_argument("--mode", choices=["baseline", "blackbox", "runtime"])
    sp.add_argument("--ai", choices=["on", "off"])
    sp.add_argument("--algorithm", "-a")
    sp.add_argument("--inner-algorithm")
    sp.add_argument("--runs", "-n", type=int)
    sp.add_argument("--max-steps", type=int)
    sp.add_argument("--target", type=float, help="target closure in [0,1]")
    sp.add_argument("--seed", type=int)
    sp.add_argument("--outdir")
    sp.add_argument("--tag")
    sp.add_argument("--knobs", help="knob inventory JSON")
    sp.add_argument("--mock", action="store_true")
    sp.add_argument("--log")
    sp.add_argument("--print-config", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_run)

    # sweep
    sp = sub.add_parser("sweep", help="run baseline+blackbox+runtime and compare")
    add_common(sp)
    sp.add_argument("--modes", default="baseline,blackbox,runtime")
    sp.add_argument("--algorithm", "-a", default="linucb")
    sp.add_argument("--runs", "-n", type=int, default=8)
    sp.add_argument("--target", type=float, default=0.9)
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--outdir")
    sp.add_argument("--tag", default="")
    sp.add_argument("--mock", action="store_true")
    sp.set_defaults(func=cmd_sweep)

    # compare
    sp = sub.add_parser("compare", help="compare campaign results")
    sp.add_argument("--campaign", action="append", default=[], metavar="KEY=PATH")
    sp.add_argument("--outdir", "-o")
    sp.add_argument("--target", type=float, default=0.9)
    sp.add_argument("--baseline")
    sp.add_argument("--title", default="AId-UVO-RT coverage closure comparison")
    sp.add_argument("--repro", action="append", default=[])
    sp.set_defaults(func=cmd_compare, label_map={})

    # discover
    sp = sub.add_parser("discover", help="introspect and generate a config")
    add_common(sp)
    sp.add_argument("--out", "-o", default="config/discovered.json")
    sp.add_argument("--mode")
    sp.add_argument("--algorithm")
    sp.add_argument("--depth", type=int, default=2)
    sp.add_argument("--root", default="/")
    sp.add_argument("--coverage-file", default="")
    sp.add_argument("--workdir", default=".")
    sp.add_argument("--knobs-out", default="")
    sp.add_argument("--mock", action="store_true")
    sp.set_defaults(func=cmd_discover)

    # srie
    sp = sub.add_parser("srie", help="live simulator introspection")
    add_common(sp)
    sp.add_argument("action", choices=["probe", "selftest", "discover", "tcl"])
    sp.add_argument("--mock", action="store_true")
    sp.add_argument("--command", default="")
    sp.set_defaults(func=cmd_srie)

    # lint
    sp = sub.add_parser("lint", help="non-intrusiveness compliance check")
    sp.add_argument("--root", default=".")
    sp.add_argument("files", nargs="*")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_lint)

    # selftest
    sp = sub.add_parser("selftest", help="end-to-end check on the synthetic backend")
    sp.add_argument("--outdir")
    sp.add_argument("--quiet", "-q", action="store_true")
    sp.set_defaults(func=cmd_selftest)

    # algorithms / info / zip / knobs
    sp = sub.add_parser("algorithms", help="list RL algorithms")
    sp.set_defaults(func=cmd_algorithms)

    sp = sub.add_parser("info", help="environment information")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("zip", help="package the repository as a ZIP")
    sp.add_argument("--out", "-o", default="")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=cmd_zip)

    sp = sub.add_parser("knobs", help="write a knob inventory template")
    sp.add_argument("--out", "-o", default="config/knobs.json")
    sp.set_defaults(func=cmd_knobs)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except Exception as exc:  # noqa: BLE001
        if getattr(args, "verbose", False):
            raise
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
