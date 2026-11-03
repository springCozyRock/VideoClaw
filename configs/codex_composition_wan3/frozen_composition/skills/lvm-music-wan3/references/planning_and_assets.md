# 规划与一致性资产规范

目录：
1. plan.json 结构
2. 音乐卡 / 风格卡 / 角色卡 / 场景卡
3. 分段与时长规则
4. 参考图规格与 seed 管理

## 1. plan.json 结构

保存到 get-output-dir 输出目录根下。字段可按需增补，但以下必须存在：

```json
{
  "title": "本次MV的工作标题",
  "target_duration_sec": 90,
  "requirements_summary": "用户原始需求要点与自拟补充",
  "audio_constraints": "卡点/演唱/纯器乐等音画约束",
  "visual_constraints": "画幅、风格、必须出现的元素",
  "music_card": {
    "source": "user_audio | self_designed",
    "genre": "", "bpm": 0, "mood_arc": "",
    "instrumentation": "", "vocal": "音色/唱法/语言，或 instrumental",
    "verbatim_prompt_text": "逐字复用进每段视频提示词的音乐描述（一句话，含曲风、速度、乐器、人声音色、情绪）"
  },
  "song_structure": [{"section": "intro|verse|chorus|bridge|outro", "start": 0, "end": 12, "energy": "低|中|高"}],
  "style_card": {"verbatim_prompt_text": "逐字复用的全片视觉风格描述（画面质感、色调、光线、时代感、媒介风格）"},
  "characters": [{"id": "char_01", "name": "", "appearance_verbatim": "逐字外观描述：性别年龄、发型发色、脸型、服装配饰、体型", "timbre_note": "该角色演唱/说话的音色描述", "ref_images": ["references/char_01_sheet.png"]}],
  "scenes": [{"id": "scene_01", "description_verbatim": "逐字环境描述：地点、时间、光线、陈设、天气", "ref_images": ["references/scene_01.png"]}],
  "segments": [{
    "id": "seg_01", "order": 1, "start": 0, "duration": 12,
    "section": "intro",
    "shot_mode": "single|multi",
    "plot": "本段画面与剧情，含与前后段的衔接状态",
    "lyrics_or_lines": "本段对应的歌词/演唱内容或 instrumental",
    "scene_ids": ["scene_01"], "character_ids": ["char_01"],
    "ref_images_ordered": ["references/style_board.png", "references/char_01_sheet.png"],
    "seed": 20261016,
    "prompt_final": "实际提交给 video-gen 的完整提示词（生成前填写）",
    "output_path": "videos/seg_01.mp4",
    "status": "planned|generated|checked|failed",
    "qc_notes": "段级检查结论"
  }],
  "final": {"path": "final.mp4", "verified_duration_sec": null, "qc_summary": ""}
}
```

## 2. 四类卡片

- **音乐卡**：全片音乐一致性的唯一载体。用户给了音乐时用 audio-understanding 提炼（曲风、BPM、乐器编制、人声音色与唱法、混音氛围、结构时间轴、可辨识歌词）；未给时自拟并标注。`verbatim_prompt_text` 一经确定，每段提示词逐字复用，不得逐段改写措辞。
- **风格卡**：全片视觉基调一句话，逐字复用；用户给了参考视频/图片时，把 vision-understanding 提炼的色调、光线、质感写进去。
- **角色卡**：外观描述逐字复用；同一角色跨段必须引用同一组 ref_images。演唱角色的 `timbre_note` 写进含该角色演唱的每段提示词，与音乐卡的 vocal 描述保持一致。
- **场景卡**：复现场景逐字复用描述与参考图；同场景不同时间段（日/夜）作为不同场景卡分别建卡。

## 3. 分段与时长规则

1. 每段 --duration 为整数 2–30 秒；建议 8–15 秒，副歌/高潮段可短而密，叙事段可长。
2. `sum(segment.duration) >= target_duration_sec`，超出部分由 merge-video 的 --duration 裁尾；禁止拉伸、循环、冻结画面或补黑凑时长。
3. 段边界对齐 song_structure 的段落边界；卡点需求写进对应段提示词（如"镜头切换踩在鼓点上"）。
4. 一段内不要塞两个以上独立剧情事件；事件多时拆段。

## 4. 参考图规格与 seed 管理

1. video-gen 参考图硬约束：每次调用 ≤10 张；JPEG/PNG/BMP/WEBP；单张 ≤20MB；边长 240–8000 像素；**不能含透明通道**。给 image-gen 下参考图提示词时明确要求不透明背景（如纯白/纯灰底）。
2. 每段 ref_images_ordered 的顺序 = 提示词中"图1、图2…"的顺序；复用元素的各段必须保持相同文件与相同顺序。建议固定顺序：风格板 → 场景图 → 角色图 → 补充帧。
3. 参考图不足10张时留余量给中间回收帧（extract-video-frame 从已通过检查的段落取人物近景/场景全景稳定帧）。
4. seed：每段 seed 记录在 plan.json；相同 seed 不保证云模型逐像素一致，一致性主要靠参考图 + 逐字卡片文本。重生成不合格段时优先改提示词与参考图，再考虑换 seed。
