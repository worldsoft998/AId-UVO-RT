# Troubleshooting

## The campaign finishes in 0 runs / no coverage

**Symptom:** `final closure 0.00%`, `WARNING: no coverage found`.

* Was the design compiled with coverage? `vopt +cover=bcestfx`. Check with
  `vsim -c -do "coverage report" work.tb_top_opt`.
* Does `python -m aiduvo srie probe` report `coverage: OK`? If it reports `NO`,
  the Tcl command in `srie.coverage_cmd` does not exist on your release. The
  default is `coverage report -detail -xml -output {output}`.
* Is the coverage report being written somewhere else? Try
  `python -m aiduvo srie tcl --command "coverage report -detail -xml -output C:/tmp/c.xml"`
  and see what the simulator answers.

## `describe` returns nothing / discovery finds no ports

* Run `python -m aiduvo srie discover --config <cfg>` and look at the report.
* If `describe` is unsupported, the framework falls back to `find nets -in`.
* If both fail, your release needs a hierarchy dump: run
  `vsim -c -do "describe -depth 5 /" work.tb_top_opt > hier.txt` and point
  `srie.discover_root`/`discover_depth` at the region you care about, or reduce
  `discover_root` to your DUT instance so a shallow `describe` is enough.
* Increase `srie.discover_depth` — with `root="/"` a DUT three levels down needs
  `depth >= 3` (path segments, not regions).

## Nothing is being forced

* `python -m aiduvo srie selftest` prints the candidate list and whether a force
  succeeded. If `candidates` is empty, discovery found no **input** ports —
  check `discover_depth` and `discover_root`.
* Clock/reset-like names are excluded by default. If your inputs are named
  `clk_en`-ish, adjust `srie.deny_patterns`.
* `force` may be rejected for a signal that is not a net in the current scope;
  the log line says `force failed on <path>: ...`.
* `srie.max_forced` may be too small for your target list — raise it.

## `Timeout waiting for <command>`

The transport waits for the sentinel and never sees it. Causes:

* the command is still running (`run -all` on a design that never finishes) —
  always use bounded `run <n> ns`, which the framework does;
* the simulator is waiting for input (a prompt inside a do-file);
* a `puts` in your own Tcl printed something that looks like a prompt.

Look at `runs/<campaign>/_srie_work/*.log` for the raw transcript.

## Blackbox runs fail with "simulator executable 'vsim' not found"

`scripts\windows\env.bat` did not find `vsim.exe`. Set `QUESTA_ROOT` or add the
`win64` directory to `PATH`, then re-run. `python -m aiduvo info` prints what the
framework resolved.

## `vcover` errors when reading the UCDB

* The UCDB may be truncated because the run was killed hard instead of
  interrupted. The framework interrupts gracefully; a manual `taskkill /f` does
  not.
* If `coverage.ucdb` is actually XML (mock backend), it is parsed directly and
  `vcover` is not used.
* Set `blackbox.coverage_format` to `text` if your `vcover` cannot emit XML.

## The agent does not improve anything

In order of likelihood:

1. **The action space is empty of meaning.** With no knobs and a single
   coverage group, the only decision is the seed. Add knobs, or use runtime mode.
2. **The budget is too small.** Bandits need ~10× the number of actions to
   separate them. 4 profiles × 12 focus options needs more than 4 runs.
3. **The reward is dominated by the time penalty.** If a run is slow, every
   decision looks bad. Lower `reward.time_penalty` or `time_ref_s`.
4. **Coverage is saturating on easy bins.** Look at `per-group closure`: if the
   hard group is still at 0%, the agent is not reaching it. That is a signal to
   change *what* is driven (runtime mode, different `max_forced`), not *how* it
   learns.
5. **The target is unreachable.** Some bins need internal state the DUT never
   produces under any input you can drive.

## Runtime mode is slower than baseline in wall time

Expected for small designs: each quantum costs a round trip. Mitigations:

* raise `quantum_cycles` (fewer decisions, less overhead);
* raise `srie.coverage_every` (snapshot every N steps);
* use the socket transport (lower per-command latency than pipe);
* reduce `max_forced`;
* use `intra_steps` small and more runs instead.

The comparison table reports both cycles and wall time precisely so you can make
this trade-off with data.

## `python -m aiduvo` says "No module named aiduvo"

Run from the repository root, or set `PYTHONPATH` to it (the batch files do this
for you), or `pip install -e .`.

## Lint fails on a file I just added

That is the point. Read the rule id in the message:

* `R2` — you imported an HDL parser or a network client; do not.
* `R3` — you have an HDL filename literal in framework code; move it to a config
  or to `examples/`.
* `R4` — you referenced the example design from framework code.
* `R5` — you open an HDL file at run time.
* `R7` — you execute a compiler from framework code; construct the command line
  instead (see `aiduvo/srie/launcher.py`).

## Getting help

`python -m aiduvo info` prints versions, resolved executables and the working
directory. Attach that plus the campaign log
(`runs/<campaign>/../last_run.log`) and, if relevant, the capability matrix from
`python -m aiduvo srie probe`.
