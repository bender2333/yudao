# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## State in this repo

All five labels exist in `bender2333/yudao`. `wontfix` predates this setup (GitHub's default label); the other four were created alongside it. GitHub's default `bug` / `enhancement` / `question` labels are orthogonal — they describe *what* an issue is, the five above describe *where it sits in triage*.

## 等待条件的工单

- 试用工单（每个试用里程碑一张，见 `CLAUDE.md`「工作流程」第 7 步）在里程碑达到之前标 `needs-triage`；里程碑的工单全部关闭、集成层通过、架构师按试用指南走查以后，改为 `ready-for-human` 交给用户。
- 等待前提条件的其他工单同样标 `needs-triage`：阶段收尾的手动检查（全部工作包父工单关闭以后进行）、暂缓阶段的工单、试点开始之前的自举试点工单。前提条件满足时改为 `ready-for-agent` 或 `ready-for-human`。

## 自主推进模式的流程标签

自主推进模式（见 `CLAUDE.md` 与 `AGENTS.md`）另用四个标签表示工单在执行与审查之间的位置。同一时间一个工单只带其中一个，切换时去掉原标签。

| 标签 | 含义 | 由谁加上 |
| --- | --- | --- |
| `in-progress` | 执行者正在处理 | 执行者，领到 `ready-for-agent` 工单时 |
| `needs-review` | 执行者已交付，等待审查 | 执行者，发出 `DELIVERY:` 评论后 |
| `review-passed` | 审查通过，PR 已创建，等待架构师合并 | 审查者，发出 `REVIEW: PASS` 评论后 |
| `review-failed` | 审查未通过，等待架构师写下一轮任务 | 审查者，发出 `REVIEW: FAIL` 评论后 |

架构师在 `review-failed` 后把标签改回 `ready-for-agent`；卡住的工单改为 `ready-for-human`。
