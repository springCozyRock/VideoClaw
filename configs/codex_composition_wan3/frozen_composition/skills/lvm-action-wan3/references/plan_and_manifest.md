# plan.json 与 evaluation_manifest.json 规范

用于 Step 3 规划与 Step 8 导出。plan.json 是制作过程账本（含被丢弃的尝试），evaluation_manifest.json 是最终交付清单（只含实际采用的内容）。两者必须能对得上：manifest 的每一个 shot 都能在 plan.json 中找到对应的 adopted 段。

## 目录

- 通用规则
- plan.json schema
- 时长预算规则
- evaluation_manifest.json schema
- 从 plan 到 manifest 的映射
- 裁剪与重编号规则
- 格式示例（占位符，不是样例剧情）
- 常见错误

## 通用规则

- 所有路径写绝对路径（OUT + 相对路径），并确认文件真实存在。
- 所有时长为整数秒。
- 时间从 0 开始，全片连续覆盖，不留空洞、不重叠。
- 内容按本任务需求自主设计；本文件里的占位符只说明字段含义，不要照抄成剧情。
- 不要为了让清单好看而改写真实合成顺序或时长；清单必须反映实际采用的片段。

## plan.json schema

```json
{
  "task": {
    "request_summary": "{用户文字需求的要点}",
    "target_duration_sec": 60,
    "audio_video_constraints": ["{台词/语种}", "{BGM 要求}", "{画幅或一镜到底要求}"],
    "user_references": [
      {"path": "{绝对路径}", "kind": "image|audio|video|text", "used_for": "{用途}",
       "extracted_to": "bible.md#{小节}", "compliance": "{是否满足参考图限制，如何转制}"}
    ],
    "style_lock": "{逐字复用的风格锁定短语}",
    "seed_policy": "{seed 取值与何时改动}"
  },
  "bible_path": "bible.md",
  "direction_lock": "{全片屏幕方向与追逐地理}",
  "beats": [
    {"beat_id": 1, "name": "{节拍名}", "purpose": "{叙事作用}",
     "intensity": "low|mid|high|peak", "target_seconds": 12, "segment_ids": [1, 2]}
  ],
  "segments": [
    {
      "segment_id": 1,
      "beat_id": 1,
      "scene_id": 1,
      "duration_sec": 8,
      "shot_mode": "single|multi",
      "shots_in_call": 1,
      "description": "{本段剧情与动作}",
      "prompt": "{实际送入 video-gen 的完整 prompt}",
      "characters": ["{角色key}"],
      "props": ["{道具}"],
      "reference_images": [
        {"order": 1, "path": "{绝对路径}", "role": "character|scene_plate|prop|prev_last_frame",
         "note": "{prompt 中如何点名这张图}"}
      ],
      "handoff_in": {"from_segment": null, "frame_path": "", "motion_state": "",
                     "screen_direction": "", "distance_note": "", "environment_state": ""},
      "handoff_out": {"frame_path": "", "motion_state": "", "screen_direction": "",
                      "distance_note": "", "environment_state": ""},
      "audio_spec": {"dialogue": [{"character": "{key}", "line": "{台词}", "voice_lock": "{音色锁定短语}"}],
                     "bgm_lock": "{BGM 锁定短语}", "sfx": ["{音效}"]},
      "seed": 20261016,
      "output": "clips/segment_01.mp4",
      "status": "planned|generated|qc_pass|qc_fail|regenerated|adopted|discarded",
      "attempts": [
        {"attempt": 1, "output": "clips/segment_01.mp4", "seed": 20261016,
         "changed_from_previous": "{首次为空；重生成时写改了 prompt/参考图/seed 的哪一处}",
         "actual_duration_sec": 8, "qc_visual": "{观察}", "qc_audio": "{观察}",
         "decision": "adopt|discard|regen", "task_state": "{正常完成/SUBMISSION_UNKNOWN/失败}"}
      ],
      "adopted_path": "{实际送入 merge 的原始片段绝对路径}",
      "adopted_duration_sec": 8,
      "observations": ["{已知问题或备注}"]
    }
  ],
  "duration_budget": {"target_sec": 60, "planned_sum_sec": 60, "adopted_sum_sec": 60,
                      "merge_duration_arg": 60},
  "regen_budget": {"per_segment_max": 2, "total_max_ratio": 0.34, "used": 0},
  "qc": {
    "segment_checks": [{"segment_id": 1, "visual": "{结论}", "audio": "{结论}", "verdict": "PASS|REGEN|ACCEPT_WITH_NOTE"}],
    "final_checks": [{"tool": "grid-generate|vision-understanding|audio-understanding|get-video-metadata",
                      "target": "{检查对象}", "question": "{问了什么}", "result": "{观察}"}]
  },
  "final_video_path": "{final.mp4 绝对路径}",
  "merge_order": ["{adopted_path 顺序，与 merge --input 完全一致}"]
}
```

