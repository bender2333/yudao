# 新增细节索引

> 2026-09-25：[各阶段需求概览](stage-requirements-overview.md)整理 Stage 3 剩余工作包到 Stage 6 的大致需求、原型依赖与待讨论的问题。

> 2026-09-19：以下是需求原文与历史实现状态索引。D18 的配置 UI、D20 的指导入口及 D21 的观测能力已有后续实现，不能按旧状态重复立项；完整能力与验收边界见 [当前验收基线](../current-baseline.md)。[总体路线图](../program-roadmap.md) 定义当前阶段，D09 的次数/超时及用量只读约束继续有效。

每项新增细节单独记录，保留原话、确认规则、待定事项和实现状态。汇总范围见 [已确认需求清单](../archive/confirmed-requirements.md)。记录中的“已确认”不表示“已实现”。

| 编号 | 细节 | 状态 |
| --- | --- | --- |
| D01 | [客户端持续输入任务与命令](web-continuous-input.md) | 产品入口为桌面客户端（[ADR-0015](../adr/0015-desktop-client-and-http-contracts.md)），客户端随 D30 实施；现有浏览器页面已实现持续输入，1440/390 宽度的追加、命令与终态新任务通过 |
| D02 | [三部门 prompt 展示与修改](department-prompts.md) | 已实现；编辑、实际采用与版本审计通过 |
| D03 | [intend.md 原文保存](intend-original.md) | 首次及逐次原文已验证；首批文本，附件未支持 |
| D04 | [产品维护 PRD.md](product-prd.md) | 同源 PRD 与持续变更已实现并验证 |
| D05 | [研发先分解与计划](engineering-plan.md) | 已实现并通过 B 回归与浏览器验证 |
| D06 | [运行中输入的处理时机](in-flight-input.md) | 已实现；工具、模型及 release 交错已验证 |
| D07 | [三部门相互专家问答](expert-ask-react.md) | C 通用请求已替换单向路径，六方向及动作接续已验证 |
| D08 | [部门完整历史与逐次上下文](department-history.md) | 已实现，自动压缩的真实运行验收中 |
| D09 | [循环次数与超时限制](execution-limits.md) | 已实现 |
| D10 | [上下文窗口、记忆与自动压缩](context-compaction.md) | 文字摘要压缩已实现，真实运行验收中，3.0B 场景 C 完成 4 次压缩并到达 release；本页的压缩做法由 D25 的工单 #26、#35 实施 |
| D11 | [三部门循环的整体定义](three-department-loop.md) | 原生三部门循环已实现；多方向专家问答与动作请求由批次 C 实现，见 D07 |
| D12 | [部门专业补全](domain-completion.md) | 部门规则与默认依据已实现 |
| D13 | [完整交付封存与恢复](delivery-archive.md) | 独立恢复及 Web 下载已验证；QA 最终接纳前复验持久封存，缺失或损坏不放行 |
| D14 | [受控删除与移动](workspace-refactoring.md) | 已实现，E 整体验证通过 |
| D15 | [有效变化与执行依据](effective-contract-changes.md) | 合同、专家请求及在途输入适用性已验证 |
| D16 | [使用 Git 管理任务内变化](git-change-management.md) | 已实现，真实 Git、同任务方向调整及桌面手机差异查看通过确定性验收 |
| D17 | [模型等待与失败重试](provider-retries.md) | H 已实现；慢响应、重试边界及桌面手机已验证，真实完整流程仍有连续连接失败 |
| D18 | [统一 Provider 管理与部门绑定](department-providers.md) | 底层目录、三部门绑定与原生循环已接入，本地多连接回归通过；配置 UI 已随 D22/D23 实现；真实跨 Provider 完整验收未完成；按每次模型请求解析由 #45 实施 |
| D19 | [按原型建设 Web 工作台](web-workspace-prototype.md) | 原型已归档、任务已规划；Provider 等配置原型预留 |
| D20 | [部门定向追加指导](department-guidance.md) | 已实现（`fe78667`、`fcb06ab`）；接收、进入模型输入与部门回应分别记录，处理时机与放行关系按[处理设计](../design/department-guidance.md)；3.0B 场景 B 的真实运行中指导完成处理 |
| D21 | [模型请求、原始数据与用量观测](request-observability.md) | 原型已确定；复用已有事件；查询 `project.attempts`、`project.usage`、`run.attempt` 已由应用层提供，桌面客户端的观测页（请求记录、用量统计、请求详情）由 #80 实现，属于 Stage 3 的里程碑 M1 |
| D22 | [启动与 Provider 热生效](startup-provider-reload.md) | Stage 2.7 已实现；无参空态启动、统一模块重载、页面 Key 与独立 .env 来源均通过本地验收，真实 Go 侧已用用户指定模型完成模型测试与三部门任务；现有实现只对新任务生效，按每次模型请求生效由 #45 实施 |
| D24 | [模型管理与部门模型选择](model-management.md) | 需求与[设计说明](../design/model-management.md)已确认，实施中：调用目标每次请求解析（#45）、Provider 配置声明一种协议（#84）、获取模型列表带凭据与连接测试（#85）已完成，其余在 #83 下，属于 Stage 3 的里程碑 M1；部门默认加项目部门设置、按请求解析调用目标、推理档位，取代 D02/D18/D22/D23 中的任务冻结与事项内 Prompt 编辑 |
| D23 | [统一 Provider 层与 OpenCode Go](provider-layer.md) | 已实现；独立模块、三协议适配、预置表、候选与准入贯通；真实 Go 覆盖 Responses 与 Chat Completions 并各自完成三部门任务，Anthropic Messages 对当前两个模型受区域与端点限制，见 [执行报告](../archive/stage-2-7-provider-report.md)；按每次模型请求解析调用目标由 #45 实施 |
| D25 | [语义系统](semantic-system.md) | 需求已确认；[设计说明](../design/semantic-system.md)已按需求记录写成（2026-09-26），未实施；路线位置 Stage 5 |
| D26 | [部门内多角色与多循环](department-roles.md) | 需求已记录，规则已由用户确认；[设计说明](../design/department-roles.md)已按 2026-09-25 与 2026-09-26 的决定修改，未实施；对产品、工程、质检、运维四个部门一起引入；路线位置 Stage 5 |
| D27 | [运维部门](operations-department.md) | 需求已确认，规则于 2026-09-28 两次补充（常设授权、修复事项自动开始、同一项目按优先级排队；故障记录与修复次数上限、部署前备份与回滚、密钥、外部内容、默认运行要求、未回答的决定），未实施；路线位置 Stage 4 |
| D28 | [元观察与规则检查部门](meta-observer.md) | 需求已记录，未实施；路线位置 Stage 6，暂时不做；调研见 [JEV 决策模型](../research/jev-decision-model.md) |
| D29 | [远程执行环境](remote-execution.md) | 需求已确认；部署形态见 [ADR-0018](../adr/0018-single-control-host-remote-execution.md)，执行环境服务的合同沿用 [ADR-0007](../adr/0007-boundaries-for-distributed-deployment.md) 的边界；工作区的建立与交付的封存经过执行环境（#110）已完成，其余未实施；路线位置 Stage 3 的 3.2C 执行环境服务（#120），属于里程碑 M3 |
| D30 | [游戏化的桌面客户端界面与界面实现](web-game-frontend.md) | 需求已记录；客户端为 Electron 桌面程序（[ADR-0015](../adr/0015-desktop-client-and-http-contracts.md)）；2026-09-28 补充系统首页、机房、托盘提醒、局域网访问（认证与加密为 TODO）与接口版本核对；原型设计以 [v9](../prototypes/v9/design.md) 结束（2026-09-30，屏幕清单、页面与决定卡片沿用 [v8](../prototypes/v8/design.md)），像素画面按 [ADR-0021](../adr/0021-client-pixel-view-follows-v9-structure.md) 实现；应用层与接口层实施中（#70），桌面客户端未开始（#71），属于 Stage 3 的里程碑 M1，各工作包的界面随所属里程碑 |
| D31 | [部门内的外包角色](outsourced-agent-roles.md) | 需求已记录，未实施；路线位置待定 |
| D32 | [与单个 agent 的对照实验](comparison-experiment.md) | 需求、三个场景与评分方法已确认，未实施；版本回归与 OpenCode 对照共用三个场景（[评测场景设计](../design/evaluation-scenarios.md)）；作为 Stage 3 的评测工作线与界面工作线并行，Stage 3 结束之前必须完成，之后每个阶段结束时重复；两边使用用户提供的、有视觉能力的同一个模型；场景 1 的 Yudao 一侧依赖 3.2D；设计已由用户逐项审阅（2026-09-30），#118 的子工单待建；评测工具与 OpenCode 基础分属于里程碑 M2，场景 2、3 的 Yudao 一侧属于 M3，场景 1 属于 M4；版本回归在每个里程碑交给用户试用之前运行 |
| D33 | [接入已有项目](existing-project-onboarding.md) | 需求已确认，未实施；路线位置 Stage 3 的 3.8（#124，子工单 #134–#139），属于里程碑 M2 |
| D34 | [浏览器与 computer use](browser-and-computer-use.md) | 需求与设计已确认（[设计说明](../design/browser-and-computer-use.md)），未实施；路线位置 Stage 3 的 3.2D，工单 #123（#147 至 #155）；质检部门的建议能力是图像输入，不满足时只提醒 |
| D35 | [自举：用 Yudao 开发 Yudao](self-hosting.md) | 需求已记录（2026-09-29、09-30）：自举是核心目标；单一写入角色是短期取舍，将来用 worktree 或跨执行主机的分支并发；质量检查作为部门工序（工程对单元测试、圈复杂度与变异测试作自我保证，质检做大的验证）；圈复杂度与变异测试的研发工具放到下一阶段，Stage 3 结束之前由用户与 Claude 手动进行一次；ADR 的边界与路线位置待确认，未实施 |

日期：2026-09-06。用户明确要求新增细节单独记录；后续每项新增或修订分别更新其文件和本索引，不只记在聊天或施工日志里。
