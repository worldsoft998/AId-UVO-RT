# AId-UVO-RT

**AI-Driven Universal Verification Optimization — Runtime / Instantaneous**

A project-agnostic, coverage-driven verification acceleration framework for RTL.
It observes a running simulation, learns which stimulus decisions actually close
coverage, and steers the verification environment — **without reading, editing or
regenerating a single line of RTL, testbench, UVM or coverage-model source.**

Target platform for this release: **Siemens QuestaSim on Windows**,
**SystemVerilog / UVM**, **Python RL/ANN engine running entirely locally**
(numpy only — no external model APIs).

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  baseline (no AI)          blackbox (AI, logs only)      runtime (AI, live)  │
│  ─────────────────         ───────────────────────       ──────────────────  │
│  seed sweep                seed + plusarg profiles       everything above   │
│  no adaptation             run length, early abort       + mid-run steering  │
│                            transcript + UCDB            through SRIE        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. What it does

Functional coverage closes slowly because uniform constrained-random stimulus
keeps re-hitting the same easy bins while the corners stay dark. An engineer
fixes this by hand: read the coverage report, guess a constraint, re-run, repeat.

AId-UVO-RT automates that loop with a local reinforcement-learning agent that is
allowed to touch exactly one thing: **the simulator's control surface**. Three
interfaces, in increasing order of power:

| Mode | What the AI can do | What it can see |
|---|---|---|
| **baseline** | nothing — sequential seeds (control group) | nothing |
| **blackbox** | pick the seed, the plusarg profile, the run length, abort a useless run | transcript + coverage database, after or during the run |
| **runtime** | everything above **plus** drive discovered input ports, install value-change triggers, and decide how far to run — *inside* the simulation | live hierarchy, live signal values, live coverage, live events |

All three modes share one reward function, one coverage model, one budget
accounting and one reporting path, so the comparison between them is
apples-to-apples. That is the point of the project.

---

## 2. The non-intrusiveness promise (and how it is enforced)

The optimizer is a **blackbox with respect to source** and a **whitebox with
respect to the simulator**. It never:

* opens, parses, greps, rewrites or generates `.sv`, `.svh`, `.v`, `.vhd`, UVM
  packages, or coverage-model code;
* imports an HDL parser or elaborator;
* calls an external AI/model API;
* needs a single project-specific name in its own code.

It only uses what the simulator exposes at run time:

| Need | Mechanism | Touches source? |
|---|---|---|
| hierarchy | `describe` / `find` (Tcl) or FLI | no |
| signal values | `examine` (Tcl) or FLI | no |
| stimulus control | `force` / `release` on existing ports | no |
| events | `when` triggers pushing JSON over the channel | no |
| run control | `run` / `stop` / `run -all` | no |
| coverage | `coverage report -xml` / `vcover report -xml` (UCIS) | no |
| instrumentation | simulator switches (`vopt +cover=...`) | no |

This is checked mechanically, not just claimed:

```bat
python -m aiduvo lint
```

`aiduvo/lint/nonintrusive.py` walks the framework packages and fails on HDL file
extension literals, HDL-parser imports, example-design references, run-time HDL
file access, network / hosted-AI client imports, and any attempt to execute a
compiler from the framework. It runs in `05_selftest.bat` and in CI.

See [docs/06-nonintrusiveness.md](docs/06-nonintrusiveness.md) for the full rule list.

---

## 3. Quick start (Windows + QuestaSim)

```bat
REM 0. one-time: python -m pip install -r requirements.txt
REM    (numpy is the only hard dependency)

REM 1. compile the design with coverage enabled (simulator switches only)
scripts\windows\01_compile.bat

REM 2. interactive optimizer menu: mode / AI on-off / RL algorithm /
REM    runs / seed / coverage goal / backend
scripts\windows\02_run_optimizer.bat

REM 3. compare baseline vs blackbox vs runtime
scripts\windows\03_compare.bat
```

Or start from the top-level menu: `scripts\windows\00_menu.bat`.

**No QuestaSim licence?** Run the whole pipeline on the built-in synthetic
simulator:

```bat
scripts\windows\demo_mock.bat          REM 3-way sweep on the mock backend
scripts\windows\05_selftest.bat        REM framework selftest, no simulator
```

or directly:

