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

## 自主推进模式的流程标签

自主推进模式（见 `CLAUDE.md` 与 `AGENTS.md`）另用四个标签表示工单在执行与审查之间的位置。同一时间一个工单只带其中一个，切换时去掉原标签。

| 标签 | 含义 | 由谁加上 |
| --- | --- | --- |
| `in-progress` | 执行者正在处理 | 执行者，领到 `ready-for-agent` 工单时 |
| `needs-review` | 执行者已交付，等待审查 | 执行者，发出 `DELIVERY:` 评论后 |
| `review-passed` | 审查通过，PR 已创建，等待架构师合并 | 审查者，发出 `REVIEW: PASS` 评论后 |
| `review-failed` | 审查未通过，等待架构师写下一轮任务 | 审查者，发出 `REVIEW: FAIL` 评论后 |

架构师在 `review-failed` 后把标签改回 `ready-for-agent`；卡住的工单改为 `ready-for-human`。
