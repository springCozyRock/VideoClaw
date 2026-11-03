---
name: merge-video
description: 用 FFmpeg 将实际生成的视频片段合成完整长视频并检查时长和音轨。
---

# 长视频合成

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/composition/tools.py merge --input /absolute/clip1.mp4 --input /absolute/clip2.mp4 --output final.mp4 --duration 60`。
重复 --input 决定拼接顺序。输入必须是真实生成、含音轨的片段。输出统一720P、16:9、30FPS。
--duration 可裁剪多余尾部；脚本拒绝用不足的源片段凑时长。禁止拉伸、循环、冻结画面或补黑来冒充要求时长。
会完整解码验证、保存片段顺序与哈希清单。音轨存在不等于语义音画质量已通过，仍需按需求检查。
