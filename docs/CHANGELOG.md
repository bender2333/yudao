# 文档变更记录 (Docs Changelog)

本文档记录 `docs/` 目录下全部文档的新增、修改、重构与归档记录。修改 `docs/` 下任意文档时必须在本文档追加记录。

## 记录格式规范
`模型 ID / 时间（到分钟） / 具体的改动 / 原因`

---

claude-3-7-sonnet / 2026-09-24 14:20 / 建立 docs/archive/ 目录，将历史阶段任务文档（grok-*.md、stage-1-*.md、stage-2-*.md、早期 MVP 与临时报告）归档，建立 docs/CHANGELOG.md 变更记录 / 整理活动文档结构，将已废弃或历史文件与活跃文档隔离，减少智能体无意义的上下文消耗

claude-3-7-sonnet / 2026-09-24 14:26 / 新增 docs/architecture-issues.md 架构执行问题记录文档 / 为智能体在执行架构计划时遇到的冲突、设计缺漏与阻塞事项提供独立的登记场所

claude-opus-5-5 / 2026-09-24 16:52 / 新增 docs/model-management-design.md（模型管理设计说明）、docs/requirements/model-management.md（D24）、docs/adr/0005-resolve-call-target-per-request.md、docs/adr/0006-reasoning-levels-declared-per-model.md；改写 docs/adr/0002、0003、0004 / 用户要求编写模型管理配置的需求与设计说明，作为以后判断冲突的标准：部门默认加项目部门设置、按每次模型请求解析调用目标、推理档位由模型声明、压缩参照 OMP 与 opencode

claude-opus-5-5 / 2026-09-24 16:52 / 在 docs/requirements/README.md 登记 D24；在 department-providers.md、startup-provider-reload.md、provider-layer.md、context-compaction.md、department-prompts.md、docs/provider-layer-design.md 开头说明被 D24 取代的部分；docs/decision.md 新增 2026-09-24 条目；docs/stage-3/omp-capability-gap.md「会话内换模型」改为采用并更新合计 / 使旧文档与新设计说明保持一致，避免按已取代的「任务冻结」「仅新任务生效」实施

claude-opus-5-5 / 2026-09-24 19:50 / 归档到 docs/archive/：根目录 jour.md；docs/journal/；docs/native-harness/；confirmed-requirements.md、project-workbench-contract.md、prompt-improvement-plan.md、prototype-visual-contract.md、web-prototype-implementation-plan.md；docs/prototypes/ 下的 v2 至 v5、2026-09-06/08/09 三个日期目录与 provider-config/（归入 docs/archive/prototypes/）；research/ 下的 evidence-evaluation.md、memory-and-control.md、offline-review-design.md、provider-retry-design-review.md（归入 docs/archive/research/）。删除 docs/journal/codex/ 下 10 个从未入库的 6 月执行日志与空目录 docs/assets/ / 按用户确认的清单归档阶段已关闭、被取代与一次性的文档；日记改由 claude_jour.md 与 agents_jour.md 分别记录

claude-opus-5-5 / 2026-09-24 19:50 / 新建 docs/design/ 与索引 docs/design/README.md，移入 model-management.md、provider-layer.md、department-guidance.md（原 docs/ 根层的 *-design.md，去掉 -design 后缀）与 recovery-contract-and-fault-matrix.md（原 docs/stage-3/） / 用户要求建立保存模块设计、架构图与设计说明的目录，供计划与工单引用

claude-opus-5-5 / 2026-09-24 19:50 / 修改活动文档中指向已归档或已移动文件的链接；去掉 research/ 与 requirements/department-providers.md 中指向已删除文件或旧路径 D:/codes/oh-my-pi 的链接格式，保留文字；program-roadmap.md 第 5、12 行更新为 Stage 2.7 已于 2026-09-20 关闭，第 100 行日记改为 claude_jour.md；docs/agents/issue-tracker.md 更新日记位置并加入 docs/design/，docs/agents/domain.md 改为 CONTEXT.md 与 docs/adr/ 已存在 / 活动文档中不保留失效链接，状态与现状一致

claude-opus-5-5 / 2026-09-24 20:21 / 新增 docs/research/semantic-system-and-department-roles.md（OMP、OpenCode 子 Agent 与记忆实现，语义记忆系统与多角色组织的一手来源）；新增 docs/requirements/semantic-system.md（D25）与 docs/requirements/department-roles.md（D26）；新增 docs/design/semantic-system.md 与 docs/design/department-roles.md 两份设计草案；在 docs/design/README.md、docs/requirements/README.md、docs/research/README.md 登记 / 用户确认语义系统与部门内多角色是一定要做的模块，要求调研并写需求与设计

