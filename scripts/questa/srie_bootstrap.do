# ---------------------------------------------------------------------------
# AId-UVO-RT / SRIE bootstrap (handy copy for manual use)
#
# The framework generates an identical file per session (with the TCP port
# baked in) from aiduvo/srie/bootstrap.py, which is the canonical source.
# Load it with:   vsim -c -do "do srie_bootstrap.do" work.<tb_top>
#
# It defines the event helpers and prints a readiness banner.  It does NOT run
# the design: the optimizer decides when and how far to run.
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
