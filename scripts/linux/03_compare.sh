#!/usr/bin/env bash
# Compare the newest baseline / blackbox / runtime campaigns.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$AIDUVO_ROOT"
TARGET="${TARGET:-0.9}"
ARGS=()
for kind in baseline blackbox runtime; do
  dir=$(ls -1dt runs/${kind}_* 2>/dev/null | head -1 || true)
  if [ -n "${dir:-}" ]; then ARGS+=(--campaign "${kind}=${dir}"); fi
done
if [ ${#ARGS[@]} -eq 0 ]; then
  echo "no campaigns found under runs/; run 02_run_optimizer.sh first"
  exit 1
fi
OUT="results/comparison_$(date +%Y%m%d_%H%M%S)"
"$PY" -m aiduvo compare "${ARGS[@]}" --outdir "$OUT" --baseline baseline --target "$TARGET"
echo "report: $OUT/report.md"
