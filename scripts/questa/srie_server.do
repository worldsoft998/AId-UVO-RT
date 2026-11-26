# ---------------------------------------------------------------------------
# Start an SRIE Tcl server inside a running simulation, for interactive use.
#
#   vsim -c -do "do srie_server.do 7654" work.tb_top_opt
#
# Then, from another shell:
#   python -m aiduvo srie probe --config config/campaign.json
# with  "transport": {"kind": "socket", "port": 7654}
# ---------------------------------------------------------------------------
set PORT [lindex $argv 0]
if {$PORT eq ""} { set PORT 7654 }
source [file join [file dirname [info script]] srie_bootstrap.do]
if {[catch {socket -server srie_accept $PORT} srv]} {
    echo "srie_server.do: cannot listen on $PORT: $srv"
    quit -f -code 1
}
srie_note "SRIE server listening on port $PORT"
vsim on
