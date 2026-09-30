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

claude-opus-5-5 / 2026-09-25 15:42 / 新增 docs/requirements/stage-requirements-overview.md（各阶段需求概览：Stage 3 剩余工作包到 Stage 7 的已确认需求、原型依赖、待讨论问题与讨论顺序），在 docs/requirements/README.md 开头登记 / 用户要求先整理每个阶段的大致需求，帮助设计原型细节

claude-opus-5-5 / 2026-09-25 15:58 / docs/requirements/department-roles.md（D26）写入 2026-09-25 用户对部门内部循环、审查角色、账本显示、跨部门询问、并行与预测性探索、设计说明第 15 节规则的决定，「设计中待用户确认的规则」一节改为「设计说明的状态」；docs/requirements/stage-requirements-overview.md 第 3.1 节改为已确定的内部循环规则；docs/decision.md 新增 2026-09-25 部门内部循环条目 / 与用户逐项讨论部门内部循环的需求

claude-opus-5-5 / 2026-09-25 16:10 / docs/requirements/department-roles.md（D26）写入用户关于中心型协作的原话，角色清单改为当前的角色（增加各部门审查者，「开发者」改名「主程」），2026-09-25 的规则整理为三个部门共用的规则与工程部门的中心型协作，新增「待讨论」一节（产品与质检的内部形态）；docs/decision.md 2026-09-25 条目与 docs/requirements/stage-requirements-overview.md 第 3.1 节同步改为当前结论 / 用户提出工程部门围绕架构师的中心型协作，取代此前按经理协调写下的分派与返工规则

claude-opus-5-5 / 2026-09-25 16:12 / docs/requirements/department-roles.md（D26）改为三个部门都采用中心型协作（产品架构师、工程架构师、测试工程师为中心；中心角色不做工具角色的写入；经理对外沟通、提交成果并关注进度与数据流转），删除「待讨论」一节；docs/decision.md 2026-09-25 条目与 docs/requirements/stage-requirements-overview.md 第 3.1 节同步 / 用户决定产品与质检也采用中心型协作

claude-opus-5-5 / 2026-09-25 16:18 / 改写 docs/design/department-roles.md：中心型协作（中心角色与经理分为两节）、角色清单（增加审查者、「开发者」改为「主程」）、新增内部循环（含流程图）与预测性探索、执行槽位的优先级与让出、交出检查表，删除一次性角色的请求数与任务数上限，删除已确定的待确认规则，章节重新编号，更新验收反例与对现有设计的影响；docs/design/README.md 更新该条目；四张 mermaid 图经 mermaid 解析器检查通过 / 用户确认按 D26 2026-09-25 的决定修改设计草案

claude-opus-5-5 / 2026-09-25 16:52 / docs/requirements/semantic-system.md（D25）写入用户 2026-09-25 的两段原话，「已确认」增加两条（语义系统参照 Semantica、是给 Agent 做上下文的知识图谱；分为整理与上下文组装两部分），新增「重点 TODO：上下文组装」一节；docs/requirements/stage-requirements-overview.md 第 3.2 节同步，第 3.1 节写明设计草案已按 D26 修改 / 用户声明语义系统的定位，并要求把上下文组装作为重点 TODO 标出、专题讨论

claude-opus-5-5 / 2026-09-25 17:05 / docs/requirements/semantic-system.md（D25）「已确认」增加整理部分的七条决定，「设计中待用户确认的规则」一节改为「设计草案的状态」；docs/requirements/stage-requirements-overview.md 第 1 节 Stage 4 的需求状态改为当前状态，第 3.1 节角色清单改为主程并补上三个部门的审查者、删除已被中心型协作取代的「设计草案已写的」一行，第 3.2 节改写为已确认、重点 TODO、设计草案状态与待讨论；docs/decision.md 新增 2026-09-25 语义系统条目；CONTEXT.md 新增「语义系统」一节术语 / 用户确认整理部分的第二轮问题（轨迹、七类图谱内容、随时记录、事件投影、稳定编号），并同意改正需求概览中已被 D26 取代的内容

claude-opus-5-5 / 2026-09-25 17:30 / docs/requirements/semantic-system.md（D25）写入用户关于语义工程的原话，「已确认」增加第 8–13 条（尝试的名称、待复核规则、可见范围、知识的范围、查看与纠正、第二项职责）；docs/requirements/stage-requirements-overview.md 第 3.2 节同步并更新待讨论；docs/decision.md 2026-09-25 语义系统条目增加第三轮决定；CONTEXT.md 增加「尝试」「待复核」，「调用尝试」增加 _Avoid_ / 用户回答整理部分第三轮问题，指出语义工程还包括教训、洞见等语义

claude-opus-5-5 / 2026-09-25 17:50 / 新增 docs/research/semantica-reference.md（Semantica 0.7.0 提交 2173308 的维护状况、本体、来源与证据、冲突、上下文与决定模块，与 Yudao 七类内容和轨迹的对照，与架构原则的冲突，可以借用的做法，refact 集成设计，同类项目），docs/research/README.md 增加索引 / 用户要求语义系统参照 Semantica，需要以一手源码判断能否作为依赖、借用哪些做法

claude-opus-5-5 / 2026-09-25 18:05 / docs/requirements/semantic-system.md（D25）「已确认」增加第 14–21 条（抽象层、复盘、教训的约束力与范围、Semantica 不作为依赖、本体、关系八组、不记录置信度），第 13 条指向第 14–17 条，重点 TODO 增加可靠程度判断与变更推送两项；docs/requirements/stage-requirements-overview.md 第 3.2 节同步；docs/decision.md 增加第四轮决定；CONTEXT.md 增加教训、洞见、画像、复盘、本体 / 用户按推荐回答整理部分第四轮问题

claude-opus-5-5 / 2026-09-25 18:25 / docs/requirements/semantic-system.md（D25）写入用户关于惊讶值的原话，「已确认」增加第 22 条（压缩不再生成文字摘要）与第 23 条（实体身份）；docs/requirements/stage-requirements-overview.md 第 3.2 节同步，待讨论改为惊讶值；docs/decision.md 增加第五轮决定 / 用户按推荐回答压缩与实体身份两个问题，并补充惊讶值的需求

claude-opus-5-5 / 2026-09-25 18:40 / docs/requirements/semantic-system.md（D25）写入用户关于惊讶机制的纠正原话，「已确认」增加第 24 条（保留由惊讶得出的知识与教训），新增「TODO：惊讶机制」一节；docs/requirements/stage-requirements-overview.md 第 3.2 节增加第 17 条与惊讶机制 TODO，写明整理部分讨论完成；docs/decision.md 同步 / 用户决定惊讶的发现与处理单独专题讨论，语义系统只保留由惊讶得出的内容

claude-opus-5-5 / 2026-09-25 18:55 / 新增 docs/research/surprise-and-prediction-error.md（自由能原理与贝叶斯惊讶、EM-LLM、Titans、Nemori、PreAct、Reflexion、ExpeL、CLIN、各家 API 的 token 概率、OMP 的记忆写入规则），docs/research/README.md 增加索引，D25「TODO：惊讶机制」一节链接该调研 / 为惊讶机制专题讨论准备一手参照

claude-opus-5-5 / 2026-09-25 19:10 / docs/requirements/semantic-system.md（D25）写入用户原话，「已确认」增加第 25 条，惊讶机制 TODO 改为「惊讶机制与事件系统整理（放到后面）」；docs/requirements/stage-requirements-overview.md 第 3.2 节与 docs/decision.md 同步 / 用户决定惊讶机制与事件系统整理放到后面，当前设计要让它们以后能正常接入

claude-opus-5-5 / 2026-09-25 22:32 / 新增 docs/requirements/outsourced-agent-roles.md（D31）并登记到需求索引 / 用户确认部门内需要由外部 agent 担任的外包角色，按需求记录规则保存原话、确认结论与待确认规则

claude-opus-5-5 / 2026-09-25 23:14 / docs/requirements/semantic-system.md（D25）「重点 TODO：上下文组装」一节写入专题讨论开始时的用户原话（上下文组帧；参考 OMP 与 opencode） / 上下文组装专题讨论开始，记录用户的出发点

claude-opus-5-5 / 2026-09-25 23:32 / docs/requirements/semantic-system.md（D25）重点 TODO 一节增加「专题中已确认」第 1 条（术语只用上下文组装，每次请求由固定栏目组成）；docs/requirements/stage-requirements-overview.md 第 3.2 节与 docs/decision.md 同步；CONTEXT.md「上下文组装」的 Avoid 增加「组帧」 / 用户按推荐回答上下文组装专题第一轮 Q1

claude-opus-5-5 / 2026-09-25 23:36 / 新增 docs/research/loop-engineering-2026.md、graph-engineering-2026.md、anthropic-ai-native-sdlc-sources.md 三份调研，并在 docs/research/README.md 登记 / 用户要求调研 2026 年的 loop 工程、graph 工程与 Anthropic 发布的 AI-native SDLC，作为讨论 Yudao 架构意义的依据

claude-opus-5-5 / 2026-09-25 23:58 / 新增 docs/research/context-assembly-reference.md（Yudao 现行上下文装配事实，OMP fdfeef1f78 与 opencode 0027387 的上下文组装，Anthropic、Manus、Letta、Zep、Cognition、ExpeL、ACE 等公开做法与上下文长度研究，共同做法与现状差距），docs/research/README.md 增加索引 / 为上下文组装专题提供参照，用户要求参考 OMP 与 opencode

claude-opus-5-5 / 2026-09-26 00:12 / docs/requirements/semantic-system.md（D25）「专题中已确认」增加第 2–8 条（状态与可靠程度、JEV 证据核对、四种放入方式、组装不调用模型、顺序与缓存、工作上限、旧工具结果），并整理该节的结构；docs/requirements/stage-requirements-overview.md 第 3.2 节与 docs/decision.md 同步；CONTEXT.md 新增栏目、上下文清单、目录、接触时附加、工作上限、证据核对 / 用户按推荐回答上下文组装专题 Q2–Q7

claude-opus-5-5 / 2026-09-26 00:20 / 新增 docs/design/architecture-core-and-materials.md（系统架构原理：控制核心与可替换的材料），并在 docs/design/README.md 登记 / 用户要求把近期关于系统架构设计与项目原理的讨论保存到 docs，作为回到架构整体设计的起点

claude-opus-5-5 / 2026-09-26 00:31 / docs/requirements/semantic-system.md（D25）「专题中已确认」增加第 9–14 条（通知、目录的选择、各角色的上下文、轨迹节录、查询方式、栏目上限），第 6 条当前状态栏目的内容按第 9 条修改；docs/requirements/stage-requirements-overview.md 第 3.2 节与 docs/decision.md 同步；CONTEXT.md 新增焦点、通知、轨迹节录 / 用户采纳上下文组装专题第三轮 Q8–Q13 的推荐

claude-opus-5-5 / 2026-09-26 00:44 / docs/requirements/semantic-system.md（D25）「专题中已确认」增加第 15–17 条（跨事项、JEV 校准样本、界面要求）；docs/requirements/stage-requirements-overview.md 第 3.2 节与 docs/decision.md 同步 / 用户采纳上下文组装专题第四轮 Q14–Q16 的推荐

claude-opus-5-5 / 2026-09-26 00:58 / docs/requirements/semantic-system.md（D25）「专题中已确认」增加第 17、18 条（当前有效要求的范围、部门账本的显示），界面要求改为第 19 条，第 4、14 条接触时附加的内容与排列加入要求；docs/requirements/stage-requirements-overview.md 第 3.2 节、docs/decision.md 与 CONTEXT.md「接触时附加」同步 / 用户采纳上下文组装专题第五轮 Q17、Q18 的推荐

