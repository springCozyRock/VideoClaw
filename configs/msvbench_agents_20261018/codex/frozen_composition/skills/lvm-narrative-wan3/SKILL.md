---
name: lvm-narrative-wan3
description: 剧情叙事类长视频的可复用制作工作流（视频模型固定 wan3.0-video，720P、16:9、带音频）。当任务输入为文字剧情/故事需求 + 总时长 + 音画约束（风格、语言、台词/旁白、背景音乐等），可附带图片、音频、视频、文本等用户参考资料，要求产出完整长视频 final.mp4 时使用本技能：自主完成剧情扩写、分镜分段与 plan.json 规划、角色/场景参考图生成（image-gen）、逐段视频生成（video-gen）、段级一致性检查（vision-understanding / audio-understanding / get-video-metadata）、衔接帧提取（extract-video-frame）与最终合成（merge-video）。确保剧情逻辑连贯、多次出现的人物/场景/物体视觉一致、同一说话人音色与背景音乐全片一致、准确使用用户提供的参考资料。触发场景：长视频生成、叙事视频、剧情视频、故事视频、剧情动画、短片/影片制作、多镜头长视频、角色一致性视频、long video generation、narrative/story-driven video production。
---

# 剧情叙事长视频制作工作流 (lvm-narrative-wan3)

## 概述

把"文字剧情需求 + 总时长 + 音画约束（可选用户参考资料）"转化为一段 720P、16:9、30FPS、带音频的完整长视频。流程为：先规划，再制备一致性资产，然后按叙事顺序逐段生成并逐段检查，最后合成与全片终审。所有剧情、分镜与资产由执行 Agent 依据当前输入自主规划；本技能不预设任何具体故事或固定分镜。

产物（全部位于 get-output-dir 返回的任务输出目录 `OUT`）：

- `final.mp4`：成片，总时长满足用户要求；
- `plan.json`：规划、资产清单与每段状态（schema 见 references/planning_schema.md）；
- `observations.md`：每段与全片的检查结论、问题与重生成决策记录；
- `references/`、`clips/`、`frames/` 下的参考图、视频段与衔接帧等中间产物。

## 基础技能与硬能力边界

一切生成与检查通过下列基础技能完成（调用命令以各自 SKILL.md 为准）。要求绝对路径的输入参数（如 merge / understand / extract 的 --input）传绝对路径；输出类参数传相对任务目录的路径（如 clips/seg_01.mp4）。只使用适配器真实暴露的能力：

| 基础技能 | 用途 | 硬边界 |
|---|---|---|
| get-output-dir | 获取任务输出目录；保存任何产物前必须先调用 | stdout 即目录路径，自动创建 |
| task-tracker | 初始化/推进任务栈，防跳步，登记 output_file 与 notes | Codex 环境无需 --session-key |
| image-gen | 生成角色/场景/道具参考图；--reference-image 可带图编辑 | 相同请求内容会复用已生成结果 |
| video-gen | wan3.0-video 生成带音频视频段 | 单段整数 2–30 秒；仅暴露文本 prompt 与参考图；**视频/音频参考输入不可用** |
| extract-video-frame | 按时间点提取衔接帧/检查帧 | 输出 JPEG 到任务目录 |
| get-video-metadata | ffprobe 校验时长、分辨率、帧率、音轨 | 返回原始 JSON |
| vision-understanding | 检查图片或抽样视频画面（--with-audio 可音画同查） | 视频最多抽 16 帧；辅助检查，不是逐帧检测 |
| audio-understanding | 转写音频/视频音轨台词，描述音色、背景声 | 音频最多前 120 秒；辅助检查 |
| merge-video | 按 --input 顺序合成 final.mp4，--duration 裁剪尾部 | 拒绝用不足源凑时长；禁止拉伸/循环/冻结/补黑 |
| grid-generate | （可选）全片/镜头网格总览图辅助终审 | 仅当环境已具备其依赖时使用；不得为此安装任何包 |

