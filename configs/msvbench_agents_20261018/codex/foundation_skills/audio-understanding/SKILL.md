---
name: audio-understanding
description: 使用 Qwen3.5-Omni 听取音频或视频音轨并回答制作检查问题。
---

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/msvbench_composition/tools.py understand --audio /absolute/audio.wav --prompt "转写实际听到的台词并描述背景声"`。
视频音轨调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/msvbench_composition/tools.py understand --video /absolute/video.mp4 --with-audio --prompt "检查音频"`。
脚本记录实际送入的媒体；输出是辅助检查，不能代替正式 ASR 或自动评测。