claude-opus-5-5 / 2026-09-26 01:13 / 新建 docs/design/architecture/ 作为总体架构设计的目录：用 git mv 把 docs/design/architecture-core-and-materials.md 移为 docs/design/architecture/core-and-materials.md 并修改其中的相对链接；新增 docs/design/architecture/overall-architecture.md（分层图、各层职责与边界、待讨论事项、控制核心与执行者合同中需要先确定的问题）；docs/design/README.md 改为「总体架构设计」一组 / 用户认可分层图与职责分层表，要求保存到总体架构设计的目录，下一次会话继续讨论

claude-opus-5-5 / 2026-09-26 01:38 / docs/requirements/semantic-system.md（D25）专题第 11 条审查者接触时附加加入要求与验收条件，更新开头状态、上下文组装一节的说明与已不存在的草案引用，删去「设计草案的状态」一节；整篇改写 docs/design/semantic-system.md（整理与上下文组装：本体、轨迹、写入与证据核对、抽象层与复盘、可见范围与跨事项、栏目与顺序、焦点与目录、接触时附加、通知、查询工具、各角色的上下文、上限、长度控制、提示缓存、数据流核对、界面、惊讶机制的扩展点、验收）；新增 docs/adr/0008-trajectory-and-graph-as-event-projections.md 与 docs/adr/0009-deterministic-context-assembly.md；docs/design/model-management.md 第 1、7.5、8.3–8.7、10、12 节按工作上限、旧工具结果清理、整理请求与轨迹节录修改；docs/design/department-roles.md 第 3、4、5、6.1、6.2、7.1、9.1、9.3、10、11.2、12.1、12.4、12.5、13、15、16、17 节按新的语义系统修改；docs/requirements/context-compaction.md（D10）、department-history.md（D08）增加开头说明；docs/requirements/meta-observer.md（D28）增加 JEV 用于证据核对一节并同步校准样本与实现状态；docs/requirements/web-game-frontend.md（D30）增加上下文的界面要求；docs/requirements/department-roles.md（D26）改正一处旧用词；docs/program-roadmap.md 第 3、4、5 节同步语义系统、JEV 在 Stage 4 接入与部门内中心型协作；docs/requirements/stage-requirements-overview.md 第 1、3.2、3.4、4.2、7 节同步；docs/design/README.md、docs/research/jev-decision-model.md 第 7 节、docs/research/README.md 同步 / 用户确认上下文组装专题的全部决定与设计改写方案

claude-opus-5-5 / 2026-09-26 02:20 / docs/research/jev-decision-model.md 新增第 8 节本地实测（请求与响应格式、英文与中文证据核对 4 条样本的结果），来源改为第 9 节，阅读范围一行同步；docs/design/semantic-system.md 第 7.2 节按 Noul 只返回概率写明两个阈值的分类与记录内容 / 用户提供 JEV 的中转服务，实测接口格式与中文表现

claude-opus-5-5 / 2026-09-26 02:29 / 把 architecture-docs-on-main 合并进主分支（新增 docs/design/architecture/、docs/requirements/outsourced-agent-roles.md 与三份 2026 动向调研），worktree-docs-research-frontend-libs 的内容已被它包含，只并入提交历史；把用户放入的 docs/archive/native-harness/loop-system-principles.md 与 loop-system-architecture.md 纳入版本管理 / 用户要求合并两个架构分支，总体架构文档以这两份原理文档为依据

claude-opus-5-5 / 2026-09-26 02:43 / 新增 docs/adr/0010-control-core-drives-role-steps.md（每次模型请求在控制核心装配，自有角色的步骤由控制核心驱动）；重写 docs/design/architecture/overall-architecture.md（分层图、各层职责、语义系统在各层中的位置、依赖方向、控制核心内部模块与一步的顺序、主机工具与环境工具、待讨论的五项事项）；docs/design/architecture/core-and-materials.md 第 2、6、7、8、9 节按 ADR-0010 修改，第 4.2 节写入教训发现模块与反复退回时提醒用户；docs/design/semantic-system.md 第 4 节按总体架构重写，第 5.1、6.3、7.1、8、9、10.2、10.7、15、17 节按「教训由教训发现模块找出」修改，第 5.5、6.1、6.3、8、10.4、10.5 节写入拆分 #22 时用户同意的四处补充；docs/design/department-roles.md 第 3、5 节按总体架构重写，第 6.2、8、9.3 节去掉角色写出教训，新增第 12.5 节反复退回的提醒（交出检查顺延为 12.6），第 15、16、17 节同步；docs/requirements/semantic-system.md（D25）写入用户原话，已确认第 15 条改写、新增第 26、27 条，专题新增第 20 条，第 10、13、14、18 条同步，TODO 一节改为「惊讶机制与教训发现模块」；docs/requirements/department-roles.md（D26）写入用户原话与 2026-09-26 的两项决定，更新开头状态；docs/requirements/outsourced-agent-roles.md（D31）分析第 1、5 条按 ADR-0010 改写；docs/requirements/meta-observer.md（D28）新增「与教训发现模块的关系」一节；docs/requirements/stage-requirements-overview.md 第 3.2 节、docs/program-roadmap.md 第 5.1 节同步；CONTEXT.md 新增「系统结构」一组（控制核心、步骤驱动、工具许可、主机工具、环境工具）与「教训发现模块」，修改焦点、尝试、教训、复盘；docs/research/README.md 与 surprise-and-prediction-error.md 的专题名称同步；docs/decision.md、docs/design/README.md 同步 / 用户对总体架构核对提出的 Q1、Q2 采纳推荐，Q3 决定教训由独立的教训发现模块产生，Q4 决定反复退回时提醒用户；拆分 #22 时用户同意四处设计补充

claude-opus-5-5 / 2026-09-26 02:52 / docs/design/semantic-system.md 开头状态、第 4、5.1、8、15 节写明洞见由教训发现模块找出、只能查询取得，复盘写出或更新画像；docs/requirements/semantic-system.md（D25）写入用户原话，已确认第 15 条与 TODO 同步，新增第 28 条，专题第 5 条同步；docs/requirements/department-roles.md（D26）「教训与洞见的来源」、docs/design/department-roles.md 第 5、6.2 节、docs/design/architecture/overall-architecture.md 第 2、3、6 节、docs/requirements/stage-requirements-overview.md 第 3.2 节、docs/requirements/meta-observer.md（D28）、CONTEXT.md（教训发现模块、洞见、复盘）同步；docs/program-roadmap.md 开头与第 2 节在 3.2A 与 3.1 之间加入控制核心重构（ADR-0010），后续条目顺延；docs/decision.md 同步；GitHub #34 改为「画像与复盘」，#22 的子工单清单评论同步 / 用户采纳建议：洞见也交给教训发现模块，控制核心重构单独立工单并排在 3.1 之前

claude-opus-5-5 / 2026-09-26 09:30 / docs/program-roadmap.md 第 2 节控制核心重构一条链接工单 #43；docs/decision.md 写入 #43 的工单号与重构计划的四项决定（事件序列对照、并发不在范围内、测试只经公开接口、smoke 审计改用 P）/ 用户采纳重构计划的推荐，按 /request-refactor-plan 发布 #43

claude-opus-5-5 / 2026-09-26 09:58 / 新增 docs/research/prompt-audit-2026-09-26.md（提示词审计：范围与目标模型、提示词清单、21 项结果与 5 项只登记的条目、逐段补丁、验证方法），docs/research/README.md 登记 / 用户运行 /claude-api prompt-audit

claude-opus-5-5 / 2026-09-26 10:57 / docs/research/prompt-audit-2026-09-26.md 开头写入状态（规则文件的补丁已采用，harness/ 部分待写成工单），第 5 节去掉「需要用户确认」一句；docs/research/README.md 对应条目同步 / 用户确认规则文件的补丁，CLAUDE.md 与 AGENTS.md 已按 P1 至 P7、R1、A1 至 A7 修改

claude-opus-5-5 / 2026-09-26 12:00 / 新增 docs/adr/0011-async-control-core.md、0012-single-control-core-scalable-execution.md、0013-event-log-and-single-write-path.md、0014-versioned-definitions.md、0015-desktop-client-and-http-contracts.md；docs/adr/0007 开头写明被 ADR-0012 取代的两条后果；重写 docs/design/architecture/overall-architecture.md（分层图、各层职责、十项长期决定、依赖方向、控制核心内部、合同、动作契约、用户决定、路线图对照、使用的技术、近期实施顺序、待讨论的事项）；docs/design/architecture/core-and-materials.md 第 4.2、7.4、9、11 节与开头状态按 ADR-0011 至 ADR-0015 修改；docs/program-roadmap.md 开头、第 1 节 Stage 6 一行、第 2 节加入 #44 与 #45、第 3 节改为引用总体架构与新 ADR、第 5.1 节 D24 依赖、元观察的决策模型一段、第 5.3 节 Stage 6 按新的部署形态修改；CONTEXT.md 新增事件日志、写入口、定义、动作、执行环境、决定请求、观察者，修改控制核心；docs/decision.md、docs/design/README.md 同步；GitHub #43 按异步步骤驱动、可以序列化的合同与收拢写入修改，新建 #44、#45，#27 同时依赖 #44 / 用户要求整体重新思考架构并对 Q7 至 Q11 回答「采纳推荐」

claude-opus-5-5 / 2026-09-26 12:09 / 按 ADR-0005、ADR-0011 至 ADR-0015 统一需求与计划文档：D09 写明停止原因属于带版本的定义；D17 步数上限按 D09；D10、D08 的压缩做法改为 D25 的最终做法；D18、D22、D23 改为每次模型请求解析调用目标、控制核心不持有明文凭据；D02 按 D24 改写 Prompt 的生效方式；D07、D11 改为同一事项一个部门持有交接、其他部门可以做预测性探索；D20 实现状态改为已实现；D28 追加元观察的运行形态与 JEV 的两层准入；D29 追加部署形态与服务之间的传输；D01、D30 追加桌面客户端；D24 追加 #45 的位置；ADR-0009 按教训发现模块修改；docs/stage-3-plan.md 第 5.2、5.3、5.4、6 节与 docs/design/recovery-contract-and-fault-matrix.md 第 2 节同步 / 用户确认长期架构以后，文档之间的 18 处冲突按这些决定统一

claude-opus-5-5 / 2026-09-26 12:16 / 更新过时的状态与进度说法：docs/design/recovery-contract-and-fault-matrix.md 第 7 节按 ADR-0012 改写（不引入外部工作流引擎，控制核心逻辑上一份并持有执行权，Stage 6 加入期限与续期）；D24 已确认第 20 条「摘要请求」改为「整理请求」；docs/design/department-guidance.md 开头与 docs/requirements/README.md 的 D20 改为已实现（fe78667、fcb06ab）；README 中 D01、D30 改为桌面客户端，D10、D11、D18、D22、D23、D25、D26、D29 按各需求记录修改；D23 开头状态改为 Stage 2.7 已实现（50fd2e1）；D11 实现状态改为批次 C 已实现（925e190）；D18 的配置读取与重新读取、真实适配器支持的协议与首批服务商按 2.7 的代码修改；docs/current-baseline.md 更新日期、应用代码起点（5edf41a）与 Git 状态、3.2A 工具状态（#12 至 #14 关闭，#15 代码已提交、真实全链路验收未完成）、3.0B 三个场景已完成（9f95688）、开放项与 2.7 一行；docs/program-roadmap.md 第 1 节 Stage 3 当前状态；docs/stage-3-plan.md 开头状态与第 8 节本轮状态 / 需求与计划文档按长期架构统一以后，仍有状态与进度说法落后于代码、提交与工单的事实

