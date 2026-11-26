#!/usr/bin/env bash
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AIDUVO_ROOT"
"$PY" -m aiduvo selftest --outdir "$AIDUVO_ROOT/runs/_selftest"
