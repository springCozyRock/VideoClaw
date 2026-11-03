#!/usr/bin/env bash
set -u
cd /mnt/data/bts/repos/LongVideoMemory
for metric in detection_count shot_perspective_alignment state_shift_persistence clothes_color_consistency relative_size_consistency physical_interaction_accuracy; do
 bash scripts/msvbench.sh --method public_reference_smoke --story 01 --metric "$metric" --videos experiments/msvbench_smoke/public_pair/videos --prompt experiments/msvbench_smoke/public_pair/prompt.txt --script experiments/msvbench_smoke/public_pair/script.json --output-root experiments/msvbench_smoke/verify-qwen-v2
done
