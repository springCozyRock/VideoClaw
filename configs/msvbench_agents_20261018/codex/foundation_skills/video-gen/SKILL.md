---
name: video-gen
description: 使用 wan3.0-video 生成带音频的视频片段，可用本地参考图。
---

# 万相视频生成

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/msvbench_composition/tools.py video --prompt "镜头提示词" --duration 10 --output clips/shot_01.mp4 --seed 20261016`。

模型固定 wan3.0-video，720P、16:9、带音频，关闭服务端提示词扩写；单段整数 2–30 秒。
每个镜头的 seed 记录在计划中；相同 seed 仍不能保证云模型逐像素一致。
使用 `--reference-image /absolute/path.jpg` 添加参考图，可重复使用，顺序对应提示词中的图1、图2等。
最多10张图片；图片格式 JPEG/PNG/BMP/WEBP、单张≤20MB、边长240–8000像素，不能含透明通道。
参考图可以约束身份/风格，但不保证严格锁定首尾帧。当前适配器只暴露已验证的文本与图片参考模式。
视频、音频参考属于万相模型能力，但本适配版本尚未开放它们；不要将它们写入工作流。

输出是相对于 get-output-dir 返回目录的路径。脚本保存请求、参考图哈希、task_id、响应和校验信息。
默认轮询直至下载并验证完成；需要异步时加 `--background`，之后重复同一命令并去掉该参数继续。
相同任务名、提示词、参数和参考内容会复用任务和结果。SUBMISSION_UNKNOWN 或已失败的任务会停止，不重复收费提交。
每个镜头完成后可用 extract-video-frame 取出合适参考，是否采用由当前工作流与创作要求决定。
