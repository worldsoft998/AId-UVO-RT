"""Dependency-free SVG charts.

matplotlib is optional and only used when the caller asks for PNG.  The SVG
renderer below is enough for the two charts a coverage report needs -- a
progress curve and a bar comparison -- and it keeps the install to ``numpy``.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

PALETTE = ("#2f6feb", "#e8590c", "#12b886", "#ae3ec9", "#f08c00", "#495057", "#c2255c", "#0b7285")


def _esc(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ticks(lo: float, hi: float, n: int = 5) -> List[float]:
    if hi <= lo:
        hi = lo + 1.0
    step = (hi - lo) / max(1, n - 1)
    return [lo + i * step for i in range(n)]


def line_chart_svg(
    series: Dict[str, Sequence[Tuple[float, float]]],
    x_label: str = "cumulative cycles",
    y_label: str = "closure",
    title: str = "",
    width: int = 760,
    height: int = 380,
    y_range: Optional[Tuple[float, float]] = None,
    markers: Optional[Dict[str, float]] = None,
) -> str:
    """Multi-series line chart. ``series`` maps a label to [(x, y), ...]."""
    pad_l, pad_r, pad_t, pad_b = 64, 150, 40, 48
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    xs = [x for pts in series.values() for x, _ in pts] or [0.0]
    ys = [y for pts in series.values() for _, y in pts] or [0.0]
    x_lo, x_hi = 0.0, max(xs) if max(xs) > 0 else 1.0
    if y_range:
        y_lo, y_hi = y_range
    else:
        y_lo, y_hi = min(0.0, min(ys)), max(1.0, max(ys) * 1.05)

    def sx(x: float) -> float:
        return pad_l + (x - x_lo) / max(1e-9, x_hi - x_lo) * plot_w

    def sy(y: float) -> float:
        return pad_t + plot_h - (y - y_lo) / max(1e-9, y_hi - y_lo) * plot_h

    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI,Helvetica,Arial,sans-serif">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    if title:
        out.append(f'<text x="{pad_l}" y="24" font-size="15" font-weight="600" fill="#1b1f24">'
                   f"{_esc(title)}</text>")
    # grid + y ticks
    for t in _ticks(y_lo, y_hi, 6):
        y = sy(t)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
                   f'stroke="#e9ecef" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" font-size="11" fill="#5c636a" '
                   f'text-anchor="end">{t:.2f}</text>')
    # x ticks
    for t in _ticks(x_lo, x_hi, 6):
        x = sx(t)
        out.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" '
                   f'stroke="#f1f3f5" stroke-width="1"/>')
        label = f"{t/1e6:.2f}M" if t >= 1e6 else (f"{t/1e3:.1f}k" if t >= 1e3 else f"{t:.0f}")
        out.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" font-size="11" fill="#5c636a" '
                   f'text-anchor="middle">{label}</text>')
    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
               f'y2="{pad_t + plot_h}" stroke="#adb5bd" stroke-width="1.2"/>')
    out.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" '
               f'stroke="#adb5bd" stroke-width="1.2"/>')
    # series
    legend_y = pad_t + 6
    for i, (label, pts) in enumerate(series.items()):
        color = PALETTE[i % len(PALETTE)]
        if len(pts) >= 2:
            d = " ".join(("M" if j == 0 else "L") + f"{sx(x):.1f},{sy(y):.1f}"
                         for j, (x, y) in enumerate(pts))
            out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
                       f'stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y in pts:
            out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.6" fill="{color}"/>')
        lx, ly = pad_l + plot_w + 14, legend_y + i * 20
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="12" height="3" fill="{color}"/>')
        out.append(f'<text x="{lx + 18}" y="{ly - 1}" font-size="11.5" fill="#343a40">'
                   f"{_esc(label)}</text>")
    if markers:
        for label, value in markers.items():
            if y_lo <= value <= y_hi:
                y = sy(value)
                out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
                           f'stroke="#868e96" stroke-dasharray="5 4" stroke-width="1"/>')
                out.append(f'<text x="{pad_l + 6}" y="{y - 4:.1f}" font-size="10.5" '
                           f'fill="#868e96">{_esc(label)}</text>')
    out.append(f'<text x="{pad_l + plot_w / 2:.0f}" y="{height - 10}" font-size="12" '
               f'fill="#495057" text-anchor="middle">{_esc(x_label)}</text>')
    out.append(f'<text x="16" y="{pad_t + plot_h / 2:.0f}" font-size="12" fill="#495057" '
               f'transform="rotate(-90 16 {pad_t + plot_h / 2:.0f})" '
               f'text-anchor="middle">{_esc(y_label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def bar_chart_svg(
    labels: Sequence[str],
    values: Sequence[float],
    title: str = "",
    y_label: str = "",
    width: int = 760,
    height: int = 340,
    value_fmt: str = "{:.2f}",
) -> str:
    pad_l, pad_r, pad_t, pad_b = 64, 24, 40, 60
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    v_hi = max(values) * 1.15 if values and max(values) > 0 else 1.0
    n = max(1, len(values))
    slot = plot_w / n
    bar_w = slot * 0.55
    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI,Helvetica,Arial,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    if title:
        out.append(f'<text x="{pad_l}" y="24" font-size="15" font-weight="600" fill="#1b1f24">'
                   f"{_esc(title)}</text>")
    for t in _ticks(0.0, v_hi, 5):
        y = pad_t + plot_h - (t / v_hi) * plot_h
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
                   f'stroke="#e9ecef"/>')
        out.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" font-size="11" fill="#5c636a" '
                   f'text-anchor="end">{t:.2f}</text>')
    for i, (label, value) in enumerate(zip(labels, values)):
        h = max(0.0, value / v_hi) * plot_h
        x = pad_l + slot * i + (slot - bar_w) / 2
        y = pad_t + plot_h - h
        color = PALETTE[i % len(PALETTE)]
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
                   f'fill="{color}" rx="3"/>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" font-size="11.5" '
                   f'fill="#343a40" text-anchor="middle">{value_fmt.format(value)}</text>')
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{pad_t + plot_h + 18}" font-size="11.5" '
                   f'fill="#343a40" text-anchor="middle">{_esc(label)}</text>')
    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
               f'y2="{pad_t + plot_h}" stroke="#adb5bd" stroke-width="1.2"/>')
    if y_label:
        out.append(f'<text x="16" y="{pad_t + plot_h / 2:.0f}" font-size="12" fill="#495057" '
                   f'transform="rotate(-90 16 {pad_t + plot_h / 2:.0f})" text-anchor="middle">'
                   f"{_esc(y_label)}</text>")
    out.append("</svg>")
    return "\n".join(out)


def save_svg(path: str, svg: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path


def save_png(series: Dict[str, Sequence[Tuple[float, float]]], path: str,
             x_label: str = "cumulative cycles", y_label: str = "closure",
             title: str = "") -> Optional[str]:
    """Optional PNG rendering; returns ``None`` when matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    fig, ax = plt.subplots(figsize=(8.2, 4.0), dpi=140)
    for label, pts in series.items():
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.8, label=label)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
