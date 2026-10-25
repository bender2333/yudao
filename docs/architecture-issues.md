# 架构执行问题记录 (Architecture Execution Issues)

本文档记录智能体在执行计划与工单实现过程中遇到的架构设计问题、规范冲突、未覆盖边界及阻塞事项。

## 记录规则
1. 严禁在代码中私自编写违背架构原则的临时兼容层或绕过逻辑。
2. 发现架构冲突、设计缺漏或规范矛盾时，必须在此如实登记。
3. 登记条目必须包含工单上下文、具体问题描述、受阻范围与处置建议。
4. 认为总图（`docs/architecture.html`）本身有错的，问题描述开头写「总图」与节号，由总架构师处理；设计说明与代码和总图不符的，改设计说明与代码，不在这里登记。

## 记录格式规范
`模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

---

已处理的条目归档在 [docs/archive/architecture-issues-2026-09-10.md](archive/architecture-issues-2026-09-10.md)（2026-09-26 至 2026-10-11）、[docs/archive/architecture-issues-2026-10-19.md](archive/architecture-issues-2026-10-19.md)（2026-10-01 至 2026-10-17）与 [docs/archive/architecture-issues-2026-10-25.md](archive/architecture-issues-2026-10-25.md)（2026-10-21 至 2026-10-25）。
