"""Blackbox optimizer: post-run logs, databases and scripts only.

In this mode the optimizer has no access to the simulator's internals and cannot
reference the design: it chooses seeds, plusargs, run length and tests, launches
simulations as child processes, watches transcripts while they are written, and
imports coverage databases afterwards.  It is still capable of real-time
optimisation -- it can cut a run short the moment it stops being useful -- but
every decision is based on artifacts any engineer could read.
"""

from aiduvo.blackbox.backend import BlackboxBackend, MockBlackboxBackend
from aiduvo.blackbox.knobs import Knob, KnobProfile, KnobSpace, SeedStrategy
from aiduvo.blackbox.logwatch import LogEvent, TranscriptSummary, TranscriptWatcher
from aiduvo.blackbox.runner import RunArtifacts, SimRunner, write_run_do

__all__ = [
    "BlackboxBackend",
    "MockBlackboxBackend",
    "Knob",
    "KnobProfile",
    "KnobSpace",
    "SeedStrategy",
    "LogEvent",
    "TranscriptSummary",
    "TranscriptWatcher",
    "RunArtifacts",
    "SimRunner",
    "write_run_do",
]
