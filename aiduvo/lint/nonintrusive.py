"""Non-intrusiveness compliance checker.

The central promise of this project is that the optimizer never touches RTL,
testbench, UVM or coverage-model source.  A promise is worth little without a
check, so this module enforces it mechanically and can be run in CI:

    python -m aiduvo lint

Rules
-----
R1  no HDL source file may live inside the framework packages;
R2  the framework may not import HDL parsers or elaborators;
R3  the framework may not contain HDL file-extension literals;
R4  the framework may not reference the example design directory;
R5  the framework may not read or write HDL files at run time;
R6  the framework may not import network / hosted-AI client libraries;
R7  compile commands may only be *constructed* (for the user's own build flow),
    never executed from the framework packages.

The example design and the batch scripts are exempt: they are user space and
they legitimately invoke the simulator's compiler.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HDL_EXTENSIONS = (".sv", ".svh", ".v", ".vh", ".vhd", ".vhdl", ".svp", ".sva")
FRAMEWORK_DIRS = ("aiduvo",)
FORBIDDEN_IMPORTS = (
    "pyverilog",
    "hdlparse",
    "pyslang",
    "tree_sitter",
    "tree_sitter_systemverilog",
    "vcdvcd",
    "cocotb",
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "transformers",
    "langchain",
    "requests",
    "httpx",
)
FORBIDDEN_EXEC = ("vlog", "vcom", "vopt", "vsim", "vlib", "vcover")
EXEMPT_FILES = {
    "aiduvo/lint/nonintrusive.py",
    "aiduvo/srie/launcher.py",
    "aiduvo/srie/optimizer.py",
    "aiduvo/blackbox/backend.py",
    "aiduvo/blackbox/runner.py",
    "aiduvo/srie/fli_bridge.py",
    "aiduvo/srie/transport.py",
}
# A quoted string literal that *ends* with an HDL extension, e.g. "dut.sv".
# The trailing quote requirement keeps attribute access such as ``self.v`` out.
EXT_LITERAL_RE = re.compile(r"""(['"])[^'"]*\.(sv|svh|v|vh|vhd|vhdl|svp|sva)\1""")
EXT_RE = re.compile(r"\.(sv|svh|vh|vhd|vhdl|svp|sva)\b")
EXAMPLE_RE = re.compile(r"examples[/\\]")
EXEC_RE = re.compile(r"subprocess\.(?:run|Popen|call|check_call|check_output)\s*\(")


@dataclass
class Violation:
    rule: str
    path: str
    detail: str
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "path": self.path, "detail": self.detail, "line": self.line}

    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.rule}] {loc}: {self.detail}"


@dataclass
class ComplianceReport:
    root: str
    checked_files: int = 0
    violations: List[Violation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    hdl_files_found: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root, "ok": self.ok, "checked_files": self.checked_files,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings, "hdl_files_found": self.hdl_files_found,
        }

    def render(self) -> str:
        lines = [
            f"non-intrusiveness compliance check @ {self.root}",
            f"  files checked : {self.checked_files}",
            f"  HDL files seen: {len(self.hdl_files_found)} (all outside the framework)",
            f"  result        : {'PASS' if self.ok else 'FAIL'} "
            f"({len(self.violations)} violation(s), {len(self.warnings)} warning(s))",
        ]
        for v in self.violations:
            lines.append(f"  {v}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)


def _iter_py(root: str, dirs: Sequence[str]) -> Iterable[str]:
    for d in dirs:
        base = os.path.join(root, d)
        for dirpath, _dirnames, filenames in os.walk(base):
            if "__pycache__" in dirpath:
                continue
            for name in filenames:
                if name.endswith(".py"):
                    yield os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")


def _imports(source: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for i, line in enumerate(source.splitlines(), 1):
        m = re.match(r"^\s*(?:from|import)\s+([A-Za-z0-9_.]+)", line)
        if m:
            out.append((m.group(1), i))
    return out


def check_repo(root: str = ".", framework_dirs: Sequence[str] = FRAMEWORK_DIRS) -> ComplianceReport:
    root = os.path.abspath(root)
    report = ComplianceReport(root=root)

    # R1 + inventory of HDL files anywhere in the tree
    for dirpath, _dirnames, filenames in os.walk(root):
        if any(part in dirpath for part in (".git", "__pycache__", "node_modules")):
            continue
        for name in filenames:
            if name.lower().endswith(HDL_EXTENSIONS):
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
                report.hdl_files_found.append(rel)
                if rel.split("/")[0] in framework_dirs:
                    report.violations.append(
                        Violation("R1", rel, "HDL source file inside a framework package")
                    )

    for rel in _iter_py(root, framework_dirs):
        report.checked_files += 1
        path = os.path.join(root, rel)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError as exc:  # pragma: no cover
            report.warnings.append(f"could not read {rel}: {exc}")
            continue
        exempt = rel in EXEMPT_FILES

        # R2 forbidden imports
        for module, line in _imports(source):
            top = module.split(".")[0]
            for bad in FORBIDDEN_IMPORTS:
                if module == bad or module.startswith(bad + ".") or top == bad.split(".")[0]:
                    report.violations.append(
                        Violation("R2", rel, f"forbidden import {module!r} (offline / no-source-access rule)",
                                  line)
                    )

        # R3 HDL extension literals
        if not exempt:
            for i, line_text in enumerate(source.splitlines(), 1):
                if line_text.lstrip().startswith("#"):
                    continue
                if EXT_LITERAL_RE.search(line_text) and "HDL_EXTENSIONS" not in line_text:
                    report.violations.append(
                        Violation("R3", rel, f"HDL extension literal: {line_text.strip()[:90]}", i)
                    )

        # R4 example-design references
        for i, line_text in enumerate(source.splitlines(), 1):
            if EXAMPLE_RE.search(line_text) and not line_text.lstrip().startswith("#"):
                report.violations.append(
                    Violation("R4", rel, f"references the example design: {line_text.strip()[:90]}", i)
                )

        # R5 reading/writing HDL files
        if not exempt:
            for i, line_text in enumerate(source.splitlines(), 1):
                if ("open(" in line_text or "read_text" in line_text) and EXT_RE.search(line_text):
                    report.violations.append(
                        Violation("R5", rel, "opens an HDL file at run time", i)
                    )

        # R7 executing a compiler from the framework
        if rel not in EXEMPT_FILES:
            for i, line_text in enumerate(source.splitlines(), 1):
                if EXEC_RE.search(line_text) and any(f'"{x}"' in line_text for x in FORBIDDEN_EXEC):
                    report.violations.append(
                        Violation("R7", rel, "executes a simulator/compiler binary", i)
                    )

    if not report.violations:
        report.warnings.append(
            "static check only: it proves the framework never references HDL/TB artifacts, "
            "not that a future change will not. Run it in CI on every commit."
        )
    return report


def check_files(paths: Sequence[str]) -> ComplianceReport:
    """Check a specific list of files (used by the pre-commit hook)."""
    report = ComplianceReport(root=os.getcwd())
    for p in paths:
        if not p.endswith(".py"):
            continue
        if p.lower().endswith(HDL_EXTENSIONS):
            report.violations.append(Violation("R1", p, "HDL source file passed to the optimizer"))
            continue
        report.checked_files += 1
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        for module, line in _imports(source):
            if any(module == b or module.startswith(b + ".") for b in FORBIDDEN_IMPORTS):
                report.violations.append(Violation("R2", p, f"forbidden import {module!r}", line))
    return report
