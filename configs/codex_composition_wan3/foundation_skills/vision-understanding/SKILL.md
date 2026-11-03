---
name: vision-understanding
description: 使用 Qwen3.5-Omni 检查图片或抽样视频内容。
---

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/composition/tools.py understand --image /absolute/image.jpg --prompt "要检查的问题"`。
视频调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/composition/tools.py understand --video /absolute/video.mp4 --prompt "检查人物场景和剧情"`，需要音画一起检查时加 --with-audio。
模型固定 qwen3.5-omni-plus。视频最多抽16帧，音频检查最多前120秒；这是一项制作辅助检查，不是论文正式评测协议。
保存请求哈希、实际输入及原始回复；同样检查复用结果。用观察描述记录问题，不把抽样理解当成逐帧检测。
