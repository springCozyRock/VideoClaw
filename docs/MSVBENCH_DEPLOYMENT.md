# MSVBench 服务器部署

工作目录：`/mnt/data/bts/repos/LongVideoMemory`。官方仓库 https://github.com/HITsz-TMG/MSVBench 固定于 `309318bf29594fe21a487d4fd78284faef0d777b`，源码在 `benchmarks/msvbench`。

## 当前状态

已有 **15/19 个命名指标通过真实冒烟测试**。DOVER 含 aesthetic/technical 两个分支，因此按分支统计为20项。冒烟测试使用合成或公开 MSVBench 参考图生成的测试视频，只验证部署链路；不构成正式模型成绩或完整20故事评测。

- 新增通过：`character_consistency`、`face_consistency`、`action_recognition`。
- 角色指标已产生非空跟踪裁剪和特征比较；人脸指标验证了动画分支，真实 VGG-Face 另有独立推理证据；动作指标验证了 Qwen→VideoMAE→CLIP 完整入口，另验证 GroundingDINO→SAM2裁剪→VideoMAE→CLIP 分支。
- 待完整链路验证：VQA、背景一致性、叙事一致性、相机控制；精确KaLM-v2现已下载并通过GPU嵌入推理，ShareCaptioner的942/942架构张量匹配已验证；对应大权重正在断点下载，入口和主要依赖已补齐。仅导入成功不会标为可用。
- 实时清单：`configs/msvbench/deployment.json`；测试证据：`experiments/msvbench_smoke`；日志：`.cache/msvbench`。

```bash
cd /mnt/data/bts/repos/LongVideoMemory
.venvs/msvbench/bin/python scripts/msvbench_status.py
```

## 下载与单次接续验证

后台下载包括 CLIP-FlanT5-XXL、原始 Step1X-Edit i1258/VAE、ShareCaptioner-Video、精确 KaLM-mini-instruct-v2 和 MonST3R。版本和状态在 `configs/msvbench/vqa-download.json` 与 `configs/msvbench/downloads/*.json`。网络失败最多重试5次，保留断点；磁盘不足20GiB会停止后续下载。下载完成不代表推理验证通过。

`scripts/msvbench_autoverify.py` 是本次部署的单次接续作业。它等待各指标所需下载完成，GPU4空闲显存至少30000MiB后逐项测试公开素材，最多等待24小时；不处理用户私有项目视频。每项推理最多4小时，失败保留 FAILED/日志，不自动用零分充数。状态与进程号在 `configs/msvbench/continuation.json`，进程启动收据在 `.cache/msvbench/background-processes.json`。运行错误或超过时限后需要检查日志，不能把等待状态当作完成。

```bash
# 如接续进程已退出，确认原因后可重新运行；文件锁阻止重复启动。
.venvs/msvbench/bin/python scripts/msvbench_autoverify.py
```

## 环境和本地模型复用

主环境 `.venvs/msvbench` 使用 Python3.10、只读复用服务器 PyTorch2.5.1+cu121。GroundingDINO CUDA、SAM2可选CUDA后处理和MMCV2.2.0已编译。VideoMAE 使用纯PyTorch算子，MMCV编译为CPU算子版本即可支撑当前入口，不表示所有MMCV GPU算子可用。`spatial_correlation_sampler` 未安装时 DeAOT 使用其自带PyTorch回退。

真实人脸通过独立 `.venvs/msvbench_face`（Python3.11、TensorFlow2.15.1、Keras2.15、tf-keras2.15.1、DeepFace0.0.93）运行，桥接保留 `DeepFace.verify` 原始参数和返回值。环境锁定文件为 `configs/msvbench/environment-overlay.txt`、`environment-face.txt`，共享Torch约束见 `shared-torch-constraints.txt`。

来源、路径、大小、已有哈希和验证范围在 `configs/msvbench/reused-models.json`。本项目仅创建引用，不改其他用户目录：

- AniMaker/EvalCrafter：SAM-ViT-B、R50-DeAOT-L、GroundingDINO-SwinT、BERT、VideoMAEv2、CLIP-ViT-B/32、VGG-Face、DOVER。
- AniMaker/models：DreamSim的CLIP/OpenCLIP/DINO、ensemble LoRA与DINO源码/骨干。
- `/mnt/data/lzy/remote/dense-img/Models/sam2.1_hiera_large.pt`：SAM2.1-Large，实际跟踪已验证。
- `/mnt/data/share/Qwen2.5-VL-7B-Instruct`：Step1X所需视觉语言模型，已链接；完整背景推理仍待DiT/VAE权重。

现有 MusIQ 是SPAQ，当前使用KonIQ，未互换；KaLM v1/v1.5/v2d5 未冒充精确v2。

## 正式单指标入口

```bash
bash scripts/msvbench.sh --method my_method --story 01 \
  --metric visual_attribute_consistency --videos /absolute/path/to/story01/shots
```

默认GPU4，可用 `CUDA_VISIBLE_DEVICES=5` 覆盖。视频目录只放镜头视频，使用 `01.mp4`、`02.mp4` 等连续补零编号，按字典序与提示词对齐。不能用整部故事视频替代跨镜头输入。服装、体型、角色和人脸的原生匹配规则依赖编号，输入检查会拒绝不匹配的剧本数量。

