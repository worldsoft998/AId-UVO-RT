# QuestaSim on Windows

## Prerequisites

* Siemens QuestaSim (any release with Tcl support — 10.7 through 2024.x),
  including a licence for `vsim`/`vcover`;
* Python 3.9+ with numpy;
* `vsim.exe` on `PATH`, or `QUESTA_ROOT` set to the install directory
  (`scripts\windows\env.bat` looks in `%QUESTA_ROOT%\win64`, `%QUESTA_ROOT%\bin`,
  and `C:\questasim64_2024.1\win64`).

```bat
set QUESTA_ROOT=C:\questasim64_2024.1
scripts\windows\00_menu.bat
```

## Compile with coverage

`01_compile.bat` runs `scripts/questa/compile.do`:

```
vlib work
vlog -sv -work work +incdir+examples/demo_fifo/tb <sources>
vopt -work work +cover=bcestfx -o tb_top_opt tb_top
```

`+cover=bcestfx` enables branch, condition, expression, statement, toggle and FSM
coverage. These are **simulator switches**: no source file changes, no `ifdef`
insertion, no instrumentation pass over your code.

To compile your own project, either edit the two lists at the top of
`compile.do`, or point the batch file at your existing script:

```bat
scripts\windows\01_compile.bat --do-file path\to\my_compile.do
```

## How the runtime mode launches the simulator

```
vsim -c -quiet -coverage -sv_seed <seed> -l <log> \
     -do "do <work>\srie_bootstrap.do" \
     work.tb_top_opt +NUM_TXNS=800 +STIM_MODE=1
```

The generated bootstrap (from `aiduvo/srie/bootstrap.py`) defines `srie_evt` and
`puts "@@SRIE_READY ...@@"`, then **returns to the prompt without running**. The
optimizer drives `run` itself, in quanta. That is the whole trick: `vsim` is
elaborated and idle, and Python owns the run loop.

For the socket transport, the same file additionally opens a Tcl server on a port
baked in at generation time (no do-file argument conventions to get wrong).

## Command surface actually used

| Purpose | Command | Fallback |
|---|---|---|
| version | `version -short` | — |
| hierarchy | `describe -depth 1 <path>` | `find nets -in <path>` |
| values | `examine -value <path>` | — |
| drive | `force -freeze <path> <val>` / `force -deposit` | — |
| release | `release <path>` | — |
| trigger | `when -label L {expr} {srie_evt "..."}` | — |
| run | `run <n> ns` | `run <n>` |
| coverage | `coverage report -detail -xml -output f` | `coverage report -detail` (text) |
| UCDB export | `vcover report -xml -output f <ucdb>` | — |
| clock | `examine -time` | — |

If your release spells one of these differently, change it in
`aiduvo/srie/tcl.py` — it is the only place commands are constructed — and the
probe will tell you immediately whether the change worked.

## Recommended first session

```bat
REM 1. does the simulator respond at all?
python -m aiduvo srie probe --config examples\demo_fifo\cfg\campaign_runtime.json

REM 2. does discovery find your hierarchy and coverage?
python -m aiduvo srie selftest --config examples\demo_fifo\cfg\campaign_runtime.json

REM 3. one short runtime campaign with a tiny budget
python -m aiduvo run --config examples\demo_fifo\cfg\campaign_runtime.json ^
       --runs 1 --max-steps 2 --target 0.99

REM 4. inspect what it did
type runs\fifo_runtime\_srie_work\*.log
```

Step 3 with `"dry_run": true` in the config prints every Tcl command instead of
executing it — the safest possible first contact.

## Windows specifics

* **Paths with spaces.** Everything the framework builds quotes arguments; the
  batch files quote `%AIDUVO_ROOT%`. If you still hit a quoting problem, use a
  short root (e.g. `C:\aiduvo`).
* **Long paths.** QuestaSim on older Windows builds dislikes deep paths; keep the
  repo within 3–4 directory levels from the drive root.
* **Ctrl-Break.** The blackbox backend uses `CTRL_BREAK_EVENT` to abort a run
  gracefully; the process is started with `CREATE_NEW_PROCESS_GROUP` so the signal
  reaches only the simulator.
* **Antivirus.** Real-time scanning of `runs\` slows campaigns down measurably;
  exclude the work directory.
* **Line endings.** Generated do-files use `\n`; QuestaSim accepts both.

## Performance

| Setting | Guidance |
|---|---|
| `quantum_cycles` | 100–500 for a small block, 1 000–10 000 for a large SoC |
| `coverage_every` | 2–5 if the coverage report dominates the round trip |
| `max_forced` | 4–8; more forces mean stronger stimulus but bigger command batches |
| `discover_depth` | the shallowest depth that still reaches your DUT's ports |
| blackbox `run_time` | short runs (100–500 µs) give the agent more decisions per hour |

Measure the per-quantum overhead once with `srie selftest` and set
`quantum_cycles` so a quantum takes a few tens of milliseconds of wall clock. That
is the sweet spot between steering granularity and overhead.

## Using an existing SRIE server

If you prefer to keep the simulator in a separate shell:

```bat
REM shell 1
vsim -c -do "do scripts\questa\srie_server.do 7654" work.tb_top_opt

REM shell 2 -- config with "transport": {"kind": "socket", "port": 7654}
python -m aiduvo srie probe --config config\socket.json
```

This is also the mode to use when you want to drive the agent from a Jupyter
notebook while watching the simulator transcript in another window.