字段要点：

- `segments` 的排列顺序就是计划合成顺序；实际合成顺序以 `merge_order` 为准，两者不一致时必须在 observations 里说明原因。
- `attempts` 保留全部尝试（含被丢弃的），这是重生成与成本可追溯的证据。
- 只有 `status` 为 adopted 且 `adopted_path` 非空的段才进入 merge 与 manifest。
- `task_state` 出现 SUBMISSION_UNKNOWN 或失败时，停止该段后续提交，保留现场并在 observations 记录。

## 时长预算规则

1. `sum(segments[].duration_sec)` 精确等于 `target_duration_sec`。
2. 每段 2–30 整数秒。
3. 生成后用 get-video-metadata 记录 `actual_duration_sec`；若实际比计划短，选择重生成该段或把差值分配到后续段，并更新 duration_budget。
4. 采用时长 `adopted_duration_sec` 是整数秒，且所有 adopted 段之和 ≥ target；多出的尾部由 merge `--duration target` 裁掉，裁剪只发生在最后一段。
5. 禁止用拉伸、循环、冻结画面、黑帧、静帧或重复片段补足时长；merge-video 本身会拒绝用不足的源片段凑时长。

## evaluation_manifest.json schema

```json
{
  "duration_sec": 60,
  "bible": "{角色场景统一设定的摘要}",
  "shots": [
    {"shot_id": 1, "duration_sec": 8, "description": "{本段具体内容与动作}",
     "source_video_path": "{该段采用的原始生成视频绝对路径}",
     "source_start_sec": 0, "character_keys": ["{角色key}"]}
  ],
  "scenes": [
    {"scene_id": 1, "start_sec": 0, "end_sec": 60, "description": "{逻辑场景}"}
  ],
  "characters": [
    {"key": "{key}", "name": "{名称}", "prompt_en": "{适合定位人物的英文外观短语}",
     "tag": "realistic_human|unrealistic_human|non_human", "first_shot_id": 1}
  ]
}
```

硬性规则：

- `shots` 按实际合成顺序排列，`shot_id` 从 1 开始连续递增，不跳号、不重复。
- `duration_sec` 为正整数，所有 shot 之和等于顶层 `duration_sec`，且等于目标总时长。
- `source_video_path` 指向拼接前使用的原始生成片段的绝对路径，**不得指向 final.mp4**；文件必须真实存在。
- `source_start_sec` 为 0（merge-video 从每个输入片段的起点开始使用）。
- `scenes` 连续覆盖 0 到 `duration_sec`：第一个 start_sec 为 0，后一个 start_sec 等于前一个 end_sec，最后一个 end_sec 等于 `duration_sec`；scene_id 从 1 连续。
- `characters` 覆盖需求中的预期角色，`prompt_en` 是能唯一定位该人物的英文外观短语，`tag` 取 realistic_human、unrealistic_human、non_human 之一，`first_shot_id` 指向该角色首次应出现的 shot。
- 每个 shot 的 `character_keys` 标注该段应出现的角色，取值必须来自 `characters[].key`。
- 无人物任务才允许 `characters` 为空；不得把缺失的预期角色隐藏成无人物任务。
- `bible` 写统一设定摘要（风格、主要角色、场景、音频基调），不写评测分数。
- manifest 不写评分，也不调用正式评测模型；它只反映最终采用的计划、片段顺序与时长。

