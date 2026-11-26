# ---------------------------------------------------------------------------
# Compile the design with coverage enabled.
# Edit ONLY the two lists below; this file is user space, not framework code.
#
#   vsim -c -do "do scripts/questa/compile.do"     (run from the repository root)
#
# Coverage switches (simulator-side instrumentation, no source edits):
#   b = branch, c = condition, e = expression, s = statement, t = toggle, f = fsm
# ---------------------------------------------------------------------------
set LIB      work
set TOP      tb_top
set COVERAGE bcestfx
set SOURCES {
    examples/demo_fifo/rtl/fifo.sv
    examples/demo_fifo/tb/fifo_if.sv
    examples/demo_fifo/tb/fifo_tb_pkg.sv
    examples/demo_fifo/tb/fifo_tb_top.sv
}

if {[file exists $LIB]} { vdel -lib $LIB -all }
vlib $LIB
vmap $LIB $LIB
foreach src $SOURCES {
    if {[catch {vlog -sv -work $LIB +incdir+examples/demo_fifo/tb $src} err]} {
        echo "compile failed on $src: $err"
        quit -f -code 1
    }
}
if {[catch {vopt -work $LIB +cover=$COVERAGE -o ${TOP}_opt $TOP} err]} {
    echo "vopt failed: $err"
    quit -f -code 1
}
echo "compile.do: built ${LIB}.${TOP}_opt with coverage=$COVERAGE"
quit -f