video-gen 关闭了服务端提示词扩写，prompt 必须自足完整：风格、场景、人物外观、动作、台词与音频描述都要写全，不能指望模型自动补细节。参考图硬约束：每次最多 10 张；JPEG/PNG/BMP/WEBP；单张 ≤20MB；边长 240–8000 像素；**不得含透明通道**；--reference-image 顺序对应 prompt 中"图1、图2…"。seed 记入计划，但相同 seed 不保证逐像素一致。

由能力边界导出的关键策略（细则见 references/consistency_playbook.md）：

- **音频一致性**：音频参考输入不可用；说话人音色与 BGM 的一致性靠"逐字复用的音频描述文本块"写入每段 prompt，并用 audio-understanding 校验、按 qa_checklist 纠偏。
- **镜头衔接**：视频参考输入不可用；需要画面接续时用 extract-video-frame 取前段尾帧作为下一段参考图之一，且必须与人物/场景身份参考图同传——禁止只靠尾帧衔接。
- **用户音视频资料转化**：音频经 audio-understanding 转为音色/风格文字描述；视频经 vision-understanding 与 extract-video-frame 转为文字描述与关键帧图片参考；不得把音视频文件直接送入 video-gen。

## 硬性规则

1. 在当前会话内顺序执行全部步骤；不派生子代理、不并行开新会话；不安装包、不改动共享环境与冻结的技能。
2. 为生成类调用设置充足超时。video-gen 默认轮询直至下载校验完成；需要异步时加 --background，之后重复同一命令并去掉该参数继续轮询；相同任务名、提示词、参数与参考内容会复用任务与结果，不会重复计费。
3. 出现 SUBMISSION_UNKNOWN 或已失败的付费提交：立即停止该提交，把命令、任务名与时间记入 observations.md，保留现场；不得再次发起新的付费提交。
4. 不手动创建媒体子目录：references/、clips/、frames/ 等相对路径直接传给工具参数；plan.json 与 observations.md 保存在 OUT 根目录。
5. 总时长必须诚实达成：各段时长之和 ≥ 目标总时长，多余部分由 merge-video --duration 裁尾；禁止补黑、静止画面、循环或拉伸凑时长。
6. 用户提供的每份参考资料都必须实际消费（转成参考图、文字描述块或剧情依据），并在 plan.json 的 user_assets 中登记用途；不得忽略，也不得用自创设定顶替。
7. 不预设、不复制任何既有故事或样例分镜；全部剧情只来自当前输入，细节缺失时按 Step 3 自主补全并登记。
8. plan.json 状态与 observations.md 随做随写；只登记真实生成、真实检查过的产物与结论。

## Step 1: 初始化输出目录与任务追踪

1. 调用 get-output-dir 获取任务输出目录 `OUT`（Codex 环境无需 --session-key）；此后所有产物路径以其为根。
2. 用 task-tracker 以本 SKILL.md 初始化任务栈（action=init，--skill-md-path 指向本文件）；此后每完成一个 Step 用 next-step 推进，并如实填写 --output、--output-file、--notes。
3. 依据 references/planning_schema.md 建立 plan.json 骨架（task 输入摘要 + 空 story/assets/segments），保存到 `OUT/plan.json`；建立 `OUT/observations.md`，写入输入摘要与初始决策。

## Step 2: 解析输入需求与用户参考资料

