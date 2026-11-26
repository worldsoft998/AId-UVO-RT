"""Markdown report generation."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from aiduvo.reporting import charts
from aiduvo.reporting.compare import Comparison, DISCLAIMER, markdown_table, verdict


def _curve_series(cmp_: Comparison, key: str = "cum_cycles") -> Dict[str, List[tuple]]:
    series: Dict[str, List[tuple]] = {}
    for r in cmp_.rows:
        pts = r.curve_cycles if key == "cum_cycles" else r.curve_wall
        series[f"{r.label} ({r.final_closure * 100:.1f}%)"] = pts
    return series


def build_report(
    cmp_: Comparison,
    outdir: str,
    title: str = "AId-UVO-RT coverage closure comparison",
    extra_sections: Optional[Sequence[tuple]] = None,
    repro: Optional[Sequence[str]] = None,
    write_html: bool = True,
) -> str:
    """Write ``report.md`` (plus charts and ``report.html``); return the markdown."""
    os.makedirs(outdir, exist_ok=True)
    curve_svg = charts.line_chart_svg(
        _curve_series(cmp_),
        x_label="cumulative simulated cycles",
        y_label="functional closure",
        title="Coverage closure vs simulated effort",
        markers={f"target {cmp_.target * 100:.0f}%": cmp_.target},
    )
    charts.save_svg(os.path.join(outdir, "closure_curve.svg"), curve_svg)

    bars_svg = charts.bar_chart_svg(
        [r.label for r in cmp_.rows],
        [r.final_closure * 100 for r in cmp_.rows],
        title="Final functional closure (%)",
        y_label="closure %",
        value_fmt="{:.2f}",
    )
    charts.save_svg(os.path.join(outdir, "final_closure.svg"), bars_svg)

    rows = [r for r in cmp_.rows if r.speedup_cycles or r.closure_at_baseline_budget is not None]
    effort_svg = ""
    if rows:
        effort_svg = charts.bar_chart_svg(
            [r.label for r in rows],
            [r.speedup_cycles or 0.0 for r in rows],
            title="Speedup to reach the target closure (x, higher is better)",
            y_label="speedup",
            value_fmt="{:.2f}x",
        )
        charts.save_svg(os.path.join(outdir, "speedup.svg"), effort_svg)

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Generated: {cmp_.generated}  ")
    lines.append(f"Target closure for time-to-target: **{cmp_.target * 100:.0f}%**  ")
    lines.append(f"Baseline campaign: `{cmp_.baseline_key}`")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    lines.append(verdict(cmp_))
    lines.append("")
    lines.append(markdown_table(cmp_))
    lines.append("")
    lines.append("![Coverage closure curve](closure_curve.svg)")
    lines.append("")
    lines.append("![Final closure](final_closure.svg)")
    if effort_svg:
        lines.append("")
        lines.append("![Speedup](speedup.svg)")
    lines.append("")

    lines.append("## Per-run detail")
    lines.append("")
    for r in cmp_.rows:
        lines.append(f"### {r.label}")
        lines.append("")
        lines.append(
            f"- mode: `{r.mode}`  algorithm: `{r.algorithm}`  AI: "
            f"{'on' if r.ai else 'off'}  runs: {r.runs}  stopped: `{r.stopped_reason}`"
        )
        lines.append(
            f"- final closure: **{r.final_closure * 100:.2f}%** "
            f"(weighted {r.final_wclosure * 100:.2f}%)"
        )
        lines.append(
            f"- simulated cycles: {r.total_cycles:,.0f}   sim time: {r.total_sim_ns:,.0f} ns   "
            f"wall: {r.total_wall_s:,.1f} s"
        )
        if r.ttc_cycles is not None:
            lines.append(f"- cycles to {cmp_.target * 100:.0f}%: {r.ttc_cycles:,.0f}")
        else:
            lines.append(f"- cycles to {cmp_.target * 100:.0f}%: not reached")
        if r.closure_at_baseline_budget is not None:
            lines.append(
                f"- closure within the baseline's cycle budget: "
                f"{r.closure_at_baseline_budget * 100:.2f}%"
            )
        if r.group_closures:
            lines.append("- per-group closure:")
            lines.append("")
            lines.append("| group | closure |")
            lines.append("|---|---|")
            for g, v in sorted(r.group_closures.items(), key=lambda kv: kv[1]):
                lines.append(f"| {g} | {v * 100:.2f}% |")
        if r.error:
            lines.append(f"- **error:** `{r.error}`")
        lines.append("")

    if extra_sections:
        for heading, body in extra_sections:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(body)
            lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        "All three campaigns use the same reward function, the same coverage importer, "
        "the same budget accounting and the same reporting path. The only differences are "
        "the action space and how the optimizer talks to the simulator:"
    )
    lines.append("")
    lines.append(
        "- **baseline** - sequential seeds, no knobs, no adaptation (plain constrained random)."
    )
    lines.append(
        "- **blackbox** - seeds / plusarg profiles / run length chosen by the RL agent; "
        "observations come only from the transcript and the coverage database."
    )
    lines.append(
        "- **runtime** - the RL agent steers a live simulation through SRIE: it samples "
        "signals, reads coverage mid-run, and drives discovered input ports between run quanta."
    )
    lines.append("")
    lines.append(
        "No RTL, testbench, UVM or coverage-model source is read or modified by any mode."
    )
    lines.append("")

    if repro:
        lines.append("## Reproduce")
        lines.append("")
        lines.append("```bat")
        for cmd in repro:
            lines.append(cmd)
        lines.append("```")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    for note in cmp_.notes:
        lines.append(f"- {note}")
    lines.append("")

    md = "\n".join(lines)
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    cmp_.save(os.path.join(outdir, "comparison.json"))
    if write_html:
        from aiduvo.reporting.html import build_html

        build_html(md, os.path.join(outdir, "report.html"), title=title)
    return md
