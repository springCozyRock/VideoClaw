#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/.venvs/msvbench-official-overlay${PYTHONPATH:+:$PYTHONPATH}"
export MSVBENCH_KALM_ATTN=flash_attention_2
exec bash "$ROOT/scripts/msvbench.sh" "$@"
