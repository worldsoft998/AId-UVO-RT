# AGENTS.md — repository knowledge for future sessions

AId-UVO-RT: AI-driven, coverage-driven verification optimization for RTL. It
observes a **running** simulator and steers stimulus through the simulator's own
control surface. It never reads/parses/edits RTL, TB, UVM or coverage-model
source. QuestaSim + SystemVerilog/UVM is the only validated target; the RL engine
is numpy-only and fully local.

## Non-negotiable invariants

1. **No source access.** Nothing in `aiduvo/` may reference HDL files, HDL
   parsers, or the example design. `python -m aiduvo lint` enforces this
   (`aiduvo/lint/nonintrusive.py`, rules R1–R7). Run it before every commit.
2. **No project-specific identifiers in the framework.** Paths, covergroups and
   plusargs are discovered at run time or supplied by the user in a config.
3. **No network / hosted AI.** numpy is the only hard dependency.
4. **Forces are dangerous.** Only discovered *input* ports, never clock/reset,
   capped by `srie.max_forced`, ledgered, and always released (`restore()` in a
   `finally`).
5. **Comparability.** All three modes (baseline / blackbox / runtime) must share
   the reward, the coverage model, the budget accounting and the report path. If
   you change one, change it in `aiduvo/core/`, not in a backend.

## Build / test / run

```bash
python -m pip install -e ".[dev]"

python -m aiduvo lint                # compliance (must pass)
python -m pytest -q                  # unit tests
python -m pytest -q -m "not slow"    # fast subset (no campaign loops)
python -m aiduvo selftest            # end-to-end on the synthetic backend
python -m aiduvo sweep --mock --runs 8 --outdir results/_demo   # 3-way report
```

Windows workflow: `scripts/windows/00_menu.bat` → `01_compile` → `02_run_optimizer`
→ `03_compare`. `demo_mock.bat` needs no licence.

## Layout (where things live)

| Path | Responsibility |
|---|---|
| `aiduvo/core/types.py` | `Action`, `Observation`, `EpisodeResult`, `CampaignResult`, `Budget` |
| `aiduvo/core/space.py` | `FactoredActionSpace`, `Head`, `StateEncoder` (24 features) |
| `aiduvo/core/reward.py` | hardness-weighted reward + plateau/goal terms |
| `aiduvo/core/engine.py` | `Campaign` — the only place the outer loop lives |
| `aiduvo/core/backend.py` | `Backend` ABC + `BackendInfo` |
| `aiduvo/srie/transport.py` | pipe / Tcl-socket / mock transports (+ FLI in `fli_bridge.py`) |
| `aiduvo/srie/protocol.py` | sentinel framing, `Event`, error types |
| `aiduvo/srie/tcl.py` | **all** Tcl command builders and output parsers |
| `aiduvo/srie/introspection.py` | capability probe, hierarchy discovery, coverage read |
| `aiduvo/srie/reflection.py` | force/release/trigger/run control + safety rails |
| `aiduvo/srie/optimizer.py` | `RuntimeBackend` — nested inter/intra-run loops |
| `aiduvo/srie/bootstrap.py` | canonical Tcl bootstrap (generated per session) |
| `aiduvo/srie/mock.py` | synthetic Questa-like simulator (tests/demos) |
| `aiduvo/blackbox/backend.py` | real + mock blackbox backends |
| `aiduvo/blackbox/runner.py` | subprocess supervision, generated do-file, early abort |
| `aiduvo/blackbox/knobs.py` | knob inventory, profiles, `SeedStrategy` |
| `aiduvo/coverage/ucis.py` | UCIS XML / CSV / text importers |
| `aiduvo/rl/*` | policies (bandits, Q, DQN, PPO, surrogate) + numpy MLP |
| `aiduvo/reporting/*` | comparison, SVG charts, markdown, HTML |
| `aiduvo/discovery/discover.py` | hierarchy+coverage discovery → config |
| `aiduvo/lint/nonintrusive.py` | the compliance rules |
| `scripts/questa/` | do-files (compile/run/coverage/bootstrap/server) + FLI C shim |
| `scripts/windows/` | `.bat` menus (env, compile, optimizer, compare, report, selftest, package) |
| `scripts/tools/make_config.py` | JSON config builder used by the batch menu |
| `examples/demo_fifo/` | demo DUT + UVM TB + generated configs (**user space**) |

## Gotchas learned the hard way

* **`is_noise()` must not strip `#` lines.** QuestaSim's `describe` output uses
  `#` prefixes; only prompt lines (`VSIM n>`) are noise.
* **Region detection.** `describe` output does not always label sub-regions.
  `parse_describe` looks for `region`/`instance`/`(module` and `discover()` has a
  one-extra-level probe fallback when nothing is labelled.
* **Discovery depth is in path segments.** With `root="/"`, reaching
  `/tb_top/u_dut/wr_en` needs `discover_depth >= 3`; the mock design
  (`/tb/top/u_dut/in_00`) needs 4.
* **The mock's root children** are found by `path.count("/") == 1`, not by
  `rsplit` (a quirk of `/`-rooted paths).
* **Socket framing carries the cid**: `<cid>\t<command>`; the Tcl server echoes
  `@@SRIE_END <cid> rc=...@@`. Pipe mode wraps the command in `catch` instead.
* **`when` bodies use double quotes, not braces**, so `[now]` is substituted:
  `srie_evt "{\"kind\":\"trigger\",\"t\":\"[now]\"}"`. `triggers.trigger_body`
  builds this.
* **Reward efficiency is incremental** (`Δclosure / (1 + log1p(Δcycles))`). A
  cumulative efficiency term makes the plateau penalty meaningless.
* **Baseline uses the same runner as blackbox** with a fixed action
  (`seed_mode=sweep`, `profile=none`). Do not give it a separate code path.
* **`hash()` is not stable across processes** — use `zlib.crc32` for anything
  that must be reproducible (see `_bias_targets`).
* **Mock results must stay labelled as illustrative.** `compare()` adds a
  disclaimer when any campaign's backend is `mock`.
* **`_ensure_loaded()` must not be guarded by `if _REGISTRY: return`.** Importing
  any learner module registers a class, so a non-empty registry says nothing
  about whether the control policies (`none`/`random`/`round_robin`) were added.
  It is guarded by an explicit `_LOADED` flag; without that, every baseline
  campaign raises `unknown algorithm 'none'`.
* **`*.log` is git-ignored** (simulator transcripts), so anything under
  `tests/fixtures/` needs an explicit `!tests/fixtures/*.log` exception or it
  silently never reaches CI. Audit with: list files on disk minus `git ls-files`.
* **CI must pin `ubuntu-22.04`.** On the current `ubuntu-latest` (26.04)
  `actions/setup-python` has no 3.9 build, and the resulting failure cancels the
  whole matrix under `fail-fast` — the suite appears to run and does not.
* **Transcript parsing is line-buffered.** `poll()` holds the last partial line
  back while tailing; call `flush()` at end of run or `$finish` written without
  a trailing newline is missed. `scan_text()` goes through `_consume`/`_classify`
  directly because it has no file to `poll()`.

## Conventions

* Python 3.9+; no `match`, no `X | Y` runtime unions.
* Public functions get type hints and a docstring explaining intent.
* Comments only for non-obvious invariants/trade-offs, never for narration.
* Keep the layer boundaries: a backend may not compute rewards, and `core` may
  not know what a signal is.
* Every behaviour needs a test that runs **without** a simulator (mock backend).
