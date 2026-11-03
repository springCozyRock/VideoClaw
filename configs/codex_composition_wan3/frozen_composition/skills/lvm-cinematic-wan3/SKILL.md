---
name: lvm-cinematic-wan3
description: 电影镜头语言（cinematography）展示类长视频的可复用制作工作流。当任务输入为文字需求、目标总时长与音画约束（可附带图片/音频/视频/文本等用户参考资料），需要自主规划分镜与视觉参考、用 wan3.0-video 逐段生成带音频的视频片段、保持人物/场景/物体/音色/背景音乐全片一致、合成交付 final.mp4 并检查最终产物时使用。触发场景：电影镜头语言展示视频、运镜/构图/光影 showcase、cinematic long video、分镜规划+长视频生成+成片检查。
---

# lvm-cinematic-wan3：电影镜头语言长视频制作工作流

按本工作流把「文字需求 + 总时长 + 音画约束（+可选用户参考资料）」制作为一部剧情连贯、
视觉与音频一致的镜头语言展示长视频 `final.mp4`。全流程在当前会话内串行执行，
规划与全部中间产物落盘，供检查与复用。

## 硬性约束（先读，任何阶段不得违反）

1. 视频模型固定 `wan3.0-video`（video-gen 技能）：720P、16:9、自带音频生成、服务端提示词扩写已关闭——提示词必须自足、具体，写全镜头语言与音频要求。
2. 单段时长为整数 2–30 秒；长视频只能由多段真实生成的片段用 merge-video 拼接，`--duration` 只裁剪多余尾部；禁止拉伸、循环、冻结画面、补黑帧冒充时长。
3. 适配器只暴露文本 + 参考图输入：`--reference-image` 可重复（≤10 张，JPEG/PNG/BMP/WEBP，单张≤20MB，边长 240–8000 像素，不能含透明通道）。视频参考、音频参考未开放，不要写入任何调用。
4. 音频一致性只能靠「逐字复用的音频描述文本块 + 生成后 audio-understanding 检查 + 必要时重生成」达成，不能靠音频参考输入。
5. 所有产物保存前必须先调用 get-output-dir 获取本任务输出目录（Codex 环境自动识别，无需传参）；不要手动另建目录树，plan.json、assets.json、qa_report.md 等文本产物写入该目录。
6. 生成类调用是付费提交：出现 SUBMISSION_UNKNOWN 或结果不明时，立即停止该任务线并保留现场（记录命令、task 状态、已有产物），不得重复提交；相同任务名+提示词+参数+参考内容会复用已成功结果，恢复时原样重发同一命令（去掉 `--background`）。
7. 不使用 sessions_spawn、子代理、并行 agent；单段生成等待用足够长的 `--timeout`，或 `--background` 提交后按第 6 条恢复轮询。
8. 不读取 dataset、历史实验样例或凭据文件；剧情、分镜、参考资产全部由本次输入与自主规划产生。

## 工作流总览

Phase 0 初始化 → Phase 1 输入解析与参考资料处理 → Phase 2 分镜规划(plan.json) →
Phase 3 一致性资产制备 → Phase 4 逐段生成 → Phase 5 段级检查 →
Phase 6 合成 final.mp4 → Phase 7 全片检查与交付。
Phase 4/5 按计划顺序循环；发现问题回到对应 Phase 修正并更新 plan.json。

## Phase 0 初始化

1. 调用 get-output-dir 得到输出目录 `OUT`，后续所有路径基于它。
2. 通读用户输入，登记三项基本约束：文字需求、目标总时长 D_total（秒）、音画约束（画幅/风格/是否有人物台词/BGM 要求等）。缺项按合理默认补齐并在 plan.json 的 `assumptions` 中显式记录，不得凭空更改用户明确给出的值。
3. 可选：用 task-tracker 把本工作流初始化为任务树，随进度更新状态。

## Phase 1 输入解析与参考资料处理

对每一份用户参考资料先「理解」再「转化」，转化结果登记进 assets.json（schema 见
references/planning_and_assets.md）：

- 图片：get-image-metadata 校验格式/尺寸/是否透明通道；vision-understanding 描述内容（人物外貌、场景、风格），判断可直接用作参考图还是需 image-gen 改绘（如去透明底、生成多视角）。
- 音频：audio-understanding 转写台词、描述音色（性别/年龄感/音质/语速）与 BGM 风格，把结论写进全局音频文本块；音频文件本身不能作为生成输入。
- 视频：get-video-metadata 读取时长/分辨率；extract-video-frame 抽取代表性帧，再用 vision-understanding 描述；可用的帧转化为参考图（需满足硬性约束 3 的图片规格）。
- 文本：整理、扩写、消歧，作为剧情与风格约束的权威来源。

文字需求不足以支撑 D_total 的剧情时，自主补全剧情细节、旁白与台词
（镜头语言展示类视频可以让运镜本身承担叙事主体），补全内容全部写入 plan.json。

## Phase 2 分镜规划