claude-opus-5-5 / 2026-09-26 12:18 / docs/program-roadmap.md 第 2 节加入 #46、#47（提示词审计补丁与请求结构）、#48（带版本的定义）、#49（用户决定），后续条目顺延；docs/design/architecture/overall-architecture.md 第 10 节的近期实施顺序同步，写明 #15 的真实验收可以与关键路径并行 / 架构师建立 #46 至 #49，并解除 #43 对 #15 的依赖（#15 的代码已合入，只剩取决于凭据的真实验收）

claude-opus-5-5 / 2026-09-26 12:30 / docs/research/prompt-audit-2026-09-26.md 开头的状态改为 harness/ 的补丁与 T4 工具合并已按 #46 实施；docs/research/README.md 对应条目同步 / #46 已修改工具描述、删除请求中的剩余循环次数、质检部门只保留 run_check

claude-opus-5-5 / 2026-09-26 12:34 / docs/design/department-roles.md：第 6.2 节中心角色增加「更新计划」工具，第 9.3 节审查结果写明被审查成果的内容摘要，第 11.3 节执行槽位按正在执行步骤的角色计数，第 12.4 节停滞时中心角色保留历史、连续工具角色从新的历史开始，第 12.6 节交出检查要求内容摘要相等的审查通过记录并写明工程自测的判断方法，第 13 节写明发起专家请求时角色任务照常进行与恢复规则的位置，第 16 节验收对照按独立检查判断、每个任务运行 3 次，第 17 节链接 ADR-0016、ADR-0017，开头状态行更新；docs/design/semantic-system.md 第 4 节表格与模块图、依赖规则、第 8 节改为复盘由流程编排安排、中心角色通过一次单独的请求完成，P 包含压缩之前的整理请求；docs/design/model-management.md 第 5 节按 ADR-0017 增加角色默认与项目角色设置、四层解析顺序、生效与记录，第 5.5 节改为流程编排发出待恢复的决定请求（#49），第 6 节时序与说明按角色解析，第 1、2、3、4.6、4.7、7.2 节同步；docs/design/recovery-contract-and-fault-matrix.md 新增第 5 节角色任务的恢复，原第 5 至 7 节顺延；CONTEXT.md 新增「部门内多角色」一组 13 个词条；docs/design/README.md 更新模型管理、部门内多角色与恢复契约三条 / 架构师为 D26 建立工单时发现设计缺口，在已确认设计的范围内作出决定并补全相关文档

claude-opus-5-5 / 2026-09-26 15:05 / docs/architecture-issues.md 登记 #47 的架构问题：没有工具调用时主机追加的 user 消息与「通知」的关系、D09 的停止原因清单缺少 no_tool_call、请求合同没有 tool_choice / #47 修复中发现设计与需求文档没有覆盖的边界，交给架构师处理

claude-opus-5-5 / 2026-09-26 15:13 / 新增 docs/design/app-and-interface.md（应用层与接口层：模块、命令合同与清单、查询与读取模型、事件流、能力清单、访问方式与认证、与现有 Web 的对照与迁移、使用的技术、验收，第 10 节为架构师的决定）；docs/design/README.md 登记；docs/design/architecture/overall-architecture.md 第 10 节加入 #72、#73 至 #77、#79 至 #82、#50 下的 D26 工单与 3.2B（#68、#69），第 11 节加入长期目标能否修改；docs/program-roadmap.md 第 2 节加入应用层骨架 #72（排在 #49 之前）、Stage 4 的部门内多角色写明 ADR-0016、ADR-0017 与工单，新增应用层、接口层与桌面客户端一条；GitHub 新建 #50 至 #67（D26 与 #22 下的两张）、#68 与 #69（3.2B）、#70 至 #82（应用层、接口层与桌面客户端），#44、#49、#16 的正文与依赖同步，解除 #16 对 #15 的依赖 / 用户要求自动推进项目；应用层是用户决定、3.1 的继续执行与桌面客户端的共同前提

claude-opus-5-5 / 2026-09-26 15:40 / docs/design/model-management.md 第 4.3 节写明容量只从上游模型列表预填、连接测试读取模型列表地址、fake 协议只在测试或演示方式启动时可用，第 4.4 节写明影响列表由查询 catalog.change_impact 提供，第 5.2 节写明每个项目每个部门一份设置一个版本；docs/design/README.md 与 docs/program-roadmap.md 第 5.1 节写入 D24 的工单；GitHub 新建 D24 父工单 #83 与子工单 #84 至 #96 / 为 D24 建立工单时出现的五处设计缺口由架构师在已确认设计的范围内决定

claude-opus-5-5 / 2026-09-26 15:49 / docs/architecture-issues.md 为 #47 登记的架构问题追加处理结论；CONTEXT.md 新增「主机提示」；docs/design/semantic-system.md 第 10.1 节历史栏目加入主机提示，第 10.6 节写明主机提示与通知的区别与 no_tool_call；GitHub 新建 #101（修正两项在本机失败的测试，#43 依赖它）与 #102（最后一次主机提示要求调用工具，依赖 #43），#47 经核对关闭 / 处理 #47 执行中登记的架构问题

claude-opus-5-5 / 2026-09-26 16:10 / docs/architecture-issues.md 登记 #101 的架构问题：工作区出现链接后运行在下一次取快照时失败，停止原因记为 context_overflow、provider_error 或 host_commit_error，与实际原因不符；登记命令可以在工作区留下链接；拒绝原因带有主机绝对路径 / #101 从运行系统整体验证链接拒绝时发现设计没有覆盖的边界，交给架构师处理

claude-opus-5-5 / 2026-09-26 16:25 / docs/architecture-issues.md 登记 #101 的第二条架构问题：Responses 请求时限包含 openai SDK 的一次性初始化与主机落盘 / 修正流式超时测试时查明第一次请求在发出之前就会超时，交给架构师决定请求时限的计算范围

claude-opus-5-5 / 2026-09-26 17:00 / 新增 docs/stage-3/3.2a-registered-commands-e2e-report-2026-09-26.md，记录 #15 真实模型全链路验收的环境、两次运行（run_c4e724a13fb14af0 发现的适配器缺陷与 run_5f1aff849e244a37 的全链路结果）、登记命令动作回执与验收标准对照 / #15 要求按验收路径保留应用版本、运行身份、有序事件、检查回执、封存与采纳的证据

claude-opus-5-5 / 2026-09-26 17:10 / docs/requirements/execution-limits.md（D09）停止原因清单加入 `no_tool_call` 与 `workspace_unrepresentable`，并写明单次请求的时限只计算等待模型提供方的时间；docs/stage-3-plan.md 第 4.2 节新增「公开树」一行（按项目的忽略规则取得，参照 OpenCode 快照）与路径一律相对的规则；docs/architecture-issues.md 为 #101 的两条问题追加处理结论；docs/program-roadmap.md 第 2 节与 docs/design/architecture/overall-architecture.md 第 10 节写入 #101、#103 在 #43 之前，#102、#104、#105 在 #43 之后 / 处理 #101 登记的架构问题与 #15 真实验收发现的交付说明缺漏，安排新工单的顺序

claude-opus-5-5 / 2026-09-26 17:50 / docs/architecture-issues.md 登记 #103 的架构问题：`run_command` 的描述与工程部门提案合同中的「主机回执」没有区分动作回执与交付的检查回执 / 实施 #103 时发现请求中另有两处相关文字不在工单范围内，交给架构师决定是否修改

claude-opus-5-5 / 2026-09-26 18:22 / docs/architecture-issues.md 为 #103 登记的问题追加处理结论；docs/program-roadmap.md 第 2 节与 docs/design/architecture/overall-architecture.md 第 10 节加入 #106 / #103 发现请求中另有两处文字没有区分动作回执与检查回执，统一说法并排在 #43 之前

claude-opus-5-5 / 2026-09-26 20:02 / docs/current-baseline.md、docs/stage-3-plan.md、docs/program-roadmap.md 与 docs/design/architecture/overall-architecture.md 第 10 节把 3.2A 改为已验收（#12 至 #15 关闭，真实模型全链路 run_5f1aff849e244a37），删除基线中 #15 受凭据阻塞的开放项 / #15 真实验收完成并关闭

claude-opus-5-5 / 2026-09-26 15:10 / docs/architecture-issues.md 登记 #4、#5 验收标准与 ADR-0003、ADR-0004 现行内容的冲突及未拆工单的 D24 改动 / Stage 2.7 工单核对中发现的规范矛盾

claude-opus-5-5 / 2026-09-26 20:52 / docs/requirements/execution-limits.md（D09）与 docs/requirements/provider-retries.md（D17）中的模型步数上限改写为部门循环的参数 `max_model_steps` / #43 第 2 个提交把重试间隔、尝试次数与最大模型步数改为部门循环的参数（StepLimits），模块常量 `MAX_MODEL_STEPS` 已删除

claude-opus-5-5 / 2026-09-26 20:55 / docs/architecture-issues.md 为 2.7 核对登记的问题追加处理结论（由 #84、#48、#91 覆盖）；docs/current-baseline.md 第 5 节写明 2.7 工单的核对结果与 #7 等待 Messages 模型 / 2.7 工单核对完成

claude-opus-5-5 / 2026-09-26 21:40 / 新增 docs/research/fermat-formalization-prove2me.md，docs/research/README.md 登记新资料 / 用户要求在 research 下补充 Anthropic 费马大定理形式化博客与 Prove2Me 项目的一手来源调研及与 Yudao 的对照

claude-opus-5-5 / 2026-09-26 23:53 / docs/architecture-issues.md 登记裁决规则（U）直接读取工作区（路径解析与树摘要）与「控制核心不直接读写工作区文件」的冲突 / #43 第 4、5 个提交把工具许可与提案的提交判断搬入 U 时发现，需要架构师在动作合同之前决定这些依据的来源

claude-opus-5-5 / 2026-09-27 01:09 / docs/design/architecture/overall-architecture.md 第 6.3 节新增「工作区的事实」：U 需要的工作区事实由执行环境的只读查询提供，作为输入交给 U，依据的摘要写进承载判断结果的事件；第 6.1 节 P 与 U 的代码位置改为 assembly.py 与 adjudication.py；docs/architecture-issues.md 追加处理结论 / #43 第二段登记裁决规则直接读取工作区的问题

claude-opus-5-5 / 2026-09-27 01:15 / docs/architecture-issues.md 登记 Messages 协议流式回复中途断开时的错误分类与另外两种协议不一致 / #43 第 3 个提交的审查修正中增加真实 Provider 的事件序列场景时发现

claude-opus-5-5 / 2026-09-27 01:24 / docs/architecture-issues.md 为 Messages 流中途断开的分类问题追加处理结论（#108） / #43 审查修正中发现的原有缺陷

claude-opus-5-5 / 2026-09-27 02:59 / docs/architecture-issues.md 登记两条：步骤驱动取消时工具进程的停止放在第 14 个提交；安全节点接口的两类时点（proceed 与 settle） / #43 第 10 至 13 个提交执行中发现

claude-opus-5-5 / 2026-09-27 03:03 / docs/design/architecture/overall-architecture.md 第 5 节写明安全节点接口的两个操作，第 7.3 节写明进程类动作的超时与取消结束整个进程树、回执记为超时或已取消；docs/architecture-issues.md 为 #43 第三段登记的两条问题追加处理结论 / #43 第 10 至 13 个提交登记的问题

claude-opus-5-5 / 2026-09-27 05:04 / docs/architecture-issues.md 登记：提案校验之后、提交之前的变化没有公开的时点，替换 evaluate_proposal 的 6 项端到端测试已删除 / #43 第 15 个提交清理测试时发现

