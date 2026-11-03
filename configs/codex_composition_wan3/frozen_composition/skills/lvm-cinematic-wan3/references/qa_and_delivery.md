# 检查、再生成与交付

目录
1. 检查工具与已知限制
2. 段级 QA 清单（Phase 5）
3. 再生成策略
4. 成片 QA 清单（Phase 7）
5. qa_report.md 与交付物

## 1. 检查工具与已知限制

- vision-understanding：`understand --image <绝对路径> --prompt "..."` 查图片；`understand --video <绝对路径> --prompt "..."` 查视频，单次最多抽 16 帧——超过 ~30 秒的段或全片检查按时间范围/分段多次调用；需音画同查加 `--with-audio`。
- audio-understanding：`understand --audio <绝对路径> --prompt "..."` 或 `understand --video <绝对路径> --with-audio --prompt "..."`；音频检查最多前 120 秒，长内容分段查。
- 二者均为制作辅助检查（抽样理解，不是逐帧检测）：结论用观察描述记录，重要判断（如台词内容）在提示词层面同时兜底。
- grid-generate：`scripts/grid_generate.py --video_path <绝对路径> --mode by-time|by-shot ...` 生成带序号+时间戳的网格图与 sidecar JSON，配合 vision-understanding --image 做全片一致性与物理异常粗查。
- get-video-metadata / get-image-metadata：客观规格验证（时长、分辨率、fps、音轨）。

## 2. 段级 QA 清单（Phase 5）

每段生成后逐项检查，结论写入 plan.json 的 qa_notes：

视觉：
- [ ] 主体身份与角色/场景参考图一致（脸、服装、发型、标志物、空间布局）
- [ ] 镜头语言按提示词执行（景别、运镜方向与速度、单/多镜头切点）
- [ ] 画面无明显畸变、多余肢体、穿帮、闪烁
- [ ] 风格与 style_block 相符（影调、色彩、质感）

音频：
- [ ] 有音轨；台词内容、语种、说话人与计划一致
- [ ] 音色与角色 voice_text 相符；BGM 与 audio_block 相符
- [ ] 音画大体同步（口型/动作与声音无明显错位）

规格：
- [ ] 实际时长与计划一致或可解释（get-video-metadata）
- [ ] 720P、16:9

## 3. 再生成策略

- 判定 qa_fail 后按顺序尝试，单段累计重生成一般不超过 3 次：
  1. 修订提示词：把缺失的镜头/一致性要素写得更具体（前置到提示词开头），保持 style/audio 块逐字不变；
  2. 换参考帧：用本段更好的一帧或重取尾帧作续接参考；
  3. 换 seed：固定提示词与参考，仅改 seed。
- 每次尝试记录进 plan.json 的 attempts；重生成命令仍遵守幂等与 SUBMISSION_UNKNOWN 规则（结果不明即停，不重复提交）。
- 3 次后仍不达标：评估是否可用（轻微问题记录为遗留项）或调整分镜设计（改镜头方案后回到 Phase 2 更新计划），不得为凑数使用明显穿帮的段。
- 音色/BGM 跨段漂移：优先重生成漂移段并在其音频块前追加一句强化描述（如「与前段完全相同的男声与同一首钢琴主题曲」），不改全局块本身。

## 4. 成片 QA 清单（Phase 7）

对 OUT/final.mp4 逐项执行并记录：

- [ ] 规格：get-video-metadata 确认时长=目标 D_total、720P、16:9、30FPS、含音轨。
- [ ] 全片概览：grid-generate by-time（interval 2s）→ vision-understanding --image 检查剧情连贯、节奏、有无重复/跳变；再 by-shot 网格检查跨镜头视觉一致性。
- [ ] 分段深查：按时间段对 final.mp4（或各片段）vision-understanding --with-audio 抽查关键段：人物/场景/物体跨段一致、剧情逻辑连贯。
- [ ] 音频全片复核：audio-understanding 分段（≤120 秒/次）确认同一角色音色一致、BGM 风格统一、无意外静音或杂音。
- [ ] 需求符合性：对照用户文字需求与音画约束逐条核对；用户提供的参考资料确认已被实际使用（对照 assets.json 的 user_assets）。
- [ ] 中间产物齐全：各段片段、参考图、帧、网格图、plan.json、assets.json 均在 OUT 下且 plan.json 状态为最终值。

## 5. qa_report.md 与交付物

qa_report.md 写入 OUT，内容：逐项清单结论、发现的问题与处理方式、重生成记录摘要、
遗留问题与建议。最终交付物（全部保留在 OUT，不删除）：

```
OUT/
├── final.mp4          # 合成成片
├── plan.json          # 最终版规划与执行状态
├── assets.json        # 一致性资产与用户资料转化清单
├── qa_report.md       # 检查报告
├── clips/…            # 各段片段（含重生成版本）
├── references/…       # image-gen 参考图
├── frames/…           # 抽取帧
└── images/…           # grid-generate 网格图与 sidecar
```