先读 references/cinematic_shot_language.md（镜头语言词汇与提示词写法）和
references/planning_and_assets.md（plan.json / assets.json schema 与一致性资产策略），再规划：

1. 把剧情切分为逻辑连贯的段（segment），每段 2–30 秒（整数），段时长合计 ≥ D_total（merge 时裁掉多余尾部）；镜头节奏服从音画约束与叙事需要。
2. 每段确定：剧情要点、单镜头("Single shot")或多镜头("Shot cut")、景别/运镜/光影设计、场景、出场主体、完整提示词（含逐字复用的全局风格块与音频块）、参考图列表及顺序、seed、生成顺序。
3. 同一人物/场景/物体跨段复现时，必须挂接同一份一致性资产（同一路径的参考图 + 同一段资产描述文本）。
4. 写 plan.json 与 assets.json 到 OUT，并从中提取全部待制备一致性资产清单。

## Phase 3 一致性资产制备

按 assets.json 清单制备，先资产后片段：

1. 角色参考图：用 image-gen 生成（如白底三视图/多角度定妆图）；用户提供的人物图优先直接用或经 image-gen 编辑规范化。生成后用 vision-understanding 核对与设定描述一致，再登记路径与 seed。
2. 场景/物体参考图：同上，每个反复出现的场景与关键物体一张主参考图。
3. 全局风格文本块：一段固定的画面风格描述（影调、色彩、质感、时代/题材），逐字进入每个片段提示词。
4. 全局音频文本块：固定的 BGM 风格描述 + 每个说话角色的音色描述（来自用户音频资料或自主设定），逐字进入每个片段提示词；台词逐段单独写。
5. 所有参考图必须满足硬性约束 3 的规格；不合规的先转换（image-gen 改绘或 extract-video-frame 重取）。

## Phase 4 逐段生成

按 plan.json 的生成顺序逐段调用 video-gen（命令、参考图用法、续接策略见
references/planning_and_assets.md 第 4 节）：

1. 提示词 = 本段镜头语言与剧情 + 全局风格块 + 全局音频块（+本段台词），一次写全；参考图按「图1、图2…」顺序与提示词中的指称严格对应。
2. 记录 seed；长等待用足够大的 `--timeout` 或 `--background` 提交后按硬性约束 6 恢复。
3. 每段成功后把实际输出路径、实际时长写回 plan.json，并用 extract-video-frame 取尾帧/关键帧，供下一段续接与后续检查使用。
4. 连续单镜头长段（一镜到底）：下一段必须同时传上一段尾帧参考图 + 该镜头涉及的角色/场景主参考图，并在提示词中说明接续关系；只传尾帧不足以保持一致。

## Phase 5 段级检查

每段生成后立即检查（工具、限制与清单见 references/qa_and_delivery.md）：

1. vision-understanding 检查画面：主体/场景与参考一致、镜头语言按提示词执行、无明显畸变穿帮。
2. audio-understanding 检查音轨：台词内容与语种、音色是否符合音频块、BGM 风格是否一致。
3. 不合格 → 按再生成策略处理（改提示词/换 seed/换参考帧，最多重试次数见 qa 参考）；每次重生成都登记进 plan.json。SUBMISSION_UNKNOWN → 停止并保留现场。

## Phase 6 合成

全部段通过后，用 merge-video 按 plan.json 顺序重复 `--input`（绝对路径）拼接，
`--output final.mp4 --duration D_total`。检查返回的时长与音轨信息；合成失败先排查片段
规格（720P/16:9/含音轨），不得用降质手段凑数。

## Phase 7 全片检查与交付

按 references/qa_and_delivery.md 的成片清单执行：

1. get-video-metadata 验证 final.mp4 时长=D_total、720P、16:9、30FPS、含音轨。
2. grid-generate 生成 by-time 全片概览图与 by-shot 镜头网格；vision-understanding 结合网格图分段检查剧情连贯与跨段一致性（视频单次最多抽 16 帧，长片按时间范围分次检查）。
3. audio-understanding 分段复核音色与 BGM 全片一致（单次音频检查限前 120 秒）。
4. 把逐项结论与遗留问题写入 OUT/qa_report.md，更新 plan.json 的最终状态。
5. 交付：OUT 下的 final.mp4 + plan.json + assets.json + qa_report.md + 全部中间产物（参考图、片段、帧、网格图），不删除中间产物。

## 常见错误（显式避免）

- 把用户音频/视频文件直接塞给 video-gen（适配器不支持，只能转化为文本描述与参考帧）。
- 只靠上一段尾帧续接而丢掉角色/场景主参考图，导致跨段换脸换景。
- 每段提示词各自改写风格与音色描述，导致画风/音色漂移；必须逐字复用文本块。
- 手动新建输出目录或把产物写到 OUT 之外；一切以 get-output-dir 结果为准。
- 生成失败或结果不明时盲目重试付费提交。
- 片段时长合计不足 D_total 却试图拉伸/补黑；应加长片段或增加段数后重新合成。
