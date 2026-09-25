# Loop engineering 调研

调研日期：2026-09-25。标注「转述」的条目来自二手来源，其余条目均已读取原文或原始仓库。日期写法为 YYYY-MM-DD；推文时间为 UTC。

---

## 1. 出处、时间与传播；与 context engineering 的关系

### 1.1 谁、何时、在哪里提出

「loop engineering」这个名字没有唯一的发明人。它在 2026 年 6 月上旬由三件相互关联的事情共同推出，其中 Addy Osmani 的文章首次把它作为一门工作的名称并给出组成部分。

- **Boris Cherny（Anthropic，Claude Code 负责人）的访谈发言**。场合是 Acquired Unplugged（WorkOS 主办）。WorkOS 对这次访谈的整理文章发布于 2026-06-02，文中转述：他现在不再直接向 Claude 发提示，而是编写循环，让循环去提示 Claude 并决定下一步做什么（[WorkOS，2026-06-02](https://workos.com/blog/boris-cherny-claude-code-acquired-interview-takeaways)）。WorkOS 页面本身没有逐字引语；被广泛引用的原话 “I don't prompt Claude anymore. I have loops running that prompt Claude and figuring out what to do. My job is to write loops.” 见于 Osmani 的文章（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）。Lulla 等人的论文把这次访谈的日期记为 2026-06-02（[arXiv 2608.21884，2026-08-22/26](https://arxiv.org/abs/2608.21884)）。
- **Peter Steinberger（OpenClaw 作者）的推文**，2026-06-07 18:58 UTC：“Here's your monthly reminder that you shouldn't be prompting coding agents anymore. You should be designing loops that prompt your agents.” 截至 2026-09-25 显示约 853 万次浏览、1,786 条回复（[x.com/steipete/status/2063697162748260627](https://x.com/steipete/status/2063697162748260627)，数据经 [api.fxtwitter.com](https://api.fxtwitter.com/steipete/status/2063697162748260627) 读取）。
- **Addy Osmani 的文章《Loop Engineering》**，发表于 2026-06-07，地址 [addyosmani.com/blog/loop-engineering](https://addyosmani.com/blog/loop-engineering/)。文章引用了上面两句话，并给出定义：“Loop engineering is replacing yourself as the person who prompts the agent. You design the system that does it instead.” 作者页面现写明他是 Anthropic 的技术人员（Member of Technical Staff，负责 Claude Code 相关工作），此前在 Google 工作 14 年以上。Lulla 等人的论文认定 Osmani 的这篇文章为这一实践命名（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。

后续传播中的主要节点：

- 2026-06-30，Anthropic 官方博客以《Loop engineering: Getting started with loops》为题发布 Claude Code 团队的循环指南，作者 Delba de Oliveira、Michael Segner（[claude.com/blog/getting-started-with-loops，2026-06-30](https://claude.com/blog/getting-started-with-loops)）。
- 2026-07-14，Gergely Orosz 在 The Pragmatic Engineer 发表《What is "loop engineering"?》（[newsletter.pragmaticengineer.com，2026-07-14](https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering)）。
- 2026-07-17，IBM Think 发布术语条目《What Is Loop Engineering?》，作者 Ivan Belcic、Cole Stryker（[ibm.com/think/topics/loop-engineering，2026-07-17](https://www.ibm.com/think/topics/loop-engineering)）。
- 2026-08-22（v1）/2026-08-26（v2），第一篇以此为题的实证论文《Loop Engineering: Building Blocks, Adoption, and Impact》（Singapore Management University 与 Heidelberg University）上线 arXiv（[arXiv 2608.21884](https://arxiv.org/abs/2608.21884)）。

### 1.2 名称出现之前的产品功能与前身

名称出现在 2026 年 6 月，但相应的产品功能在 3 月到 5 月之间已经发布：

- 2025-07-14，Geoffrey Huntley 发表《Ralph Wiggum as a "software engineer"》，提出 “Ralph is a Bash loop”：`while :; do cat PROMPT.md | claude-code ; done`（[ghuntley.com/ralph，2025-07-14](https://ghuntley.com/ralph/)）。Orosz 把它列为 loop engineering 的直接前身（[Pragmatic Engineer，2026-07-14](https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering)）。
- 2026-03-06，Claude Code v2.1.71 新增 `/loop`（按间隔重复运行提示）（[Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；发布时间取自 npm 的 `@anthropic-ai/claude-code` 版本时间）。
- 2026-04-16 至 2026-04-25，OpenAI Codex 合并 Goals 功能的 5 个 PR（#18073 至 #18077，作者 Eric Traut）（[openai/codex PR #18073](https://github.com/openai/codex/pull/18073)）；2026-04-30 随 Codex 0.128.0 发布（[Codex release rust-v0.128.0，2026-04-30](https://github.com/openai/codex/releases/tag/rust-v0.128.0)；版本号见 [OpenAI Cookbook，2026-07-14 修订](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)）。
- 2026-05-11，Claude Code v2.1.139 新增 `/goal`（[Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)）。
- 2026-05-28，Claude Code v2.1.154 推出 dynamic workflows（由脚本编排数十到数百个 agent）（[Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)）。

### 1.3 「最新动向」的时间位置

- 2026-07-18 00:34 UTC，Steinberger 发布推文 “Are we still talking loops or did we shift to graphs yet?”（截至 2026-09-25 约 313 万次浏览）（[x.com/steipete/status/2078277297791189132](https://x.com/steipete/status/2078277297791189132)）。同日 05:09 UTC，Hamel Husain 发布 X Article《Loop Engineering Is Dead. Enter Graph Engineering》，正文只有一张动图（[x.com/HamelHusain/status/2078346425621237935](https://x.com/HamelHusain/status/2078346425621237935)）；他随后补充 “If I saw this on the TL I would personally be afraid to click on it. But I promise its not what you think it is.”（[x.com/HamelHusain/status/2078348097697263855，2026-07-18](https://x.com/HamelHusain/status/2078348097697263855)）。
- Louis-François Bouchard 把这两条帖子描述为玩笑：“Peter Steinberger posted one tongue-in-cheek line … Then Hamel Husain played along …”，并称后续讨论 “mostly all a big meme around creating new terms”（[louisbouchard.substack.com，2026-07-22](https://louisbouchard.substack.com/p/graph-engineering-explained-what)）。
- Turing Post 指出 loop engineering 这个名字当时只存在了约六周，随后出现的「graph engineering」相关说法中有大量夸大与错误归属（例如把单篇研究的数字说成行业结论、把 DSPy 说成知识图谱工具）（[turingpost.com，2026-07-20](https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it)）。

截至 2026-09-25，loop engineering 是 2026 年 6 月至 7 月形成的说法；它在 7 月中旬已被「graph engineering」话题接续，而后者起源于玩笑，其实质内容（多个循环之间的编排）见第 2.3 节与第 3.1 节。

### 1.4 名称冲突

同一名称还有另一种用法：Haggai Roitman 的书稿《The Hitchhiker's Guide to Agentic AI》把 “loop engineering” 用于指 inference-time RL、generate-verify-retry 优化与自适应预算控制（[arXiv 2606.24937，2026-06-22 初版，2026-07-27 修订](https://arxiv.org/abs/2606.24937)）。Lulla 等人在效度讨论中也提到这个名称与无关用法冲突（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。本文只讨论编码 agent 方向的用法。

### 1.5 与 context engineering 的关系

**context engineering 的来源（2025 年）**

- Tobi Lütke（Shopify CEO），2025-06-19：“I really like the term "context engineering" over prompt engineering. It describes the core skill better: the art of providing all the context for the task to be plausibly solvable by the LLM.”（[x.com/tobi/status/1935533422589399127](https://x.com/tobi/status/1935533422589399127)）
- Andrej Karpathy，2025-06-25：把 context engineering 描述为 “the delicate art and science of filling the context window with just the right information for the next step”，并在同一条推文中列出 context engineering 之上还需要的一层：“break up problems just right into control flows … dispatch calls to LLMs of the right kind and capability … handle generation-verification UIUX flows”（[x.com/karpathy/status/1937902205765607626](https://x.com/karpathy/status/1937902205765607626)）。这里列出的控制流与「生成—验证」流程，正是 2026 年 loop engineering 讨论的对象。
- Anthropic《Effective context engineering for AI agents》，2025-09-29：定义为 “The set of strategies for curating and maintaining the optimal set of tokens (information) during LLM inference”；面向长任务给出三种技术：compaction（接近上限时摘要并重新开始）、structured note-taking（agent 把笔记写到上下文窗口之外，之后再取回）、sub-agent architectures（子 agent 在干净的上下文里工作，只返回 1,000 至 2,000 token 的摘要）（[anthropic.com/engineering/effective-context-engineering-for-ai-agents，2025-09-29](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)）。

**层次关系**

- Osmani 在 2026-04-19 的《Agent Harness Engineering》中写 “Agent = Model + Harness”，并说 “Context is scarce, and harnesses are largely delivery mechanisms for good context engineering.”（[addyosmani.com/blog/agent-harness-engineering，2026-04-19](https://addyosmani.com/blog/agent-harness-engineering/)）。在《Loop Engineering》中他写 “Loop engineering sits one floor above the harness.”（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）
- Lulla 等人给出四层：prompt engineering（单条指令）→ context engineering（模型上下文窗口里的全部内容）→ harness engineering（驱动单次运行的模型外围软件）→ loop engineering（跨时间的重复运行）（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。
- Sandeco Macedo 的论文同样把 loop 放在 context 之上、harness 之外：context engineering 管 agent 知道什么，harness 提供工具与环境，loop 包裹 harness（[arXiv 2607.00038，2026-06-28](https://arxiv.org/abs/2607.00038)）。
- codecentric 的文章强调下层缺陷会被上层放大：循环会更快地重复建立在糟糕上下文之上的结果；糟糕的 harness 会被自动化反复调用（[codecentric.de，2026-07-05](https://www.codecentric.de/en/knowledge-hub/blog/loop-harness-context-engineering-explained)）。

**具体的依赖**：loop engineering 的几个核心部件直接沿用 2025 年 context engineering 的技术。外部状态文件对应 structured note-taking；maker 与 checker 分离、workflow 中的子 agent 对应 sub-agent architectures；同一会话内的长循环依赖 compaction。context engineering 回答「这一次调用看到什么」；loop engineering 回答「何时发起调用、重复多少次、何时停止、两次调用之间的状态放在哪里」。

---

## 2. 核心主张与具体做法

### 2.1 核心主张

- 人从「逐轮输入下一条提示的人」变为「设计替自己发提示的系统的人」（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）。
- 学术上的工作定义：“the practice of designing automated control structures that repeatedly invoke coding agents, triggered on a schedule or by events, with each run bounded by a machine-checkable stop condition.”（[Lulla 等，arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）
- Anthropic Claude Code 团队的定义：“agents repeating cycles of work until a stop condition is met”（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)）。
- Armin Ronacher 区分两层循环：内层 agent loop（模型调用工具、读取文件、运行测试、给出答案）与外层 harness loop（外部系统把任务排进队列、分配给机器尝试，并决定继续、修改上下文或改变方向），外层的特点是 “The task stays alive beyond the point where the model by itself would normally have said: 'I am done.'”（[lucumr.pocoo.org，2026-06-23](https://lucumr.pocoo.org/2026/6/23/the-coming-loop/)）。loop engineering 讨论的是外层。

### 2.2 组成部分

**Osmani 的五个部件加一层记忆**（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）

- Automations：定时的发现与分诊任务，是循环的「心跳」；列出 `/loop`（按节奏重复）与 `/goal`（直到条件成立）。
- Worktrees：并行 agent 各用独立的 git worktree，避免文件冲突。
- Skills：以 `SKILL.md` 记录项目约定与构建步骤，每次运行都读取。
- Plugins 与 connectors：通过 MCP 接入工单系统、数据库、Slack 等。
- Sub-agents：把产生方案的 agent（maker）与检查的 agent（checker）分开，可使用不同模型与推理强度。
- Memory：Markdown 文件或 Linear 看板，保存「做完了什么、下一步是什么」。
- 他给的典型循环：早上定时运行分诊 skill → 读取 CI 失败、issue 与最近提交 → 为每项修复创建独立的 worktree → 一个子 agent 编写修复草稿 → 另一个子 agent 按测试与 skill 检查 → connector 创建 PR 并更新工单 → 状态文件记录进度供次日运行。

**Anthropic 的四种循环**（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)）

| 类型 | 触发 | 停止 | 适用 |
|---|---|---|---|
| Turn-based | 用户提示 | “Claude judges it has completed the task or needs additional context.” | 短小、探索性任务 |
| Goal-based（`/goal`） | 用户实时设定 | 目标达成或达到轮次上限 | 有可验证出口的任务 |
| Time-based（`/loop`、`/schedule`） | 时间间隔 | 手动取消或工作完成（PR 合并、队列清空） | 周期性工作、与外部系统交互 |
| Proactive | 事件或日程，无人实时参与 | 单个任务按目标退出，routine 持续到被停用 | 缺陷报告、issue 分诊、迁移、依赖升级 |

Proactive 循环由 `/schedule`（routine）+ `/goal` + skills + dynamic workflows + auto mode 组合而成。

**Macedo 的 loop specification**（[arXiv 2607.00038，2026-06-28](https://arxiv.org/html/2607.00038v1)）

- 五个要素：trigger、goal、verification、stopping rule、memory；定义为 “a bounded, reusable artifact that a human designs and hands to an agent harness so the agent pursues a goal on its own”。
- 停止规则要把运行引向有名字的终止状态：success、no-op、blocked、stalled、exhausted。
- 验证分五级：L1 确定性检查（断言、退出码、标准输出比对）；L2 规则约束（linter、schema、策略）；L3 延迟的真实反馈（测试、部署、真实用户反馈）；L4 模型评审（按 rubric）；L5 人工审批。L1 至 L2 为可无人值守运行的区间。

**Lulla 等人从灰色文献中整理的构件**（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）

触发器、机器可检查的停止条件、持久状态文件（如 `STATE.md`、`LOOP.md`）、skills、worktree 并行隔离、maker/checker 分离、人工监督与上报点、token 预算与暂停控制、分级放权（L1 只出报告 → L2 辅助修复 → L3 无人值守）。其中 maker/checker 分离是被强调最多的构件。

### 2.3 各项做法的细节

**停止条件的写法**

- Claude Code 文档要求条件包含：一个可度量的终态（测试结果、构建退出码、文件数、空队列）、一个明确的检查方式（如 “`npm test` exits 0”）、途中不得改变的约束；可在条件里加轮次或时间上限，如 “or stop after 20 turns”；条件最长 4,000 字符（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)，读取于 2026-09-25）。
- OpenAI 建议 Goal 写明六项：Outcome、Verification surface、Constraints、Boundaries、Iteration policy、Blocked stop condition（[OpenAI Cookbook《Using Goals in Codex》，2026-07-14 修订](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)）。
- Anthropic：“When you define the success criteria, Claude doesn't have to make a determination on what is 'good enough' and end the loop early.”（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)）

**验证与反馈**

- Claude Code `/goal`：每轮结束后评估模型给出三种结论之一，Not yet met 时 “Claude keeps working and takes the reason as guidance for the next turn”（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)）。
- Hermes Agent `/goal`：可挂 shell 命令作为 quality gate，gate 失败时把输出交给 agent 继续修改（[hermes-agent.nousresearch.com/docs/user-guide/features/goals](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)，读取于 2026-09-25）。
- Osmani：“The most useful structural thing in a loop, by far, is splitting the one who writes from the one who checks. The model that wrote the code is way too nice grading its own homework.”（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）

**重试与失败处理**

- Claude Code `/goal`：认证失败、额度耗尽、自动压缩无法解决的上下文溢出、模型不可用这四类错误会清除目标；服务器过载、断线等会自动重试，三次后暂停；速率限制、用量上限会暂停并在额度恢复后继续（v2.1.269 起）（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)）。
- Codex：同一阻塞条件连续出现至少三个 goal 轮次后，模型才可把目标标为 `blocked`（[openai/codex `codex-rs/ext/goal/templates/goals/continuation.md`，提交 bf832f4678，2026-09-25](https://github.com/openai/codex/blob/bf832f4678/codex-rs/ext/goal/templates/goals/continuation.md)）。
- Claude Code dynamic workflows：结构化输出校验失败时重试 5 次；文档给出「修复直到 `tsc` 通过，或连续两轮没有进展」这类循环写法（[code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)）。

**无进展检测**

- Claude Code `/goal`：连续若干轮没有工具调用时停止循环并交还控制（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)）。
- Codex：一次自动继续的轮次如果没有任何工具调用，下一次自动继续被抑制；继续提示要求模型把上一轮归类为 progress、verified wait 或 no progress（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)；[continuation.md，bf832f4678](https://github.com/openai/codex/blob/bf832f4678/codex-rs/ext/goal/templates/goals/continuation.md)）。

**长时间自主运行**

- Claude Code routines：保存的提示 + 仓库 + connectors，在云端按日程（最短 1 小时）、API 调用或 GitHub 事件运行，无权限确认环节；目前为 research preview（[code.claude.com/docs/en/routines](https://code.claude.com/docs/en/routines)）。
- `/loop` 的周期任务 7 天后自动过期，“This bounds how long a forgotten loop can run.”（[code.claude.com/docs/en/scheduled-tasks](https://code.claude.com/docs/en/scheduled-tasks)）
- `/goal` 遇到后台任务未结束时推迟评估，30 分钟后发起检查，之后间隔加倍（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)）。
- 案例：Anthropic 的 C 编译器项目用 `while true` 脚本反复启动 Claude，约两周内 2,000 次会话、16 个 agent 并行，产出 10 万行编译器（[anthropic.com/engineering/building-c-compiler，2026-02-05](https://www.anthropic.com/engineering/building-c-compiler)）；Karpathy 的 autoresearch 让 agent 通宵运行约 100 次 5 分钟训练实验（[karpathy/autoresearch program.md，2026-03-09](https://github.com/karpathy/autoresearch/blob/master/program.md)）。

**多个循环的组合**

- Anthropic 的 proactive 循环例子：routine 每小时检查新反馈 → 分诊并处理每份报告 → 用 workflow 在三个并行 worktree 里探索三种解法，并由 judge agent 做对抗式评审（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)）。
- Claude Code dynamic workflows 用 JavaScript 脚本编排子 agent：`agent()` 启动一个子 agent，`pipeline()` 对列表逐项启动，`parallel()` 并发执行；单次运行最多 1,000 个 agent，默认并发 16 个（[code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)）。
- 「graph engineering」话题讨论的就是这一层：Turing Post 写道 “A loop is already a graph. It is simply a graph whose path returns to an earlier node.”（[Turing Post，2026-07-20](https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it)）；Bouchard：“A graph becomes useful when one loop is no longer enough”（[Bouchard，2026-07-22](https://louisbouchard.substack.com/p/graph-engineering-explained-what)）。

**预算**

- Codex 的 goal 带 `token_budget`，额度计量用 SQL 原子更新，超出时运行时向模型注入 `budget_limit` 提示（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)；实现分析见 [gist patleeman，转述](https://gist.github.com/patleeman/b1b5768393f9bf2f60865b1defeeb819)）。
- Anthropic 建议：routine 使用更小更快的模型，需要判断的环节再用强模型；大规模运行前先试点；“Running a script is cheaper than reasoning through the steps.”（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)）

---

## 3. 确定性代码与 LLM 的分工

### 3.1 下一步做什么由谁决定

| 实现 | 下一步的具体动作 | 是否再来一轮 |
|---|---|---|
| Ralph（Huntley） | LLM：“You also need to trust Ralph to decide what's the most important thing to implement.” | bash `while` 循环，无条件继续（[ghuntley.com/ralph，2025-07-14](https://ghuntley.com/ralph/)） |
| Anthropic 长任务 harness | LLM 从 JSON 功能清单中挑选优先级最高的未完成项 | 外部 harness 启动新会话（[anthropic.com/engineering/effective-harnesses-for-long-running-agents，2025-11-26](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)） |
| C 编译器项目 | LLM 自行选择任务，通过在 `current_tasks/` 中创建锁文件并借助 git 同步避免重复 | `while true` 脚本（[Anthropic，2026-02-05](https://www.anthropic.com/engineering/building-c-compiler)） |
| Claude Code `/loop` | LLM | 固定间隔由 cron 决定；自定节奏模式由 Claude 选择 1 分钟到 1 小时的间隔，并可调用 `ScheduleWakeup` 的 `stop: true` 自行结束（[scheduled-tasks 文档](https://code.claude.com/docs/en/scheduled-tasks)） |
| Claude Code `/goal` | LLM | 评估模型的结论决定（见 3.2）（[goal 文档](https://code.claude.com/docs/en/goal)） |
| Codex Goals | LLM：“Codex can … choose the next useful action” | 运行时决定：只在线程空闲、无排队输入、目标为 active 且未超预算时继续；中断即暂停（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)） |
| Claude Code dynamic workflows | 脚本：文档对比表中 “Who decides what runs next” 一栏，subagents 与 skills 为 “Claude, turn by turn”，agent teams 为 “The lead agent, turn by turn”，workflows 为 “The script” | 脚本中的循环与分支；运行时限制总数 1,000 个 agent（[workflows 文档](https://code.claude.com/docs/en/workflows)） |
| Google ADK 2.0 | 图中的确定性节点负责路由、调度与数据变换；模型负责分类等判断 | 图的边与重试策略（[ADK Go 2.0 公告，2026-06-30](https://developers.googleblog.com/announcing-adk-go-20/)；[adk.dev/2.0](https://adk.dev/2.0/)） |

要点：

- 在大多数编码循环里，LLM 决定具体做什么，确定性代码决定「是否再运行一轮」（触发器、继续条件、预算、上限）。
- Claude Code workflows 与 ADK 2.0 把「计划」本身移进代码。Claude Code 文档原话：“A workflow moves the plan into code. With subagents, skills, and agent teams, Claude is the orchestrator … A workflow script holds the loop, the branching, and the intermediate results itself, so Claude's context holds only the final answer.”（[workflows 文档](https://code.claude.com/docs/en/workflows)）值得注意：workflow 脚本由 Claude 编写，写好后由运行时确定性地执行；为了保证中断后能重放，脚本里的 `Date.now()`、`Math.random()` 会直接报错。
- ADK Go 2.0 公告的表述：“The model makes the decision; the graph makes it reliable, observable, and resumable.” 动机是 “Real agent applications … classify, branch, fan out to specialists, gather results, ask a human to approve something, retry on failure, and loop until done. Expressing that as ad-hoc control flow gets brittle fast.”（[developers.googleblog.com，2026-06-30](https://developers.googleblog.com/announcing-adk-go-20/)）
- Ronacher 的观察：“Many successful applications of loops use another LLM as a judge or as an orchestrator.”（[lucumr.pocoo.org，2026-06-23](https://lucumr.pocoo.org/2026/6/23/the-coming-loop/)）

### 3.2 什么算完成、什么结果被接受为事实

可以按「谁作出完成判定」分成四类，同一实现常组合多类。

**（1）工作中的 LLM 自己宣布**

- Claude Code 官方 Ralph 插件：Stop hook 拦截退出、把同一提示重新送入；模型输出约定的 completion promise 字符串（如 `<promise>COMPLETE</promise>`）即结束，`--max-iterations` 作为上限（[anthropics/claude-plugins-official `plugins/ralph-loop/README.md`，提交 986deab6a1，2026-03-28](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop)）。
- Codex Goals：由正在工作的模型调用 `update_goal`，把状态设为 `complete`。工具说明写 “Set status to `complete` only when the objective has actually been achieved and no required work remains.” 继续提示要求先做 completion audit：“treat completion as unproven … For every explicit requirement … identify the authoritative evidence that would prove it … Treat uncertain or indirect evidence as not achieved”。暂停、恢复、预算受限这些状态迁移由用户或系统控制：“You cannot use this tool to resume, budget-limit, or usage-limit a goal; those status changes are controlled by the user or system.”（[openai/codex `codex-rs/ext/goal/src/spec.rs` 与 `templates/goals/continuation.md`，提交 bf832f4678，2026-09-25](https://github.com/openai/codex/tree/bf832f4678/codex-rs/ext/goal)）。OpenAI Cookbook 的说法：“The model can start a Goal and can mark an existing Goal complete only when the evidence supports completion.”（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)）也就是说，Codex 的完成判定仍由工作模型作出，约束来自提示中的审计要求。
- Claude Code turn-based 循环与自定节奏 `/loop`：由 Claude 判断完成（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)；[scheduled-tasks 文档](https://code.claude.com/docs/en/scheduled-tasks)）。

**（2）另一个 LLM 评审**

- Claude Code `/goal`：“`/goal` is a wrapper around a session-scoped prompt-based Stop hook.” 每轮结束后把条件与目前的对话发给 small fast model（Claude API 上默认 Haiku），返回 Not yet met / Met / Impossible 之一及理由。评估模型 “does not call tools, so it can only judge what Claude has already surfaced in the conversation.” 条件里的轮次上限同样由评估模型根据对话内容判断（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)）。
- Hermes Agent `/goal`：辅助模型读取目标文本与 agent 最后一次回复（约 4 KB），返回 `done`、`blocked`、`continue`、`wait`；评审出错时按 `continue` 处理（fail-open），以轮次预算（默认 20）为最后保障（[Hermes 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)）。
- Osmani 的 verifier sub-agent；Claude Code workflow 的对抗式评审（`/deep-research` 对每条论断投票，未通过交叉核对的论断被过滤）（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)；[workflows 文档](https://code.claude.com/docs/en/workflows)）。

**（3）确定性检查**

- Hermes 的 quality gates：挂接的 shell 命令必须以 0 退出，之后才进入 LLM 评审（[Hermes 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)）。
- Claude Code Stop hook 可以运行脚本做确定性检查（[code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal) 的对比说明）。
- karpathy/autoresearch：`prepare.py` 只读，“The `evaluate_bpb` function in `prepare.py` is the ground truth metric.” 规则是 val_bpb 降低就保留提交，否则 `git reset`。执行保留或回退的仍是 agent 本身（[program.md，提交 068d93da75，2026-03-09](https://github.com/karpathy/autoresearch/blob/068d93da75/program.md)）。
- C 编译器项目：测试集与作为 “known-good compiler oracle” 的 GCC 驱动进度（[Anthropic，2026-02-05](https://www.anthropic.com/engineering/building-c-compiler)）。
- Anthropic 长任务 harness：初始化 agent 写出 200 多项端到端功能清单，每项带 `passes` 布尔值，编码 agent 只允许修改这个字段，“It is unacceptable to remove or edit tests”；这个结构用来解决模型过早宣布项目完成的问题。该字段仍由编码 agent 在自己完成浏览器自动化测试之后修改（[Anthropic，2025-11-26](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）。
- Macedo 对 50 个真实循环的统计：70% 的验证落在 L1 至 L2（确定性检查与规则约束），22% 依赖模型评审（[arXiv 2607.00038](https://arxiv.org/html/2607.00038v1)）。

**（4）人**

PR 评审、code owners、上报点（[Lulla 等，arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。

**关于「完成」可信度的共同看法**

- Osmani：“even then 'done' is a claim and not a proof.”（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）
- OpenAI：“Codex can keep moving, but the evidence decides whether it is done.”（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)）
- 即使检查本身是确定性的（运行测试），在 Claude Code `/goal`、Codex、Ralph 等实现里，测试通常由工作中的 LLM 运行并在对话中报告，评审方读取的是这份报告。
- 预算与上限的执行方式各不相同：Codex 的 token 预算由运行时强制；Hermes 的轮次上限由代码强制；Claude Code workflow 的 1,000 个 agent 上限由运行时强制；Claude Code `/goal` 的轮次上限写在条件文字里，由评估模型判断。

### 3.3 每次调用的上下文如何组成

**（a）同一会话累加，必要时压缩**

- Claude Code `/goal`、`/loop` 都在当前会话中运行；评估模型收到「条件 + 目前为止的对话」；自动压缩无法解决的上下文溢出会清除目标（[goal 文档](https://code.claude.com/docs/en/goal)；[scheduled-tasks 文档](https://code.claude.com/docs/en/scheduled-tasks)）。
- Codex Goals 是线程级状态：“the objective belongs to the thread where the relevant context lives, including the files Codex inspected, the commands it ran, the diffs it produced”（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)）。每次自动继续时，运行时重新注入目标原文与预算数字，并要求 “Use the current worktree and external state as authoritative. Previous conversation context can help locate relevant work, but inspect the current state before relying on it.”（[continuation.md，bf832f4678](https://github.com/openai/codex/blob/bf832f4678/codex-rs/ext/goal/templates/goals/continuation.md)）
- Hermes：继续提示作为普通 user 消息追加到历史中，不修改 system prompt，不破坏提示缓存（[Hermes 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)）。
- autoresearch 在一个长会话里「LOOP FOREVER」，并要求把训练输出重定向到文件，只用 `grep` 读取指标：“do NOT use tee or let output flood your context”（[program.md](https://github.com/karpathy/autoresearch/blob/068d93da75/program.md)）。

**（b）每一轮全新上下文，从文件重新装配**

- Ralph：每次迭代都是新的上下文窗口，重新载入 `PROMPT.md`、`specs/*` 与 `fix_plan.md`；“The more you use the context window, the worse the outcomes you'll get”（[ghuntley.com/ralph](https://ghuntley.com/ralph/)）。
- C 编译器项目：每个 agent 在新的 Docker 容器里启动，读取 `AGENT_PROMPT.md`、README 与进度文件；作者强调测试输出要为 Claude 设计，“The test harness should not print thousands of useless bytes”（[Anthropic，2026-02-05](https://www.anthropic.com/engineering/building-c-compiler)）。
- Anthropic 长任务 harness：每个会话开始先执行 `pwd`，读取 git log 与 `claude-progress.txt`，读取功能清单，启动开发服务器并运行基本的端到端测试（[Anthropic，2025-11-26](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）。
- Claude Code routines：每次运行都是新会话，仓库重新克隆，输入是保存的提示加可选的触发载荷；载荷包在 `<routine-fire-payload>` 块中并标为不可信数据（[routines 文档](https://code.claude.com/docs/en/routines)）。
- Osmani 在《Long-running agents》中总结 Anthropic 的经验：摘要式压缩对超长任务不够，改为彻底重置上下文，再从结构化的交接文件重建（[addyosmani.com/blog/long-running-agents，2026-04-28](https://addyosmani.com/blog/long-running-agents/)）。Orosz 也把「用新的上下文窗口减少 context rot」列为循环的特征（[Pragmatic Engineer，2026-07-14](https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering)）。

**（c）脚本逐次装配、按任务分发**

- Claude Code workflows：每个 `agent()` 调用的提示由脚本计算，子 agent 各自的上下文互不共享；“Intermediate results stay in script variables instead of landing in Claude's context.” 可用 `schema` 要求子 agent 返回符合结构的 JSON（[workflows 文档](https://code.claude.com/docs/en/workflows)）。
- Macedo 的设计原则 C 要求在生成方与评审方之间切断共享上下文，防止 reward hacking；原则 D 要求记忆经过筛选再保留，避免无差别累加（[arXiv 2607.00038](https://arxiv.org/html/2607.00038v1)）。

### 3.4 会话或 agent 是否持久，是否跨任务保留记忆

- **会话级**：`/loop` 任务随会话存在，开新对话即清空，恢复会话时恢复未过期的 cron 任务，自定节奏的 `/loop` 不恢复（[scheduled-tasks 文档](https://code.claude.com/docs/en/scheduled-tasks)）。`/goal` 每个会话一个，恢复会话时恢复条件，但轮次、计时与 token 基线清零（[goal 文档](https://code.claude.com/docs/en/goal)）。
- **线程级持久**：Codex Goals 存在 SQLite 表 `thread_goals` 中；“Goals are implemented as persisted thread state, not as global memory and not as project-level instructions.”（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)；[openai/codex `codex-rs/state/migrations/0029_thread_goals.sql`](https://github.com/openai/codex/blob/bf832f4678/codex-rs/state/migrations/0029_thread_goals.sql)）。Hermes 的 goal 状态存于 `SessionDB.state_meta`，可跨 `/resume` 保留（[Hermes 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)）。
- **每次运行都是新 agent**：routines 的 GitHub 触发 “Claude Code doesn't reuse sessions across events, so two PR updates produce two independent sessions.”（[routines 文档](https://code.claude.com/docs/en/routines)）；Ralph 与 C 编译器项目的每次迭代同样如此。
- **跨任务的记忆放在文件与外部系统里**：Osmani：“the model forgets everything between runs so the memory has to be on disk and not in the context.”（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）；“the agent itself is amnesiac, but the filesystem isn't.”（[Osmani，2026-04-28](https://addyosmani.com/blog/long-running-agents/)）。常见载体为 `STATE.md`、`progress.txt`、`CHANGELOG.md`、`CLAUDE.md`、`AGENTS.md`、skills、Linear 看板、git 历史。Anthropic 的科学计算长任务中，`CLAUDE.md` 由 agent 自己在工作中修改，`CHANGELOG.md` 作为 “portable long-term memory” 记录已完成任务与失败的尝试（[anthropic.com/research/long-running-Claude，2026-03-23](https://www.anthropic.com/research/long-running-Claude)）。
- **持久的是循环定义**：`.claude/loop.md`、保存到 `.claude/workflows/` 的脚本、routine 配置、skills 都随仓库或账号保存，每次运行重新读取（[scheduled-tasks 文档](https://code.claude.com/docs/en/scheduled-tasks)；[workflows 文档](https://code.claude.com/docs/en/workflows)；[routines 文档](https://code.claude.com/docs/en/routines)）。
- **实际采用情况与主张有差距**：Lulla 等人扫描 36,710 个仓库，确认 217 个自主 agent 循环，状态文件检测到 2 个、确认 0 个，“almost none commits the state files the discourse prescribes”（[arXiv 2608.21884](https://arxiv.org/abs/2608.21884)）；Macedo 的 50 个循环中只有 32% 有持久记忆（[arXiv 2607.00038](https://arxiv.org/html/2607.00038v1)）。

---

## 4. 代表性实现、产品与开源项目

### 4.1 产品内置功能

- **Claude Code**（Anthropic）
  - `/loop` 与 cron 工具：v2.1.71（2026-03-06）加入；文档 [code.claude.com/docs/en/scheduled-tasks](https://code.claude.com/docs/en/scheduled-tasks)。
  - `/goal`：v2.1.139（2026-05-11）加入；文档 [code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)。
  - Dynamic workflows：v2.1.154（2026-05-28）加入；文档 [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows)。
  - Routines（`/schedule`，云端，research preview）：[code.claude.com/docs/en/routines](https://code.claude.com/docs/en/routines)。
  - 版本记录：[github.com/anthropics/claude-code/blob/main/CHANGELOG.md](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)（当前最新 2.1.282）。
- **OpenAI Codex Goals**：Codex 0.128.0（2026-04-30）起可用；实现位于 [openai/codex `codex-rs/ext/goal`](https://github.com/openai/codex/tree/bf832f4678/codex-rs/ext/goal)（本文引用提交 bf832f4678，2026-09-25）；用法见 [OpenAI Cookbook《Using Goals in Codex》](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)（2026-05-13 首次提交，2026-07-14 修订）。
- **Hermes Agent `/goal`**（Nous Research）：LLM 评审 + shell quality gates + completion contract，文档 [hermes-agent.nousresearch.com/docs/user-guide/features/goals](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals)；Orosz 记为 2026 年 5 月发布（[Pragmatic Engineer，2026-07-14](https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering)，转述）。

### 4.2 插件、模式库与开源示例

- **Ralph Loop 插件**（Anthropic 官方插件目录）：[anthropics/claude-plugins-official/plugins/ralph-loop](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop)，最近提交 986deab6a1（2026-03-28）。
- **cobusgreyling/loop-engineering**：模式库与 CLI（`loop init`、`loop doctor`、`loop cost`），含 daily-triage、PR babysitter、CI sweeper 等模式与 L1/L2/L3 放权分级；2026-06-09 创建，约 1.13 万 star（2026-09-25）（[github.com/cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering)）。
- **karpathy/autoresearch**：agent 自主修改 `train.py`，运行 5 分钟训练，按 val_bpb 保留或回退；2026-03-06 创建（[github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)）。
- **anthropics/claudes-c-compiler**：并行 Claude 循环写出的 C 编译器（2026-02-04 创建）（[github.com/anthropics/claudes-c-compiler](https://github.com/anthropics/claudes-c-compiler)；说明文章 [Anthropic，2026-02-05](https://www.anthropic.com/engineering/building-c-compiler)）。
- **Anthropic autonomous-coding quickstart**：长任务 harness 的参考实现（[github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding)；说明文章 2025-11-26）。
- **Emmimal/loop-engine**：纯 Python、无 LLM 调用的目标驱动控制器，用来单独测量循环结构本身的收益：在 300 个随机种子下，目标驱动控制器平均完成 47.7% 的任务，线性流水线为 2.1%（[github.com/Emmimal/loop-engine](https://github.com/Emmimal/loop-engine)；[Towards Data Science，2026-07-17](https://towardsdatascience.com/context-engineering-isnt-enough-a-loop-engineering-experiment-with-no-llm-inside-the-loop/)）。

### 4.3 相关编排框架

- **Google ADK 2.0**：从层级执行器改为图执行引擎，确定性节点负责路由，支持 human-in-the-loop 暂停；Python 版 2026-05-19 GA，Go 版 2026-06-30 GA，TypeScript 版 2026-08-21 GA（[adk.dev/2.0](https://adk.dev/2.0/)；[developers.googleblog.com/announcing-adk-go-20](https://developers.googleblog.com/announcing-adk-go-20/)）。

### 4.4 研究与基准

- Lulla、Nersesyan、Mohsenimofidi、Treude、Baltes，《Loop Engineering: Building Blocks, Adoption, and Impact》，[arXiv 2608.21884](https://arxiv.org/abs/2608.21884)（2026-08-22 v1，2026-08-26 v2），补充材料在 Zenodo。
- Sandeco Macedo（Instituto Federal de Goiás），《Stop Hand-Holding Your Coding Agent: Engineering the Loops that Replace Step-by-Step Prompting》，[arXiv 2607.00038](https://arxiv.org/abs/2607.00038)（2026-06-28）。
- Li 等（Microsoft），《LoopsBench: From Harness Engineering to Loop Engineering in Coding Agent Evaluation》，[arXiv 2608.00267](https://arxiv.org/abs/2608.00267)（2026-07-31 v1，2026-08-10 v2）；112 个任务，每个任务是可分别测试的开发单元组成的依赖 DAG，共 5,300 多个单元；项目页 [loopsbench.ai](https://loopsbench.ai/)，代码 [github.com/microsoft/Loopsbench](https://github.com/microsoft/Loopsbench)。
- Hou、Wang、Zhao、Wang，《When Agents Do Not Stop: Uncovering Infinite Agentic Loops in LLM Agents》，[arXiv 2607.01641](https://arxiv.org/abs/2607.01641)（2026-07-02），静态分析工具 IAL-Scan。

---

## 5. 批评与已知局限

### 5.1 新意存疑

- Mike Piccolo（iii 创始人）把术语逐一对应到已有概念：定时自动化对应 cron 触发器，会话外记忆对应键值存储，互不干扰的子 agent 对应从消息队列取任务的隔离 worker，verifier 对应带重试的 pub/sub 消费者，失败任务收件箱对应 dead-letter queue；“The naming is different. The systems are the same.”（[iii.dev，2026-06-25](https://iii.dev/blog/loop-engineering-is-just-software-engineering/)）
- Orosz 认为这些本质上是开发者用了几十年的触发器与 cron 的高级版本；他转引 Max Kanat-Alexander 的看法，循环可能是 “a temporary hack while tooling caught up”，并提到有开发者试用后放弃循环，发现人主导的流程效果更好（[Pragmatic Engineer，2026-07-14](https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering)，其中 Kanat-Alexander 的话为转述）。
- Firecrawl 记录 Steinberger 推文下的反对意见，典型说法为 “a cron job wearing a hat”（[firecrawl.dev/blog/loop-engineering，2026-06-11](https://www.firecrawl.dev/blog/loop-engineering)，转述回复内容）。
- Isaac Hagoel 指出编码 agent 本身已经在循环（查看代码、修改、运行命令、查看结果、再次修改），外加一层循环需要「一直做到完成」之外的理由（[dev.to，2026-07-07](https://dev.to/isaachagoel/loop-engineering-minus-the-hype-4ibn)）。

### 5.2 「完成」的可信度与验证负担

- Osmani 自己列出的三项负担：验证负担（“A loop running unattended is also a loop making mistakes unattended.”）、comprehension debt、cognitive surrender（[Osmani，2026-06-07](https://addyosmani.com/blog/loop-engineering/)）。
- Lulla 等人记录的失败模式包括 “verifier theater”（verifier 没有真正检查就放行）（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。
- Claude Code `/goal` 的评估模型不运行命令、不读文件，只能依据工作模型在对话中给出的内容作出判断（[goal 文档](https://code.claude.com/docs/en/goal)）。
- Blake Crosley：自动化能否成功取决于验证成本，与任务难度关系不大；Cherny 点名的那些循环都有机器可检查的成功条件（CI 通过、PR 已 rebase、报告已送达）；新功能需要人工评审，架构变更的验证要以月计，不适合无人值守；他自己的 worktree 自动化两次删除共享临时目录，缓存清理在部署完成前执行导致 11 小时 404（[blakecrosley.com，2026-06-09](https://blakecrosley.com/blog/loops-win-where-verification-is-cheap)）。
- Hagoel：构建与发现同时进行，测试失败时循环无法区分是功能错了还是测试错了；规格不完整时模型会自行补空，可能偏离意图；编写可靠的验证可能比与 agent 交互式开发更耗时（[dev.to，2026-07-07](https://dev.to/isaachagoel/loop-engineering-minus-the-hype-4ibn)）。

### 5.3 适用范围

- Hagoel 借用控制系统的说法：循环适合做 regulator（让系统维持在既定目标附近、完成可预期的工作、恢复已知的正常状态），不适合做 reference-setter（解释模糊意图、在相互竞争的产品结果之间取舍、定义什么算好）（[dev.to，2026-07-07](https://dev.to/isaachagoel/loop-engineering-minus-the-hype-4ibn)）。
- Ronacher：循环在代码移植（他用循环把 MiniJinja 移植到 Go）、性能探索、安全扫描与研究中效果好，共同点是改写已有代码或产出非永久性的产物；在他在意的生产代码上，模型倾向写防御性、局部推理的代码，“add fallbacks instead of making bad states impossible”，每轮迭代叠加更多防御层，系统 “less understandable while appearing more robust”（[lucumr.pocoo.org，2026-06-23](https://lucumr.pocoo.org/2026/6/23/the-coming-loop/)）。
- Ralph 的作者本人：“There's no way in heck would I use Ralph in an existing code base”，并认为没有资深工程师的引导做不到（[ghuntley.com/ralph，2025-07-14](https://ghuntley.com/ralph/)）。

### 5.4 理解与责任

- Ronacher：“Looping is powerful but it removes responsibility more and more, and it at least today very much encourages us to give in to the machine.” 在 harness 循环中，由 harness 决定工作何时结束，人变成传话者；他担心代码库变得默认需要机器参与维护（[lucumr.pocoo.org，2026-06-23](https://lucumr.pocoo.org/2026/6/23/the-coming-loop/)）。
- Hacker News 上对 Osmani 文章的讨论中，有评论问 “How do you have so much trust in a non-deterministic system?”（[news.ycombinator.com/item?id=48514387](https://news.ycombinator.com/item?id=48514387)）。

### 5.5 成本、失控与评审瓶颈

- Lulla 等人汇总的失败模式：成本失控（报告案例为 48 小时消耗 800 万 token）、无限修复循环、通知过多、评审人沦为盖章；“Review capacity is the practical bottleneck. Nightly agent runs can open more pull requests than teams can review.”（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）
- IAL-Scan 在 6,549 个 agent 仓库中发现 74 个疑似无限循环，人工确认 47 个项目中 68 个真实问题，成因来自 agent 逻辑、框架语义、运行时观察与终止机制之间的相互作用（[arXiv 2607.01641，2026-07-02](https://arxiv.org/abs/2607.01641)）。
- Anthropic 自己的提醒：workflow 可能一次启动数百个 agent，应先在小范围试点；token 成本差异很大，模型与推理强度是主要的成本杠杆（[Anthropic，2026-06-30](https://claude.com/blog/getting-started-with-loops)；[workflows 文档](https://code.claude.com/docs/en/workflows)）。

### 5.6 实证证据不足

- 采用率低：36,710 个仓库中确认 217 个自主循环（0.59%），其中 180 个仅由事件触发，多为 PR 评审；Claude Code 占 189 个；在已提交的配置中，目标或停止条件、verifier、预算的检出数都为 0；没有仓库声明自己的放权等级（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。作者也说明，`/loop`、`/goal` 这类平台内置调度、私有仓库与 dynamic workflows 在扫描中不可见。
- 收益数据多为自报：Stripe「Minions」每周约 1,300 个 agent PR、Firefox 一个月 423 个安全修复等数字，论文作者注明 “no published study or dataset” 支持（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)，其中公司数字为论文转述）。
- 长任务能力的上限：LoopsBench 上最强配置（Claude Code + Opus 4.7）只解决 25% 的任务，记录下来的计划只能恢复部分前置依赖信息，回归问题持续存在（[arXiv 2608.00267](https://arxiv.org/abs/2608.00267)）。
- Macedo 承认自己的论文是 “a position paper anchored in descriptive corpus study, not a controlled experiment”，并建议以 “cost per accepted change”（消耗 token 除以最终留存的改动数）作为衡量标准（[arXiv 2607.00038](https://arxiv.org/html/2607.00038v1)）。

### 5.7 术语炒作

- 名称出现约六周后，「graph engineering」以玩笑形式出现，随即出现课程、路线图与大量夸大说法；Turing Post 提醒：“A box-and-arrow diagram does not make an agent more advanced.”（[Turing Post，2026-07-20](https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it)）
- Lulla 等人把 loop engineering 视为可能的过渡阶段：工具正把显式命令吸收为默认行为，但给非确定性的 worker 加上验证、预算与上报边界这一设计问题会继续存在（[arXiv 2608.21884](https://arxiv.org/html/2608.21884v2)）。

---

## 来源

一手来源（作者原文、官方文档、代码仓库、论文）：

1. Addy Osmani，《Loop Engineering》，2026-06-07，https://addyosmani.com/blog/loop-engineering/
2. Addy Osmani，《Agent Harness Engineering》，2026-04-19，https://addyosmani.com/blog/agent-harness-engineering/
3. Addy Osmani，《Long-running agents》，2026-04-28，https://addyosmani.com/blog/long-running-agents/
4. Peter Steinberger，X 推文，2026-06-07，https://x.com/steipete/status/2063697162748260627
5. Peter Steinberger，X 推文，2026-07-18，https://x.com/steipete/status/2078277297791189132
6. Hamel Husain，X Article《Loop Engineering Is Dead. Enter Graph Engineering》，2026-07-18，https://x.com/HamelHusain/status/2078346425621237935
7. Hamel Husain，X 推文，2026-07-18，https://x.com/HamelHusain/status/2078348097697263855
8. Delba de Oliveira、Michael Segner（Anthropic），《Loop engineering: Getting started with loops》，2026-06-30，https://claude.com/blog/getting-started-with-loops
9. Claude Code 文档《Keep Claude working toward a goal》，读取于 2026-09-25，https://code.claude.com/docs/en/goal
10. Claude Code 文档《Run prompts on a schedule》，读取于 2026-09-25，https://code.claude.com/docs/en/scheduled-tasks
11. Claude Code 文档《Orchestrate subagents at scale with dynamic workflows》，读取于 2026-09-25，https://code.claude.com/docs/en/workflows
12. Claude Code 文档《Automate work with routines》，读取于 2026-09-25，https://code.claude.com/docs/en/routines
13. Claude Code CHANGELOG（v2.1.71 / v2.1.139 / v2.1.154；发布时间取自 npm），https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
14. Anthropic 官方插件 Ralph Loop，提交 986deab6a1（2026-03-28），https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop
15. Anthropic，《Effective context engineering for AI agents》，2025-09-29，https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
16. Justin Young（Anthropic），《Effective harnesses for long-running agents》，2025-11-26，https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
17. Nicholas Carlini（Anthropic），《Building a C compiler with a team of parallel Claudes》，2026-02-05，https://www.anthropic.com/engineering/building-c-compiler
18. Siddharth Mishra-Sharma（Anthropic），《Long-running Claude for scientific computing》，2026-03-23，https://www.anthropic.com/research/long-running-Claude
19. OpenAI Cookbook，《Using Goals in Codex》，2026-05-13 首次提交，2026-07-14 修订，https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex
20. openai/codex，`codex-rs/ext/goal`（`src/spec.rs`、`templates/goals/continuation.md`），提交 bf832f4678（2026-09-25），https://github.com/openai/codex/tree/bf832f4678/codex-rs/ext/goal
21. openai/codex PR #18073（2026-04-16 创建，2026-04-25 合并）与 #18076，https://github.com/openai/codex/pull/18073 ，https://github.com/openai/codex/pull/18076
22. openai/codex release 0.128.0，2026-04-30，https://github.com/openai/codex/releases/tag/rust-v0.128.0
23. Nous Research，Hermes Agent Goals 文档，读取于 2026-09-25，https://hermes-agent.nousresearch.com/docs/user-guide/features/goals
24. Google，ADK 2.0 文档，读取于 2026-09-25，https://adk.dev/2.0/
25. Toni Klopfenstein、Sampath Kumar Maddula（Google），ADK Go 2.0 公告，2026-06-30，https://developers.googleblog.com/announcing-adk-go-20/
26. Geoffrey Huntley，《Ralph Wiggum as a "software engineer"》，2025-07-14，https://ghuntley.com/ralph/
27. Andrej Karpathy，autoresearch `program.md`，提交 068d93da75（2026-03-09），https://github.com/karpathy/autoresearch/blob/068d93da75/program.md
28. Andrej Karpathy，X 推文，2025-06-25，https://x.com/karpathy/status/1937902205765607626
29. Tobi Lütke，X 推文，2025-06-19，https://x.com/tobi/status/1935533422589399127
30. Armin Ronacher，《The Coming Loop》，2026-06-23，https://lucumr.pocoo.org/2026/6/23/the-coming-loop/
31. Lulla 等，《Loop Engineering: Building Blocks, Adoption, and Impact》，arXiv 2608.21884，2026-08-22/26，https://arxiv.org/abs/2608.21884
32. Sandeco Macedo，《Stop Hand-Holding Your Coding Agent》，arXiv 2607.00038，2026-06-28，https://arxiv.org/abs/2607.00038
33. Li 等，《LoopsBench》，arXiv 2608.00267，2026-07-31/08-10，https://arxiv.org/abs/2608.00267
34. Hou 等，《When Agents Do Not Stop》，arXiv 2607.01641，2026-07-02，https://arxiv.org/abs/2607.01641
35. Haggai Roitman，《The Hitchhiker's Guide to Agentic AI》，arXiv 2606.24937，2026-06-22/07-27，https://arxiv.org/abs/2606.24937
36. cobusgreyling/loop-engineering，2026-06-09 创建，https://github.com/cobusgreyling/loop-engineering
37. Emmimal/loop-engine，2026-07-10 创建，https://github.com/Emmimal/loop-engine
38. anthropics/claudes-c-compiler，2026-02-04 创建，https://github.com/anthropics/claudes-c-compiler

评论、报道与二手来源：

39. WorkOS，Boris Cherny 访谈要点（Acquired Unplugged），2026-06-02，https://workos.com/blog/boris-cherny-claude-code-acquired-interview-takeaways
40. Gergely Orosz，《What is "loop engineering"?》，2026-07-14，https://newsletter.pragmaticengineer.com/p/what-is-loop-engineering
41. Ivan Belcic、Cole Stryker（IBM），《What Is Loop Engineering?》，2026-07-17，https://www.ibm.com/think/topics/loop-engineering
42. Benjamin Font Pera（codecentric），《Loop, Harness, Context Engineering: The Terms Explained》，2026-07-05，https://www.codecentric.de/en/knowledge-hub/blog/loop-harness-context-engineering-explained
43. Blake Crosley，《Loop Engineering: Loops Win Where Verification Is Cheap》，2026-06-09，https://blakecrosley.com/blog/loops-win-where-verification-is-cheap
44. Isaac Hagoel，《Loop Engineering Minus the Hype》，2026-07-07，https://dev.to/isaachagoel/loop-engineering-minus-the-hype-4ibn
45. Mike Piccolo，《Loop Engineering Is Just Software Engineering. We Have a Name for That.》，2026-06-25，https://iii.dev/blog/loop-engineering-is-just-software-engineering/
46. Hiba Fathima（Firecrawl），《Loop Engineering: Should You Stop Prompting Agents and Start Designing Loops》，2026-06-11，https://www.firecrawl.dev/blog/loop-engineering
47. Ksenia Se（Turing Post），《FOD#159: Is Graph Engineering Real?》，2026-07-20，https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it
48. Louis-François Bouchard，《Graph Engineering, Without the Hype》，2026-07-22，https://louisbouchard.substack.com/p/graph-engineering-explained-what
49. Emmimal P Alexander（Towards Data Science），《Context Engineering Isn't Enough — A Loop Engineering Experiment With No LLM Inside the Loop》，2026-07-17，https://towardsdatascience.com/context-engineering-isnt-enough-a-loop-engineering-experiment-with-no-llm-inside-the-loop/
50. Hacker News 讨论《Loop Engineering: Designing loops that prompt coding agents》，https://news.ycombinator.com/item?id=48514387
51. patleeman，Codex `/goal` 实现分析 gist（转述，已用源码核对工具权限与继续提示），https://gist.github.com/patleeman/b1b5768393f9bf2f60865b1defeeb819
