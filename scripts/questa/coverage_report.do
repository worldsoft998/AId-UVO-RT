# ---------------------------------------------------------------------------
# Convert a UCDB into the formats the optimizer can import.
#
#   vsim -c -do "do coverage_report.do <file.ucdb>"
# or
#   vcover report -xml -output coverage.xml file.ucdb
#   vcover report -details -output coverage.txt file.ucdb
# ---------------------------------------------------------------------------
set UCDB [lindex $argv 0]
if {$UCDB eq ""} { set UCDB "coverage_manual.ucdb" }
if {![file exists $UCDB]} {
    echo "coverage_report.do: $UCDB not found"
    quit -f -code 1
}
vcover report -xml     -output [file rootname $UCDB].xml  $UCDB
vcover report -details -output [file rootname $UCDB].txt  $UCDB
echo "coverage_report.do: wrote [file rootname $UCDB].xml and .txt"
quit -f
