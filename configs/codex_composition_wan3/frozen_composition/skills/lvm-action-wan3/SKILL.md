---
name: lvm-action-wan3
description: 动作与追逐叙事类长视频的端到端制作工作流（wan3.0-video，720P/16:9/自带音频）。输入为文字需求、目标总时长与音画约束，可附用户提供的图片、音频、视频或文本参考资料；输出 final.mp4、plan.json、evaluation_manifest.json 以及可追溯的参考图、片段与检查记录。当任务要求制作打斗、追车、追捕、逃亡、跑酷、竞速、特工或警匪对峙、灾难逃生、武打、高强度动作叙事的长视频，需要把多个片段拼成指定总时长，需要人物、场景、道具在多次出现时保持视觉一致，需要同一说话人的音色与背景音乐全片一致，需要按镜头与场景导出评测清单时使用。触发词示例：动作长视频、追逐戏、追车、打斗片段、逃亡、跑酷、竞速、多镜头拼接、按分镜生成动作视频、60秒或90秒动作短片。非动作类任务（纯音乐MV、教学讲解、静态展示、慢节奏风光片）不使用本技能。
---

# 动作与追逐叙事长视频制作（wan3.0-video）

把一个动作/追逐类文字需求做成指定总时长的 `final.mp4`：解析需求 → 建立统一设定（圣经）→ 节拍与分段规划 → 生成一致性参考资产 → 逐段生成并检查 → 合并 → 全片检查 → 导出评测清单。

每一步都必须调用基础技能的真实命令，禁止臆造未开放的能力，禁止用后期手段伪造时长或音频。

## 输入与交付契约

输入（由任务给出，可能不完整）：

- 文字需求：剧情、人物、风格、动作与追逐要求
- 目标总时长（秒）
- 音画约束：是否有台词与语种、BGM 风格、是否要求一镜到底、画幅、是否要求特定音效
- 可选参考资料：图片、音频、视频、文本

交付（全部保存到 `get-output-dir` 返回的任务目录，记为 OUT）：

- `final.mp4`：由 merge-video 合成，720P、16:9、30FPS、含音轨，时长等于目标总时长
- `plan.json`：节拍、分段、每段 prompt/seed/参考图/实际路径与实际时长/QC 结论/重生成记录
- `evaluation_manifest.json`：最终采用的计划、真实片段顺序与时长（schema 见 `references/plan_and_manifest.md`）
- `bible.md`：角色、场景、道具、方向轴线、视觉风格、音频（音色+BGM+音效）统一设定
- `observations.md`：段级与全片检查观察、已知问题、采用/丢弃决策
- 中间产物：参考图、视频片段、末帧、网格图（由基础技能自动落盘）

## 能力边界（先确认，再设计）

| 能力 | 真实状态 | 对设计的影响 |
| --- | --- | --- |
| 视频生成 | video-gen：wan3.0-video，720P、16:9、带音频，关闭服务端提示词扩写，单段 2–30 整数秒 | 长视频必须分段拼接；每段时长为整数秒；总时长在计划阶段精确分配 |
| 参考输入 | 只有文本 prompt 与 `--reference-image`：≤10 张，JPEG/PNG/BMP/WEBP，单张 ≤20MB，边长 240–8000，不能含透明通道，顺序对应 prompt 中的图1、图2…… | 一致性只能靠“文字锁定短语 + 参考图 + 末帧续接 + 剪辑点设计” |
| 视频参考、音频参考、首尾帧锁定 | 未开放，不得写入流程 | 无法做真正的视频续写；跨段连续用 handoff 协议近似 |
| 音频 | 随片段由 video-gen 一次生成，台词、BGM、音效全部写在 prompt 内 | 音色与 BGM 一致性靠逐字复用的音频锁定短语；成片后无法替换或补配音轨 |
| 语音合成、音乐生成、加/换音轨、裁剪、变速、抽帧切镜 | 无对应技能 | 不要计划“先画面后配音”；时长与音频必须在生成阶段一次做对 |
| 参考图生成与编辑 | image-gen：Qwen-Image，可重复 `--reference-image` 做编辑 | 角色三视图、场景板、道具表、用户图片合规化转制 |
| 内容检查 | vision-understanding、audio-understanding（Qwen3.5-Omni，视频最多抽 16 帧，音频最多前 120 秒）、get-video-metadata、get-image-metadata、extract-video-frame、grid-generate | 抽样检查而非逐帧检测；结论用观察描述记录 |
| 合成 | merge-video：`--input` 重复决定顺序，`--duration` 裁掉多余尾部，拒绝用不足的源片段凑时长，禁止拉伸/循环/冻结/补黑 | 片段必须真实生成且合计达到目标时长 |

