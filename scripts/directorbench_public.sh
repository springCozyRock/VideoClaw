#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$ROOT/.venvs/directorbench_public/bin/python" "$ROOT/scripts/directorbench_public.py" "$@"
