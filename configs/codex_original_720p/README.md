# 五样例实验配置

manifest.json 是实验清单，evaluation_protocol.json 保存指标协议，evaluation_units.json 定义评测单元。原始输入与分镜在 experiments/codex_original_720p/inputs/，路径均相对于项目根目录。

implementation_manifest.json 是原运行的源码快照，保留迁移前路径与哈希。当前代码哈希、真实迁移映射和验证结果见 docs/relocation_manifest.json。运行脚本通过 baselines/codex/workspace_paths.py 读取新目录中的配置。
