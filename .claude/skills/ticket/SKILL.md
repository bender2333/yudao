---
name: ticket
description: 建立或改写 Yudao 的 GitHub 工单（阶段、父、子、清理单、试用工单）：先读工单规范，按类型选模板，再用 gh 发布。
---

# 建立工单

规范正本是 [工单规范](../../../docs/agents/ticket-spec.md)；`gh` 命令在 [issue-tracker.md](../../../docs/agents/issue-tracker.md)；状态与种类标签在[工作方式](../../../docs/agents/workflow.md)第 4 节。

## 1. 定类型与归属

读工单规范「层级与归属」，按下表走。

| 类型 | 做法 |
| --- | --- |
| 阶段工单 | 总架构师在用户在场的会话里建，模板与进入条件见[验收证据规则](../../../docs/agents/acceptance-evidence.md)第 6 节；其他架构师停下来告诉用户 |
| 父工单 | 提醒用户输入 `/to-parents` |
| 子工单 | 提醒用户输入 `/to-children <父工单>` |
| 试用中发现的缺陷 | 提醒用户输入 `/trial-intake` |
| 清理单、试用工单 | 继续第 2 步 |
| 改写已有工单 | 先 `gh issue view <编号> --comments` 读完正文与评论，再继续第 2 步 |

完成：说得出这张工单的类型、上级工单和所属里程碑（清理单与「待排期与阶段总览」里的工单写「无」）。

## 2. 写正文

读工单规范「一张子工单怎么写」，用[子工单模板](../to-children/SKILL.md)的栏目写正文，用 `--body-file` 传给 `gh issue create`。试用工单正文写薄片回答的问题和怎么试用。

完成：规范里「一张子工单怎么写」的每一项都对照过，模板的每一栏有内容。

## 3. 发布

`gh issue create` 建工单，挂到上级工单与里程碑，设阻塞依赖（命令在 issue-tracker.md「阻塞」一条），加一个状态标签；阶段工单、试用工单、父工单、清理单、缺陷再加种类标签（`stage`、`trial`、`parent`、`cleanup`、`bug`）。

完成：`gh issue view <编号>` 读回来，标题、标签、里程碑、依赖都对；把编号列给用户。
