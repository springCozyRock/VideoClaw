---
name: image-gen
description: 使用百炼 Qwen-Image 生成或编辑角色、场景及分镜参考图。
---

# 参考图生成

调用 `/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python /mnt/data/bts/repos/LongVideoMemory/baselines/codex/msvbench_composition/tools.py image --prompt "参考图描述" --output references/character.png --size '1328*1328' --seed 20261016`。
模型固定在实验配置的 image_model。输入编辑参考时重复 `--reference-image /absolute/path.png`。
脚本读取服务器项目凭据，保存原始响应与用量，并按请求内容复用已成功的图片。
输出路径相对于当前任务目录。按任务需要生成参考图，不必给每个镜头重复生成。
