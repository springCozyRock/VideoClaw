---
name: extract-video-frame
description: 从视频指定时间提取参考帧或检查帧。
---

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/msvbench_composition/tools.py extract --input /absolute/video.mp4 --seconds 4.5 --output frames/frame.jpg`。
输出是当前任务目录中的 JPEG，可继续用于视频参考或视觉检查。
