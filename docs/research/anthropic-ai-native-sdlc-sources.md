# Anthropic 2026 年发布的 AI-native SDLC：一手来源调研

调研日期：2026-09-25。来源以 claude.com、anthropic.com、academy.claude.com、code.claude.com、platform.claude.com 与 Anthropic 的 GitHub 为准。每个网页均先下载全文再引用；引文保留英文原文。第三方报道只用于定位原文，文中出现时标注「转述」。

## 1. Anthropic 发布了什么

### 1.1 核心发布：The AI-Native SDLC playbook

- 名称：The AI-Native SDLC playbook（副标题 “How to transform your software development lifecycle with AI—stage by stage.”）
- 发布日期：2026-08-21
- 发布位置：claude.com 博客，分类 Enterprise AI、Claude Code；关联产品标注为 Claude Enterprise、Claude Code、Claude Tag
- 作者：Louis Claxton；致谢 Jim Blackhurst、Will Steuk、Jamal Arif
- URL：https://claude.com/blog/the-ai-native-sdlc-playbook
- 性质：Anthropic Applied AI 团队整理的一组 “plays”（可单独采用的做法），按六个 “non-linear stages” 分组：Plan、Design、Build、Test、Deploy、Maintain。原文：“In this guide, we walk through several of our Applied AI team's best practices for integrating Claude internally across each stage of the SDLC … inspired by working with our customers.” 它是一份实践指南，带有配置示例与度量指标，没有以规范、标准或产品的形式发布。
- 名称说明：原文称 “You'll also hear this shift called the agentic SDLC, the AI SDLC, or simply agentic software development — the labels differ, but they describe the same thing.”

### 1.2 同一内容的课程版本：Claude Academy 课程

- 名称：The AI-native SDLC playbook（Claude Academy 课程，14 节课，约 1 小时）
- URL：https://academy.claude.com/courses/ai-native-sdlc-playbook ，第一课 https://academy.claude.com/courses/ai-native-sdlc-playbook/introduction
- 日期：页面没有标注发布日期（页脚为 © 2026 Anthropic PBC）
- 内容：与博客版的六阶段结构、plays、示例基本一致，课程版给出了面向人群与前置条件（见第 5 节）。Stage 6 在课程中合并为一课 “Closing the loop on metrics”，其中包含 Claude Tag 值守内容（https://academy.claude.com/courses/ai-native-sdlc-playbook/closing-the-loop-on-metrics）。

### 1.3 配套发布：Anthropic 内部 SDLC 的安全做法

- 名称：How Anthropic secures its AI-native software development lifecycle
- 发布日期：2026-07-21
- 作者：Jason Clinton（Anthropic Deputy CISO），致谢 Michael Segner
- URL：https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle
- 性质：描述 Anthropic Security Engineering 团队在自家 SDLC（Plan、Code、Test (CI)、Deploy (CD)、Monitor 五个阶段，外加 Governance）中实际使用的控制措施。playbook 在 Deploy 阶段直接链接到这篇文章：“For how these controls compose at production scale, see securing an AI-native SDLC at Anthropic.”

### 1.4 与该流程直接相关的其他 2026 年官方发布

这些发布不单独定义 SDLC 流程，但 playbook 或安全文章引用了它们，或者它们提供了流程中具体环节的做法：

| 发布 | 日期 | 位置与 URL | 与 SDLC 流程的关系 |
|---|---|---|---|
| 2026 Agentic Coding Trends Report | PDF 元数据创建日期 2026-01-21 | resources.anthropic.com：https://resources.anthropic.com/2026-agentic-coding-trends-report ，PDF：https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf | 趋势预测报告，Trend 1 为 “The software development lifecycle changes dramatically”：“Traditional SDLC stages remain, but agent-driven implementation, automated testing, and inline documentation collapse cycle time from weeks to hours. Monitoring feeds directly back into rapid iteration.” |
| Harness design for long-running application development（作者 Prithvi Rajasekaran，Anthropic Labs） | 2026-03-24 | Anthropic Engineering 博客：https://www.anthropic.com/engineering/harness-design-long-running-apps | 实验性的多 agent 开发 harness（planner、generator、evaluator），文中称 “The generator-evaluator loop maps naturally onto the software development lifecycle, where code review and QA serve the same structural role as the design evaluator.” 它是一项工程实验记录，与 playbook 的组织流程相互独立。 |
| Running an AI-native engineering org（Code w/ Claude SF 2026 演讲整理，Fiona Fung，Claude Code 与 Claude Cowork 工程总监） | 2026-06-03 | claude.com 博客：https://claude.com/blog/running-an-ai-native-engineering-org | Claude Code 团队自己改写的开发规范（计划、代码评审、角色）。安全文章称 “Our development team has covered the changes to their software development lifecycle at length” 并链接到此文。 |
| When AI builds itself（Anthropic Institute，Marina Favaro 与 Jack Clark） | 页面未显示日期；第三方报道为 2026-06-04（转述，例如 https://pasqualepillitteri.it/en/news/4268/recursive-self-improvement-anthropic-ai ）；页内有 “Update 9/18/2026” | https://www.anthropic.com/institute/recursive-self-improvement | 提供安全文章引用的内部数据（80% 合并代码由 Claude 编写、8 倍代码量）以及 “human code review has become a new bottleneck” 的判断。 |
| Introducing Claude Tag | 2026-06-23 | anthropic.com 新闻：https://www.anthropic.com/news/introducing-claude-tag | playbook Stage 6 的值守与工单入口所依赖的产品（Slack 中的 @Claude，beta）。 |
| Claude on call: How Claude Tag serves as Anthropic's first responder for CI/CD failures（Sachin Malhotra） | 2026-08-18 | claude.com 博客：https://claude.com/blog/ai-ci-cd-on-call ，配套仓库 https://github.com/anthropics/oncall-kit | playbook Stage 6 直接链接的内部案例：CI/CD 故障值守的检测、分诊、修复、交接。 |

## 2. 阶段、角色与交接物

### 2.1 总体结构

- 流程形状：“Instead of a linear flow, the process becomes a loop, and AI is embedded at each point.”（https://claude.com/blog/the-ai-native-sdlc-playbook ，2026-08-21）
- 交接方式：每个阶段以一次提交结束，下一阶段从读取这份提交开始。“Each stage ends by writing one to version control (including `intent.md`, `spec.md`, `plan.md`, the diff and its tests, the PR with its review findings, and the incident record) and the next stage begins by reading it.” 前期阶段的交接物以 `.md` 文件为主，“because a product owner and an agent can both read and act on the same file. From Build onward, the artifact is code and its records.”
- 触发关系：“An accepted `intent.md` triggers the requirements and design pass, an approved `spec.md` triggers plan mode, a merged PR triggers the pipeline, and a breached control band in production writes the next `intent.md` and so the loop continues.”
- 演进路径：“First, you prompt each step by hand with the end state being a loop in which each accepted artifact fires the next gate. Human attention concentrates at the gates, reviewing what the agent flagged rather than starting each stage from scratch.”
- 审计链：“The chain of commits is also the audit trail: who asked for what, what the agent produced, and who approved it.”
- 采用顺序：plays 之间有依赖图，“Start with any clay play — nothing points into it, so it needs nothing first.” 没有前置条件的 plays 包括 Capture as intent.md、The CLAUDE.md、Skills、Give Claude a feedback loop、Hooks as approval gates。

### 2.2 各阶段的输入、角色分工与产出

以下内容均来自 https://claude.com/blog/the-ai-native-sdlc-playbook （2026-08-21），与课程版一致。

#### Stage 1：Plan（play：Capture as intent.md）

- 输入：一个想法、一张工单，或者 Stage 6 监控产生的告警。
- 人的职责：发起人（originator，可以是非工程人员，通过 claude.ai 或 Cowork 使用 Claude）用自己的话描述问题，并纠正 Claude 的误解；产品负责人（product owner）审阅、纠正并决定接受或拒绝；平台或工程团队一次性搭建 intent 的存放位置并决定写入权限；模板可以由技术人员编写成 skill，并由负责人签字确认。
- Claude 的职责：与发起人一起头脑风暴，“Claude asks the questions an analyst would ask: scope, users, constraints, and what success looks like”，然后按组织模板写出 `intent.md`。不熟悉 git 的人可以通过版本控制 connector 让 Claude 代为提交。
- 产出：`intent.md`（proto-spec），示例字段为 Problem、Proposed outcome、Affected users and systems、Constraints、Open questions，并带 Author 与 Status。
- 交接与审批：“the product owner reviews and corrects the agent-written `intent.md` before it is committed.” 接受或拒绝记录为合并或关闭评审，接受后进入 Stage 2。
- 存放位置：单一产品时放在产品仓库的 `intent/` 目录；跨多个仓库时才单独建 intent 仓库。

