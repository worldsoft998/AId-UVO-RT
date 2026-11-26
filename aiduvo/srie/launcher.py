"""Building simulator command lines (QuestaSim on Windows, and elsewhere).

Only the *simulator* is launched.  The design is whatever the user already
compiled; this module never touches compile options of user sources, and it
never writes a file into the user's source tree.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

ENV_HINTS = ("QUESTA_ROOT", "QUESTA_HOME", "MODELSIM_ROOT", "MODEL_TECH")

WINDOWS_EXE_NAMES = ("vsim.exe", "vsim")
UNIX_EXE_NAMES = ("vsim",)


def find_executable(name: str = "vsim", extra_dirs: Sequence[str] = ()) -> Optional[str]:
    """Locate a QuestaSim binary via PATH, environment hints, then known dirs."""
    found = shutil.which(name)
    if found:
        return found
    candidates: List[str] = list(extra_dirs)
    for hint in ENV_HINTS:
        root = os.environ.get(hint)
        if root:
            for sub in ("win64", "win32", "bin", os.path.join("bin", "win64")):
                candidates.append(os.path.join(root, sub))
    names = WINDOWS_EXE_NAMES if os.name == "nt" else UNIX_EXE_NAMES
    for d in candidates:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


@dataclass
class SimLaunch:
    """Everything needed to start one simulation run."""

    exe: str = "vsim"
    lib: str = "work"
    top: str = ""
    do_file: str = ""
    gui: bool = False
    coverage: bool = True
    seed: Optional[int] = None
    plusargs: Dict[str, Any] = field(default_factory=dict)
    extra: List[str] = field(default_factory=list)
    log_file: str = ""
    wlf_file: str = ""
    cwd: str = ""
    env: Dict[str, str] = field(default_factory=dict)

    def argv(self) -> List[str]:
        args: List[str] = [self.exe]
        if not self.gui:
            args.append("-c")
        args += ["-quiet"]
        if self.coverage:
            args.append("-coverage")
        if self.seed is not None:
            args += ["-sv_seed", str(int(self.seed))]
        if self.log_file:
            args += ["-l", self.log_file]
        if self.wlf_file:
            args += ["-wlf", self.wlf_file]
        if self.do_file:
            args += ["-do", f"do {self.do_file}"]
        args += list(self.extra)
        if self.top:
            args.append(f"{self.lib}.{self.top}" if self.lib else self.top)
        for key, value in self.plusargs.items():
            key = str(key).lstrip("+")
            if value is True or value is None or value == "":
                args.append(f"+{key}")
            else:
                args.append(f"+{key}={value}")
        return args

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exe": self.exe, "lib": self.lib, "top": self.top, "do_file": self.do_file,
            "gui": self.gui, "coverage": self.coverage, "seed": self.seed,
            "plusargs": self.plusargs, "extra": self.extra, "cwd": self.cwd,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SimLaunch":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def command_line(self) -> str:
        return " ".join(_quote(a) for a in self.argv())


def _quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg and not arg.startswith('"')) else arg


@dataclass
class CompilePlan:
    """Record of how the design *should* be compiled (executed by the .bat/.sh)."""

    vlib: str = "vlib"
    vlog: str = "vlog"
    vopt: str = "vopt"
    library: str = "work"
    sources: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    defines: Dict[str, str] = field(default_factory=dict)
    coverage: str = "bcestfx"     # statement+branch+condition+expression+toggle+fsm
    sv_seed: int = 0
    extra_vlog: List[str] = field(default_factory=list)
    extra_vopt: List[str] = field(default_factory=list)

    def vlog_argv(self) -> List[str]:
        args = [self.vlog, "-sv", "-work", self.library]
        for d in self.include_dirs:
            args.append(f"+incdir+{d}")
        for k, v in self.defines.items():
            args.append(f"+define+{k}={v}" if v != "" else f"+define+{k}")
        args += self.extra_vlog
        args += self.sources
        return args

    def vopt_argv(self, top: str) -> List[str]:
        args = [self.vopt, "-work", self.library, "-o", f"{top}_opt"]
        if self.coverage:
            args.append(f"+cover={self.coverage}")
        args += self.extra_vopt
        args.append(top)
        return args

    def to_dict(self) -> Dict[str, Any]:
        return {
            "library": self.library, "sources": self.sources, "include_dirs": self.include_dirs,
            "defines": self.defines, "coverage": self.coverage,
        }
