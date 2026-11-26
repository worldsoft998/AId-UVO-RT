"""Small logging helper: console + optional log file, with timestamps."""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, Optional, TextIO


class Tee:
    def __init__(self, *streams: TextIO):
        self.streams = streams

    def write(self, data: str) -> None:
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except (OSError, ValueError):
                pass

    def flush(self) -> None:
        for s in self.streams:
            try:
                s.flush()
            except (OSError, ValueError):
                pass


def make_logger(logfile: Optional[str] = None, quiet: bool = False,
                prefix: bool = True) -> Callable[[str], None]:
    """Return ``log(message)`` writing to stdout and, optionally, a file."""
    fh: Optional[TextIO] = None
    if logfile:
        os.makedirs(os.path.dirname(os.path.abspath(logfile)) or ".", exist_ok=True)
        fh = open(logfile, "a", encoding="utf-8")

    def log(message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {message}" if prefix else message
        if not quiet:
            print(line, flush=True)
        if fh is not None:
            fh.write(line + "\n")
            fh.flush()

    return log


def banner(text: str, char: str = "=") -> str:
    line = char * max(20, len(text) + 4)
    return f"{line}\n  {text}\n{line}"


def human_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def human_count(value: float) -> str:
    for unit, scale in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(value) >= scale:
            return f"{value / scale:.2f}{unit}"
    return f"{value:.0f}"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)
