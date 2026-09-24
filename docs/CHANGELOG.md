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
