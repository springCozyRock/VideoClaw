#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4
exec "$ROOT/.venvs/directorbench_public/bin/python" "$ROOT/scripts/mobileviclip_smoke.py" "$@"