claude-opus-5-5 / 2026-09-24 20:48 / docs/design/department-roles.md 工程角色改为工程经理、工程架构师、开发者、工程探索者，删去工程评审者，角色清单标为已确认；docs/design/semantic-system.md 状态改为单独讨论，检索方式改为 TODO（第 7.4 节）；D25、D26 需求记录写入用户的两项决定；调研资料第 5 节同步；docs/program-roadmap.md 第 2 节依赖图与步骤加入 3.10 语义系统与 3.6 部门内多角色，第 1、3、4、5 节同步；docs/stage-3-plan.md 改写 3.6 行、新增 3.10 行、3.9 行加入两项能力；docs/design/model-management.md 第 12 节两行 TODO 指向新设计，第 3、4 张时序图的参与者名 Loop 改为 DeptLoop / 按用户选择：工程拆出架构师、语义系统单独讨论、两个模块放在 3.1 之后；Loop 与 mermaid 关键字 loop 冲突导致两张图无法显示

claude-opus-5-5 / 2026-09-24 21:40 / docs/program-roadmap.md 阶段扩为七个：第 1 节阶段表新增 Stage 4 至 Stage 7，第 2 节依赖图与步骤只保留 Stage 3 工作包，第 3 节架构表加入运维部门、元观察与规则检查部门、决策模型调用与查询接口，并写明六条边界，第 4 节项目记忆与演化前置改为 Stage 4 与 Stage 7，第 5 节改写为后续阶段（阶段依赖图、Stage 4 至 Stage 7 的内容与依赖、Yudao 负责自己运维的愿景），第 6 节加入 2026-09-24 调整前编号的归位；新增 docs/adr/0007-boundaries-for-distributed-deployment.md；docs/decision.md 新增 2026-09-24 路线图条目 / 用户确认运维部门、元观察与规则检查部门、分布式部署三个方向，以及语义系统、部门内多角色、记忆、可观测性、前端优化放入 Stage 4

claude-opus-5-5 / 2026-09-24 21:40 / docs/stage-3-plan.md 改名为「通用工具、可靠恢复与并行」，删除 3.5、3.6、3.8、3.10 四行并修改 3.9；docs/current-baseline.md 第 5 节按新阶段拆分开放项；docs/stage-3/operations-responsibility-sample.md 的交付物运营者改为 Stage 5 运维部门，「待 3.8 确定」改为「待 Stage 5 确定」，失效的章节引用改为指向路线图；docs/design/recovery-contract-and-fault-matrix.md、docs/design/department-roles.md、docs/design/README.md 与根目录 README.md 的阶段编号同步 / 活动文档与新的阶段划分保持一致

claude-opus-5-5 / 2026-09-24 21:40 / 新增 docs/requirements/operations-department.md（D27）、meta-observer.md（D28）、distributed-deployment.md（D29）；docs/requirements/semantic-system.md（D25）与 department-roles.md（D26）写入放入 Stage 4 的原话与决定，D25 写入语义系统的两项职责；docs/requirements/README.md 登记 D27 至 D29；新增 docs/research/jev-decision-model.md 并在 docs/research/README.md 登记 / 按需求记录规则单独保存用户原话与确认结论；保存 JEV 七个一手来源的核对结果，供 Stage 5 设计使用

claude-opus-5-5 / 2026-09-24 21:48 / docs/adr/0007-boundaries-for-distributed-deployment.md 的「后果」补充一条：现有三个部门共用一个 run 工作目录，新的设计不增加对共享目录的依赖，其余部分在 Stage 6 改为快照传递 / 如实说明第 4 条边界与现有实现的差距

claude-opus-5-5 / 2026-09-24 21:54 / docs/program-roadmap.md 第 5.2 节与 docs/decision.md 2026-09-24 路线图条目写明：进入 Stage 5 时再修改 CLAUDE.md、AGENTS.md 与 README 的项目表述 / 用户决定等到 Stage 5 再修改，防止影响当前的工作

claude-opus-5-5 / 2026-09-24 22:57 / docs/design/model-management.md 第 5.5 节、第 6 节时序图与第 10 节运行层改为模型引用无法使用时事项进入待恢复，删除第 12 节「未结束事项继续执行」TODO；docs/design/recovery-contract-and-fault-matrix.md 第 1、2 节与故障矩阵第 10 行、docs/stage-3-plan.md 第 5.1、5.3 节改为按请求解析调用目标，并写入待恢复规则；docs/design/department-roles.md 第 4 节与 docs/requirements/department-roles.md 的产品部门协调角色改为「产品部门经理」；docs/decision.md 新增 2026-09-24 条目 / 用户决定模型引用无法使用时进入待恢复、协调角色名称，以及开始设计界面原型 v7

