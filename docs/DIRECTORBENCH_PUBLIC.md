# DirectorBench 公开代码与数据统一入口

服务器项目根目录：`/mnt/data/bts/repos/LongVideoMemory`。

## 固定版本与目录

本次核对的官方 HEAD 为 `63174ef2a00df2ae839d74a9af7f91883c790f8b`，来源 https://github.com/jiaminchen-1031/DirectorBench 。代码和随库公开数据都来自这个提交。

| 路径 | 用途 |
|---|---|
| `benchmarks/directorbench_public/` | 独立、固定提交的官方干净源码；跟踪文件未修改 |
| `datasets/directorbench_public/raw/` | 原始公开数据逐字节快照，保留原文件格式 |
| `datasets/directorbench_public/normalized/` | 严格一行一个对象的 JSONL；任务内容保持原样，画像别名转换另有记录 |
| `datasets/directorbench_public/index.jsonl` | 全部变体的唯一键、原始记录来源、注释缺口、输入文件哈希 |
| `datasets/directorbench_public/cases/<split>/<variant_id>/` | 每任务的元数据、完整要求文本、已公开剧本片段、已公开分镜 |
| `configs/directorbench_public/` | 协议、指标注册表、数据清单、离线审计、环境快照、视频绑定模板 |
| `.venvs/directorbench_public/` | 私有解释器入口；只读复用既有 DirectorBench / VBench 环境依赖 |
| `scripts/directorbench_public.sh` | 新公开数据的统一命令入口 |
| `scripts/directorbench_public_provider.py` | 独立 Qwen 传输适配；官方评测代码不内嵌项目适配 |
| `experiments/directorbench_public/evaluation/` | 今后新协议的正式运行产物；本次没有生成视频或付费评测 |

历史源码 `benchmarks/directorbench/` 保留原位置和本地修改，原实验仍使用它。其本地差异已留存 `configs/directorbench_public/legacy-local-changes.patch`。`codex_original_720p`、`codex_composition_wan3_720p`、`videoclaw_wan27_preview_eval` 等历史实验和原始结果没有迁移、覆盖或重新评分。

## 实际公开范围

- `original`: 75 条原始任务。
- `cross_lingual`: 134 条跨语言内容变体。
- `multilingual`: 219 条多语言指令变体。
- 合计 428 条变体；7 个官方用户画像；每个被评方法可形成 2,996 个评价组合。
- 这些是创作任务元数据，不是 428 个现成视频。不会自动将旧实验的同名视频绑定到新版本。
- 论文中的 80 条任务与本提交的 75 条原始任务不相同；本入口以实际公开文件为准，不补齐不存在的 5 条。

## 对齐规则

1. **唯一身份**：使用 `<split>/<variant_id>`，例如 `original/DB_001`、`cross_lingual/DB_001_content_en`、`multilingual/DB_001_instr_en`。`meta_id` 在语言变体间重复，不能独立用来关联视频。
2. **严格解析**：上游 `.jsonl` 实际含多行对象和对象间逗号。解析器仅接受这些明确格式，不像上游宽松读取器那样跳过无法解析的字符。原始文件不重写。
3. **用户画像**：保留全部 7 个官方画像、原权重和硬约束；将画像 4 的 `lip_sync: "must"` 显式映射成模型可识别的 `wants_lip_sync: true`，保留原字段与转换记录。
4. **类别**：公开中文 `video_type` 原样保留，索引另提供英文 `canonical_video_type`。不更改公开任务语义。
5. **不补造标注**：公开数据中 144 条变体缺少目标时长，74 条的剧本镜头时长不完整，226 条已知剧本时长和目标不一致，102 条文字与视觉镜头 ID 集不一致。均在索引中逐条标记；这些警告可重叠。不能将一个 18 秒的公开剧本片段扩充为声称完整的 67 秒标准分镜。
6. **参考模式**：默认 `reference-free`，让原生评测器从实际视频重建叙事，完整任务要求仍放入 `user_prompt`。明确指定 `--reference-mode published-reference` 才把公开片段与分镜传给原生 `script_text/storyboard`；这时须保留其不完整标注警告。
7. **生成与评测分开**：`evaluation_prompt.txt` 是“原始 main_instruction + 全部公开目标规格”的确定性评价上下文，不冒称作者提供的个性化生成 prompt；本版本未提供的 LLM 个性化生成提示不另行合成。绑定视频时另记真实生成画像与生成 prompt。

