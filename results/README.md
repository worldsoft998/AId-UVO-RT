# Results

This directory holds the three-way comparison reports produced by the framework.
Nothing here is hand-written: every report is generated from the campaign
directories under `runs/`, which are themselves generated from a campaign config.

## Producing the comparison

```bat
REM one command: baseline + blackbox + runtime, then the report
python -m aiduvo sweep --runs 10 --seed 1 --target 0.9 --outdir results\sweep_01

REM or step by step
02_run_optimizer.bat        REM mode=baseline, AI=off  -> runs\baseline_*
02_run_optimizer.bat        REM mode=blackbox, AI=on   -> runs\blackbox_*
02_run_optimizer.bat        REM mode=runtime,  AI=on   -> runs\runtime_*
03_compare.bat
```

Each report directory contains:

| File | Contents |
|---|---|
| `report.md` | the full report (tables, charts, method, per-run detail) |
| `report.html` | the same, single file with inline SVG |
| `comparison.json` | machine-readable rows, curves and metrics |
| `closure_curve.svg` | closure vs cumulative cycles, all campaigns |
| `final_closure.svg` | final closure bar chart |
| `speedup.svg` | cycles-to-target speedup bar chart |

## What is in the box right now

`TEMPLATE.md` is the empty report skeleton: it documents exactly which numbers
are reported and how to read them. It is intentionally *not* filled with numbers.

**Why no pre-filled numbers?** Because a comparison report is only meaningful for
a specific design, simulator version and budget. Fabricating a table — or quoting
the synthetic mock backend — would be worse than shipping none. Run
`03_compare.bat` on your design and you get a real one in a minute.

The synthetic demo (`demo_mock.bat`) produces a full report under
`results/demo_mock/` so you can see the format and confirm the toolchain works
end to end. It is stamped with a disclaimer: mock numbers are illustrative.

## Reproducing an old report

Every campaign directory contains `campaign_result.json` with its curve and
metrics, so reports can be rebuilt without a simulator:

```bat
04_build_report.bat results\sweep_01
```
