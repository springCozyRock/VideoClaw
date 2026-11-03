#!/usr/bin/env bash
set -euo pipefail
cd /mnt/data/bts/repos/LongVideoMemory
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
.venvs/msvbench/bin/python -m pip install -c configs/msvbench/shared-torch-constraints.txt peft==0.15.2 segment-anything==1.0 supervision==0.25.1 hydra-core==1.3.2 mmengine==0.10.7 easydict ftfy prettytable
.venvs/msvbench/bin/python -m pip install --no-deps deepface==0.0.93 retina-face==0.0.17 mtcnn==1.0.0 fire==0.7.0 Flask==3.1.1 gunicorn==23.0.0