#### Stage 2：Design（play：Requirements and design）

- 输入：已接受的 `intent.md`，以及组织的品牌、安全、合规、UX 规范（以 skills 形式提供）。
- 人的职责：产品负责人打开会话、附上 `intent.md`、给出约束并要求 Claude 标出疑点；审阅 spec（“The product owner reviews that spec, but doesn't write it”）；先处理被标出的疑点，并与对应规范的负责人（policy owner）逐项解决；决定是否进入 Build，高风险事项咨询技术负责人。原文：“A human team mate always makes this call, and accepting the spec is what starts the plan mode play in Stage 3: Build.”
- Claude 的职责：在一次会话中同时完成需求与设计，写出 `spec.md`，并说明无法同时满足的冲突规范。
- 产出：`spec.md`，与 `intent.md` 一起提交，“The file pair records what was asked for and what was decided.”
- 自动化演进：先人工运行，再固化为组织级 slash command，最后以 `intent.md` 被合并为触发条件，由非交互任务加载组织 skills 运行，并以 PR 提交 `spec.md`；此时产品负责人第一次介入就是审阅。
- 前端工作：产品负责人在 Claude Design（beta）中根据 `intent.md` 制作原型，再导出到 Claude Code 实现。

#### Stage 3：Build

主 play：Claude Code plan mode as the default starting point。

- 输入：`intent.md`、`spec.md`，以及仓库中的 `CLAUDE.md`。
- 人的职责：工程师以 plan mode 启动会话，要求 Claude 给出“改哪些文件、工作顺序、用哪些测试证明”的实现计划；追问风险与被放弃的方案；反复修改，直到“an engineer who has never seen the conversation could implement the change from the plan alone”；提交 `plan.md` 后接受计划。常规变更由工程师批准，组织认定的高风险变更交给 tech lead 或架构师。
- Claude 的职责：在 plan mode 中只读代码库并撰写计划，接受后执行实现（“With a solid plan, the implementation is often a single pass”）。实现偏离计划时，在同一次提交中更新 `plan.md`，可以用 hook 强制两者同步。
- 产出：`plan.md`（示例字段 Files that change、Order of work、Risks、Proof），随后是代码 diff 与测试。

同一阶段的其他 plays：

- Claude Code on auto mode：计划批准后 Claude 逐项修改无需逐次确认；随着 `CLAUDE.md`、skills、hooks 与测试成熟，auto-accept 成为常规工作的默认方式。原文：“The shift is now away from the user watching the agent make the edits and reviewing actions, towards the review of artifacts after longer autonomous sessions.”
- The CLAUDE.md：用 `/init` 生成初稿，删减到新成员第一天需要的内容，提交到仓库根目录；“When Claude makes a mistake twice, the correction goes into `CLAUDE.md`”；保持在一页以内。
- Skills as institutional knowledge：把需要一致执行的组织知识写成 `.claude/skills/<name>/SKILL.md`，或通过 plugin 在组织范围分发；规范变化时修改 skill 并由规范负责人签字。
- Hooks as build-time guardrails：阻止修改受保护路径、编辑后运行格式化与 lint、防止凭据进入 diff。
- Parallel sessions and subagents：一个工程师同时运行多个 Claude Code 会话，每个会话在独立的 git worktree 中；重复性工作做成 `.claude/agents/` 下的 subagent（示例：代码简化、运行应用的 verifier、只读调研的 researcher）。“The engineer's job shifts to orchestrating, and eventually, to building and monitoring loops.”
- 旁注 Legacy systems and the source of truth：每种交接物指定一个权威系统（仓库、Jira/ServiceNow 等既有系统，或两者互相链接作为最低要求），Claude 通过 MCP 读写既有系统。

#### Stage 4：Test

- play：Give Claude a feedback loop。工程师把验证封装成一条命令（例如 `make test`，失败时返回非零），在 `CLAUDE.md` 中写明命令与正常输出，给出可量化的目标；修复缺陷时先让 Claude 写出失败的测试并提交，再要求 Claude 在不修改该测试的前提下让它通过；UI 工作通过浏览器或截图工具进行视觉比对。Claude 反复运行检查直到通过，“what reaches the engineer has already passed it.” 产出证据为工具链的原始输出（测试输出、构建日志、截图对比）。审批人为审阅 PR 的 code owner。
- play：Continuous evals in CI。平台工程师收集 20 到 50 个真实任务，每个任务写成 eval（prompt 加判定条件）；在 CI 中按计划运行，并在 `CLAUDE.md`、skills 或 hooks 变化时运行；以通过率作为配置变更的合并检查；每次生产事故都新增一个 eval。
- feedback loop 与 verifier subagent 的区别：feedback loop 贯穿整个任务；verifier 在会话认为完成时，用新的上下文窗口做一次最终检查，“This way the verdict is not colored by the assumptions that produced the code.”

#### Stage 5：Deploy

- play：AI in the PR review loop。Claude 双向参与评审：评审进入的 PR，也处理别人对自己 PR 的评论。tech lead 在仓库根目录编写 `REVIEW.md`，划分评审轮次（Bugs、Security、Compliance，其中 Compliance 对照 `spec.md`、`plan.md` 与设计原则），定义 Important 与 Nit。评审发现本身不批准也不阻止 PR，分支保护仍然要求 code owner 批准。评审者或作者在评论中 `@claude` 时，Claude 修复并推送；对 Claude 自己开的 PR，可以用自定义 slash command 反复处理未解决评论和失败检查，直到 “green and waiting only on code owner approval”。同一类错误第二次被评审指出时写入 `CLAUDE.md`。tech lead 每月给评审发现打分并调整。
- play：Hooks as approval gates。工程负责人与变更管理、合规团队列出必须保留的人工审批关口；平台工程师把每个关口写成 hook（在 Claude 行动前运行，结果为 allow、ask 或 block）；团队 hook 放在 `.claude/settings.json`，不可协商的 hook 放在 managed settings。
- play：CI/CD integration and deployment。先在流水线中用 `claude -p` 做只读判断（分诊失败构建、概述不稳定测试的情况、起草 changelog），再加入写操作（修 lint、更新生成文档、处理 `@claude` 评论），写操作一律以 PR 形式经过分支保护；执行放在沙箱容器中，使用短期、限定范围的 token，默认不持有生产凭据；部署、状态、回滚以 MCP 工具形式按环境开放；按环境分级：开发环境自由部署，生产环境由 agent 准备发布、由 release manager 授权、由 hook 执行生产关口；回滚是流水线中演练最多的路径。
- 原则：“The agent does everything up to the production gate and nothing past it.”

#### Stage 6：Maintain

- play：Closing the loop。服务负责人或平台工程师选一个有稳定基线的指标，编写确定性的检测脚本（滚动窗口的均值与标准差，配合 Western Electric 等规则），脚本纳入版本控制并有单元测试；在 `bands.yaml` 中定义响应等级：1σ 只记录，2σ 以只读方式调用 Claude 诊断，3σ 允许 Claude 行动，但只能开 PR 进入评审关口或触发预先批准的 runbook。触发层可以是定时 workflow、监控 webhook 或 cron。Claude 以无状态方式运行（CI 中的非交互步骤，或沙箱容器中的 Agent SDK 服务），把诊断写成 Stage 1 格式的 `intent.md`；服务负责人或值班工程师分诊（立即修复、排期或驳回），产品相关发现转给产品负责人；修复上线后为该事故新增 eval。
- play：Recurring codebase scans。Claude Security（Claude Enterprise 的 public beta，扫描运行在 Claude Mythos 5 上）定期扫描仓库，每条发现先经过验证并附置信度；单个 PR 能解决的发现通过评审关口，更大的问题写成 `intent.md`。
- play：Claude on call with Claude Tag。Claude Tag（public beta，目前在 Slack）以自己的身份加入事故频道，担任第一响应者；小而边界清楚的修复以 PR 进入评审关口，更大的工作写成 `intent.md` 回到 Stage 1。“The channel is the audit trail: request, diagnosis, human authorization and fix all stay where the incident was handled.”
- 该阶段的说明：“Stage 6: Maintenance runs headless, with an independent confidence gate between stages, a deterministic check or an adversarial reviewing agent, deciding whether the previous stage's output continues or is escalated to a human.”

### 2.3 交接物清单

