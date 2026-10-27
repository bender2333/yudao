# 新增细节索引

> 2026-09-19：以下是需求原文与历史实现状态索引。D18 的配置 UI、D20 的指导入口及 D21 的观测能力已有后续实现，不能按旧状态重复立项；完整能力与验收边界见 [当前验收基线](../current-baseline.md)。[总体路线图](../program-roadmap.md) 定义当前阶段，D09 的次数/超时及用量只读约束继续有效。

> 2026-10-07：[D38 系统意图与基础规则](system-intent.md)是 Yudao 的总体意图，其他需求记录与它冲突时以它为准。

每项新增细节单独记录，保留原话、确认规则、待定事项和实现状态。汇总范围见 [已确认需求清单](../archive/confirmed-requirements.md)。记录中的“已确认”不表示“已实现”。

| 编号 | 细节 | 状态 |
| --- | --- | --- |
| D01 | [Web 持续输入任务与命令](web-continuous-input.md) | 产品入口为 Yudao 服务提供的网页界面（[ADR-0032](../adr/0032-interface-served-as-web-pages.md)），界面随 D30 实施；现有浏览器页面已实现持续输入，1440/390 宽度的追加、命令与终态新任务通过 |
| D02 | [三部门 prompt 展示与修改](department-prompts.md) | 已实现；编辑、实际采用与版本审计通过 |
| D03 | [intend.md 原文保存](intend-original.md) | 首次及逐次原文已验证；首批文本，附件未支持 |
| D04 | [产品维护 PRD.md](product-prd.md) | 同源 PRD 与持续变更已实现并验证 |
| D05 | [研发先分解与计划](engineering-plan.md) | 已实现并通过 B 回归与浏览器验证 |
| D06 | [运行中输入的处理时机](in-flight-input.md) | 已实现；工具、模型及 release 交错已验证 |
| D07 | [三部门相互专家问答](expert-ask-react.md) | C 通用请求已替换单向路径，六方向及动作接续已验证 |
| D08 | [部门完整历史与逐次上下文](department-history.md) | 已实现，自动压缩的真实运行验收中 |
| D09 | [循环次数与超时限制](execution-limits.md) | 已实现；2026-09-30 补充：因为不调用工具或工作区出现无法表示的条目而暂停的 run，由用户决定处理以后继续，由 #204 实施（M2）；2026-10-20 补充：单次模型请求的时限按多久没有收到新数据计算，未实施（#644） |
| D10 | [上下文窗口、记忆与自动压缩](context-compaction.md) | 文字摘要压缩已实现，真实运行验收中，3.0B 场景 C 完成 4 次压缩并到达 release；本页的压缩做法由 D25 的工单 #26、#35 实施 |
| D11 | [三部门循环的整体定义](three-department-loop.md) | 原生三部门循环已实现；多方向专家问答与动作请求由批次 C 实现，见 D07 |
| D12 | [部门专业补全](domain-completion.md) | 部门规则与默认依据已实现 |
| D13 | [完整交付封存与恢复](delivery-archive.md) | 独立恢复及 Web 下载已验证；QA 最终接纳前复验持久封存，缺失或损坏不放行 |
| D14 | [受控删除与移动](workspace-refactoring.md) | 已实现，E 整体验证通过 |
| D15 | [有效变化与执行依据](effective-contract-changes.md) | 合同、专家请求及在途输入适用性已验证 |
| D16 | [使用 Git 管理任务内变化](git-change-management.md) | 已实现，真实 Git、同任务方向调整及桌面手机差异查看通过确定性验收 |
| D17 | [模型等待与失败重试](provider-retries.md) | H 已实现；慢响应、重试边界及桌面手机已验证，真实完整流程仍有连续连接失败 |
| D18 | [统一 Provider 管理与部门绑定](department-providers.md) | 底层目录、三部门绑定与原生循环已接入，本地多连接回归通过；配置 UI 已随 D22/D23 实现；真实跨 Provider 完整验收未完成；按每次模型请求解析已由 #45 完成（2026-09-29） |
| D19 | [按原型建设 Web 工作台](../archive/requirements/web-workspace-prototype.md) | 2026-10-25 归档：被 D30 与原型 v9 至 v13 取代，旧工作台已由 #78 删除 |
| D20 | [部门定向追加指导](department-guidance.md) | 接收与查询已实现（`fe78667`、`fcb06ab`）；2026-10-12 按 ADR-0036 修改送达与处理结果，后按 ADR-0039 改为接收部门关注的成果（通知或开始一轮工作），删除正式回应与放行前的核对；2026-10-27 已实施（#476 关闭），见[处理设计](../design/department-guidance.md) |
| D21 | [模型请求、原始数据与用量观测](request-observability.md) | 原型已确定；复用已有事件；查询 `project.attempts`、`project.usage`、`run.attempt` 已由应用层提供，界面的观测页（请求记录、用量统计、请求详情）由 #80 实现，属于 Stage 3 的里程碑 M1 |
| D22 | [启动与 Provider 热生效](startup-provider-reload.md) | Stage 2.7 已实现；无参空态启动、统一模块重载、页面 Key 与独立 .env 来源均通过本地验收，真实 Go 侧已用用户指定模型完成模型测试与三部门任务；按每次模型请求生效已由 #45 完成（2026-09-29） |
| D24 | [模型管理与部门模型选择](model-management.md) | 需求与[设计说明](../design/model-management.md)已确认；父工单 #83 于 2026-10-19 关闭，随 M1 交付（0.1.2）。实施经过：调用目标每次请求解析（#45）、获取模型列表带凭据与连接测试（#85）已完成，其余在 #83 下，属于 Stage 3 的里程碑 M1；2026-10-07 M1 试用以后，调用协议属于模型访问定义（[ADR-0033](../adr/0033-protocol-belongs-to-model-access.md)），自定义服务的模型列表地址默认取「地址/models」，加入模型时直接采用预填的容量并自动进行模型测试；部门默认加项目部门设置、按请求解析调用目标、推理档位，取代 D02/D18/D22/D23 中的任务冻结与事项内 Prompt 编辑 |
| D23 | [统一 Provider 层与 OpenCode Go](provider-layer.md) | 已实现；独立模块、三协议适配、预置表、候选与准入贯通；真实 Go 覆盖 Responses 与 Chat Completions 并各自完成三部门任务，Anthropic Messages 对当前两个模型受区域与端点限制，见 [执行报告](../archive/stage-2-7-provider-report.md)；按每次模型请求解析调用目标已由 #45 完成（2026-09-29） |
| D25 | [语义系统](semantic-system.md) | 需求已确认；[设计说明](../design/semantic-system.md)已按需求记录写成（2026-09-26），未实施；路线位置 Stage 5 |
| D26 | [部门内多角色与多循环](department-roles.md) | 需求已记录，规则已由用户确认；[设计说明](../design/department-roles.md)已按 2026-09-25 与 2026-09-26 的决定修改，未实施；对产品、工程、质检、运维四个部门一起引入；路线位置 Stage 5 |
| D27 | [运维部门](operations-department.md) | 需求已确认，规则于 2026-09-28 两次补充（常设授权、修复事项自动开始、同一项目按优先级排队；故障记录与修复次数上限、部署前备份与回滚、密钥、外部内容、默认运行要求、未回答的决定），未实施；路线位置 Stage 4 |
| D28 | [元观察与规则检查部门](meta-observer.md) | 需求已记录，未实施；路线位置 Stage 6（自举第二层），排在最后，前置条件见[总体路线图](../program-roadmap.md)；调研见 [JEV 决策模型](../research/jev-decision-model.md) |
| D29 | [远程执行环境](remote-execution.md) | 需求已确认；部署形态见 [ADR-0018](../adr/0018-single-control-host-remote-execution.md)，代码在执行位置上直接运行（[ADR-0022](../adr/0022-run-directly-without-containers.md)），执行环境服务的合同沿用 [ADR-0007](../adr/0007-boundaries-for-distributed-deployment.md) 的边界；工作区的建立与交付的封存经过执行环境（#110）已完成，其余未实施；路线位置 Stage 3 的 3.2C 执行环境服务（#120），属于里程碑 M3；远程执行代理的真实验收使用 Orange Pi AIpro 开发板，开发板已经到位 |
| D30 | [游戏化的 Web 界面与界面实现](web-game-frontend.md) | 需求已记录；界面是 Yudao 服务提供的网页，一次发布是一个 wheel，包含构建好的页面文件与执行代理的安装包，服务手动启动，局域网访问用 `--access lan`（2026-10-07，[ADR-0032](../adr/0032-interface-served-as-web-pages.md)，[设计说明](../design/web-interface-and-release.md)）；2026-09-28 补充系统首页、机房、局域网访问（认证与加密为 TODO）；原型设计以 [v9](../archive/prototypes/v9/design.md) 结束（2026-09-30，屏幕清单、页面与决定卡片沿用 [v8](../archive/prototypes/v8/design.md)），像素画面按 [ADR-0021](../adr/0021-client-pixel-view-follows-v9-structure.md) 实现；2026-10-07 确定外观以原型 v9 为准、验收用截图与原型 v9 同一场景并排对照，画面文字使用微软雅黑并按屏幕的实际分辨率绘制，页面内容区最宽 1280 像素居中；应用层、接口层与界面随里程碑 M1 交付，0.1.1 在用户试用中（#183），各工作包的界面随所属里程碑；画面分事实层与表演层，动画属于表演层（[D38](system-intent.md)） |
| D31 | [部门内的外包角色](outsourced-agent-roles.md) | 需求已记录，未实施；路线位置 Stage 5：主程的执行者种类增加外包，经 ACP 接入，在自举的配对工单上对照自有主程与外包主程 |
| D32 | [与单个 agent 的对照实验](comparison-experiment.md) | 需求、三个场景与评分方法已确认，运行器已有实现，完整对照待验收；版本回归与 OpenCode 对照共用三个场景（[评测场景设计](../design/evaluation-scenarios.md)）；报告合同要求结束状态与放行分别取证、未知用量与费用保持未知、统计有效与未知样本数；作为 Stage 3 的评测工作线与界面工作线并行，Stage 3 结束之前必须完成；#118 下 #188 至 #198 与 #324 负责外部场景，#342 下 #413 负责 omp 流程基线；场景 1 的 Yudao 一侧属于 M4，其余评测工具与报告属于 M2；每个里程碑试用前运行版本回归，之后每个阶段结束时重复；3.9 增加共享上下文一组；留出场景第一次运行在 Stage 4 结束时；2026-10-20 确认对照条件（起点相同、上下文与输出上限相同、每次 120 分钟、第一次交付与最终交付都评分）与「高于」的判法（D38 的 N-G1），场景 3 的第一份对等读数见[架构与需求诊断](../research/architecture-diagnosis-2026-10-19.md)；运行器的对等条件由 #324、对照工具由 #642 实施，场景 2 的对照在 #198 |
| D33 | [接入已有项目](existing-project-onboarding.md) | 需求已确认；建档相关 #134–#137、#346 已实施，#138、#139、#347 待完成；采纳写回按 ADR-0034 使用三份代码树、冲突停止、最终树核验和外部动作核实；路线位置 Stage 3 的 3.8（#124），属于里程碑 M2 |
| D34 | [浏览器与 computer use](browser-and-computer-use.md) | 需求与设计已确认（[设计说明](../design/browser-and-computer-use.md)），未实施；浏览器的部分在 Stage 3 的 3.2D 实施，工单 #123（#147 至 #149、#151 至 #155），属于里程碑 M4；computer use 的部分是以后阶段的专题（[D34](browser-and-computer-use.md)「computer use 专题待重新确定的事项」），工单 #150、#246、#247；质检部门的建议能力是图像输入，不满足时只提醒 |
| D35 | [自举：用 Yudao 开发 Yudao](self-hosting.md) | 需求已记录（2026-09-29、09-30）：自举是核心目标；单一写入角色是短期取舍，将来用 worktree 或跨执行主机的分支并发；质量检查作为部门工序（工程对单元测试、圈复杂度与变异测试作自我保证，质检做大的验证）；圈复杂度与变异测试的研发工具放到下一阶段，Stage 3 结束之前由用户与 Claude 手动进行一次；2026-10-07 确定边界与路线位置（[D38](system-intent.md)、[ADR-0027](../adr/0027-trusted-kernel-outside-self-modification.md)）：自举是路线图的一条工作线，第一层的试点在 M2 关闭并且五项前置条件完成以后开始，成果以合并请求交给现有的审查流程，第二层是 Stage 6；未实施 |
| D36 | [网络取回与 MCP 工具](network-and-mcp.md) | 需求与设计已确认（[设计说明](../design/network-and-mcp.md)），未实施；路线位置 Stage 3 的 3.2B，工单 #122（#68、#69、#236，界面 #237 至 #239），属于里程碑 M3；取回与 MCP 服务器在控制主机上运行（[ADR-0025](../adr/0025-network-and-mcp-run-on-control-host.md)），搜索经 MCP 提供；2026-10-13 按 [ADR-0038](../adr/0038-function-first-commands-without-registration.md) 修改：取回任何 http 与 https 地址，MCP 服务器写在项目设置中、工具全部直接提供 |
| D37 | [新建项目的起始文件夹](project-initial-files.md) | 需求与设计已确认（[设计说明](../design/project-initial-files.md)），未实施；路线位置 Stage 3 的 3.8 的补充（#124 下），属于里程碑 M2；新建项目可以带起始文件夹，快照是第一次采纳之前每个事项的起点，不建档；评测场景 3 的数据文件需要它 |
| D38 | [系统意图与基础规则](system-intent.md) | 2026-10-07 意图校准确认：三条目的、可迭代状态的五条判据、六条基础规则与可视化的决定 A–H，需求编号 N-xx；由路线图的「迭代底座」工作包、自举工作线与 Stage 4 至 Stage 6 分别实现；2026-10-20 N-G1 的验收改为「高于」的判法（只看质检这一段带来的提高） |
| D39 | 黑板编排 | 暂缓：需求、设计与 ADR-0041 在 PR #751 里不合并（用户 2026-10-23 决定暂时不做）；编号保留 |
| D41 | [三个空间：楼、机房、城](game-world-three-spaces.md) | 需求已确认（2026-10-25）：画面是投影、七种元件、三个空间、状态只来自记录、规则是物件与物理、指向式输入、城只读；六步按路线图五个阶段咬合，设计随各阶段写 |
| D40 | [骨架与应用](skeleton-and-application.md) | 需求已确认（2026-10-23）：系统分两层，骨架向后兼容、应用一次完成；裁决只读骨架自己算的最小投影；路由、装配、执行三道契约按定义选择实现，任务池是以后的路由实现；MCP 与技能照做；看门狗只写设计（[ADR-0042](../adr/0042-skeleton-and-application-two-layers.md)、[设计说明](../design/skeleton-and-application.md)）；Stage 3 工作包「骨架与应用」，里程碑 M0.5，未实施 |

日期：2026-09-06。用户明确要求新增细节单独记录；后续每项新增或修订分别更新其文件和本索引，不只记在聊天或施工日志里。
