"""Single-file HTML report.

A small markdown subset is converted inline so the report is one portable file
with no external CSS, no JS and no image dependencies: the SVG charts produced
next to the markdown are inlined into the page.
"""

from __future__ import annotations

import html as _html
import os
import re
from typing import List, Optional

CSS = """
:root { --fg:#1b1f24; --muted:#5c636a; --line:#e9ecef; --accent:#2f6feb; --bg:#ffffff; --soft:#f8f9fa; }
* { box-sizing: border-box; }
body { margin:0; padding:0; background:var(--soft); color:var(--fg);
  font-family:"Segoe UI",Helvetica,Arial,sans-serif; line-height:1.55; }
main { max-width: 1080px; margin: 0 auto; background:var(--bg); padding: 40px 48px 64px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
h1 { font-size: 26px; margin: 0 0 8px; letter-spacing:-.2px; }
h2 { font-size: 19px; margin: 36px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }
h3 { font-size: 15px; margin: 24px 0 8px; color:#343a40; }
p, li { font-size: 14px; }
code { background:var(--soft); border:1px solid var(--line); border-radius:4px;
  padding:1px 5px; font-family:Consolas,"Courier New",monospace; font-size:12.5px; }
pre { background:var(--soft); border:1px solid var(--line); border-radius:6px; padding:12px 14px;
  overflow-x:auto; }
pre code { border:none; background:none; padding:0; }
table { border-collapse: collapse; width:100%; margin:14px 0; font-size:13px; }
th, td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
th { background:var(--soft); font-weight:600; }
tr:nth-child(even) td { background:#fcfcfd; }
img, svg { max-width:100%; height:auto; display:block; margin:16px 0; }
blockquote { border-left:3px solid var(--accent); margin:12px 0; padding:4px 14px; color:var(--muted); }
hr { border:none; border-top:1px solid var(--line); margin:28px 0; }
.badge { display:inline-block; font-size:11px; padding:2px 8px; border-radius:10px;
  background:#e7f0ff; color:#1c4fd8; margin-left:8px; vertical-align:middle; }
footer { max-width:1080px; margin:0 auto; padding:14px 48px 40px; color:var(--muted); font-size:12px; }
"""


def _inline(text: str) -> str:
    out = _html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def md_to_html(md: str, base_dir: str = "") -> str:
    """Convert the markdown subset used by the report generator."""
    lines = md.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            i += 1
            block: List[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + _html.escape("\n".join(block)) + "</code></pre>")
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].replace("|", "").strip()) <= set("-: "):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            body: List[List[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_inline(c)}</th>" for c in header)
                       + "</tr></thead><tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if m:
            alt, src = m.group(1), m.group(2)
            path = os.path.join(base_dir, src) if base_dir else src
            if os.path.exists(path) and src.lower().endswith(".svg"):
                with open(path, "r", encoding="utf-8") as fh:
                    out.append(fh.read())
            else:
                out.append(f'<p><em>[missing chart: {_html.escape(src)}]</em></p>')
            i += 1
            continue
        if stripped.startswith(("- ", "* ")):
            out.append("<ul>")
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                out.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("</ul>")
            continue
        if not stripped:
            i += 1
            continue
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,4}\s|\||```|- |\* |!\[)", lines[i].strip()
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def build_html(md: str, out_path: str, title: str = "AId-UVO-RT report",
               subtitle: str = "AI-Driven Universal Verification Optimization") -> str:
    body = md_to_html(md, base_dir=os.path.dirname(os.path.abspath(out_path)))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title>
<style>{CSS}</style></head>
<body><main>
<h1>{_html.escape(title)}<span class="badge">AId-UVO-RT</span></h1>
<p style="color:var(--muted);margin-top:0">{_html.escape(subtitle)}</p>
{body}
</main>
<footer>Generated locally by AId-UVO-RT. No external services were contacted;
all learning and inference ran on this machine.</footer>
</body></html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path
