# Usage reference

Everything the batch files do, you can do from a shell. The batch files are
convenience wrappers around these commands.

## Commands

```
python -m aiduvo <command> [options]

  init         write a starter campaign config (+ knob inventory template)
  run          run one campaign (baseline | blackbox | runtime)
  sweep        run baseline + blackbox + runtime, then build the comparison report
  compare      compare existing campaign results
  discover     introspect a design and generate a config from what was found
  srie         probe / selftest / discover against a live simulator
  lint         non-intrusiveness compliance check
  selftest     end-to-end framework check on the synthetic backend
  algorithms   list available RL/ANN algorithms
  info         environment and version information
  knobs        write a knob inventory template
  zip          package the repository into a single downloadable ZIP
```

## `init`

```bat
python -m aiduvo init --out config\campaign.json --mode runtime --top tb_top --lib work
```

Writes `config/campaign.json` and `config/knobs.json`. `--mock` targets the
synthetic backend.

## `run`

```bat
python -m aiduvo run --config config\campaign.json ^
       --mode runtime --ai on --algorithm ppo --runs 8 --seed 1 --target 0.95
```

| Option | Meaning |
|---|---|
| `--config` | base config (JSON; TOML on Python 3.11+) |
| `--mode` | `baseline` / `blackbox` / `runtime` (overrides the config) |
| `--ai` | `on` / `off` |
| `--algorithm` | outer policy name |
| `--inner-algorithm` | intra-run policy (runtime mode) |
| `--runs` | `budget.max_runs` |
| `--max-steps` | `budget.max_steps_per_run` |
| `--target` | `budget.target_closure` in [0,1] |
| `--seed` | base seed |
| `--outdir` / `--tag` | where results go / campaign name |
| `--knobs` | knob inventory JSON |
| `--mock` | force the synthetic backend |
| `--print-config` | dump the resolved config and exit (with `--dry-run`) |
| `--log` | tee the campaign log to a file |

Exit code 0 on success, 1 on a failed campaign.

## `sweep`

The one command that produces the deliverable comparison:

```bat
python -m aiduvo sweep --mock --runs 10 --seed 1 --target 0.9 --outdir results\demo
```

Runs baseline, blackbox and runtime back to back with the same seed and budget,
then writes `report.md`, `report.html`, `comparison.json` and three SVG charts
into the output directory.

## `compare`

```bat
python -m aiduvo compare ^
    --campaign baseline=runs\fifo_baseline ^
    --campaign blackbox=runs\fifo_blackbox ^
    --campaign runtime=runs\fifo_runtime ^
    --outdir results\fifo --baseline baseline --target 0.9
```

`--campaign KEY=PATH` where `PATH` is a campaign directory (or a
`campaign_result.json`). `--baseline` picks the reference for speedups; without
it, the first baseline-mode campaign is used.

## `discover`

```bat
python -m aiduvo discover --config config\campaign.json ^
       --out config\discovered.json --depth 3 --root /
```

Opens a session, walks the hierarchy, reads the coverage tree, classifies signal
roles, and writes a config whose focus groups and action space come from what it
found. `--coverage-file <ucdb|xml>` does the same from a database without a
simulator.

## `srie`

```bat
python -m aiduvo srie probe     --config config\campaign_runtime.json
python -m aiduvo srie selftest  --config config\campaign_runtime.json
python -m aiduvo srie discover  --config config\campaign_runtime.json
python -m aiduvo srie tcl       --command "examine /tb_top/u_dut/level"
```

`probe` prints the capability matrix; `selftest` exercises every capability once
and prints JSON; `tcl` prints the command it *would* send (useful when you want
to paste it into a live `vsim` prompt).

## `selftest`

```bat
python -m aiduvo selftest --outdir runs\_selftest
```

Six checks, no simulator required: coverage import, every RL algorithm, a
baseline campaign, a blackbox campaign, a runtime campaign, report generation,
and the compliance linter. Exits non-zero if any fails.

## Campaign config reference

```jsonc
{
  "mode": "runtime",              // baseline | blackbox | runtime
  "ai": true,                     // false => algorithm is forced to "none"
  "algorithm": "linucb",          // outer policy
  "inner_algorithm": "ppo",       // intra-run policy (runtime only)
  "seed": 1,
  "outdir": "runs",
  "name": "fifo_runtime",         // campaign directory name
  "focus_limit": 8,               // how many coverage groups become focus options
  "save_policy": true,

  "budget": {
    "max_runs": 6,                // simulation runs
    "max_wall_s": 0,              // 0 = unlimited
    "max_cycles": 0,              // 0 = unlimited
    "target_closure": 0.95,       // stop early when reached
    "max_steps_per_run": 8,       // intra-run decisions
    "min_runs": 1,
    "plateau_runs": 0             // stop after N runs with no new coverage
  },

  "reward": {                     // all optional; defaults shown in docs/04
    "hard_bin_weight": 1.0,
    "new_bin_weight": 0.8,
    "efficiency_weight": 0.2,
    "time_penalty": 0.25,
    "cycle_penalty": 0.1,
    "plateau_penalty": 0.15,
    "goal_bonus": 5.0
  },

  "knobs": {                      // your plusarg inventory (see docs/03)
    "knobs": [],
    "profiles": []
  },

  "srie": {                       // runtime mode
    "transport": { "kind": "pipe" },   // pipe | socket | mock | fli
    "discover_root": "/",
    "discover_depth": 3,
    "coverage_cmd": "coverage report -detail -xml -output {output}",
    "max_forced": 8,
    "allow_outputs": false,
    "value_base": "dec",          // dec | hex | bin
    "quantum_cycles": 500,
    "period_ns": 10.0,
    "intra_steps": 8,
    "dry_run": false,
    "probe": true,
    "trigger_specs": [],
    "launch": {                   // how to start vsim
      "exe": "vsim", "lib": "work", "top": "tb_top_opt",
      "coverage": true, "plusargs": {}
    }
  },

  "blackbox": {                   // blackbox and baseline modes
    "kind": "questa",             // questa | mock
    "run_time": "2000us",
    "period_ns": 10.0,
    "timeout_s": 1800,
    "abort_on_error": true,
    "abort_on_assert": false,
    "stall_seconds": 0,
    "tests": ["tb_top_opt"],
    "user_do": "",
    "coverage_seed_file": "",
    "launch": { "exe": "vsim", "lib": "work", "top": "tb_top_opt" }
  },

  "policy_kwargs": {},            // e.g. {"alpha": 0.8}
  "inner_policy_kwargs": {}       // e.g. {"lr": 0.002, "rollout": 256}
}
```

Any key you omit falls back to the default in `aiduvo/config.py`.

## Outputs

```
runs/<campaign>/
├── campaign_config.json      resolved config
├── campaign_result.json      curve, episodes, metrics
├── history.sqlite            per-run coverage + actions
├── policy.npz / .json        learned model (AI modes)
├── _artifacts/run_XXXX/      transcript.log, coverage.ucdb, run.do
└── _srie_work/               bootstrap, per-run vsim logs
results/<report>/
├── report.md
├── report.html               single file, inline SVG
├── comparison.json
├── closure_curve.svg
├── final_closure.svg
└── speedup.svg
```

## Python API

```python
from aiduvo.core.engine import Campaign, CampaignConfig

cfg = CampaignConfig.load("config/campaign.json")
cfg.mode, cfg.ai, cfg.algorithm = "runtime", True, "linucb"
result = Campaign(cfg, log=print).run()
print(result.final_closure, result.runs_used, result.stopped_reason)
```