## 执行约束（硬性）

- 在当前会话内顺序执行；禁止委派子代理、并行会话或 `sessions_spawn`，因此也不存在子代理超时问题。
- 只使用上表列出的真实能力；不要引用 reference_video、reference_audio、首尾帧锁定等未开放参数。
- 不修改冻结的基础技能与配置，不安装依赖，不改共享环境。
- 只写 OUT 目录；不要手工创建额外目录树，相对输出路径（如 `clips/segment_01.mp4`、`references/character_a.png`、`frames/segment_01_last.jpg`）由适配器在 OUT 下保存。
- 成本安全：适配器按“任务名 + prompt + 参数 + 参考内容”复用已有结果，要真正重生成必须至少改动一处（prompt 措辞、参考图或 seed），每次改动都是新的付费提交。
- 付费提交返回 SUBMISSION_UNKNOWN 或已失败：立即停止，不重复提交，保留现场，把状态写入 `plan.json` 并向用户说明。
- 长耗时轮询：优先用 video-gen 默认等待；确需异步时加 `--background`，之后用完全相同的命令去掉该参数续接，中途不要改 prompt 或参数。
- 禁止用拉伸、循环、冻结画面、黑帧、静帧或重复片段凑时长。

## 工作流总览

| 步骤 | 动作 | 主要产物 |
| --- | --- | --- |
| 0 | 取任务目录，可选初始化任务追踪 | OUT |
| 1 | 解析需求与用户参考资料，找出缺口 | requirement_notes（写入 observations.md） |
| 2 | 建立动作圣经 | bible.md |
| 3 | 节拍与分段规划，写全每段字段 | plan.json |
| 4 | 生成并自检一致性参考资产 | references/ 下参考图 |
| 5 | 逐段生成 + 段级 QC + 末帧 handoff | clips/、frames/、plan.json 更新 |
| 6 | 合并 | final.mp4 |
| 7 | 全片 QC（网格图 + 音画检查） | observations.md 更新 |
| 8 | 导出并校验评测清单 | evaluation_manifest.json |
| 9 | 汇报交付 | 交付说明 |

## Step 0 — 任务目录与追踪

运行 get-output-dir 取 OUT（需要子目录时用 `--subdir`）。后续所有绝对路径 = OUT + 相对路径。可选：用 task-tracker `init --skill-md-path` 指向本技能，逐步用 `next-step` 记录 output/output_file，避免长流程丢状态。

## Step 1 — 解析需求与参考资料

1. 列出全部输入：文字需求原文、目标总时长（整数秒）、音画约束、参考文件绝对路径。
2. 逐个把参考文件转成可用文字设定：
   - 图片：get-image-metadata（宽高/格式/大小）+ vision-understanding（人物外观、服装、道具、风格、光线、能否直接当参考图）
   - 音频：audio-understanding（逐句转写、说话人性别与年龄、音色特征、BGM 乐器与节奏、音效）
   - 视频：vision-understanding `--video`（需要音画一起看时加 `--with-audio`）：人物外观、动作风格与节奏、场景与地理、镜头语言、音色与 BGM
   - 文本：整理成结构化设定
