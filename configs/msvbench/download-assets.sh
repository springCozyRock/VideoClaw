#!/usr/bin/env bash
set -euo pipefail
cd /mnt/data/bts/repos/LongVideoMemory/.cache/msvbench/downloads
for name in Dataset ConsistencyEvalModels; do
 curl -fL --retry 3 --connect-timeout 20 -C - "https://hf-mirror.com/datasets/MrSunshy/MSVBench/resolve/main/${name}.zip" -o "${name}.zip"
done
sha256sum Dataset.zip ConsistencyEvalModels.zip