1. 提取并写入 plan.json.task：剧情需求（题材、人物、情节、结局、禁忌）、总时长（换算为明确的目标秒数并登记）、音画约束（视觉风格、语言、台词/旁白要求、BGM 风格等）。
2. 逐份检查用户资料并登记到 plan.json.task.user_assets（转化细则见 references/consistency_playbook.md 的矩阵）：
   - 图片：get-image-metadata 读取尺寸/格式；vision-understanding 确认内容与用途；核对参考图硬约束。含透明通道的图先平铺到纯色背景（如 ffmpeg 转白底 JPEG）；不可行时用 image-gen 以其为编辑参考重绘等效纯色底图。
   - 音频：audio-understanding 转写台词并描述音色（性别/年龄/音质/语速/情绪）与 BGM/音效风格，固化为文字块存入 plan.json 的 assets.audio，供全片逐字复用。
   - 视频：vision-understanding（需查音轨时加 --with-audio）确认内容与风格；extract-video-frame 提取代表性关键帧作为图片参考；其音轨信息经 audio-understanding 转为文字块。
   - 文本（剧本/设定/字幕）：并入剧情扩写依据；其中台词与旁白逐字采用或最小化编辑，不改语言、不改语义。
3. 资料与文字需求冲突时，以用户明确的文字需求为准，冲突与取舍记入 observations.md。

## Step 3: 剧情补全与分镜规划（plan.json）

1. 剧情补全：把输入扩写为有起承转合的完整故事，补齐缺失的情节、动作、情绪与环境细节；为需要的节拍写台词/旁白（用用户指定语言；未指定时依剧情选定并在 plan.json 登记）。用户已给完整情节时不重写，只补缺。
2. 分段：按叙事顺序切成连续段，每段整数 2–30 秒（推荐 5–15 秒）；各段时长之和 ≥ 目标总时长（可多 5–15%，合成时裁尾）；每段是逻辑自洽的情节单元，关键动作与台词不被段边界硬切断。
3. 定每段镜头形态：单一连续镜头写 "Single shot"；段内需要切镜时用 "Shot cut" 关键词并在 prompt 内逐镜头描述；登记 shot_mode 与 shots 数。
4. 资产规划：列出全部重复出现的人物/场景/道具，为其确定参考图清单与 canonical 外观/场景描述文本块；为每个说话人确定音色文本块、为全片确定 BGM 文本块（用户资料优先，缺失的自拟并在 assets 中标记 source=generated）。
5. 生成顺序规划：默认段号升序执行（利于衔接帧与一致性传递）；为每段登记参考图组合（身份参考图 + 衔接帧，总数 ≤10，"图N"位置全片统一）、完整 prompt 要点、duration、seed。
6. 把以上全部写入 `OUT/plan.json`（字段与状态词表见 references/planning_schema.md）；此后每段完成即时回写 status 与 qa 结论。

## Step 4: 一致性资产制备

1. 为每个缺参考图的资产调用 image-gen：角色优先纯色（白）底多视图/全身像以便约束身份，场景用无人物的定场图，道具用纯色底图；登记每张的 seed 与 source；有用户原图/关键帧时以 --reference-image 作为编辑输入以保持忠实。
2. 每张参考图用 vision-understanding 检查：与 canonical 描述一致、无多余人物与乱码文字、背景干净、无透明通道问题；不合格则调整 prompt 或 seed 重生成；最终采用版本登记到 plan.json 的 assets（checked=true）。
3. 冻结音频文字块：assets.audio 中每个说话人音色块、BGM 块、旁白风格块定稿；此后所有段的 prompt 逐字复用，禁止每段另行改写措辞。
4. 资产制备完成后，把采用清单回写 plan.json 并在 observations.md 记录每张图的检查结论。

## Step 5: 按叙事顺序逐段生成视频并段级检查

对 segments 按计划顺序执行以下循环（检查细则、失败分级与重试预算见 references/qa_checklist.md）：

1. 组装该段完整 prompt（模板见下），核对 reference_images 清单、顺序与 plan.json 完全一致。
2. 调用 video-gen：--prompt、--duration（整数秒）、--seed（计划值）、--output clips/seg_XX.mp4，并按计划顺序逐个传 --reference-image。默认阻塞轮询到下载完成；确需异步才用 --background，之后重复同一命令去掉该参数续查。
3. 生成后立即检查并登记：
   - get-video-metadata：实际时长、720P、帧率、音轨存在；
   - vision-understanding --video（加 --with-audio）：情节与镜头数符合 prompt、人物/场景与参考图一致、无明显视觉异常；
   - audio-understanding：台词逐字与语言正确、说话人音色符合音色块、BGM 符合 BGM 块。
