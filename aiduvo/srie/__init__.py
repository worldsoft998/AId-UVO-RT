"""Simulator Runtime Introspection Engine (SRIE).

SRIE treats the simulator as a dynamic white box *at run time*: it reads the live
hierarchy, signal values, event activity and coverage, and it writes back
stimulus through the simulator's own control commands (``force``/``release``/
``when``/``run``).  It never reads, generates or edits HDL, testbench or UVM
source, and it never recompiles the design.

Layers
------
``protocol``      wire framing and error types
``transport``     pipe / Tcl-socket / FLI / mock channels
``tcl``           command builders and tolerant output parsers
``introspection`` hierarchy, values, coverage (read-only)
``reflection``    forces, triggers, run control (write, with safety rails)
``triggers``      asynchronous event plumbing
``session``       one live simulator, wired together
``launcher``      simulator command lines
``mock``          synthetic simulator for self-tests and demos
"""

from aiduvo.srie.introspection import Hierarchy, Introspector
from aiduvo.srie.launcher import CompilePlan, SimLaunch, find_executable
from aiduvo.srie.protocol import (
    CapabilityError,
    CommandError,
    CommandResult,
    Event,
    SRIEError,
    TransportError,
)
from aiduvo.srie.reflection import BIAS_MODES, ReflectionController
from aiduvo.srie.session import SRIEConfig, SRIESession
from aiduvo.srie.transport import (
    MockTransport,
    QuestaPipeTransport,
    QuestaTclSocketTransport,
    Transport,
    make_transport,
)
from aiduvo.srie.triggers import EventBus, trigger_body

__all__ = [
    "Hierarchy",
    "Introspector",
    "CompilePlan",
    "SimLaunch",
    "find_executable",
    "SRIEError",
    "TransportError",
    "CommandError",
    "CapabilityError",
    "CommandResult",
    "Event",
    "ReflectionController",
    "BIAS_MODES",
    "SRIEConfig",
    "SRIESession",
    "Transport",
    "MockTransport",
    "QuestaPipeTransport",
    "QuestaTclSocketTransport",
    "make_transport",
    "EventBus",
    "trigger_body",
]