默认故事01读取官方Dataset标注。自定义内容必须显式提供适用的 `--prompt`、`--script`、`--camera`、`--characters`，不能沿用官方故事标签。提示/运镜每行对应一个镜头；脚本clip数须匹配。缺少有效标注应记缺失/NA，不生成假标签当作官方测试。

```bash
bash scripts/msvbench.sh --method my_method --story my_story \
  --metric physical_plausibility --videos /absolute/path/to/shots \
  --prompt /absolute/path/to/prompt.txt
```

输出在 `experiments/msvbench/evaluation/<method>/<story>/<metric>/`，包含 `status.json`、`protocol.json`、`run.log`、原生结果和裁判调用审计。API、加载、解析失败及非有限数值判为失败。不同输入/代码协议用新的 `--output-root` 保留旧证据。记录视频、参考图、标注、全部Python适配源码哈希与上游补丁。

## 协议差异

1. 按用户选择，`qwen3.5-omni-plus` 替代原版 `gemini-2.5-flash`。根目录 `.env` 读取凭据，禁止输出密钥。视频输入为1fps JPEG帧序列、最长边768、最多240秒/240帧；超出拒绝，不静默截断。它不等同于Gemini原生视频接口。
2. 保留上游rubric、评分公式、采样/聚合逻辑；异常使成绩无效。不可声称复现论文94.4%人类相关性，或将适配结果直接当原版排行榜总分。尚未完成完整20故事正式评测。
3. 原仓库缺少 `GroundedSAM2Tracker`、`SimpleSlidingCaptioner`、`MonST3RProcessor` 等定制接口。本次基于官方/本地源代码重建，明确不是作者未公开实现。原生计分入口仍保留。
4. 动作跟踪使用GroundingDINO-SwinT OGC和SAM2.1-Large；首帧最高置信框、box阈值0.25/text阈值0.30，传播后取所有帧mask包围框的并集并加10%边距裁剪，保留FPS。具体记录随裁剪输出。
5. ShareCaptioner沿用官方2秒滑窗、首帧描述、相邻帧变化描述、最后汇总算法。使用原生支持的eager注意力而非FlashAttention2，保持模型权重和生成参数；默认beam3/max_new_tokens2048。可用 `MSVBENCH_CAPTION_ATTN` 覆盖。视觉塔按官方CLIP-L/14-336配置初始化，最终必须由完整ShareCaptioner检查点加载所有张量，加载缺失即失败，避免下载随后被覆盖的CLIP初始化权重。官方检查点不含视觉塔的pooled-output norm，适配器将该未使用分支设为Identity；描述器只读hidden_states[-1]的patch特征，特征分支不变。
6. KaLM使用精确v2权重，默认SDPA替代FlashAttention2；可用 `MSVBENCH_KALM_ATTN` 覆盖。Step1X复用代码使用SDPA，保留i1258权重、28步、1024尺寸、cfg6、种子42，启用CPU/GPU卸载以适配A10040GB，不量化。
7. MonST3R使用官方实现，CroCo固定提交；沿用原生300步、512输入、flow权重0.01和时间平滑目标，使用官方默认batchify优化实现。帧数最多200，均匀取样；c2w轨迹导出为原生解析器需要的wxyz顺序，欧拉角返回弧度；每次运行独立缓存。SEA-RAFT官方safetensors转换为pth时仅恢复模型共享存储对应的别名，严格加载并真实GPU推理已通过，源和转换哈希有记录。
8. MusIQ官方未注明训练变体，本部署选KonIQ并记录。发布代码两处/255行为保留。PyTorch/transformers/timm版本与原仓库不同，环境和补丁已锁定。

源码来源固定在 `.cache/msvbench/msvbench-extra-source.json`：MonST3R `574cc77ad278bad582f470e5382624e01f8769a7`、CroCo `bd6f4e07d5c4f13ae5388efc052dadf142aff754`、ShareGPT4Video `7e02ee61506d2104b85d1e301a2fde4a637ffe1f`。跟踪器来自服务器EvalCrafter副本，Step1X模块来自服务器Step1X副本；各Python文件由运行哈希清单固定。上游已跟踪文件改动快照为 `configs/msvbench/upstream-path-repairs.patch`。

## 官方数据校验

数据仓库 https://huggingface.co/datasets/MrSunshy/MSVBench ，20故事、276镜头、136角色参考图、276镜头参考图，跨故事计73个角色定义。

- `Dataset.zip` SHA256：`c1aeaba551c0b6aa679046c5933123873bd52f27d9434cc93810782a9612f98f`
- `ConsistencyEvalModels.zip` SHA256：`7e13f9e4fc0a31c5dc1c251c95be5b1ad3db8bc96f8ffdd8eb3a72f4ba9effaa`

两个压缩包均已校验。一致性权重按实际 `.pth.tar` 检查点格式保存为入口要求的 `.pth` 名称。

2026-10-18 更新：相机权重已到齐，SAM2张量加载桥保留MonST3R原始bicubic/均值方差预处理；静态测试仍有SVD非收敛，完整相机指标未通过。参见最新deployment.json，不能按旧PENDING_WEIGHTS说明判断。