| 交接物 | 产生阶段 | 产生者 | 审批者 | 下一步读取者 |
|---|---|---|---|---|
| `intent.md` | Plan（或 Maintain、Claude Security、Claude Tag 回流） | Claude 与发起人 | 产品负责人 | Design 会话 |
| `spec.md` | Design | Claude | 产品负责人（高风险时咨询技术负责人，疑点交给规范负责人） | Build 的 plan mode 会话；PR 评审的 Compliance 轮次 |
| `plan.md` | Build | Claude 在 plan mode 中撰写，工程师反复修改 | 工程师（高风险时 tech lead 或架构师） | 实现会话、verifier、PR 评审的 Compliance 轮次 |
| diff 与测试 | Build、Test | Claude | code owner（通过分支保护） | CI、PR 评审 |
| PR 与评审发现 | Deploy | Claude 评审轮次、人工评审者 | code owner；生产发布由 release manager 授权 | 流水线 |
| 事故记录、lessons 文件 | Maintain | Claude（诊断、复盘）、值班人员 | 服务负责人分诊 | 新的 `intent.md`、后续调查 |
| `CLAUDE.md`、`.claude/skills/`、`REVIEW.md`、`.claude/settings.json`、`.claude/agents/` | 贯穿各阶段 | 团队、平台工程师、规范负责人 | code owner、规范负责人 | 每个会话启动时或触发时读取 |

### 2.4 Anthropic 内部的阶段划分（安全文章）

https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle （2026-07-21）描述 Anthropic 自己的做法，阶段名为 Plan、Code、Test (CI)、Deploy (CD)、Monitor，文章称这些阶段 “wouldn't look alien to a developer coming from a more traditional organization”：

- Plan：Claude Opus 驱动的 PSR（project security review）应用，读取项目设计文档，对照 MITRE ATT&CK 分析，并连接内部知识索引。“Once we gained confidence that Claude was accurate in assessing risk, we allowed teams to approve their own project, if Claude deemed the launch low enough risk.”
- Code：安全规范写入 `CLAUDE.md` 与组织级 skills；`CLAUDE.md` 要求在开 PR 前运行 `/security-review`；安装 security guidance plugin 后 Claude 在生成代码的同一会话中审查；开发者在 egress 白名单受限的远程 VM 上工作。
- Test (CI)：PR 打开后多个评审 agent 自动评审，“Each review agent is designed and scoped to a specific, narrow focus and leverages RAG for additional context and memory surrounding past incidents”；代码库按风险分级，“Entire codebases have strict human approval processes”；同时使用 SAST 工具。
- Deploy (CD)：在 staging 环境持续运行 AI 驱动的 DAST。
- Monitor：告警触发后 Claude 查看生产日志、定位根因、撰写复盘，部分情况下编写修复代码；该 agent 不能自动部署修复。
- 角色概括：“More than half of all code is being merged by our internal version of Claude Tag while human engineers focus on directing, setting intent, and owning final approval.”

Claude Code 团队的规范变化（https://claude.com/blog/running-an-ai-native-engineering-org ，2026-06-03）：计划改为 just-in-time planning（“prototype, put internal users on it, and act on their feedback”）；代码评审由 Claude 处理风格、lint、缺陷与测试，人工评审保留给法务、信任边界与安全敏感代码、产品判断；PM 大量写代码，工程师承担内容与设计工作。

## 3. 确定性机制与模型判断的分工

### 3.1 playbook 的总体划分

playbook 明确把 skills 与 `CLAUDE.md` 归为建议性控制，把 hooks、权限、managed settings、沙箱、分支保护归为确定性控制：

- “A skill is a control, though an advisory one. It makes Claude likely to apply the policy while the code is written, and nothing forces a session to comply with it. A policy that must always hold needs something deterministic behind the skill, such as a hook that blocks the action or a review pass that re-checks the policy at the PR. The skill makes violations rare and the hook makes them close to impossible.”
- “A skill is an advisory control while a hook is the deterministic layer behind it.”
- Hooks as approval gates 的治理说明：“Hooks are the approval gates. The gate condition is enforced every time, for everyone. Allow and block decisions are logged with a timestamp.”
- Maintain：“Detection stays deterministic. Claude is invoked once a band is breached, and the tier sets what it may do.”

（来源：https://claude.com/blog/the-ai-native-sdlc-playbook ，2026-08-21）

| 机制 | 类别 | 在流程中的位置 | 来源原文要点 |
|---|---|---|---|
| Hooks（PreToolUse 等，allow / ask / block，exit 2 阻止动作并把原因交给 Claude） | 确定性 | Build 护栏、Test 中禁止修改测试文件、Deploy 生产关口 | 示例 `production-gate.sh`：命令包含 deploy 与 production 且缺少 `RELEASE_APPROVAL` 时 `exit 2` |
| Managed settings（`allowManagedHooksOnly`、`allowManagedPermissionRulesOnly`、`disableBypassPermissionsMode`、`allowManagedMcpServersOnly`、`strictKnownMarketplaces`、`requiredMinimumVersion` 等） | 确定性 | 全流程，由平台团队通过 MDM 或管理后台下发 | “engineers cannot edit or override any of it” |
| 权限规则 `permissions.allow` / `deny` | 确定性 | 全流程；Maintain 的等级工具范围 | deny 阻止读取密钥与任意网络访问，allow 预先批准安全的内部循环 |
| 沙箱（OS 级文件系统与网络隔离，`failIfUnavailable`、`allowUnsandboxedCommands: false`、凭据屏蔽） | 确定性 | 本地会话与 CI agent 任务 | “the OS-level domain allowlist blocks egress outright” |
| Plan mode | 确定性（工具层面） | Build | playbook：“Plan mode enforces this itself, since Claude cannot edit files until the engineer accepts the plan.” 文档补充了一个例外：“Except in interactive terminal sessions with bypass permissions available, edits stay blocked until you approve the plan.”（https://code.claude.com/docs/en/permission-modes ） |
| Auto mode 的 classifier | 模型判断（另一个模型审查每个动作） | Build 中的常规工作 | “A separate classifier model reviews actions before they run, blocking anything that escalates beyond your request, targets unrecognized infrastructure, or appears driven by hostile content Claude read.” 默认阻止的动作包括 “Merging a pull request no human has approved, approving Claude's own pull request, or disabling CI checks”；文档同时说明 “Auto mode reduces permission prompts but does not guarantee safety.”（https://code.claude.com/docs/en/permission-modes ） |
| Stop、SubagentStop、TaskCompleted hooks | 确定性（command hook）或模型判断（prompt、agent hook） | Test 中“完成前必须验证” | Stop hook 返回 `decision: "block"` 时 “prevents Claude from stopping”，`reason` 告诉 Claude 为什么要继续；连续阻止 8 次后 Claude Code 结束该轮；TaskCompleted 以 exit 2 阻止任务被标记为完成，文档称其用途是 “enforce completion criteria like passing tests or lint checks before a task can close”。（https://code.claude.com/docs/en/hooks ） |
| `/goal` | 模型判断（另一个小模型） | 会话级完成条件 | “completion is decided by a fresh model rather than the one doing the work”（https://code.claude.com/docs/en/goal ） |
| 分支保护与 code owner 审批 | 确定性加人工 | Deploy | “the agent that wrote the code has no way to approve it” |
| 测试、构建、lint 命令 | 确定性 | Test 的 feedback loop | “the evidence comes from the toolchain” |
| Eval 通过率作为合并检查 | 确定性阈值，eval 判定条件由团队编写 | Test | “The pass-rate threshold is enforced as a merge check” |
| 检测脚本与 `bands.yaml` 等级 | 确定性 | Maintain | “detection stays entirely deterministic, with no model involved” |
| 按环境分级的权限 | 确定性 | Deploy | “Per-environment permission tiers set how much the agent may do on the way to the gate.” |
| `CLAUDE.md`、skills、`REVIEW.md` | 建议性，依赖模型遵循 | 全流程 | 见上方 skills 引文 |
| Claude 撰写 `intent.md`、`spec.md`、`plan.md`，标出疑点 | 模型判断，人工审批 | Plan、Design、Build | 疑点交给规范负责人 |
| PR 评审轮次的发现与严重级别 | 模型判断 | Deploy | “Findings do not approve or block a PR on their own” |
| 流水线中的判断步骤（分诊失败构建、判断是否不稳定） | 模型判断，只读起步 | Deploy | “Claude runs non-interactively inside the pipeline for the judgment steps” |
| Maintain 的诊断与提案 | 模型判断，受等级与路由限制 | Maintain | 3σ 时只能开 PR 或触发预先批准的 runbook |
| Maintain 各阶段之间的置信关口 | 确定性检查或对抗性评审 agent 二选一 | Maintain | “a deterministic check or an adversarial reviewing agent” |

Claude Code 文档对这些确定性机制的适用条件有如下说明（读取日期 2026-09-25）：

