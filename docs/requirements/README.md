# 新增细节索引

> 2026-09-19：以下是需求原文与历史实现状态索引。D18 的配置 UI、D20 的指导入口及 D21 的观测能力已有后续实现，不能按旧状态重复立项；完整能力与验收边界见 [当前验收基线](../current-baseline.md)。[总体路线图](../program-roadmap.md) 定义当前阶段，D09 的次数/超时及用量只读约束继续有效。

每项新增细节单独记录，保留原话、确认规则、待定事项和实现状态。汇总范围见 [已确认需求清单](../confirmed-requirements.md)。记录中的“已确认”不表示“已实现”。

| 编号 | 细节 | 状态 |
| --- | --- | --- |
| D01 | [Web 持续输入任务与命令](web-continuous-input.md) | 已实现；桌面/手机追加、命令与终态新任务通过 |
| D02 | [三部门 prompt 展示与修改](department-prompts.md) | 已实现；编辑、实际采用与版本审计通过 |
| D03 | [intend.md 原文保存](intend-original.md) | 首次及逐次原文已验证；首批文本，附件未支持 |
| D04 | [产品维护 PRD.md](product-prd.md) | 同源 PRD 与持续变更已实现并验证 |
| D05 | [研发先分解与计划](engineering-plan.md) | 已实现并通过 B 回归与浏览器验证 |
| D06 | [运行中输入的处理时机](in-flight-input.md) | 已实现；工具、模型及 release 交错已验证 |
| D07 | [三部门相互专家问答](expert-ask-react.md) | C 通用请求已替换单向路径，六方向及动作接续已验证 |
| D08 | [部门完整历史与逐次上下文](department-history.md) | 已实现，自动压缩的真实运行验收中 |
| D09 | [循环次数与超时限制](execution-limits.md) | 已实现 |
| D10 | [上下文窗口、记忆与自动压缩](context-compaction.md) | 已实现，真实运行验收中 |
| D11 | [三部门循环的整体定义](three-department-loop.md) | 已确认，分工作包落实 |
| D12 | [部门专业补全](domain-completion.md) | 部门规则与默认依据已实现 |
| D13 | [完整交付封存与恢复](delivery-archive.md) | 独立恢复及 Web 下载已验证；QA 最终接纳前复验持久封存，缺失或损坏不放行 |
| D14 | [受控删除与移动](workspace-refactoring.md) | 已实现，E 整体验证通过 |
| D15 | [有效变化与执行依据](effective-contract-changes.md) | 合同、专家请求及在途输入适用性已验证 |
| D16 | [使用 Git 管理任务内变化](git-change-management.md) | 已实现，真实 Git、同任务方向调整及桌面手机差异查看通过确定性验收 |
| D17 | [模型等待与失败重试](provider-retries.md) | H 已实现；慢响应、重试边界及桌面手机已验证，真实完整流程仍有连续连接失败 |
| D18 | [统一 Provider 管理与部门绑定](department-providers.md) | 底层及原生循环已接入；本地多连接验证，真实跨 Provider 最终 QA 待验收，配置 UI 待原型 |
| D19 | [按原型建设 Web 工作台](web-workspace-prototype.md) | 原型已归档、任务已规划；Provider 等配置原型预留 |
| D20 | [部门定向追加指导](department-guidance.md) | 用户场景已确认；处理时机、原文范围及放行关系待设计，尚未实现 |
| D21 | [模型请求、原始数据与用量观测](request-observability.md) | 原型已确定；复用已有事件，完整采集及新查询/页面待实现 |
| D22 | [启动与 Provider 热生效](startup-provider-reload.md) | 已实现；无参空态启动、统一模块重载、仅新任务生效、页面 Key 与独立 .env 来源均通过本地验收，真实 Go 侧已用用户指定模型完成模型测试与三部门任务 |
| D23 | [统一 Provider 层与 OpenCode Go](provider-layer.md) | 已实现；独立模块、三协议适配、预置表、候选与准入贯通；真实 Go 覆盖 Responses 与 Chat Completions 并各自完成三部门任务，Anthropic Messages 对当前两个模型受区域与端点限制，见 [执行报告](../stage-2-7-provider-report.md) |

日期：2026-09-06。用户明确要求新增细节单独记录；后续每项新增或修订分别更新其文件和本索引，不只记在聊天或施工日志里。
