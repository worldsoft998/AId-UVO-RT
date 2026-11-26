#!/usr/bin/env bash
# Compile the demo design with coverage instrumentation.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AIDUVO_ROOT"
[ "$HAS_VSIM" = "1" ] || { echo "[compile] vsim not found"; exit 1; }
vsim -c -quiet -do "do scripts/questa/compile.do"
echo "[compile] done"