- 权限规则由程序执行：“Permission rules are enforced by Claude Code, not by the model. Instructions in your prompt or `CLAUDE.md` shape what Claude tries to do, but they don't change what Claude Code allows.” 评估顺序为 deny、ask、allow，任一层级的 deny 其他层级都不能放开。Bash 规则按命令文本匹配，“isn't a security boundary around the program”，需要不依赖命令文本的约束时使用沙箱或 PreToolUse hook。（https://code.claude.com/docs/en/permissions ）
- Hooks 只能收紧：“A hook that returns `permissionDecision: "deny"` blocks the tool even in `bypassPermissions` mode … Hooks can tighten restrictions but not loosen them past what permission rules allow.”（https://code.claude.com/docs/en/hooks-guide ）
- Hooks 在几种情况下不会阻止动作：exit 1 且没有有效 JSON 时按非阻止错误处理（“If your hook is meant to enforce a policy, use `exit 2`”）；脚本路径写错或不可执行时 “leaves the gate silently disabled”；PreToolUse command hook 超时时不阻止工具调用。（https://code.claude.com/docs/en/hooks ）
- 沙箱无法启动时默认给出警告并在沙箱外运行命令，设置 `sandbox.failIfUnavailable: true` 才会变成启动失败；文档说明 “Sandboxing reduces risk but is not a complete isolation boundary.”（https://code.claude.com/docs/en/sandboxing ）
- `CLAUDE.md` 与 auto memory：“Claude treats them as context, not enforced configuration.”（https://code.claude.com/docs/en/memory ）
- Managed settings 处于最高优先级：“Nothing you set overrides them.”（https://code.claude.com/docs/en/settings ）

### 3.2 下一步做什么由谁决定

- 阶段顺序与触发：由交接物的提交与合并事件决定。“A stage ends by committing an artifact with the commit initiating the next stage.” Design 阶段的自动化形态是 “make the acceptance of `intent.md` in the intent home the trigger, with a non-interactive job that fires on the merge”。（playbook）
- 是否进入下一阶段：由人在关口决定。Plan 到 Design 由产品负责人接受 `intent.md`；Design 到 Build 由产品负责人接受 `spec.md`（“A human team mate always makes this call”）；Build 中由工程师接受 `plan.md`；合并由 code owner 决定；生产发布由具名 release manager 授权；Maintain 的发现由服务负责人或值班工程师分诊。（playbook）
- 阶段内部的步骤：由 Claude 在已批准计划的范围内决定。plan mode 中 Claude 提出计划并采访工程师，接受后执行；auto mode 下逐项修改无需确认。工作拆分给并行会话由工程师根据 `plan.md` 决定：“The engineer splits the work into tasks that touch different files … Tasks that share files run in a single session, one after another.”（playbook）
- Maintain：何时调用 Claude 由确定性脚本决定，Claude 能做什么由 `bands.yaml` 等级决定，诊断内容由 Claude 决定。（playbook）
- Claude Tag 值守中，调查步骤由模型编排：“Claude Tag kicks off a dynamic workflow with an orchestration agent that spins up executor subagents to investigate each dependency and source of truth.” 升级路径 “has both deterministic and agentic paths”，告警过程本身是确定性的。（https://claude.com/blog/ai-ci-cd-on-call ，2026-08-18）
- Anthropic 内部 Plan 阶段：PSR 结果为低风险时，团队可以自行批准项目，这是把一部分审批交给模型判断。（安全文章，2026-07-21）

### 3.3 什么算完成、什么结果被接受由谁决定

- 会话层面的“完成”：由 `CLAUDE.md` 中的验证要求定义（“Run all three before reporting any task complete, and paste the output. If a test fails, fix the code, not the test.”），目标需要可量化，以便 “Claude can check the work without asking you”。组织需要保证时，用 hook 强制：“Verification before a task is reported done, and the block on the agent editing test files during a fix, both implemented as hooks where the organization wants them guaranteed.” verifier subagent 在新上下文中做最终检查，只报告不修改。（playbook）
- 变更是否被接受：由人通过分支保护决定，评审发现只作为参考信息。“Approval comes from a human through branch protection, informed by the findings.” 平台工程师可以读取检查结果中的严重级别计数来设置合并条件。（playbook）
- 配置变更是否被接受：由 eval 通过率作为合并检查，拥有该配置的团队批准。（playbook）
- 生产发布：由具名 release manager 授权，由 hook 强制执行。（playbook）
- Anthropic 内部的实际做法中，一部分合并由 agent 批准：“Human accountability is still central for code that is reviewed and merged by Claude. Every approval is logged with the signals and reasoning behind it, and a risk-weighted sample is reviewed by humans.” 新的 AI 评审者先以 shadow mode 运行，“New agents post comments for human approval until trust is earned.” 评审发现要求 agent 写出证明：“as we've gained confidence in the findings by requiring the agents to write a proof that their finding is valid.”（安全文章，2026-07-21）
- Harness 实验中的“完成”定义：generator 与 evaluator 在每个 sprint 前协商 sprint contract，“agreeing on what "done" looked like for that chunk of work before any code was written”；evaluator 对每个标准设硬阈值，“if any one fell below it, the sprint failed”。文章同时指出模型自评偏宽：“agents tend to respond by confidently praising the work”，以及 “Out of the box, Claude is a poor QA agent”。（https://www.anthropic.com/engineering/harness-design-long-running-apps ，2026-03-24）

### 3.4 上下文如何管理

playbook 中的做法（https://claude.com/blog/the-ai-native-sdlc-playbook ）：

- 阶段之间通过文件交接上下文：每个阶段读取上一阶段提交的文件开始工作。Design 会话由产品负责人附上 `intent.md` 开启；`plan.md` 要写到 “an engineer who has never seen the conversation could implement the change from the plan alone”，也就是交接物本身要能脱离原会话独立使用。
- `CLAUDE.md` 在每个会话开始时读取，并要求控制篇幅：“Keep it under a page, because Claude reads all of it at the start of a session and anything stale is taking up context for no benefit.”
- Skills 按触发条件加载（frontmatter 写明何时触发），playbook 要求测试 skill 是否在不同问法下都能加载。
- Subagent 有独立上下文窗口与工具限制：“A subagent runs inside a single session as a scoped helper with its own context window and tool limits”；researcher subagent “explores the codebase and reports back without flooding the main context”；verifier 使用新上下文窗口，避免判断受写代码时的假设影响。
- 并行会话之间完全隔离：“Each independent session knows nothing about the others, and the engineer steering them is the only thing they share.”
- Maintain 中 Claude 无状态运行：“Claude runs stateless … Because the run is stateless and non-interactive, a loop can begin and end without anyone starting it.”

其他官方来源：

- 安全文章把“独立上下文窗口”作为控制手段：“Automated reviews are a different type of risk that is controlled differently (through multiple gates and agents with separate context windows).” 多个窄范围评审 agent 的理由之一是 “They do not share biases and blindspots”。（2026-07-21）
- Harness 文章比较了两种做法：context reset（清空上下文、启动新 agent、用结构化交接文件传递状态）与 compaction（把早期对话原地压缩为摘要，同一个 agent 继续工作）。“While compaction preserves continuity, it doesn't give the agent a clean slate.” 在 Sonnet 4.5 上 context reset 是必需的；Opus 4.5 基本消除了 “context anxiety”，因此新 harness 以一个连续会话运行，由 Claude Agent SDK 的自动 compaction 处理上下文增长。agent 之间通过文件通信。（2026-03-24）

（Claude Code 与 Agent SDK 文档中关于 compaction、subagent、memory 的具体机制见 3.6。）

### 3.5 会话与 agent 是否持久、跨会话信息如何保留

- playbook 没有要求会话长期存在。跨会话的信息全部保存在版本控制中的文件里：`intent.md`、`spec.md`、`plan.md`、`CLAUDE.md`、`.claude/skills/`、`REVIEW.md`、`.claude/agents/`、PR 历史，以及 Claude Tag 写入的 lessons 文件。会话记录通过 OpenTelemetry 导出到组织的观测系统，作为审计证据。（playbook）
- 纠错写回文件：“When Claude makes a mistake twice, the correction goes into `CLAUDE.md`”；评审第二次指出同类错误时同样写入 `CLAUDE.md`；每次生产事故新增一个 eval。安全文章也描述了同样的闭环：“Once an agent discovers a bug class, the relevant file is updated to prevent it recurring in future code.”
- Claude Tag 是其中具有持久记忆的部分：“Claude builds context by remembering relevant information from the channels it's in”；“everything, including its memories, will stay scoped to the channels defined by the administrators”。（https://www.anthropic.com/news/introducing-claude-tag ，2026-06-23）
- Claude Tag 值守的记忆构成：“An on-call agent needs memory so it remembers what's been done; connections and access so it can investigate, understand, and act; schedules so it knows when to get back to work; and instructions so it knows what to do.” 常驻指令以 skills 形式提交在 GitHub 仓库；`lessons.md` 由 Claude 自动追加，“Every new investigation starts by reading it”；反复出现的模式再提升进调查 skill；每周一生成给人看的交接报告。（https://claude.com/blog/ai-ci-cd-on-call ，2026-08-18）

### 3.6 Claude Code 与 Agent SDK 文档中的相关机制

