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

claude-opus-5-5 / 2026-09-26 12:34 / docs/design/department-roles.md：第 6.2 节中心角色增加「更新计划」工具，第 9.3 节审查结果写明被审查成果的内容摘要，第 11.3 节执行槽位按正在执行步骤的角色计数，第 12.4 节停滞时中心角色保留历史、连续工具角色从新的历史开始，第 12.6 节交出检查要求内容摘要相等的审查通过记录并写明工程自测的判断方法，第 13 节写明发起专家请求时角色任务照常进行与恢复规则的位置，第 16 节验收对照按独立检查判断、每个任务运行 3 次，第 17 节链接 ADR-0016、ADR-0017，开头状态行更新；docs/design/semantic-system.md 第 4 节表格与模块图、依赖规则、第 8 节改为复盘由流程编排安排、中心角色通过一次单独的请求完成，P 包含压缩之前的整理请求；docs/design/model-management.md 第 5 节按 ADR-0017 增加角色默认与项目角色设置、四层解析顺序、生效与记录，第 5.5 节改为流程编排发出待恢复的决定请求（#49），第 6 节时序与说明按角色解析，第 1、2、3、4.6、4.7、7.2 节同步；docs/design/recovery-contract-and-fault-matrix.md 新增第 5 节角色任务的恢复，原第 5 至 7 节顺延；CONTEXT.md 新增「部门内多角色」一组 13 个词条；docs/design/README.md 更新模型管理、部门内多角色与恢复契约三条 / 架构师为 D26 建立工单时发现设计缺口，在已确认设计的范围内作出决定并补全相关文档

claude-opus-5-5 / 2026-09-26 15:13 / 新增 docs/design/app-and-interface.md（应用层与接口层：模块、命令合同与清单、查询与读取模型、事件流、能力清单、访问方式与认证、与现有 Web 的对照与迁移、使用的技术、验收，第 10 节为架构师的决定）；docs/design/README.md 登记；docs/design/architecture/overall-architecture.md 第 10 节加入 #72、#73 至 #77、#79 至 #82、#50 下的 D26 工单与 3.2B（#68、#69），第 11 节加入长期目标能否修改；docs/program-roadmap.md 第 2 节加入应用层骨架 #72（排在 #49 之前）、Stage 4 的部门内多角色写明 ADR-0016、ADR-0017 与工单，新增应用层、接口层与桌面客户端一条；GitHub 新建 #50 至 #67（D26 与 #22 下的两张）、#68 与 #69（3.2B）、#70 至 #82（应用层、接口层与桌面客户端），#44、#49、#16 的正文与依赖同步，解除 #16 对 #15 的依赖 / 用户要求自动推进项目；应用层是用户决定、3.1 的继续执行与桌面客户端的共同前提

claude-opus-5-5 / 2026-09-26 15:40 / docs/design/model-management.md 第 4.3 节写明容量只从上游模型列表预填、连接测试读取模型列表地址、fake 协议只在测试或演示方式启动时可用，第 4.4 节写明影响列表由查询 catalog.change_impact 提供，第 5.2 节写明每个项目每个部门一份设置一个版本；docs/design/README.md 与 docs/program-roadmap.md 第 5.1 节写入 D24 的工单；GitHub 新建 D24 父工单 #83 与子工单 #84 至 #96 / 为 D24 建立工单时出现的五处设计缺口由架构师在已确认设计的范围内决定
