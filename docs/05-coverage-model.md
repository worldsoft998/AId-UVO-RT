# The coverage model

## Why not read the coverage source

A coverage model is source code: `covergroup`, `coverpoint`, `bins`, `cross`.
Reading it would be the easiest way to know what to chase — and it is exactly what
the project forbids. So the framework learns the coverage *structure* from the
database the simulator writes, and treats every name as an opaque string.

## The tree

```
CoverageSnapshot
└── CoverGroup  ("cg_ops", "cg_flags", "cg_level", ...)
    └── Coverpoint ("cp_op", "cp_level", "x_op_full", ...)
        └── Bin ("write", "read", "lvl[3]", "cross_2_1", ...)
              hits, goal, weight, excluded
```

`flat()` returns `{"cg_ops.cp_op.write": Bin(...)}` — a stable key used
everywhere (history store, hardest-bin ranking, reports).

## Importers

| Format | Function | Notes |
|---|---|---|
| UCIS XML | `parse_ucis` | primary; namespace- and version-tolerant |
| CSV | `parse_csv` | configurable column names |
| Questa text report | `parse_text_report` | fallback when XML export is unavailable |
| `load_coverage(path)` | auto-detect | by extension, then by content sniffing |

The UCIS parser walks the element tree and only cares about three things: a
group, a coverpoint, and a bin with a hit count. Hit counts are accepted as

* a `hits` / `count` / `covercount` attribute,
* a child `<ucis:count>` / `<hits>` element,
* in any namespace (`ucis:`, none, or a vendor one).

Ignore bins are imported with `excluded=True` and never counted in the totals.

## Metrics

| Metric | Meaning |
|---|---|
| `closure` | covered bins / total bins |
| `weighted_closure` | same, with hardness weights |
| `hardness_weights` | `1/(1+hits)^α`, normalised to mean 1 — never-hit bins dominate |
| `entropy` | normalised Shannon entropy of the hit distribution (is the stimulus stuck?) |
| `novelty(prev, cur)` | fraction of bins newly covered since `prev` |
| `zero_bin_ratio` | fraction of bins at zero |
| `group_closures` | per-group closure, for the report |
| `hardest_bins(snap, k)` | the k most urgent bins (0 hits first) |
| `time_to_closure(curve, target)` | interpolated cycles/wall to reach a target |
| `area_under_curve(curve)` | a single "how early did you get there" number |

## Merging

Coverage is a set: a bin is covered if it was covered in **any** run, and its hit
count is the maximum observed (`how="max"`). `how="sum"` matches `vcover merge`
counter semantics if you need it.

The campaign's cumulative snapshot is what the reward is computed against, so
"did this run add anything" is answered exactly, not approximately.

## The history store

`history.sqlite` keeps, per campaign:

* `campaigns` — mode, algorithm, config;
* `episodes` — the full `EpisodeResult` JSON per run;
* `snapshots` — cumulative closure per run, plus the full snapshot JSON;
* `bins` — one row per (run, bin) with hits, so hardest-bin queries are SQL;
* `actions` — the decision and its reward breakdown.

That makes a campaign resumable and auditable: `store.hardest_bins(campaign, 20)`
answers "what is still dark after 12 runs" without re-reading any UCDB.

## Practical notes

* If your simulator reports coverage as percentages only (no bin counts), use the
  text importer; the optimizer still works, but hardness weighting degrades to
  uniform because every bin looks either hit or not.
* `option.weight` in the UCIS file is imported but currently not used for
  closure; hardness weighting is derived from observed hits instead, which is
  design-agnostic.
* `excluded` bins are the only way to remove a bin from the goal. The optimizer
  never excludes anything itself — that would be cheating.