3. 核对每张图片是否满足 video-gen 限制（JPEG/PNG/BMP/WEBP、≤20MB、边长 240–8000、无透明通道）。不满足时用 image-gen `--reference-image` 转制：透明底改纯白不透明底、单图改三视图、统一到本片风格。
4. 写 requirement_notes 到 `observations.md`：明确需求、隐含需求、缺口（剧情细节不足、人物外观缺失、时长未分配、音频要求模糊、参考资料之间冲突）。
5. 缺口一律自行补全（剧情细节、台词、镜头、时长分配、音色与 BGM 设定），补全结果写进 `bible.md` 与 `plan.json` 保证可追溯；不要因为需求不完整就停摆。用户已明确给定的设定优先，不得被自创内容覆盖。

## Step 2 — 建立动作圣经 bible.md

按 `references/consistency_playbook.md` 的模板写全，并锁死以下要素：

- 视觉风格锁定短语：一段固定文字，逐字复用到每段 prompt 开头
- 角色表：key、姓名、外观锁定短语（中英各一）、服装与随身道具、类型 tag（realistic_human / unrealistic_human / non_human）、音色锁定短语、台词语种与口头禅
- 场景表：scene_id、地点、时间与天气、光源方向与色温、色调、空间关系（门、路口、拐角、可破坏物、追逐路线）、场景板参考图路径
- 道具与载具表：外观、状态变化（例如车前灯碎了就一直碎着）
- 方向轴线：direction_lock（谁向画面哪一侧移动）、追逐地理顺序、允许越轴的唯一转折点
- 音频设定：BGM 主题锁定短语（乐器编制、节奏快慢、风格、情绪、是否贯穿）、音效层次、台词规范（每段最多 2 句短台词、标明说话人）
- 禁止项：画面内可读文字、字幕、水印、logo、多余人物、无关旁白

## Step 3 — 节拍与分段规划 plan.json

1. 用 `references/action_shot_language.md` 的强度曲线把剧情切成节拍（铺垫 → 触发事件 → 追逐升级 → 障碍或转折 → 高潮对峙 → 收尾）。节拍名称与内容按本任务需求自主设计，不套固定样例。
2. 把节拍切成生成段（一段 = 一次 video-gen 调用）：
   - 每段 2–30 整数秒，所有段时长之和精确等于目标总时长
   - 高强度快节奏优先“一次调用内多镜头”：prompt 含 `Shot cut`，单镜头 3–6 秒，比多次单独调用更省成本且节奏更连贯
   - 沉浸式追逐或一镜到底用 `Single shot`，8–20 秒
   - 每段是一个逻辑完整的动作单元，切点落在动作进行中或运动匹配处，用来掩盖跨调用的不连续
3. 每段写全字段（完整 schema 见 `references/plan_and_manifest.md`）：description、prompt、duration_sec、shot_mode 与 shots_in_call、scene_id、characters、reference_images（顺序与用途）、handoff_in/handoff_out、audio_spec、seed、output。
4. prompt 用固定顺序组装：风格锁定 → 镜头类型与运动 → 主体锁定短语 → 本段动作与物理细节 → 环境与光线 → 屏幕方向与位置 → 音频（引号台词 + 音色短语 + BGM 短语 + 音效列表），并显式点名图1、图2 各是什么参考。
5. 规划自检：时长合计等于目标、场景覆盖连续无空洞、每段都有参考图与 handoff 说明、每段角色都在角色表内、台词不超过 2 句、每段动作数量不超过 2 个清晰动作。

## Step 4 — 生成一致性参考资产

1. 角色：image-gen 生成三视图或表情表，纯白不透明背景，一个主要角色一张；写实人物按真实质感描述并对应 tag。
2. 场景：每个逻辑场景一张定场板；同一场景多次出现只生成一次，全片复用同一张。
3. 道具与载具：只在反复出现或影响剧情时生成。
4. 每张图用 vision-understanding 自检（是否纯白底、是否符合锁定短语、有无多余元素或文字、服装细节是否清晰），必要时 get-image-metadata 核对尺寸与格式。不合格再调整 prompt 重生成，图片生成同样是付费提交，先把 prompt 想清楚。
5. 把最终采用的参考图路径写回 `bible.md` 与 `plan.json`。用户已提供且合规的参考图优先直接使用，不要重绘覆盖用户设定。

