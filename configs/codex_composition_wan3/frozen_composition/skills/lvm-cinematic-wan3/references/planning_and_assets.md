# 规划文件、一致性资产与生成调用

目录
1. plan.json schema
2. assets.json schema（一致性资产清单）
3. 用户参考资料的转化规则
4. video-gen 调用模板与生成顺序
5. 续接与一致性挂接策略
6. seed、幂等与状态记录

## 1. plan.json schema

写入 get-output-dir 返回的 OUT 根目录，随生成进度持续更新（状态与实测字段回填）：

```json
{
  "task": "用户文字需求的整理版（一段话）",
  "total_duration_sec": 0,
  "av_constraints": {"画幅/风格/台词/BGM 等音画约束逐项列出": "..."},
  "assumptions": ["输入缺失时自主补全的决定，逐条记录"],
  "story": "完整剧情梗概：起因-展开-高潮-收尾，含旁白/台词要点",
  "style_block": "全局风格文本块（逐字复用于每段提示词）",
  "audio_block": "全局音频文本块：BGM 描述 + 每个说话角色的音色描述",
  "segments": [
    {
      "id": "seg_01",
      "plot": "本段剧情/镜头看点",
      "shot_mode": "single | multi",
      "camera": "景别+运镜+机位设计",
      "duration_sec": 10,
      "scene": "场景 id 或描述",
      "subjects": ["出场主体 id 列表"],
      "consistent_assets": ["assets.json 中的资产 id"],
      "reference_images": [
        {"path": "绝对路径", "role": "图1=角色A定妆图 / 图2=场景主参考 / 图3=上段尾帧", "source": "image-gen | user | extract"}
      ],
      "prompt": "完整最终提示词（含风格块、音频块、台词）",
      "seed": 20261016,
      "gen_order": 1,
      "status": "planned | submitted | done | qa_pass | qa_fail | regenerated | halted_unknown",
      "output_path": "实际片段路径",
      "actual_duration_sec": 0,
      "qa_notes": "段级检查结论与问题",
      "attempts": [{"seed": 0, "change": "首次 | 改提示词 | 换参考帧", "result": "pass | fail | unknown"}]
    }
  ]
}
```

要点：段时长为整数 2–30；Σduration ≥ total_duration_sec（留 5–10% 裁尾余量）；
每个跨段复现的主体/场景必须挂同一 consistent_assets id。

## 2. assets.json schema（一致性资产清单）

```json
{
  "characters": [
    {"id": "char_A", "name": "角色A", "appearance_text": "固定外貌描述（逐字进入相关段提示词）",
     "voice_text": "音色描述（进音频块）", "ref_images": [{"path": "...", "seed": 0, "desc": "白底三视图"}],
     "origin": "user | generated"}
  ],
  "scenes": [
    {"id": "scene_1", "desc_text": "固定场景描述", "ref_images": [{"path": "...", "seed": 0}], "origin": "user | generated"}
  ],
  "props": [
    {"id": "prop_1", "desc_text": "关键物体描述", "ref_images": [{"path": "..."}]}
  ],
  "style_block": "与 plan.json 相同的全局风格文本块",
  "audio_block": "与 plan.json 相同的全局音频文本块",
  "user_assets": [
    {"original_path": "...", "type": "image | audio | video | text",
     "understanding": "vision/audio-understanding 的理解结论摘要",
     "derivatives": [{"path": "...", "usage": "参考图 | 文本块来源"}]}
  ]
}
```

资产制备顺序：先角色/场景/物体参考图（image-gen，生成后 vision-understanding 核对再入库），
再固化 style_block 与 audio_block，最后才进入片段生成。
角色参考图推荐白底三视图或多角度定妆图；场景参考图取能代表该场景全貌的单帧构图。

## 3. 用户参考资料的转化规则

适配器只接受文本与图片，用户资料必须转化后使用，原件与衍生物都登记进 assets.json：

- 图片：get-image-metadata 校验（JPEG/PNG/BMP/WEBP、≤20MB、边长 240–8000、无透明通道）。合规 → 直接登记为参考图；含透明通道或规格不符 → image-gen 以原图为 `--reference-image` 改绘合规版本；人物图优先衍生三视图供多角度段使用。
- 音频：audio-understanding 转写台词、提炼音色与 BGM 描述 → 写入对应 character.voice_text 与 audio_block。音频文件本身不进入任何生成调用。
- 视频：get-video-metadata 读元数据；extract-video-frame 抽代表帧（人物出场帧、场景全景帧）→ 帧图合规则登记为参考图，并用 vision-understanding 补充文字描述。
- 文本：整理为 story/风格约束输入；与用户其它资料冲突时以用户明确指令为准，冲突记录进 assumptions。

用户明确指定的资料必须实际用上（作为参考图或转化为文本块），不得忽略；
确实无法转化时（如超长视频仅取帧）在 assumptions 中说明取舍。

## 4. video-gen 调用模板与生成顺序

```bash
/mnt/data/bts/repos/LongVideoMemory/.venvs/codex_composition/bin/python \
  /mnt/data/bts/repos/LongVideoMemory/baselines/codex/composition/tools.py video \
  --prompt "<plan.json 中该段完整 prompt>" \
  --duration <整数2-30> --seed <记录的seed> \
  --reference-image <图1绝对路径> [--reference-image <图2绝对路径> ...] \
  --output clips/seg_01.mp4 --timeout 1800
```

- `--output` 是相对 OUT 的路径（脚本约定）；`--reference-image` 必须绝对路径，顺序=提示词中图1、图2…的顺序，单段 ≤10 张。
- 默认阻塞轮询直至下载校验完成；预计超长时用 `--background` 提交，随后重发同一命令（去掉该参数）继续取回；期间不要改变任何参数。
- 生成顺序 = plan.json 的 gen_order：按剧情顺序串行，先制备资产、先生成被续接依赖的段；不要跳跃生成需要尾帧续接的后续段。
- 每段完成：回填 output_path/actual_duration_sec/status，用 get-video-metadata 核对实际时长，extract-video-frame 取尾帧与关键帧备用。

## 5. 续接与一致性挂接策略

- 一镜到底跨段：下一段参考图 = [上一段尾帧] + [本镜头涉及的角色/场景主参考图]，提示词用「Single shot」并写明「延续图N画面，机位/运动状态不变继续…」。只用尾帧不挂主参考图是禁止的坏实践。
- 同场景不同机位：挂场景主参考图，提示词写新机位与运镜。
- 同角色换场景：挂角色定妆图 + 新场景参考图。
- 多镜头段（Shot cut）内部各镜头共用该段参考图集合；一致性要求高的镜头拆成独立单镜头段。
- 每段提示词末尾逐字粘贴 style_block 与 audio_block，不做同义改写。

## 6. seed、幂等与状态记录

- 每段首次生成选定 seed 并记录；重生成时的策略见 qa_and_delivery.md（改 prompt 优先，换 seed 次之）。相同 seed 不保证云端逐像素一致，seed 只用于可复现记录。
- 工具按「任务名+提示词+参数+参考内容」哈希复用已成功结果：恢复中断时原样重发同一命令即可取回，不会重复计费。
- 任何一次提交出现 SUBMISSION_UNKNOWN/超时不明：把该段 status 置 halted_unknown，记录完整命令与时间，停止该段后续提交，先检查其它段并在 qa_report.md 中说明。
