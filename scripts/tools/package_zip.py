#!/usr/bin/env python3
"""Package the repository into a single downloadable ZIP.

Excluded: .git, virtualenvs, caches, previous archives, run artifacts.  The
archive keeps the top-level folder so it unpacks cleanly.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from typing import List, Optional

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".idea", ".vscode", "node_modules",
    ".venv", "venv", "build", "dist", "runs", "work", "_artifacts", "htmlcov",
}
EXCLUDE_SUFFIX = (
    ".pyc", ".pyo", ".wlf", ".ucdb", ".vcd", ".log", ".zip", ".o", ".obj", ".dll", ".so",
)
EXCLUDE_NAMES = {"modelsim.ini", "transcript", ".DS_Store", "Thumbs.db", ".coverage"}


def iter_files(root: str) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".egg")]
        for name in filenames:
            if name in EXCLUDE_NAMES:
                continue
            if name.lower().endswith(EXCLUDE_SUFFIX):
                continue
            if name.startswith("~$"):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def build_zip(out: Optional[str] = None, root: str = ".", version: str = "1.0.0") -> str:
    root = os.path.abspath(root)
    top = os.path.basename(root.rstrip(os.sep)) or "AId-UVO-RT"
    if not out:
        out = os.path.join(root, "dist", f"{top}-v{version}-{time.strftime('%Y%m%d')}.zip")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    files = iter_files(root)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            src = os.path.join(root, rel)
            if os.path.abspath(src) == os.path.abspath(out):
                continue
            arc = os.path.join(top, rel).replace(os.sep, "/")
            try:
                zf.write(src, arc)
            except OSError:
                continue
        manifest = (
            f"AId-UVO-RT v{version}\n"
            f"packaged: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"files   : {len(files)}\n"
            "See README.md for installation and the Windows batch workflow.\n"
        )
        zf.writestr(os.path.join(top, "PACKAGE_MANIFEST.txt").replace(os.sep, "/"), manifest)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="package AId-UVO-RT into a ZIP")
    ap.add_argument("--out", "-o", default="")
    ap.add_argument("--root", default=".")
    ap.add_argument("--version", default="1.0.0")
    args = ap.parse_args(argv)
    path = build_zip(args.out or None, args.root, args.version)
    size = os.path.getsize(path) / 1024.0
    print(f"wrote {path} ({size:.1f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
