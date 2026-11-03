#!/usr/bin/env bash
set -euo pipefail
cd /mnt/data/bts/repos/LongVideoMemory
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
.venvs/msvbench_face/bin/python -m pip install .cache/msvbench/wheels/tensorflow-2.15.1-cp311-*.whl numpy==1.26.4 keras==2.15.0 deepface==0.0.93 retina-face==0.0.17 mtcnn==1.0.0 opencv-python-headless==4.11.0.86 opencv-python==4.11.0.86 pandas==2.2.3 gdown