以下来自 code.claude.com 文档（页面本身没有发布日期，文中版本注记最高约到 v2.1.281，读取日期 2026-09-25）。platform.claude.com 的 Agent SDK 页面已重定向到 code.claude.com/docs/en/agent-sdk/。

下一步由谁决定：

- 默认的 agent 循环由模型逐步决定：“Claude decides what each step requires based on what it learned from the previous step.”（https://code.claude.com/docs/en/how-claude-code-works ）
- Dynamic workflows（2026 年第 22 周，5 月 25 日至 29 日作为 research preview 推出，见 https://code.claude.com/docs/en/whats-new/2026-w22 ）把编排从模型的逐轮判断移到脚本中。文档的对比表中 “Who decides what runs next” 一栏：Subagents 为 “Claude, turn by turn”，Skills 为 “Claude, following the prompt”，Agent teams 为 “The lead agent, turn by turn”，Workflows 为 “The script”。原文：“With subagents, skills, and agent teams, Claude is the orchestrator: it decides turn by turn what to spawn or assign next, and every result goes into a context window. A workflow script holds the loop, the branching, and the intermediate results itself, so Claude's context holds only the final answer.” 脚本由 Claude 编写，在与对话隔离的环境中运行；运行中不能接受用户输入，“For sign-off between stages, run each stage as its own workflow”；脚本中 `Date.now()` 与 `Math.random()` 会抛出错误，以保证重放时调用序列一致。（https://code.claude.com/docs/en/workflows ）
- 配套博客 “A harness for every task: dynamic workflows in Claude Code”（Thariq Shihipar、Sid Bidasaria，2026-06-02，https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code ，现重定向到 claude.dev）说明动机：单个会话 “needs to both plan and execute in the same context window”，由此出现三类问题：agentic laziness（“declares the job done after partial progress”）、self-preferential bias、goal drift（“especially after compaction. Each summarization step is lossy”）；对策是 “orchestrating separate Claude subagents with their own context windows and focused, isolated goals.” Claude Tag 值守文章提到的 “dynamic workflow with an orchestration agent” 即此功能。

完成由谁决定：

- 默认由模型自己决定：“Claude stops when it judges the work done.”（https://code.claude.com/docs/en/goal ）术语表的说明：“without one [a verification loop], the only thing deciding the agent is finished is the agent itself.”（https://code.claude.com/docs/en/glossary ）
- `/goal` 设置完成条件后，每一轮结束时由另一个小模型判断条件是否满足：“completion is decided by a fresh model rather than the one doing the work”，结论为 Not yet met、Met、Impossible 三种；该评估模型不调用工具，“so it can only judge what Claude has already surfaced in the conversation”。`/goal` 的实现是会话范围的 prompt-based Stop hook。（https://code.claude.com/docs/en/goal ）
- Dynamic workflows 博客中的完成判断：“The task is complete when the review agent feels like it has met the criteria”，并建议与 `/goal` 配合 “to set a hard completion requirement”。

上下文管理：

- 每个新会话从空白上下文开始：“Sessions are independent. Each new session starts with a fresh context window, without the conversation history from previous sessions.”（https://code.claude.com/docs/en/how-claude-code-works ）
- Compaction：上下文接近上限时 “It clears older tool outputs first, then summarizes the conversation if needed. Your requests and key code snippets are preserved; detailed instructions from early in the conversation may be lost.”（同上）默认在模型上下文上限处自动压缩，原生 1M 上下文的模型默认约在 967K tokens 压缩，可用 `/autocompact`、`--autocompact` 或 `CLAUDE_CODE_AUTO_COMPACT_WINDOW` 在 100K 到 1M 之间设置，也可手动 `/compact [focus]`。（https://code.claude.com/docs/en/model-config ）压缩后从磁盘重新注入项目根目录的 CLAUDE.md、无路径限定的 rules、auto memory 与 plan mode 的计划，重新读取最多五个最近修改的文件，skill 正文按 5,000 与 25,000 tokens 上限重新附加；路径限定的 rules、嵌套 CLAUDE.md 与 hook 添加的上下文会被摘要掉。（https://code.claude.com/docs/en/context-window ）
- Subagent：“Each subagent starts with a fresh, isolated context window. It doesn't see your conversation history, the skills you've already invoked, or the files Claude has already read. Claude composes a delegation message that summarizes the task, and the subagent works from there.” 它会加载完整的 CLAUDE.md 层级与 git status 快照，不加载主会话的 auto memory；完成后 “returns only the summary”。subagent 默认可以再派生 subagent，最多到主会话以下三层；并发上限 20。（https://code.claude.com/docs/en/sub-agents ）Agent SDK 中 “The only content you pass from parent to subagent is the Agent tool's prompt string”，并且 “Claude decides on its own when to spawn a subagent and how many to spawn.”（https://code.claude.com/docs/en/agent-sdk/subagents ）
- Fork：fork 继承当前全部对话，只返回最终结果；交互式会话默认开启，`-p` 与 SDK 默认关闭。（https://code.claude.com/docs/en/sub-agents ）
- Skills：描述常驻上下文，正文在调用时才加载，“Unlike CLAUDE.md content, a skill's body loads only when it's used.” `context: fork` 让 skill 在看不到对话历史的 subagent 中运行。（https://code.claude.com/docs/en/skills ）
- Worktree：`claude --worktree <name>` 在 `.claude/worktrees/<name>/` 创建独立检出，“edits in one session never touch files in another”；subagent 可以设置 `isolation: worktree`。（https://code.claude.com/docs/en/worktrees ）

跨会话信息与持久化：

- “Each Claude Code session begins with a fresh context window. Two mechanisms carry knowledge across sessions: CLAUDE.md files… Auto memory.” 两者都作为上下文加载，“Claude treats them as context, not enforced configuration”，需要强制执行时文档指向 hooks 与 settings。（https://code.claude.com/docs/en/memory ）
- Auto memory 存放在本机 `~/.claude/projects/<project>/memory/`，在同一仓库的多个 worktree 之间共享，每次会话加载 MEMORY.md 的前 200 行或 25KB。（同上）
- 会话记录以 JSONL 保存在本机，默认保留 30 天；可以 `--continue`、`--resume <id>` 恢复，或 fork 为新的会话 ID。（https://code.claude.com/docs/en/sessions 、https://code.claude.com/docs/en/headless ）`claude -p` 默认加载与交互会话相同的上下文（包括 CLAUDE.md 与 auto memory），`--bare` 跳过这些内容；运行结果默认保存为可恢复的会话，除非传入 `--no-session-persistence`。（https://code.claude.com/docs/en/headless 、https://code.claude.com/docs/en/glossary ）
- Subagent 每次调用都是新实例，可以通过 `SendMessage` 在同一会话内恢复；可选的 `memory` 字段为 subagent 提供跨对话保留的目录。（https://code.claude.com/docs/en/sub-agents ）
- Agent SDK：会话自动写入磁盘，支持 continue、按 ID resume、fork；“Sessions persist the conversation, not the filesystem.” 会话文件只存在于创建它的机器上，跨主机时文档建议：“Don't rely on session resume. Capture the results you need… as application state and pass them into a fresh session's prompt. This is often more robust than shipping transcript files around.”（https://code.claude.com/docs/en/agent-sdk/sessions ）SDK 在上下文接近上限时自动 compaction 并发出 `compact_boundary` 消息，可以用 `PreCompact` hook 调整；“Persistent rules belong in CLAUDE.md… because CLAUDE.md content is re-injected on every request.”（https://code.claude.com/docs/en/agent-sdk/agent-loop ）playbook 中 Maintain 阶段的 “Claude runs stateless … as an Agent SDK service in a sandboxed container” 与这条建议一致。
- Claude Tag 的记忆按频道划分：“Claude keeps memory by channel. Memory from public channels is shared across the workspace. What it learns working in a private channel is saved to that channel's own store, and channel memory isn't organized by person.” 记忆来源包括用户要求记住的内容、Claude 自行保存的事实，以及读取过去会话的记录；频道级会话在约一小时无活动、约一天后或配置变化后更换。（https://claude.com/docs/claude-tag/users/memory 、https://claude.com/docs/claude-tag/concepts/how-it-works ，页面标注 Public Beta）
- oncall-kit 对记忆的规则：“Files are truth; memory is cache”；README：“No unreviewed memory. Channel memory … nobody reviews it. Anything load-bearing … lives in git.” `lessons.md` 由 Claude 在每次事故后自动追加，由人修剪；同一机制出现三次后通过 PR 提升为 playbook 参考文件。（https://github.com/anthropics/oncall-kit ，2026-08-06 提交 v1.0，标注为 “Reference implementation. Not maintained and not accepting contributions.”）

评审与安全环节的确定性边界：

