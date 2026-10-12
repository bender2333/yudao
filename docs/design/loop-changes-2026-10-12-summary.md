# 2026-10-12 晚间循环结构重新规划：对照原始意图的摘要

日期：2026-10-13。性质：设计说明（只读分析的摘要），不改变任何工单或实现。完整的逐条对照由维护者本地保存。

## 结论

方向符合原始意图，但目前只落在文档里。循环核心代码没有改动。

## 符合原意的变更

- 一个事项内三个部门的 loop 同时运行，质检在交付之前做预测性探索。见 [ADR-0036](../adr/0036-concurrent-departments-and-nested-asks.md) 和 [三部门的循环结构](department-loop.md) §3，提交 91a2f6eb。
- 询问改为一次工具调用，被询问方在询问分支（子 loop）里回答，回答回到提问方；`resume_phase` 删除。见 department-loop.md §4，提交 91a2f6eb。
- 工程计划不再是正式成果，部门内部的循环不再被打断。见 [ADR-0037](../adr/0037-engineering-plan-stays-with-engineering.md)，提交 91a2f6eb。
- 只为安全或审计存在、又挡功能的门控被删除，三个部门都能用 bash。见 [ADR-0038](../adr/0038-function-first-commands-without-registration.md)，提交 768c85fa。
- 里程碑 M0「三部门的循环结构」排在 M1–M4 之前。见 program-roadmap.md 和 stage-3-plan.md，提交 2b420660。
- 设计说明按原有意图重建，提交 62e2e434，随后由 91a2f6eb 取代并归档。

## 部分偏离（已开讨论）

1. 外层交接状态机保留（department-loop.md §2）：同一时刻只有一个部门持有交接，去向由控制核心决定。中心编排和阶段状态机只是降为外层。讨论见 #488。
2. 询问链不允许回环（§4.4）：一个部门在同一条链上只出现一次，最长两层，A→B→A 被禁止。讨论见 #489。

## 实施状态

- 循环核心代码在 main@495f2184 上仍未改动，涉及 `harness/orchestrator.py`、`harness/engine.py`、`harness/models.py`、`harness/collaboration.py`、`harness/definitions/organization.json`。`orchestrator.py:995-997` 仍是「每个 run 同时只允许一个部门调用模型」，`Orchestrator.__init__` 中仍有「同一 run 只能有一次激活」。
- 唯一落地的代码是用 bash 工具替代 `run_command`：PR #487，提交 495f2184。
- 循环结构要等 M0 子工单 #469–#477 实施以后才会在运行时成立。父工单是 #466，试用工单是 #467。