claude-opus-5-5 / 2026-09-27 05:22 / #43 完成后更新：docs/design/architecture/overall-architecture.md 第 5 节写明安全节点接口的四个操作，第 6.1 节写明流程编排、步骤驱动、写入口与执行层的代码位置，第 10 节写明已完成的工作与接下来的顺序；docs/program-roadmap.md 第 2 节第 5 项写明 #43 的完成情况；docs/current-baseline.md 第 1 节新增控制核心一行；docs/architecture-issues.md 为提案校验与提交判断之间的核对追加处理结论（由 #44 的流版本核对处理） / #43 于 2026-09-27 关闭

claude-opus-5-5 / 2026-09-27 11:44 / #44 完成后更新：docs/design/architecture/overall-architecture.md 第 5 节结束运行改为按流版本核对，第 6.1 节写入口一行改为 write_path.py、event_store.py 与 projection.py 的职责，第 10 节写明 #44 已完成；docs/program-roadmap.md 第 2 节第 6 项与 docs/current-baseline.md 控制核心一行写明 #44 的完成情况 / #44 于 2026-09-27 关闭

claude-opus-5-5 / 2026-09-27 12:55 / docs/architecture-issues.md 登记三条：取消进行中时激活与运行循环交回的运行状态（#107）、三种协议的传输诊断只有 Responses 有传输阶段（#108）、Messages 流中的过载错误与流式进度的协议差异（#108 代码审查） / #107 修正了取消与激活结束之间的先后，需要写进总体架构；#108 按工单保持 Chat Completions 的结果不变，另外发现的协议差异需要架构师决定是否开工单

claude-opus-5-5 / 2026-09-27 16:55 / docs/architecture-issues.md 登记一条：两个运行同时进行的测试按墙钟时限等待的主机工作包含接纳规格时的 16 个 Git 子进程（#107） / 负载更高时这项测试仍有失败，工单不允许加长等待，需要架构师决定减少子进程或调整测试核对的内容

claude-opus-5-5 / 2026-09-27 17:40 / docs/design/architecture/overall-architecture.md 第 5 节写明取消由发起的一方写入、交回的运行状态包含已经开始的取消；docs/architecture-issues.md 为 #107、#108 登记的四条问题追加处理结论（#111、#112） / #105、#107、#108 完成后处理登记的问题

claude-opus-5-5 / 2026-09-27 18:04 / docs/architecture-issues.md 登记四条：anthropic 的声明范围与锁定版本和 Messages 协议的计时不一致、事件对象中不由命令写入的事件的 actor 与 role、能力清单的覆盖层没有标识与负责的工单、命令行的其他子命令与数据目录的进程锁 / #72 执行与代码审查中发现，需要架构师决定

claude-opus-5-5 / 2026-09-27 18:10 / docs/design/app-and-interface.md 第 5.2 节写明 actor 由写入方经写入口声明、role 在 Stage 4 之前为空，第 6.1 节给出五个覆盖层的标识与由 #73 加入，第 7.2 节写明写入的子命令取得进程锁、只读的子命令以只读方式打开数据目录；docs/architecture-issues.md 为 #72 登记的四条问题追加处理结论 / #72 完成后处理登记的问题

claude-opus-5-5 / 2026-09-27 16:25 / docs/architecture-issues.md 登记两条：组织定义中的流转规则（交接顺序与阶段迁移、质检退回的去向、询问动作的含义、事项种类）仍是状态机代码（#48）；事项记录的定义版本与运行实际使用的定义、限额可能不同（#48） / #48 迁入定义的是写在代码中的文字、清单与参数，流转规则由定义驱动、升级以后继续旧事项的处理需要架构师决定

claude-opus-5-5 / 2026-09-27 21:05 / #48 完成后更新：docs/design/architecture/overall-architecture.md 第 6.1 节写明定义层、应用层与接口层的代码位置；docs/design/semantic-system.md 第 11 节工具一行改为定义与执行环境的位置；docs/architecture-issues.md 为 #48 登记的两条问题追加处理结论 / #48 于 2026-09-27 关闭

claude-opus-5-5 / 2026-09-27 21:05 / docs/architecture-issues.md 登记两条：AGENTS.md 的安装与测试命令与 dev 依赖组和项目环境不一致、Provider 连接信任的证书来源（共用的 SSL 上下文只信任 certifi，httpx2 默认使用操作系统证书库） / #113 执行与代码审查中发现，需要架构师决定

claude-opus-5-5 / 2026-09-27 21:25 / docs/architecture-issues.md 登记两条：观测查询中估计用量的 source、旧格式的流事件记录与负的用时没有写入方；测试中以替换读取结果模拟篡改的写法与「不使用 mock」的规则不一致 / #109 把观测与 smoke 的测试改为经公开接口核对时发现，需要架构师决定

claude-opus-5-5 / 2026-09-27 21:49 / docs/requirements/provider-retries.md（D17）写明证书校验失败不重试、三种协议共用信任操作系统证书库的 TLS 上下文；docs/architecture-issues.md 为 #113、#109 登记的四条问题追加处理结论（#114、#115） / #113 与 #109 登记的问题

claude-opus-5-5 / 2026-09-27 22:54 / docs/stage-3/organization-comparison-samples.md 第 29、348、444 行去掉估计用量（estimated）的来源与 estimated_totals / #109 按规则 1 删除了没有写入方的估计用量读取

claude-opus-5-5 / 2026-09-28 16:40 / docs/design/app-and-interface.md 第 4.3 节 decisions.list：返回内容加入所属的项目、事项与 run，筛选条件由「是否已回答」改为可多选的状态（等待回答、已回答、已撤销），写明等待用户的列表只取等待回答 / #49 核对：已撤销的请求混在「未回答」中，界面按项目列出时需要知道所属事项；参照 OpenCode 与 OMP 的等待请求做法，用户确认

claude-opus-5-5 / 2026-09-28 17:55 / 新增 docs/adr/0018-single-control-host-remote-execution.md（一台控制主机，执行环境有本机进程、本机容器、远程执行代理三种实现，执行权没有期限与续期）；ADR-0007、ADR-0012 的状态说明写明被取代的部分；ADR-0013 的数据库一条改为 SQLite 保存在控制主机上，删去 3.4B 的理由；ADR-0008、ADR-0014、ADR-0016 的 Stage 7 改为 Stage 6 / 用户确认 Yudao 只有一个人使用，会部署到多台电脑与树莓派，多机需求在执行环境

claude-opus-5-5 / 2026-09-28 17:55 / 重写 docs/program-roadmap.md：阶段按执行顺序重新编号（Stage 3 通用工具、可靠恢复与执行环境，新增 3.2C、删除 3.4B；Stage 4 运维部门与长时间运行；Stage 5 部门内协作、上下文与界面；Stage 6 受治理的系统演化，暂时不做），3.1 改为启动时自动继续，3.9 第一次执行 D32 对照实验 / 用户确认的成功标准：独立高质量交付，长时间自我运行并自我修复交付的软件

claude-opus-5-5 / 2026-09-28 17:55 / 需求记录：D29 由 distributed-deployment.md 改名为 remote-execution.md 并改写为远程执行环境；D27 写入 2026-09-28 确认的运维规则（单循环形态、观察日志状态与交互日志、修复事项自动开始、常设授权清单、同项目按优先级排队、紧急故障先回滚）；新增 D32 comparison-experiment.md；D09、D17 写入等待模型服务；D25、D26、D28、D31、D30、索引与各阶段需求概览按新编号修改 / 同上

claude-opus-5-5 / 2026-09-28 17:55 / 设计文档同步：stage-3-plan.md、恢复契约（启动时自动继续，上游拒绝凭据进入等待模型服务）、总体架构、系统架构原理、应用层与接口层设计说明（删除 3.4B 的命令与未采纳候选，决定种类加入等待模型服务的通知）、模型管理设计说明第 5.5 节、语义系统与部门内多角色设计说明、设计索引、当前验收基线、原型 v7 设计说明（删除 3.4B 的元素）、运行责任样例、decision.md 与 CONTEXT.md 的新术语 / 同上；各处链接改为 remote-execution.md

