#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export HF_HOME="$ROOT/.cache/msvbench/huggingface"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-4}"
export DEEPFACE_HOME="$ROOT/.cache/msvbench/deepface"
export MSVBENCH_DREAMSIM_CACHE="$ROOT/.cache/msvbench/dreamsim"
exec "$ROOT/.venvs/msvbench/bin/python" "$ROOT/scripts/run_msvbench.py" "$@"