## 从 plan 到 manifest 的映射

| manifest 字段 | 来源 |
| --- | --- |
| duration_sec | task.target_duration_sec（= merge 的 --duration = adopted 段合计裁尾后的时长） |
| bible | bible.md 摘要 |
| shots[] | 所有 adopted 段，按 merge_order 顺序重编号 shot_id = 1..N |
| shots[].duration_sec | adopted_duration_sec（若最后一段被 merge 裁尾，写裁剪后实际采用的整数秒） |
| shots[].description | segments[].description（按实际画面修正，不写未发生的内容） |
| shots[].source_video_path | adopted_path（原始片段，不是 final.mp4） |
| shots[].source_start_sec | 0 |
| shots[].character_keys | segments[].characters |
| scenes[] | 由 segments[].scene_id 归并：连续同场景段合成一个 scene，start/end 用累计时长 |
| characters[] | bible.md 角色表；first_shot_id = 该角色第一次出现的 shot_id |

scenes 的累计时长计算：按 shots 顺序累加 duration_sec，场景边界处切分，start_sec 与 end_sec 都用累计整数秒，保证连续覆盖。

## 裁剪与重编号规则

- merge-video 从每个输入片段的起点开始使用，所以 `source_start_sec` 恒为 0。
- 若确实需要预先裁剪某段（例如去掉开头几秒的无效画面），必须把裁剪后实际送入 merge 的文件另存为独立文件（放在 OUT 下，例如 `clips/segment_03_trimmed.mp4`），manifest 引用这个独立文件，`source_start_sec` 仍写 0，`duration_sec` 写裁剪后采用的整数秒。不得填写与真实合成清单不一致的区间。
- 计划中被丢弃的段不进 manifest；shot_id 按实际采用的段重新连续编号。
- final.manifest.json（merge-video 自动保存）是可信合成清单；导出后逐项比对两者的顺序、路径与时长是否一致，不一致以真实合成为准修正 evaluation_manifest.json。

## 格式示例（占位符，不是样例剧情）

```json
{"duration_sec": 0, "bible": "{统一设定摘要}",
 "shots": [{"shot_id": 1, "duration_sec": 0, "description": "{本段内容}",
            "source_video_path": "{原始片段绝对路径}", "source_start_sec": 0,
            "character_keys": ["{key}"]}],
 "scenes": [{"scene_id": 1, "start_sec": 0, "end_sec": 0, "description": "{逻辑场景}"}],
 "characters": [{"key": "{key}", "name": "{名称}", "prompt_en": "{英文外观短语}",
                 "tag": "realistic_human", "first_shot_id": 1}]}
```

数字与人物在此仅为格式占位，实际内容必须按当前任务填写。

## 常见错误

| 错误 | 后果 | 正确做法 |
| --- | --- | --- |
| shot 时长合计 ≠ duration_sec | 评测连续性无法核对 | 用 validate_manifest.py 校验后再交付 |
| source_video_path 指向 final.mp4 | 来源不明，阻塞评测 | 指向拼接前的原始片段 |
| source_start_sec 非 0 且没有独立裁剪文件 | 与真实合成清单不一致 | 另存裁剪后文件并引用它，起点写 0 |
| shot_id 跳号或从 0 开始 | 无法与实际片段对应 | 从 1 连续编号 |
| scenes 有空洞或重叠 | 场景覆盖不完整 | 累计时长连续切分 |
| characters 缺 tag 或 prompt_en 含糊 | 人物无法定位 | tag 三选一，prompt_en 写可区分的外观短语 |
| 预期角色未列入 characters | 被判为隐藏缺失角色 | 需求中的角色全部列入并标 first_shot_id |
| 手工拼 ffmpeg 而不用 merge-video | 缺少可信 final.manifest.json | 必须用 merge-video 合成 final.mp4 |
| manifest 描述与画面不符 | 检查记录不可信 | 用 vision-understanding 的观察修正描述 |
