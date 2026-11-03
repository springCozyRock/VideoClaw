#!/usr/bin/env bash
set -euo pipefail
cd /mnt/data/bts/repos/LongVideoMemory
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
.venvs/msvbench/bin/python -m pip install --no-build-isolation -c configs/msvbench/shared-torch-constraints.txt numpy==1.26.4 transformers==4.49.0 timm==1.0.13 decord==0.6.0 google-genai==1.5.0 dreamsim==0.2.1 open_clip_torch==2.32.0 sentence-transformers==5.0.0 liger-kernel==0.5.4 omegaconf==2.3.0 einops==0.8.1 natsort==8.4.0 addict==2.4.0 scikit-video==1.1.11 openai-clip==1.0.1 accelerate==1.7.0 lmdb facexlib gdown icecream ftfy sentencepiece
.venvs/msvbench/bin/python -m pip install --no-deps pyiqa==0.1.13 t2v-metrics==1.2
