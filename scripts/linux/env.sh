#!/usr/bin/env bash
# Shared environment for the Linux workflow (parity with scripts/windows/env.bat).
# Usage:  source scripts/linux/env.sh
export AIDUVO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${AIDUVO_ROOT}:${PYTHONPATH}"
PY="${PYTHON:-python3}"
export PY
if ! "$PY" -c "import numpy" >/dev/null 2>&1; then
  echo "[env] numpy missing: $PY -m pip install -r \"$AIDUVO_ROOT/requirements.txt\""
  export AIDUVO_DEPS_OK=0
else
  export AIDUVO_DEPS_OK=1
fi
if command -v vsim >/dev/null 2>&1; then
  export HAS_VSIM=1
else
  export HAS_VSIM=0
  if [ -n "${QUESTA_ROOT:-}" ] && [ -x "$QUESTA_ROOT/bin/vsim" ]; then
    export PATH="$QUESTA_ROOT/bin:$PATH"; export HAS_VSIM=1
  fi
fi
export AIDUVO_CONFIG="${AIDUVO_ROOT}/config/campaign.json"
mkdir -p "${AIDUVO_ROOT}/config" "${AIDUVO_ROOT}/runs"
echo "[env] root=$AIDUVO_ROOT python=$PY deps=$AIDUVO_DEPS_OK vsim=$HAS_VSIM"
