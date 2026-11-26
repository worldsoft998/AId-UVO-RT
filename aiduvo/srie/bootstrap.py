"""The Tcl bootstrap that turns a QuestaSim session into an SRIE server.

This file is generated (never hand-edited) into the campaign work directory, so
the port number and any other parameter can be baked in as literals -- no
reliance on do-file argument conventions, no quoting problems on Windows.

It contains simulator commands only.  It does not run the design, does not
reference the design, and is loaded with ``-do`` so that ``vsim`` stops at its
prompt with the design elaborated and the helpers defined.
"""

from __future__ import annotations

import os
from typing import Optional

BOOTSTRAP_TCL = r"""# ---------------------------------------------------------------------------
# AId-UVO-RT / SRIE bootstrap  (generated -- do not edit)
# Defines the event helpers and announces readiness.  It never runs the design.
# ---------------------------------------------------------------------------
proc srie_evt {msg} {
    if {[info exists ::srie_chan] && $::srie_chan ne ""} {
        if {![catch {puts $::srie_chan "@@SRIE_EVT $msg@@"}]} { return }
    }
    puts "@@SRIE_EVT $msg@@"
}
proc srie_note {msg} {
    if {[info exists ::srie_chan] && $::srie_chan ne ""} {
        if {![catch {puts $::srie_chan "@@SRIE_NOTE $msg@@"}]} { return }
    }
    puts "@@SRIE_NOTE $msg@@"
}
proc srie_version_string {} {
    if {[catch {version -short} v]} { set v "unknown" }
    return $v
}
proc srie_handle {chan} {
    if {[gets $chan line] < 0} {
        if {[eof $chan]} { catch {close $chan} }
        return
    }
    set idx [string first "\t" $line]
    if {$idx < 0} {
        set cid 0
        set cmd $line
    } else {
        set cid [string range $line 0 [expr {$idx - 1}]]
        set cmd [string range $line [expr {$idx + 1}] end]
    }
    set cmd [string trim $cmd]
    if {$cmd eq ""} { return }
    if {[catch {uplevel #0 $cmd} out]} {
        catch {puts $chan "@@SRIE_ERR $out@@"}
        catch {puts $chan "@@SRIE_END $cid rc=1@@"}
    } else {
        if {[string length $out]} { catch {puts $chan $out} }
        catch {puts $chan "@@SRIE_END $cid rc=0@@"}
    }
}
proc srie_accept {chan addr port} {
    fconfigure $chan -buffering line -blocking 0 -translation auto
    set ::srie_chan $chan
    puts $chan "@@SRIE_READY [srie_version_string]@@"
    fileevent $chan readable [list srie_handle $chan]
}
set ::srie_chan ""
puts "@@SRIE_READY [srie_version_string]@@"
"""

SERVER_SNIPPET = r"""
if {[catch {socket -server srie_accept %PORT%} __srie_srv]} {
    puts "@@SRIE_FATAL cannot open Tcl server on port %PORT%: $__srie_srv@@"
} else {
    srie_note "listening on port %PORT%"
}
"""


def bootstrap_text(port: Optional[int] = None, note: str = "") -> str:
    text = BOOTSTRAP_TCL
    if note:
        text = text.replace(
            "puts \"@@SRIE_READY [srie_version_string]@@\"",
            f'srie_note "{note}"\nputs "@@SRIE_READY [srie_version_string]@@"',
            1,
        )
    if port:
        text += SERVER_SNIPPET.replace("%PORT%", str(int(port)))
    return text


def bootstrap_do_file(workdir: str, port: Optional[int] = None, note: str = "") -> str:
    """Write the bootstrap into ``workdir`` and return its path."""
    os.makedirs(workdir, exist_ok=True)
    name = f"srie_bootstrap{'_' + str(port) if port else ''}.do"
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(bootstrap_text(port=port, note=note))
    return path