```bat
python -m aiduvo sweep --mock --runs 10 --outdir results\demo_mock
python -m aiduvo selftest
```

The mock backend speaks the real wire protocol and writes real UCIS XML, so it
exercises the whole stack. **Its numbers are illustrative, not simulator
measurements** — see §7.

---

## 4. The interactive menu

`02_run_optimizer.bat` gives you selectable options, all of which map to a JSON
campaign config:

```
M  mode       baseline | blackbox | runtime
A  AI         on | off
L  algorithm  none random round_robin linucb thompson epsilon_greedy
              qlearning dqn ppo surrogate
I  inner      intra-run algorithm (ppo / dqn / qlearning / linucb / thompson)
N  runs       number of simulation runs
S  seed       base seed (sweep mode uses seed..seed+runs-1)
T  target     coverage goal in [0,1]
B  backend    questa | mock
G  go         run the selected campaign
V  verify     run baseline + blackbox + runtime and compare
```

Non-interactive use (CI, scripts) — pass any argument:

```bat
02_run_optimizer.bat auto
```

and set `MODE`, `AI`, `ALGO`, `RUNS`, `SEED`, `TARGET`, `BACKEND` in the
environment first if you want to override the defaults.

---

## 5. Repository map

```
AId-UVO-RT/
├── aiduvo/                     the optimizer (Python, numpy only)
│   ├── core/                   action space, state encoder, reward, campaign engine
│   ├── coverage/               coverage model, UCIS/CSV/text importers, SQLite history
│   ├── rl/                     LinUCB, Thompson, e-greedy, Q-learning, DQN, PPO, ANN surrogate
│   ├── srie/                   Simulator Runtime Introspection Engine
│   │   ├── transport.py        vsim pipe · Tcl socket · FLI · mock
│   │   ├── tcl.py              command builders + tolerant parsers
│   │   ├── introspection.py    hierarchy / values / coverage (read)
│   │   ├── reflection.py       force / release / triggers / run control (write)
│   │   ├── optimizer.py        the runtime backend (two nested control loops)
│   │   └── bootstrap.py        the Tcl bootstrap generated per session
│   ├── blackbox/               seed/plusarg/run-length control, transcript watcher
│   ├── discovery/              hierarchical discovery -> generated config
│   ├── semantics/              optional role annotation (clock/reset/data/...)
│   ├── reporting/              comparison tables, SVG charts, markdown + HTML
│   ├── lint/                   non-intrusiveness compliance checker
│   └── cli.py                  `python -m aiduvo ...`
├── scripts/
│   ├── questa/                 compile / run / coverage / bootstrap do-files
│   │   └── fli/                optional FLI shim (C) + build script
│   ├── windows/                .bat workflow with interactive menus
│   ├── linux/                  .sh parity
│   └── tools/                  config generator, ZIP packager
├── examples/demo_fifo/         demo DUT + UVM TB + generated configs (user space)
├── tests/                      pytest suite (runs without a simulator)
├── docs/                       architecture, usage, methodology, diagrams
└── results/                    comparison reports and how to produce them
```

---

## 6. How it works (short version)

```
   ┌───────────────┐   observe (coverage, signals, events)   ┌──────────────────┐
   │  Simulator    │ ──────────────────────────────────────► │                  │
   │  QuestaSim    │                                         │   RL / ANN       │
   │  (vsim)       │ ◄────────────────────────────────────── │   engine         │
   └───────────────┘   act (force, run quantum, seed, knobs) └──────────────────┘
              ▲                                                       │
              │            ┌───────────────────────────┐              │
              └────────────┤  SRIE  (Tcl / VPI / FLI)  │◄─────────────┘
                           └───────────────────────────┘
```

* **Outer loop (inter-run)** — after each run: which seed strategy, which
  coverage group to focus on, which knob profile. A contextual bandit is the
  right tool here: only a handful of decisions per campaign.
* **Inner loop (intra-run)** — inside a live simulation, every
  `quantum_cycles`: read the coverage snapshot, sample signals, pick a stimulus
  bias (`hold / low / high / toggle / random_walk / release`) and a run quantum.
  PPO or DQN fits this better because there are many decisions per run.