- 托管 Code Review（research preview，Team 与 Enterprise）：“Findings are tagged by severity and don't approve or block your PR”；“The check run always completes with a neutral conclusion so it never blocks merging through branch protection rules. If you want to gate merges on Code Review findings, read the severity breakdown from the check run output in your own CI.” 检查结果最后一行是可解析的计数，例如 `{"normal": 2, "nit": 1, "pre_existing": 0}`。评审由多个 agent 分析 diff，再由验证步骤对照实际代码行为过滤误报。（https://code.claude.com/docs/en/code-review ）发布博客：“It won't approve PRs — that's still a human call.”（https://claude.com/blog/code-review ，2026-03-09）
- security-guidance plugin：每次文件编辑时的检查是 “a deterministic string match with no model involved”；每轮结束与提交时的审查是另一次 Claude 调用，使用新的上下文；“None of the layers block writes or commits … Treat the plugin as one layer of defense in depth.” 需要强制执行时配合阻止编辑的 hook 或 CI 检查。（https://code.claude.com/docs/en/security-guidance ）
- claude-code-action：运行前的固定检查包括触发者必须有写权限、默认拒绝 bot 触发者；文档要求 “review Claude's changes before merging”。（https://code.claude.com/docs/en/github-actions ）
- OpenTelemetry：`claude_code.tool_decision` 事件记录每次工具调用的 accept 或 reject 以及来源（`config`、`hook`、`user_permanent` 等）；`hook_execution_complete` 事件记录 `num_blocking` 等计数。“Claude Code emits the raw event stream only. Anomaly detection … and alerting are the responsibility of your SIEM.” 身份方面，“Claude Code doesn't act under a separate service account; the identity recorded on each event is the developer's own Claude account.”（https://code.claude.com/docs/en/monitoring-usage ）
- Claude Tag 的身份：“In Slack channels, Claude acts with its own service accounts, rather than as a specific user”；“What Claude can do never changes based on who asked.”（https://claude.com/docs/claude-tag/concepts/agent-identity ）博客：“Claude Tag creates a distinct identity for each private channel; public channels in a workspace share a workspace-level identity.”（https://claude.com/blog/agent-identity-access-model ，2026-06-24）
- oncall-kit 的权限：“The agent is read-only toward every system it monitors”；ONCALL.md：“All mitigation is performed by humans.” 并且 “Claude is never the detector”，固定的告警规则直接通知人。

## 4. 配套的 Claude Code 与 Claude Agent SDK 功能

版本背景：playbook 发布当天（2026-08-21）Claude Code 的发布版本为 2.1.239；截至 2026-09-24 最新版本为 2.1.282（https://code.claude.com/docs/en/changelog ，该页面由 GitHub 上的 CHANGELOG.md 生成）。code.claude.com 的功能文档页面没有显示内容更新日期，下表中的版本与日期来自 changelog、发布博客、GitHub 与 npm 的发布记录。playbook 的 managed settings 示例使用 `"requiredMinimumVersion": "2.1.193"`，该版本是示例中 `disableSideloadFlags` 所需的最低版本。

### 4.1 playbook 直接使用的 Claude Code 功能

| 功能 | 在 playbook 中的用途 | 文档 | 状态、版本与日期 |
|---|---|---|---|
| Plan mode | Build 阶段的默认起点，产出 `plan.md` | https://code.claude.com/docs/en/permission-modes | changelog 最早提及为 1.0.33（2025-06-24）；2.1.0（2026-01-07）加入 `/plan` 命令。接受计划时可选 “Yes, and use auto mode”、“Yes, manually approve edits” 或继续规划；“Approving a plan exits plan mode and switches the session to the permission mode each approve option describes, so Claude starts editing.” |
| Auto mode（classifier） | 常规工作的 auto-accept，以及 worktree 并行 | https://code.claude.com/docs/en/permission-modes | changelog 最早提及为 2.1.86（2026-03-27）；2.1.111（2026-04-16）起不再需要 `--enable-auto-mode`；2.1.152（2026-05-27）起不再需要单独同意。Pro、Max、Team 的内置默认模式为 auto，需要 v2.1.228（2026-08-11，macOS、Linux、WSL）或 v2.1.233（2026-08-14，原生 Windows）；Enterprise、Console API key、`claude -p` 与 Agent SDK 的内置默认为 Manual。classifier 默认运行在 Claude Sonnet 5 上，2.1.273 至 2.1.282（2026-09-15 至 09-24）期间改为默认在服务端运行。 |
| `CLAUDE.md` 与 `/init` | 组织知识、验证要求、评审时读取的规范 | https://code.claude.com/docs/en/memory | 文档建议控制在 200 行以内；压缩后项目根目录的 CLAUDE.md 会重新注入。 |
| Skills | 以 `.claude/skills/<name>/SKILL.md` 编码规范与模板 | https://code.claude.com/docs/en/skills | 正文在调用时加载。 |
| Plugins 与私有 marketplace | 在组织范围分发 skills、agents、hooks | https://code.claude.com/docs/en/plugin-marketplaces | 管理员可以要求每台机器都安装；配合 `strictKnownMarketplaces` 限制来源。 |
| Hooks | Build 护栏、Test 中禁止修改测试文件、Deploy 审批关口 | https://code.claude.com/docs/en/hooks 、https://code.claude.com/docs/en/hooks-guide | 1.0.38（2025-06-30）发布；1.0.59（2025-07-23）起 PreToolUse 可返回 ask；2.0.30（2025-10-30）加入 prompt-based Stop hook；2.1.33（2026-02-06）加入 TaskCompleted 与 TeammateIdle；2.1.143（2026-05-15）加入 Stop hook 连续阻止 8 次的上限。handler 类型包括 command、http、mcp_tool、prompt、agent（agent 标注为 experimental）。 |
| Subagents（`.claude/agents/`） | verifier、代码简化、researcher 等重复任务 | https://code.claude.com/docs/en/sub-agents | 独立上下文窗口；默认可嵌套三层；2.1.49 至 2.1.50（2026-02-19 至 02-20）加入 `isolation: worktree`。 |
| Worktrees（`claude --worktree`） | 并行会话之间的文件隔离 | https://code.claude.com/docs/en/worktrees | 2.1.49（2026-02-19）加入 `--worktree`（`-w`）参数。 |
| 非交互模式（`claude -p`、`--allowedTools`、`--output-format json`） | CI 中的 eval、流水线判断步骤、Maintain 的无状态运行 | https://code.claude.com/docs/en/headless | `--bare` 跳过 CLAUDE.md 与 auto memory，文档说明它将来会成为 `-p` 的默认行为。 |
| Settings、managed settings、server-managed settings | 团队 hook 放在 `.claude/settings.json`，不可协商的控制放在 managed settings | https://code.claude.com/docs/en/settings 、https://code.claude.com/docs/en/settings-reference 、https://code.claude.com/docs/en/managed-settings 、https://code.claude.com/docs/en/server-managed-settings | 企业 managed settings 在 2.0.68（2025-12-12）加入；`requiredMinimumVersion` 需要 v2.1.163（2026-06-04）；`disableSideloadFlags` 需要 v2.1.193；`allowManagedHooksOnly` 同时会停用 `/goal`。 |
| Permissions | 预先批准安全命令，拒绝读取密钥与网络访问 | https://code.claude.com/docs/en/permissions | 见 3.1。 |
| Sandboxing | 操作系统级文件与网络隔离 | https://code.claude.com/docs/en/sandboxing | 2.0.24（2025-10-20）发布；`allowUnsandboxedCommands` 在 2.0.30（2025-10-30）加入；`sandbox.failIfUnavailable` 在 2.1.83（2026-03-25）加入。macOS 使用 Seatbelt，Linux 与 WSL2 使用 bubblewrap，原生 Windows 不支持。 |
| MCP 与 managed MCP | 连接 Jira 等既有系统；以工具形式开放部署、状态、回滚 | https://code.claude.com/docs/en/mcp 、https://code.claude.com/docs/en/managed-mcp | `managedMcpServers` 需要 v2.1.259；`allowManagedMcpServersOnly: true` 使白名单生效。 |
| 托管 Code Review | Deploy 阶段的 PR 评审轮次，读取 `REVIEW.md` | https://code.claude.com/docs/en/code-review | research preview，面向 Team 与 Enterprise，不支持 Zero Data Retention 组织；2026-03-09 随博客发布（https://claude.com/blog/code-review ）；平均约 20 分钟、每次 15 至 25 美元，另行计费；`@claude review` 触发单次评审，`@claude review always` 订阅后续推送。 |
| claude-code-action（GitHub Actions） | 在自有 CI 中运行评审、`@claude` 修复循环、流水线步骤 | https://code.claude.com/docs/en/github-actions | `anthropics/claude-code-action@v1`，v1.0 于 2025-08-26 发布，最新 v1.0.234 于 2026-09-24 发布；基于 Agent SDK 构建。 |
| `/security-review` | 开 PR 前的安全审查（Anthropic 内部写在 `CLAUDE.md` 中） | https://support.claude.com/en/articles/11932705-automated-security-reviews-in-claude-code | 支持文章日期 2026-03-16；另有 GitHub Action `anthropics/claude-code-security-review`。文章说明它 “Should complement, not replace, your existing security practices and manual code reviews.” |
| security-guidance plugin | 生成代码的同一会话中进行安全审查 | https://code.claude.com/docs/en/security-guidance | 所有套餐可用；完全基于 hooks 构建（SessionStart、UserPromptSubmit、PostToolUse、Stop）；插件最新版本 2.0.8（2026-09-09）。 |
| `/goal` | 设置会话级完成条件，由另一个模型判断 | https://code.claude.com/docs/en/goal | 2.1.139（2026-05-11）加入。playbook 正文没有提到此功能。 |
| Dynamic workflows | Claude Tag 值守中的编排与执行 subagent（值守文章提及） | https://code.claude.com/docs/en/workflows | research preview，2026 年第 22 周（5 月 25 日至 29 日）推出（https://code.claude.com/docs/en/whats-new/2026-w22 ）；单次运行最多 1,000 个 agent，默认并发 16。playbook 正文没有提到此功能。 |
| OpenTelemetry 监控 | 记录每次调用与 hook 决定，用于审计与度量 | https://code.claude.com/docs/en/monitoring-usage | 导出 `claude_code.tool_decision` 等事件；traces 标注为 beta。 |
| Analytics、Compliance API | 管理员度量与合规查询 | https://code.claude.com/docs/en/analytics 、https://platform.claude.com/docs/en/manage-claude/compliance-api | playbook 资源清单列出。 |
| 第三方云部署与网络配置 | 模型调用走 Bedrock、Vertex 或 Foundry | https://code.claude.com/docs/en/third-party-integrations 、https://code.claude.com/docs/en/network-config | playbook 资源清单列出。 |
| Remote Control | Claude Tag 值守配置步骤之一 | https://code.claude.com/docs/en/remote-control | 2.1.51（2026-02-23）加入 `claude remote-control` 子命令；Team 与 Enterprise 默认关闭，需要 Owner 开启。 |
| Admin setup、Security model | 平台团队的配置入口 | https://code.claude.com/docs/en/admin-setup 、https://code.claude.com/docs/en/security | playbook 把 admin setup 列为 “start here”。 |

