"""Reporting: comparison tables, charts and portable reports."""

from aiduvo.reporting.charts import bar_chart_svg, line_chart_svg, save_png, save_svg
from aiduvo.reporting.compare import (
    DISCLAIMER,
    Comparison,
    Row,
    compare,
    load_campaign,
    markdown_table,
    verdict,
)
from aiduvo.reporting.html import build_html, md_to_html
from aiduvo.reporting.markdown import build_report

__all__ = [
    "Comparison",
    "Row",
    "compare",
    "load_campaign",
    "markdown_table",
    "verdict",
    "DISCLAIMER",
    "build_report",
    "build_html",
    "md_to_html",
    "line_chart_svg",
    "bar_chart_svg",
    "save_svg",
    "save_png",
]
