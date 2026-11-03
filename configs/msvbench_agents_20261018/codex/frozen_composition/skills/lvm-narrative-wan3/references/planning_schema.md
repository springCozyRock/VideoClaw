# plan.json 与 observations.md Schema

## 目录与命名约定

所有路径相对 get-output-dir 返回的任务输出目录 `OUT`（工具自动落盘到正确位置，不另建目录）：

| 路径 | 内容 |
|---|---|
| `references/<asset_id>[_v<n>].png\|jpg` | 人物/场景/道具参考图；重绘版本加 _v2、_v3 后缀，保留旧版供溯源 |
| `clips/seg_XX[_r<n>].mp4` | 视频段；XX 从 01 起与段 id 对应；重生成版本加 _r2、_r3 后缀 |
| `frames/seg_XX_last.jpg`、`frames/seg_XX_t<sec>.jpg` | 衔接帧（尾帧）与检查帧 |
| `plan.json`、`observations.md` | 规划与观察记录（OUT 根目录） |
| `final.mp4` | 成片（OUT 根目录） |

## plan.json Schema

```json
{
  "task": {
    "requirement_text": "用户原始需求摘录（关键句保留原文）",
    "total_duration_sec": 60,
    "constraints": {
      "visual_style": "用户指定或规划确定的视觉风格",
      "language": "台词/旁白语言",
      "audio": "台词、旁白、BGM、音效约束",
      "other": ["其他音画约束"]
    },
    "user_assets": [
      {
        "path": "用户提供资料的原始路径",
        "type": "image|audio|video|text",
        "understanding": "vision-/audio-understanding 或元数据检查结论",
        "usage": "身份参考图|音色文字块|BGM文字块|关键帧参考|剧情依据",
        "processed_into": ["references/char_a.png", "assets.audio.speakers.char_a"]
      }
    ]
  },
  "story": {
    "logline": "一句话故事",
    "synopsis": "补全后的完整剧情",
    "beats": ["节拍1", "节拍2", "节拍3"]
  },
  "global_style_block": "全片视觉风格文字块，每段 prompt 开头逐字复用",
  "assets": {
    "characters": [
      {
        "id": "char_a",
        "name": "角色名",
        "appearance_text": "canonical 外观描述文字块（逐字复用）",
        "speaks": true,
        "ref_images": [
          {
            "path": "references/char_a.png",
            "role": "白底三视图|全身像|特写|关键帧",
            "seed": 20261016,
            "source": "generated|user|extracted",
            "checked": true,
            "check_note": "vision-understanding 检查结论摘要"
          }
        ]
      }
    ],
    "scenes": [
      {
        "id": "scene_1",
        "desc": "canonical 场景描述文字块",
        "ref_images": [{"path": "references/scene_1.png", "role": "定场图", "seed": 0, "source": "generated", "checked": true}]
      }
    ],
    "props": [
      {"id": "prop_1", "desc": "canonical 道具描述", "ref_images": []}
    ],
    "audio": {
      "bgm_text": "全片 BGM canonical 文字块（逐字复用；如剧情要求转场，分段落块并注明适用段）",
      "narration_style_text": "旁白风格文字块（有旁白时）",
      "speakers": {"char_a": "说话人音色 canonical 文字块（逐字复用）"}
    }
  },
  "segments": [
    {
      "id": "seg_01",
      "duration_sec": 8,
      "shot_mode": "single|multi",
      "shots": 1,
      "scene_ids": ["scene_1"],
      "subject_ids": ["char_a"],
      "plot": "本段情节（对应 story.beats 的哪一拍）",
      "dialogue": [{"speaker": "char_a", "line": "逐字台词"}],
      "narration": "逐字旁白或空字符串",
      "prompt": "实际发送给 video-gen 的完整 prompt",
      "reference_images": [
        {"path": "references/char_a.png", "order": 1, "role": "图1：char_a 身份参考"},
        {"path": "frames/seg_00_last.jpg", "order": 2, "role": "图2：前段尾帧衔接"}
      ],
      "seed": 20261016,
      "continuity": {"needs_prev_frame": false, "notes": "与前后段的衔接说明"},
      "output": "clips/seg_01.mp4",
      "status": "pending",
      "qa": {
        "attempts": [
          {
            "n": 1,
            "output": "clips/seg_01.mp4",
            "seed": 20261016,
            "metadata_check": "get-video-metadata 结论摘要",
            "video_check": "vision-understanding 结论摘要",
            "audio_check": "audio-understanding 结论摘要",
            "verdict": "pass|minor|critical",
            "issues": ["问题列表"],
            "action": "accepted|regenerate:理由"
          }
        ],
        "final_attempt": 1,
        "final_output": "clips/seg_01.mp4"
      }
    }
  ],
  "assembly": {
    "order": ["seg_01", "seg_02"],
    "final_output": "final.mp4",
    "duration_arg_sec": 60,
    "verified": {"duration_sec": 0, "resolution": "", "fps": 0, "audio": false}
  }
}
```

### 字段规则

1. segments 按叙事顺序升序排列；`sum(duration_sec) >= task.total_duration_sec`，每段 duration_sec 为 2–30 的整数。
2. prompt 保存完整可发送文本：含 global_style_block、镜头模式关键词（Single shot / Shot cut）、图N 映射、台词与音色块、BGM 块的逐字复用内容。
3. reference_images.order 从 1 起，与 prompt 中"图N"及 --reference-image 传参顺序一一对应；单段总数 ≤10。
4. 同一资产（人物/场景/道具/衔接帧来源）跨段引用时使用同一 path；身份参考图的"图N"位置全片统一。
5. status 词表：
   - `pending`：未生成；
   - `generated`：已下载未检查；
   - `checked`：段级 gate 全部通过；
   - `regenerated`：正在按重试预算重生成（保留历史 attempts）；
   - `accepted_with_deviation`：重试预算用尽后采用的最佳版本，偏差已登记；
   - `failed`：无可用版本，阻塞原因已记录；
   - `blocked_unknown_submission`：付费提交结果未知，已停止并保留现场。
6. 每次状态变化、每次 attempt 立即回写；plan.json 是产物溯源的唯一权威清单，与 observations.md 互为印证。
7. assembly.verified 在合成后由 get-video-metadata 的实测结果填写，不得填计划值。

## observations.md 格式

只追加（append-only）日志，按步骤分节，每条目包含时间、对象、结论、决策、产物。示例结构（内容随实际检查填写，不使用固定样例剧情）：

```
## [Step 2 / user_assets] <日期时间>
- 资料：<路径与类型>
- 检查：<所用技能与结论摘要>
- 转化：<生成的参考图/文字块及其在 plan.json 中的位置>

## [Step 5 / seg_03 / attempt 2] <日期时间>
- 检查：vision-understanding(--with-audio) 与 audio-understanding 结论摘要
- 问题：<例如：BGM 风格与块描述漂移>
- 决策：<例如：重生成，prompt 中前置 BGM 块并加“不要出现字幕”约束；seed 不变>
- 产物：clips/seg_03_r2.mp4

## [Step 7 / final] <日期时间>
- 终审：<全片视觉/音频检查方式与结论，注明抽样范围>
- 偏差项：<accepted_with_deviation 段落及原因>
- 产物清单：final.mp4、plan.json、observations.md、clips/、references/、frames/
```

最少必须包含的条目：输入摘要（Step 1）、每份用户资料的检查与转化（Step 2）、规划取舍（Step 3）、每张参考图的检查结论（Step 4）、每段每次 attempt 的检查与决策（Step 5）、合成校验（Step 6）、全片终审与最终产物清单（Step 7）。