claude-opus-5-5 / 2026-09-28 17:05 / ADR-0018 增加「扩展途径」：执行能力不够时增加执行环境，模型服务限流时增加连接，一台控制主机容纳不下时按项目分成多个控制核心实例，各有触发条件，部门不作为拆分单位；ADR-0018 不再取代 ADR-0012 的多实例一项，ADR-0012 状态说明、decision.md、D29、路线图第 3 行、第 5.4 节与历史对照表同步 / 用户认为分布式与微服务化有助于资源调度和以后的并发，是很好的长期架构，同意写进 ADR-0018
claude-opus-5-5 / 2026-09-28 17:47 / 新增 ADR-0019（项目流跨 Yudao 版本保存，run 流跟随应用版本，run 事件版本不同时排空后升级）与 D33（接入已有项目，Stage 3 的 3.8）；路线图、Stage 3 计划、恢复合同、D27、D29、ADR-0018、D32、需求索引、阶段需求总览、验收基线、原型 v7 设计说明与 decision.md 按两轮讨论的结论修改：故障记录与修复失败上限、部署前备份与回滚兼容、交付软件密钥、运维读取的内容按外部内容处理、PRD 默认运行要求、未回答的决定、常开的控制主机、外部报到与看门狗、数据保留、通知只在界面显示、Stage 4 完成依据增加连续 5 个修复事项的请求长度检查 / 用户按两条成功标准核对路线图盲区后采纳推荐
claude-opus-5-5 / 2026-09-28 21:50 / 新增 docs/design/evaluation-scenarios.md（三个评测场景、评分、过程检查点、报告与评测工具的模块划分）；改写 D32（三个场景、OpenCode 基础分现在运行、质检具备浏览器工具）；需求索引、设计索引、路线图、Stage 3 计划、decision.md 与 CONTEXT.md（评测场景、完成度、丰富程度、质检误放行）同步 / 用户确认版本回归与 OpenCode 对照共用 WebGen-Bench 待办清单、FeatBench openai-agents-python-842、PRDBench 北京地铁票价三个场景，先运行 OpenCode 基础分
claude-opus-5-5 / 2026-09-28 21:44 / 新增 docs/research/evaluation-benchmarks.md（三个评测场景的来源、版本、检查与公开成绩，同档候选，没有选用的评测与原因）；评测场景设计、D32、设计索引、调研索引与 decision.md 写明：没有建立工单，实施之前由用户逐项审阅 / 用户要求先记录需求与设计摘要，评测是最重要的工作；调研下载的材料只在会话容器中，需要把核对过的事实写进仓库
claude-opus-5-5 / 2026-09-28 22:41 / 界面工作线提前到 Stage 3：路线图、Stage 3 计划、总体架构第 10 节、D30（新增「长时间运行以后的界面」）、需求索引、阶段需求总览、应用层与接口层设计说明（系统首页的待你决定与离开期间的报告、home.mark_seen、machines.list 与 machine.save、决定种类增加初始 PRD 确认与连续修复失败、排空状态、托盘提醒、能力清单的接口版本、访问令牌加 TLS、界面没有通过验收时工作包不关闭）、设计索引与原型 v7 设计说明的状态按用户决定修改；CONTEXT.md 增加「离开期间的报告」 / 长时间运行以后用户隔一段时间回来查看，Stage 3 与 Stage 4 的决定、登记与确认都需要界面，用户采纳推荐claude-opus-5-5 / 2026-09-28 22:55 / 访问方式改为本机与局域网两种，局域网内认证与加密保留位置并标为 TODO（应用层与接口层设计说明第 6.2、6.3 节、ADR-0015 状态、ADR-0018、D29、D30、总体架构、系统架构原理、Stage 3 计划、路线图、需求索引、阶段需求总览、D12 启动与凭据重读、设计索引、CONTEXT.md）；评测工作线与界面工作线并行，Stage 3 结束之前必须完成（路线图近期顺序与第 4 节、Stage 3 计划新增一行与 3.9 前置、D32、评测场景设计、需求索引） / 用户决定只在局域网内使用期间安全只占位，评测最重要但不需要先做好、本阶段结束之前必须完成
claude-opus-5-5 / 2026-09-28 23:35 / 新增 D34（浏览器与 computer use，Stage 3 的 3.2D）与调研记录 docs/research/browser-and-computer-use.md（Codex 69f7140、OMP、OpenCode 的做法与可选方案比较）；路线图与 Stage 3 计划加入 3.2D（依赖 3.2B、3.2C，3.9 的前置）；模型管理设计说明新增第 5.6 节部门的必需能力（质检为图像输入），第 5.5 节、恢复合同第 10 行加上相应的待恢复原因；D32 与评测场景设计改为使用用户提供的、有视觉能力的同一个模型，场景 1 依赖 3.2D；总体架构、需求与设计索引、调研索引、阶段需求总览、评测场景选题调研同步；CONTEXT.md 增加「必需能力」 / 评测要在 Stage 3 结束之前完成，场景 1 需要质检操作网页；用户要求参考 Codex，决定质检必须有视觉能力，评测模型由用户提供，安全按普通浏览器 MCP 的默认做法
claude-opus-5-5 / 2026-09-28 23:38 / docs/agents/triage-labels.md 新增自主推进模式的四个流程标签（in-progress、needs-review、review-passed、review-failed）及切换者；同时 CLAUDE.md 新增「自主推进模式」，AGENTS.md 分为共同要求、执行者与审查者三部分，新增 .opencode/agent/reviewer.md / 用户决定由 Claude 自主推进工单，omp 担任执行者，OpenCode 担任审查者
claude-opus-5-5 / 2026-09-28 23:50 / 质检的视觉能力改为只提醒：模型管理设计说明第 5.6 节改为「部门的建议能力」（不满足时照常保存并提醒，请求时按模型实际能力提供工具，不能看图时不提供 computer use，浏览器只给可访问性结构），第 5.5 节与恢复合同第 10 行删去相应的待恢复原因；D34、路线图、Stage 3 计划（3.2D 的完成依据）、总体架构、需求索引、阶段需求总览、D32、评测场景设计与 decision.md 同步；CONTEXT.md 的术语改为「建议能力」 / 用户决定质检部门设置时只提醒，不强制要求支持图像
grok-4.7 / 2026-09-28 23:55 / 新增 docs/research/computer-use-implementations.md（Anthropic 工具集与 claude-quickstarts dee7116 的虚拟屏幕、截图缩放与 17 个动作，OpenAI computer 工具与容器配方，Gemini 桌面动作与 0–999 坐标，OMP fdfeef1f78 的宿主桌面工具，OSWorld 的客户机环境）；docs/research/README.md、docs/research/browser-and-computer-use.md 与 D34 待设计项加上链接 / 用户要求调研 computer use 的实现，D34 的虚拟屏幕、截图尺寸与动作集合还没有设计
claude-opus-5-5 / 2026-09-29 00:28 / 新增 docs/prototypes/v8/design.md（原型 v8 设计说明：首页状态项、楼与地下室机房、离开期间的报告与关键事实回放、决定卡片、交接管道与传信管、质检试用台、同一项目排队调整顺序、按工作包分为九档、四个示例项目与四台机器、十九个场景）；D30 增加「原型 v8 的方向」并修改机房位置与元观察范围；ADR-0018、D29、路线图、Stage 3 计划（3.2C 与第 5.3 节）、总体架构、阶段需求总览改为在系统中登记机器、在项目中授权使用；应用层与接口层设计说明增加 work_item.reorder、machine_authorization.save、需要恢复备份的回滚决定、system.status 的首页状态项、home.away_report 的关键事实列表、project.loop 的机器、project.settings 的机器授权与运维设置，删除候选相关的两个命令与 ops.accept_responsibility；需求索引与 decision.md 同步 / 用户开始 v8 原型讨论，三轮问题全部采纳推荐
claude-opus-5-5 / 2026-09-29 01:06 / 新增 docs/prototypes/v8/BUILD.md（原型 v8 构建约定：界面层与示例后端分层、Y8.api 的能力清单、查询、命令与事件流、初始数据加事件日志的折叠与按位置读取、九档、数据形状、世界设定与跨文件标识、十九个场景的分配、任务分工）与原型核心代码（index.html、y8.js、contract/registry.js、contract/backend.js、contract/handlers/core.js、ui/kit.js、ui/app.js、ui/shell.js、ui/toolbar.js、styles/base.css） / 用户要求开始制作 v8 原型，架构师做核心设计与架构，简单逻辑交给 omp
claude-opus-5-5 / 2026-09-29 01:10 / 重写 docs/stage-3-plan.md（阶段结束时用户能做什么、各工作包涉及的架构层、按工作包父工单排列的工作包表与层次和阻塞规则、版本回归规则、强制升级优先级由 3.4A 验收、执行槽位为部署设置，删除 3.3 与 3.7）；新增 docs/design/local-tools.md（3.2A 的使用过程、工具边界与依赖，由计划第 4 节移出）并加入 docs/design/README.md；路线图 D24 移入 Stage 3、删除 3.3、3.7 分到 Stage 5 与 Stage 6、依赖图与近期顺序按工作包父工单重画、历史编号表增加三行；模型管理设计说明增加模型能力表（models.dev 快照）、模型访问定义的输入方式、建议能力的提醒规则，第 4.4、4.7、5.5 节改为进入待恢复；D24 需求、CONTEXT.md（调用目标、模型访问定义、模型能力表）、Provider 层设计说明同步；应用层与接口层设计说明增加 source_directory.save、runtime.start_drain、runtime.force_upgrade、catalog.change_impact、提醒字段与能力表字段，machine_authorization.save 的运行环境与常设授权移到 Stage 4，随工作包验收界面的名单补全；总体架构第 8、10 节、阶段需求总览、当前验收基线同步；ADR-0019 项目流清单加入语义系统的跨事项内容，语义系统设计说明第 4 节增加事件流的划分，D25 增加第 29 条；startup-provider-reload 的删除目录文件改为待恢复 / 用户要求按新的路线图与总体架构重排 Stage 3 任务，并核对全部工单的依赖与拆分
opencode-go/deepseek-v4.1-flash / 2026-09-29 01:33 / 总体架构第 6.1 节的执行环境一行写明从封存快照建立工作区、执行动作并交回回执与交付封存所需的 snapshot() / 工单 #110 把工作区的建立与交付封存改到执行环境

opencode-go/deepseek-v4.1-flash / 2026-09-29 01:45 / docs/architecture-issues.md 登记 #45 提交 2 接入运行循环之前的六条待决定项（上游拒绝凭据的分类、`department_activated` 的目标字段、创建事项时的校验、部门默认读取与解析的持锁入口、删除 `provider_credentials_lost`、事项级窗口是否参与阈值） / 提交计划要求提交 2 等架构师对这六条答复，工单上仍没有答复；按 AGENTS.md 的架构问题登记要求记录冲突、可选做法与建议，避免把未确定的形状先写进事件序列基准

opencode-go/deepseek-v4.1-flash / 2026-09-29 03:20 / docs/architecture-issues.md 在 #45 六条待决定项下面追加架构师的答复与处理；docs/requirements/department-providers.md 的「当前状态」与「配置与生效」改为按每次请求解析调用目标的实现现状（创建事项不再解析、解析失败进入待恢复、新修订从下一次请求起生效），第 4 点的启动前检查注明由 #89 按项目部门设置在新建事项前引入 / 工单 #45 第 2 轮的任务评论给出六条答复，文档需要与实现以后的行为一致
claude-opus-5-5 / 2026-09-29 01:42 / 新增 docs/design/execution-environment.md（3.2C 执行环境服务：合同与三种实现、本机容器、执行代理、心跳与结果未知、执行位置、认证 TODO、验收场景与工单拆分）与 docs/research/execution-environment.md（docker-py、Anthropic computer-use-demo、OpenCode、OMP、Bazel 远程执行 API、心跳参照）；新增 docs/design/existing-project-onboarding.md（3.8 建档事项：部门产出、初始 PRD 的确认往返、基线采纳、大仓库、失败与中断、工单拆分）；docs/design/README.md 增加两项索引 / Stage 3 自主推进，3.2C 与 3.8 拆分工单之前需要设计说明
claude-opus-5-5 / 2026-09-29 01:20 / 原型 v8 新增项目楼层画面 pixel/floor.js（交接管道、传信管、回流管道、大厅队列与阀门、通往机房的门、五种覆盖层）、楼与机房 pixel/building.js、决定卡片 ui/cards.js、回放时间轴 ui/replay.js、画面面板 ui/scenes.js、首页 ui/views/home.js 与 styles/home.css；BUILD.md 增加补丁的 put 形式 / 按 v8 设计说明制作首页与循环画面
claude-opus-5-5 / 2026-09-29 01:46 / 原型 v8 的 BUILD.md 与能力登记表按新的设计说明修改：project.onboard 成为正式名称（参数增加源目录名称），增加 onboarding.restart、execution_placement.save，3.8 的临时事件改为 initial_prd_proposed、project_decision_*、baseline_adopted 等正式名称，初始 PRD 的回答写入 project_decision_answered；合同待补只剩查询的 at 参数；删除 CHANGELOG 中重复的一行 01:10 记录 / 3.2C 执行环境服务与 3.8 接入已有项目的设计说明已经写成
opencode-go/deepseek-v4.1-flash / 2026-09-29 03:45 / docs/architecture-issues.md 登记 #76 的两条（桌面客户端页面的来源字符串尚未确定；事件流订阅的验收依赖 #75） / 执行中遇到的规范遗漏与工单依赖按规则登记
opencode-go/deepseek-v4.1-flash / 2026-09-29 03:51 / docs/architecture-issues.md 登记一条：#77 目录修订号同时覆盖定义与部门默认，按修订号比较的准入陈旧标记因此比设计第 4.4 节的字段级口径粗 / 记录执行中发现的与设计口径的差异与建议
claude-opus-5-5 / 2026-09-29 07:20 / 模型管理设计说明第 4.3、4.4、10 节：删除模型测试中的图像请求，输入方式与新增的「是否接受要求调用工具」都不影响准入，值来自模型能力表与用户声明并直接使用；应用层与接口层设计说明的 catalog.model.test 与 catalog.connection.save 同步；docs/architecture-issues.md 中 #102 条目的处理改为已决定 / 用户决定信任 models.dev，出错时替换来源，不在准入中叠加核实
claude-opus-5-5 / 2026-09-29 07:24 / ADR-0002 容量预填加上模型能力表，输入方式与是否接受要求调用工具保持准入，准入作废后进入待恢复；ADR-0003 加入模型能力表（发布前由脚本从 models.dev 提取，随版本发布，运行时不刷新）；ADR-0005 调用目标带输入方式，模型无法使用时进入待恢复 / 用户同意三份 ADR 与模型管理设计说明保持一致
claude-opus-5-5 / 2026-09-29 07:30 / D17 的 TLS 上下文改为每个线程共用一个 / 用户确认；与 #114 的实现和 docs/architecture-issues.md 的处理一致
claude-opus-5-5 / 2026-09-29 07:50 / ADR-0019 增加机器流，规则 1 的例外改为项目流与机器流（CLAUDE.md、AGENTS.md）；ADR-0018 写明本机容器经本机端口用同一份 HTTP 合同调用执行代理、本机进程在进程内调用、运行环境 Stage 4 起指定；3.8 与 3.2C 设计说明的待确认项改为用户确认的决定（work_item.create 删除代码快照来源、检查时限 600 秒、验收项目 openai-agents-python、机器流、树清单 v2、机器不可用时进入待恢复、远程验收等树莓派）；应用层增加 project.onboard、onboarding.restart、execution_placement.save 与拒绝原因 container_engine_unavailable、source_invalid；评测场景 2 先建档，场景镜像登记为本机容器的基础镜像；D29、D33、总体架构第 3、7.3、7.4、8、11 节、CONTEXT.md（机器流、执行位置、运行工作区、检查工作区、执行环境池、执行代码摘要）、本地通用工具、Stage 3 计划、需求总览与设计索引同步 / 用户对 3.8 与 3.2C 的待确认项采纳推荐，暂时不能提供树莓派
claude-opus-5-5 / 2026-09-29 08:05 / 执行环境服务与接入已有项目设计说明的工单拆分节写上工单编号（#128–#131、#140–#145；#134–#139）；树莓派上的系统服务验收归入工单 I；模型管理设计说明第 4.1 节写明能力表由提取脚本在发布前生成 / 剩余工单已经建立
claude-opus-5-5 / 2026-09-29 08:12 / 新增 docs/design/browser-and-computer-use.md（3.2D 设计草稿：试用会话与试用镜像、Playwright MCP、虚拟屏幕与 8 个屏幕工具、按输入方式提供工具、截图证据、试用用例与逐条结论、恢复契约、工单拆分、第 16 节待确认）并加入设计索引 / 用户要求起草 3.2D 的设计
claude-opus-5-5 / 2026-09-29 08:22 / 原型 v8 各部分完成（omp 任务 A1 系统数据、A2 待办清单与 openai-agents、A3 地铁票价与温湿度服务、B 项目页面、C 部门页面、D 部门房间与动作图鉴、E 系统页，架构师集成并修正：采纳与修复使用各自的事件、画面增加「等待你的决定」、场景 19 按回放的实际范围重写、概览循环画面的布局、外壳对未部署项目的处理）；九档全部页面与十九个场景没有控制台错误；docs/prototypes/CHANGELOG.md 增加 v8，v8 设计说明、D30、需求索引与路线图第 4 项的状态改为「原型文件已制作，待用户审阅」 / 按 v8 设计说明与构建约定制作原型
claude-opus-5-5 / 2026-09-29 09:30 / 原型 v8 收尾（omp 任务 F）：Stage 5 之前的事件与场景不出现角色名，界面不直接显示英文枚举值与内部标识，阅读已有项目由建档事项的读取工具事件驱动，模型测试不再测图像并增加「是否接受要求调用工具」列，运行环境与常设授权只在 Stage 4 起出现；初始 PRD 的「提出修改」必须附说明（否则 not_allowed）；BUILD.md 增加画面状态 waiting_decision；九档全部页面与十九个场景复查没有控制台错误 / 集成检查发现的文字与规则问题，以及应用层设计说明 initial_prd 一行的规则

