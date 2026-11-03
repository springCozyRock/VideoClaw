#!/usr/bin/env bash
set -u
cd /mnt/data/bts/repos/LongVideoMemory
for metric in dover musiq style_consistency; do
 bash scripts/msvbench.sh --method deployment_smoke --story 01 --metric "$metric" --videos experiments/msvbench_smoke/videos --output-root experiments/msvbench_smoke/verify-local-v1
 done
