# 分诊标签

技能用五个分诊角色说话，这份文件把角色对应到本仓库实际使用的标签字符串。

| 技能中的角色 | 本仓库的标签 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 维护者需要评估这张工单 |
| `needs-info` | `needs-info` | 等报告人补充信息 |
| `ready-for-agent` | `ready-for-agent` | 规格完整，可以交给无人值守的 agent |
| `ready-for-human` | `ready-for-human` | 需要人来处理 |
| `wontfix` | `wontfix` | 不处理 |

技能提到某个角色时（例如「加上 AFK-ready 的分诊标签」），用表中对应的标签字符串。

五个标签在 `bender2333/yudao` 中都存在。`wontfix` 是 GitHub 的默认标签，其余四个随这套配置创建。GitHub 默认的 `bug`、`enhancement`、`question` 与这五个正交：它们说明工单**是什么**，这五个说明工单**在分诊中的位置**。

## 等待条件的工单

- 试用工单（每个试用里程碑一张，见 `CLAUDE.md`「工作流程」第 7 步）在里程碑达到之前标 `needs-triage`；里程碑的工单全部关闭、集成层通过、架构师按试用指南走查以后，改为 `ready-for-human` 交给用户。
- 等待前提条件的其他工单同样标 `needs-triage`：阶段收尾的手动检查（全部工作包父工单关闭以后进行）、暂缓阶段的工单、试点开始之前的自举试点工单。前提条件满足时改为 `ready-for-agent` 或 `ready-for-human`。

## 自主推进模式的流程标签

自主推进模式（见[派发者规则](dispatcher.md)与 `AGENTS.md`）另用三个标签表示工单在执行、审查与架构师之间的位置。同一时间一个工单只带其中一个，切换时去掉原标签。

| 标签 | 含义 | 由谁加上 |
| --- | --- | --- |
| `in-progress` | 执行者正在处理 | 执行者，领到 `ready-for-agent` 工单时 |
| `needs-review` | CI 已通过，交付说明已写在 PR 上，等待审查 | 执行者，在 PR 上发出 `DELIVERY:` 评论后 |
| `needs-architect` | 等架构师处理：执行者交回、审查者请架构师处理、要求修改达到上限、执行或审查异常结束、依据的设计说明在放出以后有改动 | 执行者，在工单上发出 `ARCHITECT:` 评论后；其余由派发者 |

审查的结论是 PR 审查的状态（批准或要求修改），不用标签表示。要求修改后，派发者把标签改回 `ready-for-agent`；卡住的工单改为 `needs-architect`，派发者启动架构师。架构师处理以后改为 `ready-for-agent`、`needs-review` 或 `ready-for-human`，`ready-for-human` 表示架构师已经看过、要用户决定。`needs-architect` 与等前提条件的 `needs-triage` 是两回事：架构师自己退回工单、改写正文期间用 `needs-triage`，不会启动被唤醒的架构师。

另有一个标记 `touches-core`：工单的「只改」包含核心文件（范围见[运行配置](autopilot-runtime.md)第 7 节），由架构师放出工单时加上；派发者按参数表限制同时进行的张数。它与上面的标签同时存在，表示的是「不同时进行」，不表示先后；先后用工单依赖表示。

2026-10-14 以前用过的 `review-passed`、`review-failed` 不再使用。仓库里保留这两个标签，已有工单上的记录供评测统计使用。