4. 依结论处理：通过 → status=checked；不通过 → 按重试预算重生成（先改 prompt/参考图，再改 seed，每次记录理由与新输出文件名）；遇 SUBMISSION_UNKNOWN/失败 → 立即停止并保留现场（见硬性规则 3）。
5. 若下一段需要画面接续，用 extract-video-frame 提取本段尾帧（必要时另取关键帧）存 frames/，登记进下一段的 reference_images。
6. 把本段全部检查结论、问题与决策追加到 observations.md；plan.json 回写 qa.attempts 与 status；task-tracker next-step 推进。

每段 prompt 结构模板（各块的写法细则见 references/consistency_playbook.md）：

```
[全局风格块：plan.json 的 global_style_block，逐字复用]
[镜头模式：Single shot，或 Shot cut + 段内逐镜头描述]
[场景：图N为<场景名>；环境、时间、光线、氛围]
[主体与动作：图N为<角色名>，外观与参考图完全一致；本段情节动作、表情、运镜]
[台词/旁白：<角色名>（<音色块逐字>）用<语言>说：“<台词逐字>”；旁白同理]
[BGM：<BGM 块逐字>；如需衔接或转场在此声明]
```

"图N"编号必须与 --reference-image 传入顺序一致；同一人物/场景在所有出镜段落使用同一文件路径与同一图N位置。

## Step 6: 合成 final.mp4

1. 全部段达到 checked / accepted_with_deviation（偏差已登记）后，调用 merge-video：按 plan.json 的 assembly.order 顺序重复 --input 传各段最终采用版本的绝对路径，--output final.mp4，--duration 传目标总时长秒数。
2. 用 get-video-metadata 校验 final.mp4：总时长达标、720P、16:9、30FPS、音轨完整；结果回写 plan.json 的 assembly.verified。
3. 顺序或时长不对时修正 --input 顺序/--duration 重新合成；仍禁止任何补黑、拉伸、循环、冻结手段。

## Step 7: 全片终审与产物记录

1. 全片视觉终审：用 vision-understanding 检查 final.mp4 的剧情完整性（起承转合）、叙事逻辑与跨段视觉一致性；长视频可先用 grid-generate 出全片总览图再检查（仅当环境已具备其依赖），或用 extract-video-frame 取首、尾及中部多个时间点逐帧检查；如实按"抽样检查"记录，不宣称逐帧检测。
2. 全片音频终审：audio-understanding --video --with-audio 检查 final.mp4 开头部分的台词、音色与 BGM 连续性（该检查最多覆盖前 120 秒）；中后段以各段段级音频检查结论为准，覆盖范围如实写入 observations.md。
3. 发现 critical 问题 → 回到 Step 5 重生成对应段并重新执行 Step 6/7；minor 问题 → 登记为偏差项。
4. 收尾：补全 plan.json（全部 status、assembly.verified）；observations.md 写入终审结论、偏差项与最终产物清单；核对 OUT 内 final.mp4、plan.json、observations.md 与全部采用资产齐备。
5. 向用户报告：final.mp4 路径与实际时长、需求逐项满足情况（总时长/剧情/资料使用/一致性）、登记的偏差项与阻塞项。

## References 导航

- references/planning_schema.md — plan.json 与 observations.md 的完整 schema、命名规范、状态词表（Step 1/3 规划时必读）。
- references/consistency_playbook.md — 视觉/音频一致性文本块写法、用户资料转化矩阵、衔接与 seed 策略（Step 2/4/5 必读）。
- references/qa_checklist.md — 段级与全片检查 gate、失败分级与重试预算、付费调用安全（Step 5/6/7 必读）。
