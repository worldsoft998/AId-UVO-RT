# Changelog

All notable changes to AId-UVO-RT. Format: [Keep a Changelog](https://keepachangelog.com/);
versioning: semantic.

## [1.0.0] — 2025-11-26

First complete release: QuestaSim + SystemVerilog/UVM, Python RL/ANN engine,
runtime and blackbox optimizers, comparison reporting, Windows batch workflow.

### Added — core
- `Campaign` engine: budget accounting, reward shaping, state encoding, factored
  action space, SQLite history, reproducible seeding.
- Three nested modes (baseline / blackbox / runtime) sharing one reward, one
  coverage model and one report, so the comparison is apples-to-apples.
- 24-feature design-agnostic state vector; hardness-weighted reward that
  emphasises never-hit bins.

### Added — SRIE (runtime)
- Wire protocol with sentinel framing and asynchronous event push.
- Transports: `vsim -c` over pipes, Tcl socket server, FLI shim (reference
  implementation), and a synthetic mock that speaks the same protocol.
- Tcl command builders and tolerant parsers (`describe`, `examine`, `force`,
  `release`, `when`, `run`, `coverage`).
- Capability probing with graceful degradation (`describe` -> `find` -> dump).
- Hierarchical discovery (BFS, depth in path segments, region-detection fallback).
- Reflection controller with a force ledger, input-only enforcement, clock/reset
  deny list, force cap and guaranteed release.
- Two nested control loops (inter-run bandit, intra-run PPO/DQN) with optional
  `when` triggers that push events mid-run.

### Added — blackbox
- `vsim` runner with generated simulator-only do-file, transcript tailing,
  graceful early abort (Ctrl-Break / SIGINT).
- Knob inventory (plusarg int/enum/flag/string, `uvm_set_config_*`) with
  auto-generated profiles; seed strategies (sweep / fresh / resume_best /
  mutate_best).
- UCDB -> UCIS XML import via `vcover`, with XML passthrough.

### Added — coverage
- Project-agnostic coverage tree; UCIS XML parser tolerant of namespaces and of
  both count encodings; CSV and Questa text fallbacks.
- Metrics: closure, hardness-weighted closure, entropy, novelty, zero-bin ratio,
  per-group closure, time-to-target, area under the curve.
- SQLite history store with per-bin rows for hard-bin queries.

### Added — RL / ANN (numpy only, fully local)
- LinUCB, Thompson sampling, epsilon-greedy, tabular Q-learning, double DQN,
  PPO, and an ANN coverage surrogate, all behind one `Policy` interface.
- Numpy MLP with Adam, Huber loss, gradient clipping, standardiser, replay buffer.
- Save/load for every learner.

### Added — reporting
- Three-way comparison (final closure, closure at baseline budget,
  cycles-to-target, speedup, per-group, remaining hard bins).
- Dependency-free SVG charts, markdown report, single-file HTML report.
- Mock-backend results are stamped with an explicit disclaimer.

### Added — governance
- `aiduvo lint`: seven mechanical non-intrusiveness rules, run in selftest and CI.
- `aiduvo selftest`: end-to-end check on the synthetic backend, no simulator needed.
- Windows batch workflow with interactive menus (mode, AI on/off, algorithm,
  runs, seed, target, backend), plus Linux shell parity.
- Demo FIFO DUT + UVM testbench (user space) and three campaign configs.
- Optional semantic metadata layer (clock/reset/data/control/handshake roles).

### Known limitations
- QuestaSim + SystemVerilog/UVM is the only validated target.
- The FLI shim compiles against the documented `mti` API but is not validated on
  every release; the Tcl transports are the supported path.
- Tcl command spelling varies between QuestaSim releases; all of it is confined
  to `aiduvo/srie/tcl.py` and surfaced by `aiduvo srie probe`.
