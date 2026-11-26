"""AId-UVO-RT -- AI-Driven Universal Verification Optimization (Runtime/Instantaneous).

A project-agnostic, coverage-driven verification acceleration framework.

The package is organised in layers, each of which is independently usable:

    aiduvo.core        abstract action/observation/reward/engine abstractions
    aiduvo.coverage    project-agnostic coverage model (UCIS XML, text, CSV)
    aiduvo.rl          local, numpy-only RL / ANN learners (no external APIs)
    aiduvo.srie        Simulator Runtime Introspection Engine (live, in-sim)
    aiduvo.blackbox    post-run / log-and-database driven optimizer
    aiduvo.discovery   hierarchical discovery -> abstract spaces (no source access)
    aiduvo.reporting   comparison reports, charts, HTML
    aiduvo.lint        non-intrusiveness compliance checker

Nothing in this package reads, parses or rewrites RTL / testbench / verification
methodology source.  Every project-specific fact is obtained at run time from the
simulator (Tcl/VPI/FLI/UCIS) or from files the simulator itself produced.
"""

from aiduvo.version import __version__, BUILD_NAME

__all__ = ["__version__", "BUILD_NAME"]