opencode-go/deepseek-v4.1-flash / 2026-09-29 10:30 / docs/architecture-issues.md 登记：应用层保存的读取模型（数据目录的 read-models.sqlite，只读打开时在内存中重建）与「只有事件日志打开数据库并写 events、projections、commands」的源码检查冲突，检查保留原有意图并为 app/read_models.py 加具名例外 / #73 按设计说明第 4.2 节保存可以删除后重建的调用尝试表与流转记录，等待架构师确认
claude-opus-5-5 / 2026-09-29 10:50 / 3.2D 设计说明改为已确认（启动方式由工程写在交付说明的 launch 字段，缺少时退回工程；逐条验收条件的通过证据才能放行；新增质检无法核验；所有本机容器带试用层；不提供 browser_evaluate 与 browser_run_code_unsafe；8 个屏幕工具），第 17 节写上工单 #147–#155；CONTEXT.md 新增试用一组术语；D34、应用层（run.trials、evidence.screenshot、质检无法核验，查询 34 个）、模型管理第 5.6 节、执行环境服务第 5.2.3 节、总体架构第 7.3、7.4 节、恢复契约第 4 节、语义系统第 13 节、评测场景第 9 节、Stage 3 计划、路线图第 10 项、需求索引、需求总览与设计索引同步 / 用户对 3.2D 设计第 16 节采纳推荐
claude-opus-5-5 / 2026-09-29 10:58 / 原型 v8 按已确认的 3.2D 设计修改：设计说明第 6 节增加决定种类「质检无法核验」，第 7.1 节试用记录改为截图标明模型是否看到并可查看原尺寸与可访问性结构摘录，第 7.3 节交付增加交付说明中的启动方式，第 8.3 节试用台的截图来自 1280×800 的虚拟屏幕、模型不能看图时照常显示截图并标明「模型只读取文字」，删除第 15 节中已确定的截图尺寸一项；原型代码增加查询 run.trials、evidence.screenshot 与决定种类 cannot_verify，部门工作间的试用记录显示缩略图与原尺寸；BUILD.md 同步 / yudao-67 转告 3.2D 设计（36f0a03）与原型的两处不一致
claude-opus-5-5 / 2026-09-29 14:19 / 应用层与接口层设计说明第 4.1 节增加「按位置读取（回放）」：可回放的查询接受 at 参数，返回处理到该位置时的快照；第 4.3 节 system.status、projects.list、decisions.list、project.loop、machines.list 的「位置」一列标为可回放；第 6.1 节能力清单的 queries 标明是否可回放；decision.md 记录决定；原型 v8 删除「合同待补」的标注，BUILD.md 同步 / 用户同意把原型回放用的 at 参数写进接口合同

claude-sonnet-5 / 2026-09-29 15:58 / 修改 core-and-materials.md 第 2 节「四条不变量」（权威拓扑改为属于 ADR-0014 的组织定义，只随用户批准的新版本改变，并加入裁决规则 U 采纳新版本前校验权威关系结构的三条标准）与第 3 节「人留在意图这一层」（产品部门的解释立即生效，用独立下游核验的有无判断要不要阻塞等待用户）；同步修改文中另外两处「权威拓扑是设计时的常量」的措辞；修改 adr/0014-versioned-definitions.md 理由部分的措辞；新增 adr/0020-block-only-when-no-downstream-check.md；decision.md 记录决定 / 用户认为「权威拓扑是设计时的常量」「目标层只由用户修改」两条写法容易把事情说死、有讨好与免责的嫌疑，要求按第一性原理重新审查并写回文件

claude-sonnet-5 / 2026-09-29 16:10 / 新增 docs/prototypes/v9/design.md（像素引擎改为实体—组件—系统结构：房间与管道图结构声明代替 layoutFor/pipesFor 写死坐标，事件变任务或者信号、任务目录复用 v8 design.md 第 5.4、8.3 节两张表，角色头顶对话框补完 v8 第 8.3 节已写但没实现的思考气泡；范围明确只换引擎结构，屏幕、导航、画风、事实对照表不变，不新增部门）；docs/prototypes/CHANGELOG.md 增加 v9 条目 / 用户确认继续做原型，验证游戏化方向的第一步——结构改动要现在做、范围收到最小，画法与导航之类的扩展留给之后逐步验证
claude-opus-5-5 / 2026-09-29 16:10 / 新增 docs/design/test-pyramid.md（测试分层：三层定义与目录、边界检查、时间上限、各角色运行的层、集成层每 5 个 PR 批量运行与失败处理、测试往下层移、输出读取），设计索引增加条目 / 全量测试 28 分钟、每个执行者与审查者都运行并把输出带进上下文，并发运行时内存耗尽；用户要求整理成三层的测试金字塔，并决定审查者只跑单元与模块层、集成层按批运行
claude-opus-5-5 / 2026-09-29 16:40 / test-pyramid.md 第 8 节写明层之间的导入规则由 import-linter 契约检查；第 9 节把往下层移分成可以同时进行的两部分，写明第 2 步合并后进行中分支的处理；新增第 10 节保存用户已确认的规则文件修改原文 / 用户确认规则文件的修改内容，等第 2 步合并以后写入
claude-opus-5-5 / 2026-09-29 16:55 / 测试分层设计说明与设计索引写上工单 #157（#158 至 #161） / 建立测试分层的父工单与子工单
claude-opus-5-5 / 2026-09-29 17:18 / 测试分层设计说明改为用登记表 harness/tests/layers.toml 表示分层：测试文件与辅助文件原地不动，不建层目录，混合文件登记为最高一层，根 conftest 按登记表加标记并按层检查，运行命令改为按标记选择；第 3、8、9 节重写，第 10 节的规则文件修改已写入并删除；AGENTS.md 常用命令（uv、三层命令、执行者与审查者不运行全量）、执行者自测与交付、审查者测试与结论，CLAUDE.md 自主推进模式增加第 4 步集成层批量运行 / 用户要求用对进行中工单影响更小的方式实施测试分层，并先修改规则
opencode-go/deepseek-v4.1-flash / 2026-09-29 17:40 / 合入 main（a540917）后的记录整理：#110 的第 1 轮记录与 #45 的两轮记录按时间顺序并列保留，没有改动既有条目 / 工单 #110 第 2 轮把分支合入 main 并解决 agents_jour.md 与 docs/CHANGELOG.md 的追加冲突
claude-sonnet-5-5 / 2026-09-29 18:07 / docs/prototypes/v9/BUILD.md 与 design.md 中部门房间 room.js 的范围改为原样保留：分层图去掉 room.js 到 ecs.js 的连线，文件结构、负责者表（去掉任务 R）、接口说明、渲染说明与设计说明第 1、7 节同步修改；BUILD.md 第 3.3 节代码注释里的「任务 T」改为「任务 F」 / 用户确认取消任务 R，v9 只改项目楼层与楼里的画面
claude-opus-5-5 / 2026-09-29 18:20 / docs/architecture-issues.md 中 #73 读取模型数据库一条写入处理：采纳具名例外，读取模型使用自己的 read-models.sqlite，不打开事件日志的数据库、不写三张日志表 / #73 审查通过并合并
claude-sonnet-5-5 / 2026-09-29 18:21 / 新增 docs/prototypes/v9/checks/（env.js、record.js、replay.js）：楼层画面的确定性验收脚本，record.js 在 v8 页面播放全部场景并录下项目楼层画面收到的调用，replay.js 把录下的调用按固定的时钟与随机数回放给 v8 与 v9 的楼层画面，在静止检查点比较整张画面的像素与小人的位置姿势 / 任务 F 改写楼层画面，需要不依赖执行者自述的客观验收依据
claude-sonnet-5-5 / 2026-09-29 19:19 / docs/prototypes/v9/js/pixel/ecs.js 与 floor.js 改写为实体—组件—系统：房间与管道由声明排布，部门角色的持续状态取自快照（ch.rest），事件变成任务放进队列，交接由两端角色的任务与沿管道移动的包裹实体组成，小人头顶按当前任务显示对话框，待机时偶尔起身走动；building.js 由任务 B 改写并合入，room.js 保持 v8 原样；checks/ 的 replay.js 增加减少动画选项、随机走动开关与有差异时重跑一次 / 实现 v9 设计说明第 3 至 6 节，静止画面与 v8 逐像素相同
claude-sonnet-5-5 / 2026-09-29 19:47 / docs/prototypes/v9/BUILD.md 第 2、3、4 节与 design.md 第 3 至 8 节按已实现的 ecs.js 改写：实体与组件的形状、房间与管道的声明、任务目录、队列规则（持续状态、上限、静止、待机走动）、渲染与对话框、验收脚本；docs/prototypes/CHANGELOG.md 的 v9 条目改为已交付；docs/prototypes/v9/checks/ 增加 matrix-home.js、matrix-floor.js、scenarios.js、walkers.js、identity-building.js、life.js / 设计说明与构建约定和代码保持一致；用户确认按已实现的内容改写
claude-sonnet-5-5 / 2026-09-29 21:12 / docs/prototypes/v9/design.md 与 BUILD.md 按补全后的实现改写：第一步补上多角色、空闲角色自己找事做、管道持续流动、机房与楼的实体化，第二步运维部门只写声明（新增 js/pixel/floor-decl.js），第三步决定请求在世界里回答（新增 js/pixel/decision-card.js，项目概览页的决定区块改为大厅的板与文字列表）；docs/prototypes/CHANGELOG.md 的 v9 条目同步；docs/prototypes/v9/checks/ 增加 behaviors.js，replay.js、life.js、record.js 增加自主行为开关与录制选项 / 用户提供架构师 16:10 的原话，要求按原话把没做到的部分补上
opencode-go/deepseek-v4.1-flash / 2026-09-29 21:35 / harness/tests/openapi/openapi.json 按服务端重写（`--write-openapi-snapshot`）：合入 main 后同一份文档里同时包含 16 个应用层项目查询（含读取模型）与 #77 的目录查询、目录与凭据命令；harness/app/application.py 的能力清单把 `*PROJECT_QUERIES` 与目录命令、查询合并；harness/tests/test_api.py 的命令集合、查询集合与覆盖层断言按合并后的清单重写 / #77 第 3 轮合入 main（#45、#73、#110）
claude-opus-5-5 / 2026-09-29 20:15 / docs/architecture-issues.md 中 #76 两条与 #77 一条写入处理：客户端页面来源固定为 yudao://app（#79 沿用）；局域网订阅事件流的验收移到 #75；准入陈旧改按受影响字段判断（#86） / #76、#77 审查通过并合并


