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

自主推进模式（见[派发者规则](dispatcher.md)与 `AGENTS.md`）另用两个标签表示工单在执行与审查之间的位置。同一时间一个工单只带其中一个，切换时去掉原标签。

| 标签 | 含义 | 由谁加上 |
| --- | --- | --- |
| `in-progress` | 执行者正在处理 | 执行者，领到 `ready-for-agent` 工单时 |
| `needs-review` | CI 已通过，交付说明已写在 PR 上，等待审查 | 执行者，在 PR 上发出 `DELIVERY:` 评论后 |

审查的结论是 PR 审查的状态（批准或要求修改），不用标签表示。要求修改后，派发者把标签改回 `ready-for-agent`；卡住的工单改为 `ready-for-human`。

2026-10-14 以前用过的 `review-passed`、`review-failed` 不再使用。仓库里保留这两个标签，已有工单上的记录供评测统计使用。
