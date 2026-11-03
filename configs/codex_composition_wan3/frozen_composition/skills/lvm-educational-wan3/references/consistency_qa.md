# 一致性资产、plan.json、QA 检查表与失败处理

## 目录

1. plan.json 结构
2. 一致性资产清单规范
3. 逐段自检问题集
4. 成片检查表
5. 失败与重试策略
6. 留档要求

## 1. plan.json 结构

保存到 `get-output-dir` 返回的任务目录根下，随制作过程持续回写实际结果：

```json
{
  "task": {"topic": "...", "audience": "...", "target_duration_s": 90,
            "av_constraints": {"language": "zh", "narration": "...", "bgm": "...", "aspect": "16:9"}},
  "user_references": [{"id": "ref_img_1", "path": "/abs/or/task-relative", "type": "image",
                        "understanding": "vision-understanding 结论摘要", "used_as": "角色外观依据"}],
  "assets": [
    {"id": "char_host", "kind": "character_image", "path": "references/host_turnaround.png", "used_by": ["seg_01","seg_03"]},
    {"id": "scene_lab", "kind": "scene_image", "path": "references/lab.png", "used_by": ["seg_02"]},
    {"id": "anchor_style", "kind": "style_text", "text": "全片风格锚点原文"},
    {"id": "anchor_voice", "kind": "voice_text", "text": "声音锚点原文（旁白音色+BGM）"},
    {"id": "char_host_voice", "kind": "voice_text", "text": "角色对白声音描述原文"}
  ],
  "segments": [
    {"id": "seg_01", "order": 1, "duration_s": 12, "shots": 1,
     "narration": "本段台词原文", "visual_brief": "画面要点",
     "asset_ids": ["char_host", "scene_lab", "anchor_style", "anchor_voice"],
     "reference_images": ["references/host_turnaround.png", "references/lab.png"],
     "seed": 20261016, "task_name": "seg01_v1",
     "output": "clips/shot_01.mp4",
     "checks": {"metadata": "PASS 12s 720P 有音轨", "vision": "PASS 角色一致", "audio": "PASS 台词完整"},
     "attempts": [{"task_name": "seg01_v1", "seed": 20261016, "result": "台词被截断", "action": "缩短台词并+seed 重试"}]}
  ],
  "final": {"path": "final.mp4", "duration_s": 90, "merge_inputs": ["..."], "qa": "见 qa_report.md"}
}
```

要点：segments 时长之和 ≥ target_duration_s；每段的 seed、task_name、尝试历史必须留档。

## 2. 一致性资产清单规范

- 每个反复出现的角色/场景/物体有且只有一个"权威资产"（设定图或文本锚点），全片各段引用同一份文件路径或同一段逐字文本。
- 角色设定图：单张图内多视图（正面/侧面/背面），纯色背景，无透明通道，边长 240–8000、≤20MB；生成后用 `vision-understanding` 确认视图完整、外观无歧义再入库。
- 用户提供图片：先用 `get-image-metadata` 验证格式/尺寸/透明通道；含 alpha 或边长不合规时先转换（合到纯色底、缩放）再作为参考图；原件与转换件都登记，注明 used_as。
- 用户提供的音频/视频：不作为生成参考。音频 → `audio-understanding` 转写与音色描述 → 写入声音锚点文本资产；视频 → `vision-understanding` 内容描述 + `extract-video-frame` 关键帧 → 帧图经验证后可作图像参考。登记原始文件路径与转化产物，保持可追溯。
- 文本资产（风格锚点、声音锚点、角色声音、术语表）以"原文"字段存入 plan.json，禁止各段改写同义句；术语表列出全片必须逐字一致的专有名词。

## 3. 逐段自检问题集

每段生成后立即执行三项检查并把结论写回 plan.json：

1. `get-video-metadata`：时长是否等于计划整数秒？720P/16:9？有音轨？
2. `vision-understanding`（--video，必要时 --with-audio）提问模板：
   - 画面中角色外观是否与设定图一致（五官/发型/着装/配色）？
   - 场景布局与光线是否与场景参考图一致？
   - 画面动作是否完成了提示词要求的讲解内容？图表/文字元素是否可读、无乱码？
   - 有无肢体畸变、穿模、物体漂浮等物理异常？
3. `audio-understanding`（--video --with-audio）提问模板：
   - 转写实际听到的台词，与计划旁白是否一致、完整、无截断？
   - 旁白音色是否符合声音锚点描述？BGM 风格与音量关系是否正确？

## 4. 成片检查表（写入 qa_report.md）

合成 final.mp4 后逐项记录 PASS/FAIL 与证据（帧图/网格图/转写文本路径）：

- [ ] 总时长符合目标（merge 校验通过，无拉伸/循环/补黑）
- [ ] 章节顺序与 plan.json 叙事结构一致，逻辑连贯无跳步
- [ ] grid-generate 网格总览：全片角色外观一致、场景配色统一、风格无漂移
- [ ] 反复出现的物体/图表在各段中形态一致
- [ ] 旁白覆盖全部计划知识点，术语与术语表逐字一致
- [ ] 全片旁白音色一致（长片按 ≤120 秒窗口分段抽查 audio-understanding）
- [ ] BGM 风格全片延续、音量始终低于人声
- [ ] 口播段台词与口型无明显错位
- [ ] 720P、16:9、30FPS、音轨完整（get-video-metadata）

任一 FAIL：定位到具体片段，回到第 4 步重生成该段（新 task_name），重新 merge 并复检相关项。

## 5. 失败与重试策略

- 生成结果复用规则：相同任务名+提示词+参数+参考内容会命中历史任务。因此**重试必须至少改变一项**（推荐：新 task_name + 修改提示词或换 seed），否则会拿回同一个失败/劣质结果。
- 画面不一致 → 优先加强参考图引用（把对应设定图排到图1并在提示词中显式约束），其次才是改 seed。
- 台词截断/语速异常 → 缩减该段台词字数或把该段拆成两段（各自 2–30 秒整数），更新 plan.json。
- 音色/BGM 漂移 → 核对声音锚点是否逐字复用；漂移严重的段重生成，禁止指望后期修复（无音频替换能力）。
- `video-gen` 返回 SUBMISSION_UNKNOWN 或任务已失败停止时：**不要重复提交同一请求**，保留现场（命令、task_id、响应记录），更换 task_name 与至少一项参数后再试；若再次未知，停止该段制作并向用户报告状态。
- 单段连续 3 次重试仍不合格：降级处理（简化该段画面动作/改为图表特写+画外音），并在 qa_report.md 中记录降级原因。
- `merge-video` 拒绝合成（片段时长不足）：回到规划补生成内容，不得用重复片段或黑场凑数。

## 6. 留档要求

任务目录中最终应包含：

- `final.mp4`
- `plan.json`（含 attempts 历史与实际输出路径）
- `qa_report.md` 及检查证据（网格图、抽帧、转写记录）
- `references/`（设定图与场景图等图像资产）、`clips/`（各段成片）——以工具实际落盘路径为准，不手动搬动
- `video-gen`/`image-gen`/理解类工具自动保存的请求、响应、哈希与校验记录（留在工具默认位置即可）
