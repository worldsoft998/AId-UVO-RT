# Results and methodology

## What is being measured

Three campaigns, identical in everything except how much the agent may see and do:

| | baseline | blackbox | runtime |
|---|---|---|---|
| seeds | sweep 1..N | agent chooses | agent chooses |
| plusargs | none | agent chooses a profile | agent chooses a profile |
| run length | fixed | agent-bounded, early abort | agent-bounded per quantum |
| stimulus | untouched | untouched | input ports driven between quanta |
| sees inside the simulator | no | no | yes |

Metrics, all derived from `CampaignResult`:

| Metric | Definition | Why it matters |
|---|---|---|
| final closure | covered / total bins after the last run | did we get there |
| closure @ baseline budget | closure reached within the baseline's *total cycle* budget | fair "same effort" comparison |
| cycles to target | interpolated simulated cycles to reach e.g. 90% | the speedup number |
| wall time | real seconds | what you actually pay |
| simulated time | ns simulated | simulator-independent effort |
| runs used | number of `vsim` invocations | licence/queue cost |
| per-group closure | closure inside each covergroup | did it fix the *hard* group |
| remaining hard bins | bins still at 0 | what is left for a human |

## The headline table

`03_compare.bat` (or `python -m aiduvo compare`) emits exactly this:

| Campaign | Mode | AI | Runs | Final closure | Closure @ baseline budget | Cycles to target | Speedup (cycles) | Sim time (ns) | Wall (s) |
|---|---|---|---|---|---|---|---|---|---|
| baseline | baseline | no | … | … | … | … | 1.00x | … | … |
| blackbox | blackbox | yes | … | … | … | … | … | … | … |
| runtime | runtime | yes | … | … | … | … | … | … | … |

Plus a curve (`closure_curve.svg`), a bar chart of final closure, a bar chart of
speedup, per-group tables, and the list of bins still at zero.

## How to run it honestly

1. **Same budget for everyone.** Same `max_runs`, same `run_time`, same target.
   `sweep` does this for you.
2. **Same seed base.** `--seed 1` for all three. The baseline's seeds are
   1..N; the agents start from the same base.
3. **More than one seed.** A single campaign is an anecdote. Run the whole sweep
   three times with `--seed 1/2/3` and report the spread, not just the best run.
4. **Report the target, not just the endpoint.** "Reached 90% in 3 runs instead
   of 7" is a stronger claim than "ended at 97% instead of 93%", because the
   latter hides how much budget the agent burned.
5. **Check the hard bins.** A closure gain concentrated in easy groups is a
   measurement artefact; look at `per-group closure` and the remaining hard bins.
6. **Watch wall time.** A runtime campaign that closes coverage in fewer cycles
   but takes more wall time has not necessarily saved you anything. Both numbers
   are in the table.
7. **Do not tune on the test set.** If you pick the algorithm after looking at
   the results, say so.

## Reading the numbers

* **Cycles to target** is the fairest "speed" metric: it is independent of
  machine load and of how many CPUs the regression farm has.
* **Speedup (cycles)** = baseline cycles-to-target / campaign cycles-to-target.
  It is `-` when either campaign never reaches the target.
* **Closure @ baseline budget** answers "if I gave the AI exactly the effort the
  baseline used, where would it be?" — usually the most persuasive number.
* **Area under the curve** (in `comparison.json`) rewards reaching coverage
  early, not just eventually.

## What the synthetic backend proves, and what it does not

`--mock` runs a fake simulator. It proves:

* the protocol layer works end to end (framing, events, force/release ledger);
* the coverage importer handles real UCIS XML;
* the reward/state/action plumbing produces learning signal;
* the three modes are measured identically, so a difference between them is a
  difference in *information*, not in the harness.

It does **not** prove anything about your design, and its numbers must not be
quoted. The report generator stamps mock results with a disclaimer for exactly
this reason.

## A worked example of the shape to expect

On a real design you should expect the following *pattern* (not these numbers):

```
closure
 100% │                                   ╭──── runtime (AI + SRIE)
      │                          ╭────────╯
  90% │                 ╭────────╯   ╭──── blackbox (AI, logs only)
      │        ╭────────╯   ╭────────╯
  70% │  ╭─────╯    ╭──────╯  ╭────────── baseline (no AI)
      │ ╱      ╭───╯   ╭──────╯
  50% │╱   ╭───╯  ╭────╯
      └────────────────────────────────────► cumulative cycles
```

If your runtime curve does **not** beat the blackbox curve, the most common
causes are (in order): the forced signals are not the ones that matter; the
quantum is too long to influence anything; coverage is dominated by a group the
agent cannot reach without internal state.

## Reproducing a report

```bat
REM from an existing results directory
04_build_report.bat results\comparison_20250101_1200

REM or explicitly
python -m aiduvo compare ^
  --campaign baseline=runs\baseline_linucb_20250101_1200 ^
  --campaign blackbox=runs\blackbox_linucb_20250101_1200 ^
  --campaign runtime=runs\runtime_ppo_20250101_1200 ^
  --outdir results\final --baseline baseline --target 0.9
```

Everything needed for the report is inside each campaign directory
(`campaign_result.json`), so a report can be rebuilt months later without the
simulator.