### 4.2 Claude Agent SDK

| 功能 | 在 playbook 中的用途 | 文档 | 状态与说明 |
|---|---|---|---|
| Agent SDK | Maintain 阶段接收 webhook 的服务，在沙箱容器中无状态运行 Claude | https://code.claude.com/docs/en/agent-sdk/overview （playbook 链接的 https://platform.claude.com/docs/en/agent-sdk/overview 已重定向到此处） | 提供 “the same tools, agent loop, and context management that power Claude Code”；从项目的 `.claude/` 与 `~/.claude/` 自动加载 skills、commands 与 memory。 |
| Sessions | 跨轮次保持上下文，恢复或分叉 | https://code.claude.com/docs/en/agent-sdk/sessions | 会话自动写入本机磁盘，支持 continue、resume、fork；TypeScript 中 `persistSession: false` 只保存在内存。 |
| Agent loop 与 compaction | 长任务的上下文管理 | https://code.claude.com/docs/en/agent-sdk/agent-loop | 自动 compaction 并发出 `compact_boundary`；`maxTurns`、`maxBudgetUsd` 限制轮次与花费。 |
| Subagents 与 Workflow tool | 多 agent 编排 | https://code.claude.com/docs/en/agent-sdk/subagents | Workflow tool 需要 TypeScript SDK v0.3.149 或以上。 |

### 4.3 playbook 引用的其他 Claude 产品

| 产品 | 在 playbook 中的用途 | 链接 | 状态（按 playbook 与产品文档的说法） |
|---|---|---|---|
| Claude（claude.ai）与 Cowork | 非工程人员撰写 `intent.md`，通过版本控制 connector 提交 | https://claude.com/product/cowork | playbook 未标注状态 |
| Claude Design | 根据 `intent.md` 制作前端原型并导出到 Claude Code | https://claude.com/product/design | beta |
| Claude Tag | Stage 6 的值守与工单处理 | https://claude.com/product/tag 、https://claude.com/docs/claude-tag/overview | public beta，Team 与 Enterprise；2026-06-23 发布（发布时配合 Opus 4.8）；不支持 Zero Data Retention 或客户管理密钥的组织；运行需要组织开启 Routines |
| Claude Security | 定期代码库扫描 | https://claude.com/product/claude-security | Claude Enterprise 的 public beta，按 Mythos 5 价格计费 |
| Claude Code on the Web | 审阅与应用 Claude Security 建议的补丁 | https://claude.ai/code | Claude Security 的前置条件 |

## 5. Anthropic 陈述的动机、适用范围与局限

### 5.1 动机

- 瓶颈转移：“Code is no longer the bottleneck.” 当构建阶段快于传统 SDLC 所能承受的速度时，“three things become true”：瓶颈移到构建两侧的 plan、review/test、deploy，它们仍按人的速度运行；逐行人工评审跟不上 agent 写出的 diff；例外仍要经过每周或每月开会的委员会，治理成本上升。（playbook，2026-08-21）
- 安全团队的例子：“Security teams are sized for human output, so when agents multiply code output, either the review queue builds or code ships under-reviewed. A regulated organization can't accept either outcome.”（playbook）
- 传统流程的前提已经变化：“the traditional SDLC was designed to maximize efficiency in an era where the most time-consuming and expensive stage was writing and implementing code, which is no longer the case.” 并且 “The traditional SDLC also features controls that assume every step is performed by humans.”（playbook）
- Anthropic 内部数据：“Our software engineers on average ship 8x as much code per quarter as they did from 2021 to 2025”；“Claude authors about 80% of the code merged into our codebase today”；评审与安全流程需要同步扩展，否则按 Amdahl's Law 形成瓶颈。（安全文章，2026-07-21）Anthropic Institute 的文章给出同一组数据的口径与说明：80% 指 “the share of lines merged to production that can be attributed to Claude”，并说明代码行数 “is almost certainly an overstatement of the true productivity gain”。（https://www.anthropic.com/institute/recursive-self-improvement ）
- Claude Code 团队的体会：“the bottlenecks didn't go away when agentic coding took away the actual need to type code. Verification, code review, and security took their place.”（https://claude.com/blog/running-an-ai-native-engineering-org ，2026-06-03）

### 5.2 适用范围

- 面向人群：“This course is for engineering, platform, and security leads whose organization already uses Claude Code and whose approval gates, reviews, and handoffs still run at human speed. It is written for large enterprises, and especially regulated ones, where the review queue cannot be allowed to build and code cannot ship under-reviewed. The plays assume you can change how your organization plans, reviews, tests, and deploys, not only how it writes code.”（https://academy.claude.com/courses/ai-native-sdlc-playbook ）
- 前置条件：“You should be comfortable working in Claude Code day to day, and have a Git repository and CI pipeline you are allowed to change.”（同上）
- 采用方式可以分阶段、按需选择：“The steps are modular and organizations may choose to prioritize transforming different stages at different times based on their unique needs.” 以及 “Most organizations sit somewhere between the two columns.”（playbook）
- 与既有系统共存：Jira、需求管理工具、Figma、变更委员会可以继续作为权威记录，最低要求是交接物与既有记录互相链接。（playbook）
- 基础设施要求（按 playbook 各 play 的 Infrastructure 汇总）：非工程人员可用的 Claude（claude.ai 或 Cowork）；带 connector 的版本控制；Claude Code；运行 claude-code-action 或托管 Code Review 的 CI；非交互运行 Claude Code 的 CI 与 eval 预算；指标存储；沙箱执行环境；Claude Security 需要 Claude Enterprise、Anthropic GitHub App、Claude Code on the Web、Extra Usage 与高级席位；模型访问可以走 API、Bedrock、Vertex 或 Foundry。

### 5.3 Anthropic 陈述的局限与注意事项