## Step 5 — 逐段生成与段级 QC（严格顺序）

对每一段 i：

1. 组装最终 prompt：复用锁定短语 + 本段动作 + handoff_in 的末帧状态复述（姿态、位置、速度、方向、双方距离）。
2. 传参考图：主角图、对手图、场景板、上一段末帧；顺序与 prompt 中图1、图2 一致，总数 ≤10，只放本段必要集合。
3. 调 video-gen：`--duration` 为整数秒，`--seed` 记入 plan.json，`--output clips/segment_XX.mp4`。默认等待轮询完成；确需异步加 `--background`，之后用同一命令去掉该参数续接。
4. 立刻用 get-video-metadata 核对实际时长、分辨率、fps、音轨存在。实际时长短于计划：记录并选择重生成或调整后续段时长，绝不补黑或拉伸。
5. extract-video-frame 取末帧（`--seconds` 接近实际时长末尾）与关键中间帧，路径写回 handoff_out，供下一段复用与后续检查。
6. 视觉检查用 vision-understanding `--video`，音频检查用 audio-understanding `--video ... --with-audio`；prompt 模板见 `references/qc_checklist.md`。
7. 判定 PASS / REGEN / ACCEPT_WITH_NOTE，写入 plan.json 与 observations.md。REGEN 必须实际改动至少一处（prompt 措辞、参考图或 seed）；每段最多重生成 2 次，仍不达标则采用最不坏版本并把问题记为已知缺陷。
8. 只有状态为 adopted 且有 adopted_path 的段才进入合并；被丢弃的段保留在 plan.json 中作为记录，不进 manifest。

## Step 6 — 合并 final.mp4

1. 按 plan.json 的合成顺序，用绝对路径依次传 merge-video 的 `--input`。
2. `--output final.mp4`，`--duration` 填目标总时长以裁掉多余尾部。
3. 合并后用 get-video-metadata 核对：1280x720、30fps、含音轨、时长等于目标总时长。
4. merge-video 拒绝用不足的源片段凑时长时，回 Step 5 补真实片段，不要用其他手段绕过。
5. merge 生成的 final.manifest.json 是可信合成清单，Step 8 的 shots 必须与它逐项对应。

## Step 7 — 全片 QC

1. grid-generate `by-time` 生成全片概览网格图，再用 vision-understanding `--image` 检查：节奏曲线、身份与服装漂移、追逐方向是否全片一致、场景与破坏状态是否连续。
2. grid-generate `by-shot` 生成镜头网格，检查跨镜头一致性与镜头语言是否按计划执行。
3. vision-understanding `--video final.mp4 --with-audio`：剧情逻辑与因果连贯、动作是否完成、音画是否一致（注意视频最多抽 16 帧、音频最多前 120 秒；更长的片子改为对各片段分别检查后汇总）。
4. audio-understanding `--video final.mp4 --with-audio`：台词是否按要求出现、同一说话人音色是否一致、BGM 是否贯穿且风格一致、音效层次是否到位。
5. 结论写入 observations.md。只有“必须修”的问题才回 Step 5 重生成对应段并重新合并，注意重生成预算（总重生成段数不超过计划段数的三分之一，除非用户明确要求）。

## Step 8 — 导出 evaluation_manifest.json 并自检

1. 从 plan.json 的真实 adopted 结果生成 evaluation_manifest.json，字段与规则见 `references/plan_and_manifest.md`：shots 按实际合成顺序、shot_id 从 1 连续、duration_sec 为正整数且合计等于目标总时长、source_video_path 指向原始生成片段的绝对路径且不得指向 final.mp4、source_start_sec 为 0、scenes 连续覆盖全片、characters 含 key/name/prompt_en/tag/first_shot_id、每段标 character_keys。
2. 运行本技能的校验脚本：

