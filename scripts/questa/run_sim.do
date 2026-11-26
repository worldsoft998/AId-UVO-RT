# ---------------------------------------------------------------------------
# Plain (no-AI) simulation run - the manual reference point.
#
#   vsim -c -do "do run_sim.do" -sv_seed 1 work.tb_top_opt
#
# Saves a UCDB so the optimizer and the report tooling can read the result.
# ---------------------------------------------------------------------------
set RUN_TIME 1000us
set UCDB     coverage_manual.ucdb
onfinish {
    coverage save $UCDB
    quit -f
}
run $RUN_TIME
coverage save $UCDB
quit -f