claude-opus-5-5 / 2026-09-24 23:20 / 新增 docs/prototypes/v7/design.md（v7 信息结构、各页面、循环画面、部门房间与小人动作对照、界面数据合同、阶段显示、已处理的文档冲突）与 docs/prototypes/v7/BUILD.md（原型文件结构、模块接口、示例数据形状、事件与场景、测试方法） / v6 落后于七个阶段的路线图，用户要求结合后续各阶段能力设计新版原型

claude-opus-5-5 / 2026-09-25 06:30 / 新增 docs/prototypes/v7/ 原型（index.html、styles/、js/，含外壳与核心、示例数据与十二个场景、像素小人与部门房间、循环画面、动作图鉴、概览、恢复与动作核实、资料、部门工作间、观测、设置、系统页）；design.md 第 4.3、6.3、7.2 节补充对结果未知的动作作出决定；BUILD.md 补充共用函数、事项字段、画面数量字段与事件字段；docs/prototypes/CHANGELOG.md 新增 v7 条目 / 按已确认的 v7 信息结构完成原型制作

claude-opus-5-5 / 2026-09-25 07:25 / docs/prototypes/v7/BUILD.md 第 5.1 节改为画面按容器宽度缩放并填满容器（非整数倍，用 pixelated 显示）；原型的画面缩放、场景播放时的画面滚动与工具条留白随之修改 / 整体测试截图中循环画面只占容器宽度的六成，画面文字过小

claude-opus-5-5 / 2026-09-25 15:29 / 用 git mv 把 docs/prototypes/department-workspace-v6.html 与 department-workspace-v6-design.md 移到 docs/archive/prototypes/，修改 docs/design/model-management.md（开头的原型链接、第 9 节标题与说明）、docs/prototypes/CHANGELOG.md、docs/prototypes/v7/design.md 中指向它们的链接；docs/design/model-management.md 第 10 节「目录与校验」补上协议从模型访问定义移到 Provider 配置；新增 docs/requirements/web-game-frontend.md（D30）并登记到需求索引；新增 docs/research/web-frontend-technology.md 并登记到调研索引 / v6 已被 v7 取代，用户确认归档与补充；D30 记录用户对游戏化界面与界面实现的要求，调研支撑界面技术决定

claude-opus-5-5 / 2026-09-25 15:35 / docs/research/web-frontend-technology.md 第 4 节表格新增镜头（pixi-viewport）、声音（@pixi/sound）、无障碍基础组件（Base UI）三行 / 补充游戏手法中镜头平移与缩放、声音，以及界面外壳基础组件的选型依据

claude-opus-5-5 / 2026-09-25 22:32 / 新增 docs/requirements/outsourced-agent-roles.md（D31）并登记到需求索引 / 用户确认部门内需要由外部 agent 担任的外包角色，按需求记录规则保存原话、确认结论与待确认规则

claude-opus-5-5 / 2026-09-25 23:36 / 新增 docs/research/loop-engineering-2026.md、graph-engineering-2026.md、anthropic-ai-native-sdlc-sources.md 三份调研，并在 docs/research/README.md 登记 / 用户要求调研 2026 年的 loop 工程、graph 工程与 Anthropic 发布的 AI-native SDLC，作为讨论 Yudao 架构意义的依据

claude-opus-5-5 / 2026-09-26 00:20 / 新增 docs/design/architecture-core-and-materials.md（系统架构原理：控制核心与可替换的材料），并在 docs/design/README.md 登记 / 用户要求把近期关于系统架构设计与项目原理的讨论保存到 docs，作为回到架构整体设计的起点

claude-opus-5-5 / 2026-09-26 01:13 / 新建 docs/design/architecture/ 作为总体架构设计的目录：用 git mv 把 docs/design/architecture-core-and-materials.md 移为 docs/design/architecture/core-and-materials.md 并修改其中的相对链接；新增 docs/design/architecture/overall-architecture.md（分层图、各层职责与边界、待讨论事项、控制核心与执行者合同中需要先确定的问题）；docs/design/README.md 改为「总体架构设计」一组 / 用户认可分层图与职责分层表，要求保存到总体架构设计的目录，下一次会话继续讨论