```bash
python <本技能目录>/scripts/validate_manifest.py \
  --manifest OUT/evaluation_manifest.json \
  --plan OUT/plan.json \
  --target-duration <目标总时长秒数>
```

脚本会检查：字段完整性、shot_id 从 1 连续、duration_sec 为正整数且合计等于目标总时长、source_video_path 为真实存在的绝对路径且不是 final.mp4、source_start_sec 为 0、scenes 连续覆盖全片、characters 的 tag 合法且 first_shot_id 有效、每段 character_keys 已声明，并与 plan.json 的 adopted 段、merge_order、target_duration_sec、duration_budget、角色 key 交叉核对。加 `--allow-missing-files` 只做 schema 校验，加 `--json-summary {路径}` 输出机器可读结果。

3. ERROR 必须修完再交付；WARN 逐条确认并在 observations.md 说明原因。
4. characters 为空只允许在本任务确实无人物时使用；不得把缺失的预期角色隐藏成无人物任务。

## Step 9 — 汇报交付

向用户说明：final.mp4 的绝对路径与实际时长、分辨率、帧率、音轨情况；采用的段数与顺序；一致性策略（用了哪些参考资产与锁定短语）；QC 结论与已知缺陷；重生成记录；plan.json、bible.md、observations.md、evaluation_manifest.json 的路径。只汇报真实执行过的检查，不要编造结论。

## 动作与追逐专项硬规则

1. 方向轴线：追逐双方的屏幕方向全片一致（例如被追者始终向画面右方逃，追者始终从画面左方进入），只在明确转折点越轴并在 prompt 中说明转身动作。
2. 距离连续：每段 handoff 记录双方距离与主体在画面中的位置，下一段 prompt 复述后再推进，避免距离突然跳变。
3. 动作三拍：起势 → 接触 → 反应；一段最多安排 2 个清晰动作，不堆叠复杂连招。
4. 人数与物件守恒：明确写出画面中有几个人、各自位置；被撞翻的物体在后续镜头保持损坏状态。
5. 载具物理：轮子转动方向与行进一致，转弯有侧倾，背景位移速度与车速匹配。
6. 镜头运动接力：上一段是向右跟拍，下一段继续向右跟拍或用同方向运动匹配剪辑。
7. 高潮前置铺垫：追逐与打斗之前必须有交代地理与动机的定场镜头，否则观众看不懂追什么、往哪追。
8. 禁止画面内可读文字、字幕与水印，prompt 中显式排除。
9. 台词短、单人、正面：需要口型大致对齐的镜头用近景正面短句，避免侧脸长台词与多人同时说话。
10. 每段都要有声音设计：显式列出环境底噪、主体动作音、冲击音与 BGM，否则模型可能只给静默或只有音乐。

## 参考文件导航

- `references/action_shot_language.md`：动作与追逐镜头语汇、强度曲线与节奏分配、轴线与方向、匹配剪辑与 handoff、动作物理与打斗编排、prompt 组装模板与失败规避写法。Step 3、Step 5 组装 prompt 前必读。
- `references/consistency_playbook.md`：一致性资产类型、角色/场景/道具参考图规范、用户图片音频视频的合规化与转写、跨段视觉漂移控制、音色与 BGM 锁定、bible.md 模板。Step 1、Step 2、Step 4 必读。
- `references/plan_and_manifest.md`：plan.json 与 evaluation_manifest.json 的完整 schema、时长预算规则、从计划到清单的映射、裁剪与重编号规则、格式示例与常见错误。Step 3、Step 8 必读。
- `references/qc_checklist.md`：段级与全片检查命令、vision/audio 检查 prompt 模板、PASS/REGEN/ACCEPT_WITH_NOTE 判定标准、重生成预算、observations.md 模板。Step 5、Step 7 必读。
- `scripts/validate_manifest.py`：校验 evaluation_manifest.json 结构与内容（时长合计、shot_id 连续、场景覆盖、角色与 tag、源片段路径真实存在且不是 final.mp4），并可与 plan.json 交叉核对。Step 8 必须运行。
