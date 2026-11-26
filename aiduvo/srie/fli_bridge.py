"""Optional FLI (Foreign Language Interface) transport.

QuestaSim's FLI gives a C shared library loaded with ``vsim -foreign`` direct
access to the simulator's internal object database: hierarchy walk, signal
read/write, and value-change callbacks with no polling at all.  That is the
lowest-latency non-intrusive path available, and it is the only one that can
deliver *every* transition of a signal.

Architecture
------------
The C shim (``scripts/questa/fli/srie_fli.c``) is compiled once against the
Questa headers and loaded into the simulator.  It opens a TCP listener and
speaks the *same line protocol* as the Tcl transport, so this class is a thin
socket client and everything above it is unchanged.

The shim is optional: the Tcl transports cover the same capabilities (slower,
polling-based).  Use FLI when you need per-transition events or sub-millisecond
steering latency.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from aiduvo.srie.launcher import SimLaunch, find_executable
from aiduvo.srie.protocol import TransportError
from aiduvo.srie.transport import QuestaTclSocketTransport


class FLITransport(QuestaTclSocketTransport):
    """Socket client for the FLI shim (same protocol, different server)."""

    name = "questa-fli"

    def __init__(self, host: str = "127.0.0.1", port: int = 0, library: str = "",
                 design: str = "", **kwargs: Any):
        super().__init__(host=host, port=port, **kwargs)
        self.library = library
        self.design = design

    def info(self) -> Dict[str, Any]:
        d = super().info()
        d["fli_library"] = self.library
        return d


def build_fli_launch(
    shim_path: str,
    port: int,
    lib: str,
    top: str,
    do_file: str = "",
    seed: Optional[int] = None,
    plusargs: Optional[Dict[str, Any]] = None,
) -> SimLaunch:
    """Command line that loads the FLI shim into ``vsim``."""
    extra: List[str] = ["-foreign", f'"srie_fli_init {shim_path} {port}"']
    return SimLaunch(
        exe=find_executable("vsim") or "vsim",
        lib=lib,
        top=top,
        do_file=do_file,
        seed=seed,
        plusargs=plusargs or {},
        extra=extra,
    )


def shim_available(path: str) -> bool:
    return bool(path) and os.path.isfile(path)