Full details: [docs/01-architecture.md](docs/01-architecture.md),
[docs/02-srie-runtime.md](docs/02-srie-runtime.md),
[docs/03-blackbox.md](docs/03-blackbox.md),
[docs/04-rl-engine.md](docs/04-rl-engine.md).

---

## 7. Results and methodology

The framework's job is to *produce* the comparison, on *your* design. The
deliverable therefore ships:

* the measurement machinery (`python -m aiduvo compare`, `sweep`, report generator);
* the exact methodology, including which numbers mean what and how to avoid
  kidding yourself ([docs/09-results-and-methodology.md](docs/09-results-and-methodology.md));
* a results template whose tables `03_compare.bat` fills in
  ([results/](results/)).

Reported metrics per campaign: final closure, closure at the baseline's cycle
budget, cycles-to-target, simulated cycles, simulated time, wall time, per-group
closure, and the remaining hard bins.

> **On the synthetic backend.** `--mock` runs a fake simulator that speaks the
> real protocol and writes real UCIS XML. It proves the pipeline learns and that
> all three modes are measured identically. It is *not* a QuestaSim measurement
> and no speedup number from it should be quoted for any real design. Real
> numbers require `01_compile.bat` plus a `questa` backend.

---

## 8. Installation

```bat
python -m pip install -r requirements.txt      REM numpy
REM optional: python -m pip install matplotlib  (PNG charts; SVG needs nothing)
```

Python 3.9+ (3.11+ for TOML configs). QuestaSim must be on `PATH` or `QUESTA_ROOT`
must point at the installation; `scripts\windows\env.bat` detects it.

Run the framework selftest to confirm the install:

```bat
scripts\windows\05_selftest.bat
```

---

## 9. Constraints and honest limitations

* **QuestaSim + SystemVerilog/UVM is the only validated target.** The
  architecture is simulator-agnostic (everything goes through a transport and a
  command vocabulary), but VCS/Xcelium/Riviera and VHDL backends are future work,
  not shipped.
* **The Tcl command surface varies between QuestaSim releases.** Every capability
  is probed at session start (`aiduvo srie probe`) and the framework degrades
  gracefully. If `describe` is unhelpful on your release, the fallback is
  `find`, then a hierarchy dump you provide.
* **Forcing input ports changes stimulus, not the checker.** It cannot create
  coverage that requires internal state the DUT never reaches on its own.
* **A knob inventory is user data.** The framework cannot invent plusargs — they
  live inside your testbench, which it is not allowed to read. You provide
  `config/knobs.json` (or run `aiduvo knobs` for a template) and the optimizer
  explores the profiles you declare.
* **The FLI shim is a reference implementation.** It compiles against the Questa
  FLI headers and follows the documented `mti` API, but it has not been validated
  on every release. The Tcl transports are the supported path.

---

## 10. Documentation

| Document | Contents |
|---|---|
| [docs/00-overview.md](docs/00-overview.md) | problem, design goals, what "universal" can and cannot mean |
| [docs/01-architecture.md](docs/01-architecture.md) | layers, data flow, diagrams |
| [docs/02-srie-runtime.md](docs/02-srie-runtime.md) | the runtime engine in depth |
| [docs/03-blackbox.md](docs/03-blackbox.md) | the blackbox engine in depth |
| [docs/04-rl-engine.md](docs/04-rl-engine.md) | algorithms, state, reward, tuning |
| [docs/05-coverage-model.md](docs/05-coverage-model.md) | UCIS import, metrics, hardness |
| [docs/06-nonintrusiveness.md](docs/06-nonintrusiveness.md) | the rules and the linter |
| [docs/07-usage.md](docs/07-usage.md) | every CLI command and config field |
| [docs/08-questa-windows.md](docs/08-questa-windows.md) | QuestaSim specifics, troubleshooting |
| [docs/09-results-and-methodology.md](docs/09-results-and-methodology.md) | how to measure honestly |
| [docs/10-extending.md](docs/10-extending.md) | new simulator / HDL / policy / importer |
| [docs/11-troubleshooting.md](docs/11-troubleshooting.md) | symptoms and fixes |

---

## 11. Deliverable

A single ZIP of the whole tree can be produced (and is produced by
`06_package.bat`):

```bat
python -m aiduvo zip        REM -> dist\AId-UVO-RT-v1.0.0-<date>.zip
```

## 12. License

MIT. See [LICENSE](LICENSE).
