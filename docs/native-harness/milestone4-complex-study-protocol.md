# Milestone 4 - 复杂任务成对实验协议（DRAFT）

> 状态：**DRAFT / BLOCKED，不得运行正式样本**
> 日期：2026-07-10
> 研究代码基线：`35828e9` 或更新 commit
> 历史校准：`milestone3-study-protocol.md` 及其 results

## 1. 研究问题

在固定总预算和相同运行条件下，完整 multi 方案：

```text
UNDERSTAND -> PLAN_EXECUTE -> VERIFY
```

是否比 solo 在复杂软件任务上取得可重复、可归因到“完整 treatment bundle”的质量收益？

本实验不声称当前 multi 是真实并行部门，也不把潜在收益归因到某一个阶段。只有完整方案胜出后，才在新 holdout 上增加 `solo + explicit review`，区分角色结构与单纯增加推理计算。

## 2. 可证伪结论

正式批次只允许得出以下之一：

- **支持**：multi 达到第 9 节全部质量与工程门槛。
- **不支持**：multi 平均质量差 `<= 0`，或只赢 `<= 4/8` 个任务。
- **证据不足**：介于上述区间；只能按预注册规则补样，不能改 prompt 或题目。

multi 获胜不是项目完成条件。

## 3. 正式运行前置门

以下全部满足后，状态才能从 DRAFT 改为 FROZEN：

- [x] tool allowlist 在执行层强制。
- [x] calls/token 按每个 loop 增量统计，multi 不重复累计。
- [x] `bash` 返回退出码并容错解码。
- [x] PLAN 必须产生本轮新建或修改的非空交付物。
- [x] 空 reason 与失败 consult 不得形成成功证据。
- [x] 已存在的 run 目录会 fail-fast，不复用 workspace。
- [ ] agent 进程不能读取 workspace 外路径、provider key 或 hidden oracle。
- [ ] 统一硬预算已实现并测试：成功 calls、总 tokens、进程墙钟。
- [ ] 8 个 fixture、oracle、评分权重与 SHA-256 已提交。
- [ ] provider 记录可获得的模型版本、temperature、seed/system fingerprint。
- [ ] live batch 的模型额度由 `NEXT.md` 明确授权。

当前机器没有 Docker/Podman，可见的 WSL 未安装。因此“oracle 对 agent 不可见”仍是基础设施 BLOCK，不能用 prompt 自律替代。

## 4. Treatment

### S - solo

- 入口：`python -m harness.run_solo`
- 单一 agent loop，自主调查、实现、验证。
- 与 M 使用相同任务文本、fixture、工具能力和总硬预算。

### M - multi

- 入口：`python -m harness.run_multi`
- 固定三个串行角色与当前 routing。
- 正式批次中不得更改 system prompt、terminal gate、consult 或 convergence 逻辑。

本轮比较完整 S 与完整 M，不引入第三臂。

## 5. 控制变量与预算

每个 run 固定：

| 项目 | 值 |
|---|---|
| provider / model | 冻结时填写 |
| 成功模型调用上限 | 60 |
| prompt + completion token 上限 | 200,000 |
| 进程墙钟上限 | 300 秒 |
| fixture | 每次从只读源复制到全新 workspace |
| 网络 | agent 工具禁用 |
| 顺序 | 每个 `(task, repetition)` block 内随机 S/M，记录 seed |

`max_steps` 不是总预算。S/M 必须共享同一个 run 级 `max_calls`、token 和墙钟上限；multi 不得按阶段重置。

## 6. 复杂任务集

正式题使用 8 个从未用于 prompt/门禁调优的 fixture，每类 2 个：

1. **跨模块根因 bug**：共享 helper 至少 3 个调用方，局部补丁会漏 sibling path。
2. **契约型功能**：API、持久化、调用端至少跨 3 层。
3. **状态可靠性**：幂等、重试、并发或部分失败恢复。
4. **信任边界**：输入校验、权限或防数据损失。

每题必须满足：

- 8-30 个相关文件，需要修改 2-6 个文件。
- 专家参考补丁约 30-150 LOC。
- 有可见测试，也有隐藏回归/负路径 oracle。
- 无真实需求歧义、联网依赖或人工交互。
- 超时/无产物可被确定性判定。

旧 T1-T4、G1 只作 development smoke，不进入正式样本。

## 7. 样本与运行顺序

```text
8 tasks x 3 repetitions x 2 modes = 48 runs
```

- task 是统计单位；每题先取 3 次中位数。
- 同一 block 的 S/M 紧邻运行，顺序由冻结 seed 随机决定。
- 运行目录已存在即失败，禁止复用 workspace。
- 超时、异常、缺 summary 全部按 intention-to-treat 纳入，记 0 分并保留原始失败原因。
- pilot 不计入正式样本；pilot 题不得进入正式题库。

## 8. 指标

### 主指标

hidden oracle 的确定性质量分，范围 `0-100`。评分脚本在 agent loop 外运行。

### 副指标

- completion rate
- critical failure
- false-pass / missed-win
- 真实进程墙钟
- 成功模型调用数
- prompt / completion / reasoning tokens
- retry 与 tool invocation 数
- 每题和跨题方差

reasoning tokens 若已包含在 completion tokens 中，不重复计入硬预算。

## 9. 预注册门槛

判定“支持”必须同时满足：

- 8 题中 multi 至少赢 7 题。
- task-level 平均质量提升至少 `+5` 分。
- multi completion 不得比 solo 少超过 `1/24` run。
- multi critical failure 不增加。
- median token ratio `<= 2.0x`。
- median wall-clock ratio `<= 2.0x`。

8 题赢 7 题的单侧精确 sign test 为 `p = 9/256 ~= 0.035`。若质量达标但成本门不达标，只能结论为“有效但不经济”。

`5-6/8` 或平均提升 `0-5` 为证据不足。仅允许把每题重复从 3 次补到 5 次；不得边看结果边修改 treatment。

## 10. 执行流程

1. 提交 fixture、oracle、评分权重、预算实现和本协议。
2. 记录所有输入文件 SHA-256，状态改为 FROZEN。
3. 用独立 pilot 题验证 wiring、隔离、预算中止和评分。
4. pilot 通过后再次 commit，随后一次性运行 48 个正式样本。
5. 循环外运行 oracle，生成逐 run 明细和 task-level 聚合。
6. 原样报告全部失败、超时和缺失数据。
7. 输出“支持 / 不支持 / 证据不足”，不追加事后门槛。

## 11. 停止与作废

任一情况发生，整批停止并标记 INVALID：

- agent 可读取 oracle、provider key 或 workspace 外文件。
- workspace 被复用。
- calls/token/墙钟任一预算未执行。
- 正式运行开始后修改题目、prompt、router、oracle 或评分。
- summary 与原始 events 计数不一致。
- 运行顺序或失败样本被选择性删除。

## 12. 历史成本勘误

旧报告的 multi calls/token 使用“累计值再逐阶段求和”，不能继续作为成本证据。按每个 run 最后阶段的共享累计值回算：

| 批次 | 原 calls / prompt 倍数 | 纠正后 calls / prompt 倍数 |
|---|---:|---:|
| m3b | 2.8x / 3.4x | 1.8x / 2.3x |
| m3g | 6.9x / 17.2x | 4.4x / 12.8x |
| gates | 6.2x / 10.5x | 4.7x / 8.7x |

旧 `duration_ms` 只累计 LLM 请求耗时，不是真实进程墙钟，无法从现有 summary 完整恢复。质量/oracle 原始结果保留，成本结论以本勘误为准。
