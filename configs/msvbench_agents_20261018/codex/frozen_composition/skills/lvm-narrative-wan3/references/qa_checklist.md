# 检查 Gate、失败分级与重试策略

所有检查都是抽样式制作辅助检查（vision-understanding 视频最多抽 16 帧、audio-understanding 音频最多前 120 秒），结论要如实按抽样口径记录，不宣称逐帧/全程检测。

## 段级 Gate（每段全部通过才可置 status=checked）

### G1 元数据（get-video-metadata）
- [ ] 实际时长与计划 duration_sec 基本一致（±1 秒内；短缺超过 1 秒记为 critical）
- [ ] 分辨率 720P、宽高比 16:9、帧率正常
- [ ] 音轨存在（无音轨记为 critical）

### G2 画面内容（vision-understanding --video，需要音画同查时加 --with-audio）
- [ ] 情节、动作、镜头数与该段 prompt 一致，覆盖 plan.json 的 plot 与 dialogue 场景
- [ ] 出镜人物外观与身份参考图一致（发型发色、服装、标志特征）
- [ ] 场景与场景参考图/canonical 描述一致；光线与时间设定正确
- [ ] 关键道具出现且形态正确
- [ ] 无明显视觉异常：肢体畸变、面部崩坏、多余/缺失人物、乱码文字、水印、突兀字幕
- [ ] 需要衔接的段：开头画面与前段尾帧在机位、光线、人物位置上自然接续

### G3 音频（audio-understanding，对段视频音轨检查）
- [ ] 台词转写与 plan.json 登记逐字一致，语言正确，无吞字/重复/胡言
- [ ] 说话人音色符合 assets.audio.speakers 的音色块描述；同一说话人与已 checked 段听感一致
- [ ] BGM 风格符合 bgm_text；无计划外音乐；环境声与场景匹配
- [ ] 旁白（如有）内容与风格符合登记
- [ ] 音画同步：说话人开口与声音对应，无明显错位

## 失败分级

- **critical**（必须重生成）：情节错误或缺失、人物身份漂移、台词缺失/错误/语言错误、严重视觉异常、无音轨、时长短缺超 1 秒、衔接严重断裂。
- **minor**（可接受并登记）：轻微色差、背景细节偏差、BGM 响度或配器轻微出入、非关键道具形态小偏差。
- 拿不准时按 critical 处理，但在重试预算用尽后可降级为 accepted_with_deviation。

## 重试预算与规则

1. 每段最多重生成 2 次（共 3 个版本）：
   - 第 1 次：保持 seed，修 prompt/参考图（前置或强化对应 canonical 块、修正图N声明、补充负向约束如"画面中不要出现文字字幕"、更换/增加身份参考图）；
   - 第 2 次：可换 seed，并综合前两次问题继续修 prompt。
2. 重生成输出用新文件名（clips/seg_XX_r2.mp4），旧版本保留不删除；每次 attempt 完整记入 plan.json 的 qa.attempts（seed、改动点、三项检查结论、verdict、action）。
3. 预算用尽仍有 critical：选最佳版本置 accepted_with_deviation 并登记具体偏差；若无任何可用版本置 failed，写明阻塞原因，评估对后续段与合成的影响后如实继续或停止，不静默跳过、不无限重试。
4. 付费调用安全：video-gen 返回 SUBMISSION_UNKNOWN 或提交后结果不明 → 立即停止，段状态置 blocked_unknown_submission，把命令、任务名、时间、返回信息记入 observations.md；只允许重复同一命令（去掉 --background）续轮询既有任务，禁止发起新的付费提交。

## 段间连续性检查（进入 Step 6 前）

- [ ] 按 assembly.order 核对相邻段衔接：用衔接帧/检查帧（extract-video-frame）比对人物位置、光线、情绪过渡
- [ ] 全片情节因果链与 story.beats 对应：无缺拍、无重复拍、无顺序错乱
- [ ] 每个说话人音色跨段一致（汇总各段 G3 结论；发现漂移段按分级处理）
- [ ] BGM 全片风格一致，转场只发生在计划登记处
- [ ] 各段最终采用版本（qa.final_output）时长之和 ≥ 目标总时长；不足时先补规划内段落，不得用无关画面凑数

## 全片 Gate（final.mp4）

- [ ] get-video-metadata：总时长 = --duration 目标值、720P、16:9、30FPS、音轨完整；实测值写入 assembly.verified
- [ ] 段顺序与 assembly.order 一致（合成命令的 --input 顺序留档于 observations.md）
- [ ] 全片视觉终审：剧情起承转合完整、叙事逻辑连贯、跨段人物/场景/风格一致。手段任选其一并记录方式：
  - vision-understanding 直查 final.mp4（16 帧抽样，适合总体把握）；
  - grid-generate 出 by-time 或 by-shot 总览图后交给 vision-understanding 检查（仅当环境已具备其依赖；不得为它安装包）；
  - extract-video-frame 取首、尾及中部 4–8 个时间点逐帧检查。
- [ ] 全片音频终审：audio-understanding --video --with-audio 查 final.mp4（覆盖开头约 120 秒）；中后段音频以段级 G3 结论为准，覆盖范围如实写入 observations.md
- [ ] 用户要求逐项核对：总时长、剧情要点、每份参考资料的落地使用、语言、风格与 BGM 约束
- [ ] 与用户明确要求的任何偏差都已登记并有理由

## 产物记录（结束前必查）

- [ ] plan.json：全部段 status、qa.attempts、qa.final_output、assembly.verified 已回写；user_assets 全部有 usage 与 processed_into
- [ ] observations.md：含输入摘要、资料检查与转化、规划取舍、每张参考图检查结论、每段每次 attempt 记录、合成校验、终审结论、偏差项、最终产物清单
- [ ] OUT 目录内齐备：final.mp4、plan.json、observations.md、被采用的 clips/、references/、frames/（含未采用的重试版本，供溯源）
- [ ] task-tracker：各 Step 已 next-step 推进，output_file 登记真实路径
