# Demo: 8-bit FIFO with a UVM testbench

A deliberately small but complete target: a parameterised synchronous FIFO, an
interface, a UVM environment with a driver/monitor/coverage collector/scoreboard,
and a randomised test driven by four plusargs.

## Files

| File | Role |
|---|---|
| `rtl/fifo.sv` | the DUT |
| `tb/fifo_if.sv` | interface with driver/monitor clocking blocks |
| `tb/fifo_tb_pkg.sv` | UVM package: config, item, sequence, driver, monitor, coverage, scoreboard, env, test |
| `tb/fifo_tb_top.sv` | clock/reset, DUT instance, `run_test()` |
| `cfg/knobs.json` | plusarg inventory the optimizer turns into profiles |
| `cfg/campaign_baseline.json` | no-AI control campaign |
| `cfg/campaign_blackbox.json` | post-run/log-driven campaign |
| `cfg/campaign_runtime.json` | live SRIE campaign |

**Everything in this folder is user space.** The optimizer never reads it. The
configs only contain simulator-level controls (seed, plusargs, run length) and
paths discovered at run time.

## Run it

```bat
REM 1. compile with coverage (simulator switches only)
01_compile.bat

REM 2. three-way experiment
02_run_optimizer.bat          REM choose mode=runtime, backend=questa, algorithm=ppo
03_compare.bat
```

or from a shell:

```bat
python -m aiduvo run --config examples\demo_fifo\cfg\campaign_runtime.json ^
    --runs 6 --target 0.95
python -m aiduvo run --config examples\demo_fifo\cfg\campaign_blackbox.json --runs 12
python -m aiduvo run --config examples\demo_fifo\cfg\campaign_baseline.json  --runs 12
python -m aiduvo compare ^
    --campaign baseline=runs\fifo_baseline ^
    --campaign blackbox=runs\fifo_blackbox ^
    --campaign runtime=runs\fifo_runtime ^
    --outdir results\fifo --baseline baseline
```

## What the coverage model looks like

`cg_ops` has 4 operation bins, `cp_level` has 17 level bins, `cp_full`/`cp_empty`
are 2 bins each, and the two crosses add the interesting corners. `cg_flags`
covers overflow/underflow and their cross. The optimizer sees all of this as an
opaque bin tree; it never learns the names from the source, only from the
coverage database at run time.

## Why this is a good demo target

* the corners (`full` while writing, `empty` while reading, simultaneous
  read+write at the boundary) are rare under uniform random stimulus;
* a knob profile (`STIM_MODE=1` + `ERR_RATE=20` + low `RD_RATIO`) makes them much
  more likely -- which is exactly what the optimizer has to discover;
* a live force on `wr_en`/`rd_en` can create the boundary conditions directly,
  which is what runtime mode is for.
