# 架构执行问题记录 (Architecture Execution Issues)

本文档记录智能体在执行计划与工单实现过程中遇到的架构设计问题、规范冲突、未覆盖边界及阻塞事项。

## 记录规则
1. 严禁在代码中私自编写违背架构原则的临时兼容层或绕过逻辑。
2. 发现架构冲突、设计缺漏或规范矛盾时，必须在此如实登记。
3. 登记条目必须包含工单上下文、具体问题描述、受阻范围与处置建议。

## 记录格式规范
`模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

---

已处理的条目归档在 [docs/archive/architecture-issues-2026-09-10.md](archive/architecture-issues-2026-09-10.md)（2026-09-26 至 2026-10-11）与 [docs/archive/architecture-issues-2026-10-19.md](archive/architecture-issues-2026-10-19.md)（2026-10-01 至 2026-10-17）。
9router/ag/gemini-3.8-flash-high / 2026-10-21 03:35 / 工单 #633 / harness/tests/test_department_providers.py 与 harness/tests/test_smoke_guidance_audit.py 借用协作请求改用询问后，因 harness/smoke.py:891 assembly.department_history(before, event.department) 缺少 session_id=event.session_id 参数，导致分支内部的输入未能重建进历史，_model_input_audit 报错 input history differs from this department's recorded outputs。工单只改清单限制在 11 个测试文件，无法修改 harness/smoke.py。 / 建议将 harness/smoke.py 加入「只改」清单（行 891 补齐 session_id=event.session_id），或由架构师处理后继续。