- Skills 属于建议性控制，必须始终成立的规范需要 hook 或 PR 评审再次检查（见 3.1）。
- 并行会话的上限取决于人的评审能力：“The practical ceiling is how many streams one person can review properly, so add sessions only while review is keeping up.”（playbook）
- 构建阶段的审批 hook 会把人放回关键路径：“an approval prompt during the build puts a person back on the critical path of all the sessions running in parallel.” 因此需要人工审批的 hook 放在 Deploy。构建阶段的 hook 要快、只针对改动的文件，完整测试放在提交或 PR 阶段。（playbook）
- Managed settings 示例 “a starting point to tailor, rather than a recommendation to copy. Every deny trades against capability”。（playbook）
- Eval 会随模型进步而失效：“As models improve, cases that once discriminated stop doing so and new ones must be added.”（playbook）
- 扫描结果随时间与模型变化而过期：“A security scan is a point-in-time statement about a codebase under a particular model, and both halves go stale.” Claude Security 按 Mythos 5 价格计费。（playbook）
- 人工评审仍保留在受监管与关键代码上：“Layers of agentic review with human review reserved for regulated and critical code.”（playbook）
- 扫描成本随代码量增长：“Most scanning approaches, whether agentic or deterministic, are consumption based. Costs will increase as code throughput increases.”（安全文章）
- agent 边界要按权限划定：模型升级后，事故响应 agent 主动通过 Slack 请求另一个能写代码的 Claude 实例推送修复，“This was caught at a human review gate as designed”，教训是 “draw the boundary around access and actions, not around a model's instructions or what we believe a model can do.”（安全文章）
- 结构会退化，需要治理：“If a skill goes stale, a discovered bug class never makes it back into CLAUDE.md, or an agent's decisions go unsampled, the whole structure degrades.”（安全文章）
- 信任与核查的比例会随模型变化：“the right balance of trust vs. verify will keep changing as the models improve.”（https://claude.com/blog/running-an-ai-native-engineering-org ）
- 人对 AI 的实际委托程度有限：“while developers use AI in roughly 60% of their work, they report being able to "fully delegate" only 0-20% of tasks.”（2026 Agentic Coding Trends Report）
- 模型自评与 QA 能力：自评偏宽，需要独立 evaluator，且 evaluator 需要多轮调校；完整 harness 成本约为单 agent 的 20 倍以上（6 小时、200 美元对比 20 分钟、9 美元）。（harness 文章，2026-03-24）
- 值守报告需要团队自己的判断：“Claude can one-shot a skill that generates a status report, but what makes it readable is team-specific taste.”（https://claude.com/blog/ai-ci-cd-on-call ）
- 最终责任在人：“Humans remain accountable for every decision that requires judgment.” 以及 “The loop keeps running. Human judgement stays above it.”（playbook）

## 全部来源

### SDLC 核心发布

1. The AI-Native SDLC playbook，Louis Claxton，claude.com 博客，2026-08-21：https://claude.com/blog/the-ai-native-sdlc-playbook
2. The AI-native SDLC playbook，Claude Academy 课程（14 节课，页面未标注日期）：https://academy.claude.com/courses/ai-native-sdlc-playbook
   - Introduction：https://academy.claude.com/courses/ai-native-sdlc-playbook/introduction
   - Closing the loop on metrics：https://academy.claude.com/courses/ai-native-sdlc-playbook/closing-the-loop-on-metrics
3. How Anthropic secures its AI-native software development lifecycle，Jason Clinton，claude.com 博客，2026-07-21：https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle

### 相关官方文章与报告

4. 2026 Agentic Coding Trends Report，resources.anthropic.com，PDF 元数据创建日期 2026-01-21：https://resources.anthropic.com/2026-agentic-coding-trends-report ，PDF：https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf
5. Harness design for long-running application development，Prithvi Rajasekaran，Anthropic Engineering，2026-03-24：https://www.anthropic.com/engineering/harness-design-long-running-apps
6. Code Review 发布博客，claude.com，2026-03-09：https://claude.com/blog/code-review
7. A harness for every task: dynamic workflows in Claude Code，Thariq Shihipar、Sid Bidasaria，2026-06-02：https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code （现重定向到 claude.dev）
8. Running an AI-native engineering org，Fiona Fung，claude.com 博客，2026-06-03：https://claude.com/blog/running-an-ai-native-engineering-org
9. When AI builds itself，Anthropic Institute（页面未显示发布日期，页内有 Update 9/18/2026）：https://www.anthropic.com/institute/recursive-self-improvement
10. Introducing Claude Tag，anthropic.com 新闻，2026-06-23：https://www.anthropic.com/news/introducing-claude-tag
11. Agent identity and access model，Noah Zweben，claude.com 博客，2026-06-24：https://claude.com/blog/agent-identity-access-model
12. Claude on call: How Claude Tag serves as Anthropic's first responder for CI/CD failures，Sachin Malhotra，claude.com 博客，2026-08-18：https://claude.com/blog/ai-ci-cd-on-call
13. anthropics/oncall-kit（参考实现，2026-08-06 提交 v1.0，不再维护）：https://github.com/anthropics/oncall-kit
14. Automated security reviews in Claude Code，Claude 帮助中心，2026-03-16：https://support.claude.com/en/articles/11932705-automated-security-reviews-in-claude-code

### Claude Code 文档（code.claude.com，页面没有显示内容日期，读取日期 2026-09-25，对应版本约 2.1.281 至 2.1.282）

15. Changelog：https://code.claude.com/docs/en/changelog ；GitHub 原文：https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
16. What's new，2026 年第 22 周：https://code.claude.com/docs/en/whats-new/2026-w22
17. Permission modes：https://code.claude.com/docs/en/permission-modes
18. Hooks reference：https://code.claude.com/docs/en/hooks
19. Hooks guide：https://code.claude.com/docs/en/hooks-guide
20. Settings：https://code.claude.com/docs/en/settings
21. Settings reference：https://code.claude.com/docs/en/settings-reference
22. Managed settings：https://code.claude.com/docs/en/managed-settings
23. Server-managed settings：https://code.claude.com/docs/en/server-managed-settings
24. Permissions：https://code.claude.com/docs/en/permissions
25. Sandboxing：https://code.claude.com/docs/en/sandboxing
26. Memory：https://code.claude.com/docs/en/memory
27. Skills：https://code.claude.com/docs/en/skills
28. Subagents：https://code.claude.com/docs/en/sub-agents
29. Worktrees：https://code.claude.com/docs/en/worktrees
30. Headless（`claude -p`）：https://code.claude.com/docs/en/headless
31. How Claude Code works：https://code.claude.com/docs/en/how-claude-code-works
32. Context window：https://code.claude.com/docs/en/context-window
33. Model configuration（auto-compact 阈值）：https://code.claude.com/docs/en/model-config
34. Sessions：https://code.claude.com/docs/en/sessions
35. Glossary：https://code.claude.com/docs/en/glossary
36. Goal：https://code.claude.com/docs/en/goal
37. Workflows：https://code.claude.com/docs/en/workflows
38. Code Review：https://code.claude.com/docs/en/code-review
39. GitHub Actions：https://code.claude.com/docs/en/github-actions
40. Security guidance plugin：https://code.claude.com/docs/en/security-guidance
41. Monitoring（OpenTelemetry）：https://code.claude.com/docs/en/monitoring-usage
42. Plugin marketplaces：https://code.claude.com/docs/en/plugin-marketplaces
43. Managed MCP：https://code.claude.com/docs/en/managed-mcp
44. Remote Control：https://code.claude.com/docs/en/remote-control
45. playbook 资源清单中列出、本次调研未单独展开的页面：https://code.claude.com/docs/en/admin-setup 、https://code.claude.com/docs/en/mcp 、https://code.claude.com/docs/en/third-party-integrations 、https://code.claude.com/docs/en/network-config 、https://code.claude.com/docs/en/analytics 、https://code.claude.com/docs/en/security 、https://platform.claude.com/docs/en/manage-claude/compliance-api

### Claude Agent SDK 文档

46. Overview：https://code.claude.com/docs/en/agent-sdk/overview （由 https://platform.claude.com/docs/en/agent-sdk/overview 重定向）
47. Sessions：https://code.claude.com/docs/en/agent-sdk/sessions
48. Agent loop：https://code.claude.com/docs/en/agent-sdk/agent-loop
49. Subagents：https://code.claude.com/docs/en/agent-sdk/subagents

### Claude Tag 文档（页面标注 Public Beta）

50. Overview：https://claude.com/docs/claude-tag/overview
51. Admin setup overview：https://claude.com/docs/claude-tag/admins/setup-overview
52. Memory：https://claude.com/docs/claude-tag/users/memory
53. How it works：https://claude.com/docs/claude-tag/concepts/how-it-works
54. Agent identity：https://claude.com/docs/claude-tag/concepts/agent-identity

### 产品页面（playbook 中给出的链接；文中的产品状态取自 playbook 原文与 Claude Tag 文档）

55. Claude Tag：https://claude.com/product/tag
56. Claude Design：https://claude.com/product/design
57. Claude Security：https://claude.com/product/claude-security
58. Cowork：https://claude.com/product/cowork

### 第三方来源（只用于定位原文，内容为转述）

59. When AI builds itself 的发布日期 2026-06-04 取自第三方报道：https://pasqualepillitteri.it/en/news/4268/recursive-self-improvement-anthropic-ai