## 指标与协议口径

`checkpoint_registry.json` 从该提交实际的 `CHECKPOINTS` 导出：9 个注册子指标、40 个检查点。运行代码还可能输出额外的过程/汇总指标，包括 reference 模式才有的 fidelity；它们在同一个注册表文件内另列，不强行当成 40 检查点的一部分。README、论文和实际运行输出的指标数量不能混用。

项目裁判继续使用用户指定的 `qwen3.5-omni-plus`，通过独立的 SSE 传输适配保留原生提示词、解析器和评分公式；这属于裁判替换后的协议变体。凭据只读取根目录 `.env`，不写入清单或日志。

延续既有用户偏好，BGM consistency 及四个检查点标为 `SKIPPED_BY_USER`，默认运行不评价该指标；原始画像中的 BGM 要求和权重仍保留，不悄悄修改。注册表保留完整 40 检查点，并记录项目排除项。音频分离默认关闭，混合音轨相关限制须保留。

聚合使用公开代码原生实现；其中稳定性与视觉共享 `visual_camera` 权重，这是代码行为，和论文对稳定性单列的文字解释不能视为完全一致。本次未修改公式来凑齐论文。

## 操作

```bash
cd /mnt/data/bts/repos/LongVideoMemory
bash scripts/directorbench_public.sh status
bash scripts/directorbench_public.sh list
bash scripts/directorbench_public.sh audit
```

`audit` 校验官方提交、原始文件哈希、规范化数据与各案例产物，并检查全部 2,996 组输入进入原生 `GraphState` 时的画像、权重与任务关联。无外部 API 调用。

指定案例预检（没有绑定视频时显示 `WAITING_FOR_VIDEO`）：

```bash
bash scripts/directorbench_public.sh plan --case original/DB_001 --profile 4
```

明确关联生成视频后再运行。视频仅通过这一步人工指定；绑定同时区分 `--method`，不同基线不会覆盖同一个任务的视频，不能仅凭文件名自动匹配语言变体：

```bash
bash scripts/directorbench_public.sh bind --method my_baseline --case original/DB_001 \
  --video /absolute/path/to/generated.mp4 \
  --generation-profile 4 --generation-prompt /absolute/path/to/actual_generation_prompt.txt

# 默认仍然只做预检，不收费
bash scripts/directorbench_public.sh run --method my_baseline --case original/DB_001 --profile 4

# 只有明确要求实际评分时才执行；会将视频采样帧/相关文本发送给 Qwen
bash scripts/directorbench_public.sh run --method my_baseline --case original/DB_001 --profile 4 --execute
```

结果按方法名、任务唯一键、评价画像和输入/协议/运行环境摘要分别存储；已有记录不会因重跑被覆盖。原生报告、工具轨迹、API 请求摘要与响应、失败信息一起保留。工具退化或标注缺口使结果明确标为 `COMPLETED_WITH_LIMITATIONS`；模型/API/图执行失败标为 FAILED，不能把回退分数当成完整有效评测。

## 运行依赖边界

本次完成代码、数据和输入接口对齐；没有为了通过离线检查而伪造模型输出。MobileViCLIP 的官方权重等可选工具资产是否就绪，见 `runtime_preflight.json`。缺失时无法声称完成全部原生工具协议。已经过验证的本地 Whisper 模型可复用。正式执行仍应检查工具轨迹，不应将“代码可导入”当成所有指标模型已通过推理验证。

## 测试

```bash
.venvs/directorbench_public/bin/python -m unittest discover -s tests -p test_directorbench_public.py -v
```

离线覆盖格式容错边界、原始文件与案例哈希、语言变体身份、画像别名、部分标注保留、原生注册表、原生图编译及默认无 API 的预检路径。

## MobileViCLIP 部署更新（2026-10-18）

官方视频权重与 MobileCLIP-S2 基础权重已补齐，已通过真实推理与全部参数匹配验证。正式入口自动组合加载，详见 [MobileViCLIP 配置说明](MOBILEVICLIP_SETUP.md)。历史结果未重新评分。
