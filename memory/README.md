# Unified Long-video Memory

唯一运行入口：`from memory import Memory, Policy, Segment, Reference`。
唯一 VideoClaw 接入入口：`from memory.adapters.videoclaw import install`。
生产包不包含旧插件、旧控制器入口或旧路径转发；旧实现仅保存为包外压缩归档。

## 目录与职责

```text
memory/
├── contracts/            公共模型、A²RD schema、宿主协议、策略与异常
├── world/                Temporal consistency：实际世界状态、人物形态与环境参考
├── narrative/            Narrative coherence：计划、事件依赖与实际完成证据
├── assets/               检索、内容索引、版本、依赖、选择与调用回执
├── harness/              Self-Harness：检查、归因、修复、复查与经验利用
├── runtime/              唯一执行流程：规划、生成候选、选片、提交和恢复
└── adapters/videoclaw/    宿主模型调用、会话转换、状态同步与发布
```

`runtime` 串联领域能力；领域代码不依赖宿主 SDK。宿主能力由
`contracts/host.py` 定义。`runtime/controller.py` 是 Memory 内部的逐段执行器，
不是另一套可选实现。`runtime/service.py` 拥有跨阶段修复和最终验收闭环。

## 状态与 schema

A²RD 核心：`M = {M_i} ∪ R ∪ D`，`M_i = {T_i, F_i, V_i}`。
T 是实际观察状态与事件；F 是视频解码首尾帧；V 是视频资产版本。
R 保存人物和场景参考；D 保存可追溯的优化经验。
Plan 保存预期事件和分镜，不得当作实际发生的事实。
Checks、Repairs、repair_runs 保存证据、归因假设、执行和复查结果。

`assets/store.py` 的 SQLite 是运行唯一事实源；`snapshot.json` 仅用于查看。
`assets/journal.py` 保存资产和调用回执，嵌入缓存也使用这套回执机制。
`assets/checkpoint.py` 仅提供跨故事经验库的原子 JSON 存储与 runner 锁，
没有视频生成、候选提交或控制器能力。
`assets/migration.py` 只读迁移历史数据，不执行旧流水线。

## 运行闭环

故事/宿主分镜 → 计划检查 → 初始化参考 → 验证事件前置条件 →
选择生成模式 → 检索注入 → 边界帧与视频候选 → 提取实际状态 →
世界一致性与事件检查 → 选片和版本提交 → 整段验收 → 发布导出。

失败时：证据 → 归因假设 → 修订计划/替换参考/重生成片段 →
使依赖失效 → 重新检查。旧版本保留；修复次数受 Policy.chain_repairs 限制。
修复任务在外部调用前持久化，恢复使用同一任务和调用回执。
未知的外部调用结果不能盲目重试。

事件前置条件必须由实际视频检查确认。跨镜头判断需要两侧证据，
通过需要覆盖所有输入镜头；身份检查需要候选和身份参考。未知不等于通过。
模型证据仍可能判断错误，schema 校验不构成科学准确性保证。

单段选中只报告进度；整段通过后才发布完成状态。重新选片会撤销验收，
导出必须匹配当前选片的 delivery 记录。失效版本和失效依赖不得重选。

## 使用

```python
from memory import Memory, Policy
memory = Memory(run_directory, story_id, Policy(selection="strict"))
memory.register_story(segments, references)
# 或 memory.plan(story, host, constraints, references)
records = memory.generate(host, progress=on_progress, check_cancel=check_cancel)
snapshot = memory.snapshot()
```

`generate` 是同步接口；VideoClaw 适配器使用线程执行器。
宿主改选必须调用 `handle.reselect`，不能直接修改 UI selected 后假定已同步。
`Memory.audit(host)` 只做选片审计，不重新生成媒体。

运行：`scripts/run_memory.py` 仅支持统一模式。
验证：`scripts/test_memory.py --source ... --host-root ... --report ...`。
旧插件专属测试随旧实现归档；世界状态、生成、持久化、修复和原生适配测试
使用当前实现。历史 JSON 的测试输入是迁移夹具，不是另一套运行实现。