claude-sonnet-5 / 2026-09-29 22:40 / docs/examples/providers.json 按 ADR-0004 重写：协议移到 Provider 配置（新增 opencode-go-responses 与 opencode-go-chat 两条共用凭据引用的连接），模型访问定义删除 protocol 与 admitted_protocol；README.md「配置 Provider」示例同步（protocol 移到 provider），并写明请求路径拼接规则与 Provider 连接只信任操作系统证书库、SSL_CERT_FILE/SSL_CERT_DIR 不起作用 / #84 实施 ADR-0004（一份连接一种协议）与 #114 条目（README 的 Provider 证书说明），示例与文档与实现一致
claude-sonnet-5-5 / 2026-09-29 22:28 / docs/prototypes/v9/design.md 与 BUILD.md 按独立代码审查的修复同步：决定板立在大厅地面上，卡片盖章期间与说明栏的文字留着，翻页与关闭按钮分开，回放到过去的时间点没有角色，运维数据出现时世界重新声明并保留在途的包裹与角色，材料放不下时截断、选项太多时收窄；docs/prototypes/v9/checks/behaviors.js 增加 15 项 / 独立审查发现 9 处缺陷，其中 Stage 5 回放报错、决定单被插队丢失最严重，全部修复并各有回归检查
claude / 2026-09-30 02:25 / docs/architecture-issues.md 追加 #75 的两条：#75 `role` 范围参数在 events 表没有 role 索引、`EventStore.read()` 没有 role 条件（Stage 5 需要补）；#75 事件对象的 `actor` 在合同里是非空字符串而日志列可为 NULL，本次把空提出者写成空串 / #75 实现过程中发现，交架构师确认
claude-sonnet-5-5 / 2026-09-30 00:50 / docs/prototypes/v9/design.md 第 1、4、6、9、10、11 节、BUILD.md 第 1、2、3、4 节与 docs/prototypes/CHANGELOG.md 的 v9 条目按小人头顶的说话气泡改写：项目楼层与部门房间共用 js/pixel/say.js 的目录，交接、分派、询问的两端各说一句，收到询问的房间走到传信管口取信，减少动画时照样显示；docs/prototypes/v9/checks/behaviors.js 增加 33 项 / 用户指出小人的互动没有气泡（例如工程经理代表部门提交交付说明时头顶应该说「现在提交交付说明」），部门房间画面原先完全没有说话气泡

opencode-go/deepseek-v4.1-flash / 2026-09-30 10:20 / 模型管理设计说明第 3 节两张表（模型访问定义与调用目标）与 ADR-0005 的调用目标枚举加入「是否接受要求调用工具」；第 4.3、4.4 节已写明默认为接受、修改保持准入 / 工单 #102 实施该字段，文档与实现保持一致
claude-sonnet-5-5 / 2026-09-30 01:30 / docs/prototypes/v9/ 改名：js/y8.js 改名为 js/y9.js，全局对象 Y8 改为 Y9，CSS 类名前缀 y8- 改为 y9-，存储键前缀 y8. 改为 y9.，顶栏标签、页面标题与样式文件的标题写 v9；checks/env.js 增加 spaceOf，record.js、replay.js、identity-building.js、life.js 按页面所属的版本取命名空间与存储键；BUILD.md 开头说明命名随版本改名，design.md 状态改为定稿；docs/prototypes/CHANGELOG.md 的 v9 条目增加版本标识与定稿两项 / 用户要求确保原型是 v9 并结束原型设计，v9 由 v8 整份复制而来，界面与代码里仍然是 v8 的名字，与 v7 到 v8 的做法不一致
claude-sonnet-5-5 / 2026-09-30 01:58 / docs/program-roadmap.md（近期顺序图的原型节点、第 4 项界面工作线的原型依据改为原型 v9 并注明原型设计已结束，更新日期与说明补一句）、docs/design/README.md、app-and-interface.md、existing-project-onboarding.md、execution-environment.md、browser-and-computer-use.md 中对原型 v8 的引用改为原型 v9：整体性的引用（#125 的依据、原型的示例项目、构建约定的链接）直接改为 v9，指向章节号的引用写成「原型 v9 沿用 v8 设计说明第 N 节」；app-and-interface.md 的依据一行去掉「尚未制作，完成后替换链接」，改为 v9 设计说明与构建约定的链接；五份设计文档的更新日期改为 2026-09-30 / 用户要求在原型设计结束以后，把设计文档与路线图里的原型 v8 引用改成 v9；v9 的设计说明与构建约定只写与 v8 不同的地方，屏幕清单、页面导航与接口层的章节仍在 v8 的文档里，所以章节号引用保留 v8 设计说明作为出处
muse-spark-1.3-contributor-free / 2026-09-30 02:34 / harness/tests/openapi/openapi.json 按服务端重写（--write-openapi-snapshot）：#85 第 1 轮给 CatalogCandidatesCollectedPayload 增加 candidates 字段后快照未同步，本轮合入 origin/main 重跑 test_openapi_snapshot 时发现；重写后的差异只有 candidates 字段与其在 required 列表中的一项，并在 harness/tests/openapi 运行 npm run check 由快照生成 TypeScript 类型并编译通过 / #85 第 2 轮按任务评论合入最新 origin/main 后重跑 test_layers 与 test_openapi_snapshot，快照是接口合同的记录，有意的加字段变化要用测试自带的重写开关重新生成
claude-opus-5-5 / 2026-09-30 00:00 / docs/decision.md 新增「自举作为核心目标；单一写入角色是短期取舍；质量检查按部门分为工序；变异与复杂度做成研发工具」一条 / 用户在讨论变异测试、复杂度检查与测试流程进入 Yudao 时作出的决定
claude-opus-5-5 / 2026-09-30 00:53 / docs/decision.md 新增「圈复杂度与变异测试在本阶段末手动进行；工具放到下一阶段」一条，2026-09-29 一条的「影响」改为需求写进 D35、自举的 ADR 与路线图等的调整先经用户确认；新增 docs/requirements/self-hosting.md（D35 自举：用户原话、已确认的五项、讨论中的分析、前提与现在的路线位置、待用户确认的事项），docs/requirements/README.md 增加 D35 一行 / 用户决定当前阶段不建工具、不改动开发流程的规则，Stage 3 结束之前与 Claude 手动进行一次圈复杂度与变异测试，先把以后要做的事情规划好
claude-opus-5-5 / 2026-09-30 00:53 / 新增 docs/research/complexity-and-mutation-testing.md（本仓库的复杂度分布、mutmut 3.8.0 在 compaction.py 与 collaboration.py 上的试跑与成本估算、手动进行的步骤、工具的事实与成熟做法），docs/research/README.md 增加索引 / 保存 2026-09-29 至 09-30 的实测与调研结果，作为本阶段末手动检查的方法与下一阶段研发工具的依据
claude-opus-5-5 / 2026-09-30 00:53 / docs/design/README.md 测试分层一条的内容按设计说明改为登记表 layers.toml 与已有的辅助文件，状态与 docs/design/test-pyramid.md 的状态写明同日暂缓 / 索引与设计说明不一致；#157 与 #158 已由用户在 2026-09-29 决定暂缓
claude-opus-5-5 / 2026-09-30 12:10 / docs/program-roadmap.md 第 1 节 Stage 3 的状态与第 2 节近期顺序图按工单进度更新（#45、原型 v9 并入已完成，各工作包的完成数与执行中的工单）；docs/stage-3-plan.md 开头状态、第 3 节各工作包的子工单编号（#126、#140–#145、#134–#139、#146、#127）与原型依据改为 v9、第 8 节补两次集成层批量运行的结果；docs/current-baseline.md 的代码起点改为 1bbd5b81，新增集成层批量运行、用户决定与调用目标解析、应用层与接口层、模型管理四行 / 整体状态核对：三份状态文档停在 2026-09-29，没有反映此后合并的 #45、#73、#74、#76、#77、#84、#85、#102、#110 与原型设计的结束
claude-opus-5-5 / 2026-09-30 14:51 / 新增 docs/adr/0021-client-pixel-view-follows-v9-structure.md（正式客户端的像素画面按原型 v9 的实体—组件—系统结构实现，技术按 ADR-0015）；docs/stage-3-plan.md 开头状态、第 3 节（界面工作线与各工作包的工单编号、前置写法、父工单之间只保留两处阻塞、D21 由 #80 实现、#172 与 #173）、第 7 节（圈复杂度与变异测试）、第 8 节（关键路径），新增第 9 节「试用里程碑」；docs/program-roadmap.md 第 2 节写明像素画面的实现方式、界面工单与四个试用里程碑；docs/requirements/README.md 的 D21、D24、D29、D30、D32、D33 六行与 docs/design/README.md 中模型管理、执行环境服务、浏览器与 computer use、接入已有项目、应用层与接口层、评测场景、恢复契约的状态行按实施进度与里程碑更新；docs/decision.md 新增 2026-09-30「Stage 3 按四个试用里程碑推进，正式客户端的像素画面按 v9 结构实现」 / 用户要求梳理 Stage 3 的工单、任务分解、架构依赖与需求管理，并要求有自己能试用和核对的里程碑；经逐项讨论确定里程碑、界面拆分与像素画面的实现方式
claude-opus-5-5 / 2026-09-30 15:02 / docs/design/evaluation-scenarios.md 开头状态（审阅完毕、各部分所属的里程碑）、第 1 节版本回归的时机、第 3 节时间上限与超时的评分、第 10 节实施顺序（里程碑与依赖、界面智能体与裁判沿用的做法）；docs/requirements/comparison-experiment.md 状态行；docs/design/browser-and-computer-use.md 第 14 节场景 7、docs/design/existing-project-onboarding.md 第 10 节第 12 项与工单表、docs/design/execution-environment.md 第 10 节末段改为版本回归在里程碑试用之前运行；docs/stage-3-plan.md 第 3、7、9 节，docs/program-roadmap.md 第 2 节第 5 项，docs/requirements/README.md 的 D32 与 docs/design/README.md 的评测场景条目同步；docs/decision.md 新增「评测场景设计审阅」 / 用户逐项审阅评测场景设计，确定评测各部分所属的里程碑、版本回归在每个里程碑试用之前运行、超时按最后一次封存的交付评分
claude-opus-5-5 / 2026-09-30 15:21 / docs/stage-3-plan.md 第 3 节评测工作线一行与第 9 节 M2、M3、M4 三行，docs/design/evaluation-scenarios.md 开头状态，docs/design/README.md、docs/requirements/README.md 与 docs/requirements/comparison-experiment.md 的评测状态写上工单 #188 至 #198 / 用户运行 /to-tickets，#118 拆成 11 张子工单并按里程碑分组
claude-opus-5-5 / 2026-09-30 15:48 / docs/design/evaluation-scenarios.md 第 3 节模型一行、第 4.3 节与第 9 节写明评测使用的模型与模型服务的环境变量；docs/requirements/comparison-experiment.md 增加用户原话、已确认的模型一条与实现状态；docs/decision.md 新增「评测使用的模型」 / 用户提供模型服务并指定被测模型 DeepSeek V4.1 Flash、界面智能体 gh/gemini-3.8-flash、裁判 cc/claude-sonnet-5-5，三者经核对都能读图
claude-opus-5-5 / 2026-09-30 16:02 / docs/design/evaluation-scenarios.md 第 4.3 节、docs/requirements/comparison-experiment.md（原话与已确认的模型一条）、docs/decision.md「评测使用的模型」中的裁判改为 qdcn/qmodel_38max / 用户指定裁判改用 qdcn/qmodel_38max，经核对能读图
claude-opus-5-5 / 2026-09-30 16:54 / docs/architecture-issues.md 中 #16 定义版本决定请求一条写入处理：写在 run 流，种类 definitions_changed，阻塞范围为 run / #16 审查通过并合并
claude-opus-5-5 / 2026-09-30 17:47 / docs/architecture-issues.md 中 #75 两条写入处理：按角色筛选的索引与 read() 条件由 Stage 5 实施（#50 评论）；事件对象中历史事件的空提出者表示「写入时没有声明」，作为 actor 的缺省含义 / #75 审查通过并合并
claude-opus-5-5 / 2026-09-30 18:31 / docs/decision.md「评测使用的模型」补充裁判是 Qwen3.8 Max；新增「真实 Provider 验收使用 9router；长期目标可以修改；暂停的 run 可以继续；#155 的文本模型」与「远程执行验收使用的开发板是 Orange Pi AIpro」两条 / 记录用户对 Stage 3 待澄清事项的答复与核对的事实
claude-opus-5-5 / 2026-09-30 18:58 / 长期目标可以修改：docs/design/app-and-interface.md 第 3.2 节增加 `project.set_goal`、第 10 节第 12 项写明规则，docs/design/architecture/overall-architecture.md 第 11 节删去这一待讨论项；暂停以后继续：docs/requirements/execution-limits.md（D09）写明决定请求与继续的规则，app-and-interface.md 第 3.3 节与 overall-architecture.md 第 7.4 节的决定表增加这一种并补上定义版本的决定请求，CONTEXT.md「决定请求」同步；开发板改为 Orange Pi AIpro：docs/design/execution-environment.md（状态、第 1.1、5.3.2、5.3.4、6.1、10、11 节与工单表，安装包由控制主机提供，升级使用 --reinstall）、docs/stage-3-plan.md（第 1、3、8、9 节，并加入 #203、#204）、docs/program-roadmap.md、docs/requirements/remote-execution.md、docs/adr/0018-single-control-host-remote-execution.md、docs/design/architecture/core-and-materials.md、overall-architecture.md、CONTEXT.md、docs/design/existing-project-onboarding.md、docs/requirements/existing-project-onboarding.md、docs/design/README.md、docs/requirements/operations-department.md、docs/requirements/stage-requirements-overview.md、docs/requirements/README.md（D09、D29）；app-and-interface.md 增加查询 `agent.package`；docs/decision.md 两条写明修改文件 / 用户确认按清单修改文档，并建立 #203、#204
claude-opus-5-5 / 2026-09-30 19:10 / docs/stage-3-plan.md 第 3 节 3.9 一行、docs/program-roadmap.md 第 13 项、docs/requirements/stage-requirements-overview.md 3.9 一行写明组合验收使用 openai-agents-python，浏览器与 computer use 的结论引用 #155；docs/decision.md 新增「3.9 使用 openai-agents-python；模型服务不限流；开发板的登录」 / 用户采纳 3.9 的推荐，说明模型服务不限流，开发板的公钥由架构师添加
claude-opus-5-5 / 2026-09-30 19:25 / docs/decision.md 新增「不使用容器」，写明需要重新确定的设计与暂停派发的 15 张工单 / 用户决定完全不用容器
claude-opus-5-5 / 2026-09-30 19:40 / docs/decision.md「不使用容器」一条补充方向：WSL 作为一台登记的机器，以及 WSL 的核对结果 / 用户选择用 WSL 代替本机容器
claude-opus-5-5 / 2026-09-30 20:37 / docs/decision.md「不使用容器」一条改为：执行环境（包括是否需要 WSL）、computer use、跨平台工具库列为待讨论的专题，记录用户原话与意见；docs/requirements/stage-requirements-overview.md 第 6 节改为 Stage 3 待讨论的专题清单（五项）与以后阶段的讨论；docs/requirements/self-hosting.md（D35）待确认事项增加第 5 项跨平台；docs/research/complexity-and-mutation-testing.md 第 1.4 节增加能在 Windows 上运行的工具与 cosmic-ray 的实测 / 用户要求把这个话题列为 TODO 单独讨论，并记录
claude-opus-5-5 / 2026-09-30 22:18 / 新增 docs/adr/0022-run-directly-without-containers.md（代码在执行位置上直接运行，不使用容器与 WSL）；ADR-0018、ADR-0012、ADR-0010、ADR-0015 的状态行注明被取代的部分；docs/decision.md 新增「不使用容器以后的执行环境」 / 专题 1 讨论中用户采纳六项推荐，并确认修改清单
claude-opus-5-5 / 2026-09-30 22:18 / docs/design/execution-environment.md 改为本机进程与远程执行代理两种实现：第 5.2 节改为执行位置上的程序与依赖缓存，第 8 节写明代码的权限与来源不明的仓库，第 7、9、10、11 节按控制主机构建、开发板检查修改，第 12 节改用工单号；docs/design/evaluation-scenarios.md 改为在控制主机上直接运行：运行目录在仓库之外，隐藏材料在运行结束以后复制并查找材料目录的路径，三个场景使用 Python 3.13，场景 1 的端口由 PORT 给出，场景 2 写明 Windows 上的核对结果，场景 2、3 的 Yudao 一侧移到 M2 / 同上
claude-opus-5-5 / 2026-09-30 22:18 / docs/design/browser-and-computer-use.md 与 D34：试用在 run 的执行位置上直接进行，第 3.2 节改为执行位置上的程序，端口由 Yudao 分配并经 PORT 传入，computer use 的屏幕从哪里来待专题 2，第 16 节决定 3、验收场景与工单表按此修改 / 同上
claude-opus-5-5 / 2026-09-30 22:18 / CONTEXT.md、D29、D31、D32、D35、需求概览、需求索引、Stage 3 计划（第 1 至 3 节、第 7 节、关键路径、M2 与 M3 的内容，M3 改名为「远程执行、外部工具、多项目并行」）、路线图、当前验收基线、设计索引、本地通用工具、接入已有项目（来源不明的仓库，openai-agents-python 的测试命令写明 Python 3.13）、总体架构、系统架构原理、应用层与接口层按 ADR-0022 修改 / 同上
claude-opus-5-5 / 2026-09-30 22:18 / 新增 docs/research/computer-use-without-containers.md（14 个项目的屏幕来源、在同一台电脑上不打扰用户的做法、Windows 11 家庭版的限制、开发板上直接运行 Xvfb 的软件包与占用、Windows 的 UI Automation），docs/research/README.md 加入索引；需求概览第 6 节第 2 项写明调研已完成，并加入启动方式怎样适应不同系统的待讨论项 / 用户同意 computer use 的调研在后台进行；质检的检查位置可能与工程的系统不同
claude-opus-5-5 / 2026-09-30 22:46 / docs/design/execution-environment.md 第 10 节场景 1 增加可执行标记在开发板上的核对；docs/design/browser-and-computer-use.md 第 17 节截图证据与请求中的截图由 #149 实现，#148、#149 的中断验收在本机进程上进行，#155 增加 #143 的阻塞；docs/stage-3-plan.md 关键路径写明 #155 另外依赖 #143 / 同步工单时发现：可执行标记没有工单在 Linux 上验证，#148 没有截图的来源，#149 的远程验收依赖 3.2C 的远程部分
qwen3.8 / 2026-09-30 23:30 / docs/architecture-issues.md 为 #134 登记一处合入 origin/main 时的基线核对：分支落后 origin/main 7 个提交，#205 修好了 #16 与 #75 合并遗留的两处 `NewEvent(..., role=...)` 并重生成事件序列基准 / 交付 #134 前核对该失败不是本工单引入，合入以后消失
claude-opus-5-5 / 2026-10-01 01:15 / docs/architecture-issues.md 为 #202 登记的执行槽位占用问题追加处理结论 / 架构师处理执行者登记的架构问题
claude-opus-5-5 / 2026-10-01 01:46 / 新增 docs/adr/0023-client-installed-apart-release-is-one-wheel.md（桌面客户端与 Yudao 服务分开安装，一次发布是一个 wheel，客户端版本跟随 Yudao 服务）与 docs/design/client-packaging-and-release.md（桌面客户端的安装、更新与发布设计说明：安装、本机服务的启动与停止、托盘、更新、发布脚本、签名 TODO、验收、工单拆分）；新增 docs/research/client-packaging-and-update.md（客户端打包调研），docs/research/README.md 加入索引；docs/decision.md 新增「桌面客户端的打包、安装与发布」 / 用户选择专题 5 用 grill 讨论，三轮逐项采纳推荐
claude-opus-5-5 / 2026-10-01 01:46 / docs/design/app-and-interface.md 第 6.1、6.2、8、10 节、`system.status` 与 `agent.package` 按客户端的安装、更新与发布修改（更新页与更新源、本机停止请求、命令行入口 yudao、发布版本号与正在运行的 run 数、执行代理安装包随 wheel 提供）；docs/design/execution-environment.md 第 5.3.2 节执行代理的安装包改为发布时构建、随 Yudao 服务的 wheel 提供，第 12 节 #144 一行同步；docs/requirements/web-game-frontend.md（D30）与 docs/requirements/stage-requirements-overview.md 第 6 节第 5 项写明已确定并登记遗留；CLAUDE.md 工作流程第 7 步加入发布；CONTEXT.md 加入「Yudao 服务」「桌面客户端」「发布」 / 同上
claude-opus-5-5 / 2026-10-01 02:01 / docs/design/client-packaging-and-release.md 第 12 节与 docs/stage-3-plan.md（第 3 节界面工作线一行、第 9 节 M1 一行、开头更新日期）、docs/design/README.md（新增设计说明一项）、docs/requirements/README.md（D30 一行）填入工单号 #206 至 #209 / 四张 M1 工单已建立，#79、#144、#183 已修改，#144 增加 #206、#209 的阻塞
claude-opus-5-5 / 2026-10-01 04:25 / docs/architecture-issues.md 为 #134 的合入核对条目追加处理结论 / 架构师处理执行者登记的条目
