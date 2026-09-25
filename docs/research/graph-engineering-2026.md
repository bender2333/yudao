# Graph engineering 与 2026 年基于图的 agent 编排

调研日期：2026-09-25。X（Twitter）帖子需要登录才能读取，帖子正文、发布时间与浏览量通过 `api.fxtwitter.com` 接口读取，引用时给出 x.com 原始链接。发布时间按推文 ID 换算为 UTC 并与接口返回值核对一致。

## 1. 说法的出处、时间与含义

### 1.1 时间线

| 时间（UTC） | 人物与机构 | 事件 | 原始出处 |
| --- | --- | --- | --- |
| 2024-01-16 | Tal Ridnik、Dedy Kredo、Itamar Friedman（CodiumAI，现 Qodo） | 论文提出 flow engineering：用「基于测试、多阶段、面向代码的迭代流程」替代单次 prompt，GPT-4 在 CodeContests 上 pass@5 从 19% 升到 44% | https://arxiv.org/abs/2401.08500 |
| 2024-02-29 | Itamar Friedman | 在回复 @LangChain 时写到「shift from prompt engineering to flow (/graph) engineering. LangGraph and AlphaCodium are a perfect fit」，浏览量约 3 千 | https://x.com/itamar_mar/status/1763168555539812407 |
| 2026-06-07 | Addy Osmani | 发表 loop engineering 文章，这是 graph engineering 之前一个说法 | https://addyosmani.com/blog/loop-engineering/ |
| 2026-07-11 12:04 | Mike（@michaelmasson55） | 帖子列出「prompt engineering / context engineering / harness engineering / loop engineering / next is: graph engineering」，浏览量 87，是本次调研找到的 2026 年最早用法 | https://x.com/michaelmasson55/status/2075913998449701170 |
| 2026-07-18 00:34 | Peter Steinberger（OpenClaw 作者） | 发帖「Are we still talking loops or did we shift to graphs yet?」，浏览量约 313 万，这是说法流行的起点。美国太平洋时间为 7 月 17 日晚，因此二手文章里 17 日与 18 日两种日期都有 | https://x.com/steipete/status/2078277297791189132 |
| 2026-07-18 05:09 | Hamel Husain | 发布 X Article「Loop Engineering Is Dead. Enter Graph Engineering」，浏览量约 69 万。接口返回的正文只有一个句点和一张动图，属于玩笑帖 | https://x.com/HamelHusain/status/2078346425621237935 |
| 2026-07-18 16:26 | Santiago（@svpino） | 引用 Steinberger 的帖子：「Loop Engineering is dead. Long live Graph Engineering!」 | https://x.com/svpino/status/2078516761318584774 |
| 2026-07-20 | Ksenia Se（Turing Post） | 梳理时间线并批评炒作，见第 5 节 | https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it |
| 2026-07-20 | David Khourshid（XState 作者） | 发布「State machines in 2 minutes」，指出 loop 与 graph 都是状态机的不同形式 | https://x.com/DavidKPiano/status/2079209887158989231 |
| 2026-07-22 | Sydney Runkle、Harrison Chase（LangChain） | 官方博客「3 Years of Graph Engineering with LangGraph」，文中把这一轮说法的起点指向 @steipete 的帖子，并称 graph engineering 是已有做法的最新名称 | https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph |
| 2026-07-22 | Louis-François Bouchard | 「Graph Engineering, Without the Hype」，直言两条起始帖子都是玩笑 | https://louisbouchard.substack.com/p/graph-engineering-explained-what |
| 2026-07-24 22:07 | Alex Kotliarskyi（简介为 Codex @OpenAI） | 「How to graph-max with Codex and 5.6 Sol: 1. Draw a graph … 2. Send it to Codex and say "write a code mode script that implements this workflow, run it with <your inputs>"」，浏览量约 77 万 | https://x.com/alex_frantic/status/2080776965070496115 |
| 2026-07-24 22:19 | Peter Steinberger | 引用上一条：「am I a graph engineer now」，浏览量约 80 万 | https://x.com/steipete/status/2080779917130858598 |
| 2026-07-25 | Akshay Pachaar | X Article「Graph Engineering Clearly Explained」，浏览量约 57 万，是传播最广的解释文章 | https://x.com/akshay_pachaar/status/2081089131808243999 |
| 2026-08-21 | 吉林大学等机构，30 多位作者（通讯邮箱 qinggangzhang@jlu.edu.cn） | arXiv 综述「Graph Engineering in the Era of LLM Agents: From Individual Intelligence to System Intelligence」，把这个说法整理成学术框架，配套论文清单仓库 DEEP-JLU/Awesome-Graph-Engineering | https://arxiv.org/abs/2608.21156 、https://github.com/DEEP-JLU/Awesome-Graph-Engineering |

### 1.2 谁提出、谁让它流行

- 没有一位可以认定的「提出者」。2026 年最早的用法是 7 月 11 日一条 87 次浏览的帖子（https://x.com/michaelmasson55/status/2075913998449701170 ，2026-07-11）；更早的源头是 2024 年 CodiumAI 的 flow engineering 与 Itamar Friedman 的「flow (/graph) engineering」（https://arxiv.org/abs/2401.08500 ，2024-01-16；https://x.com/itamar_mar/status/1763168555539812407 ，2024-02-29）。
- 让它流行的是 Peter Steinberger 2026-07-18 的提问帖与同日 Hamel Husain 的玩笑文章（https://x.com/steipete/status/2078277297791189132 ；https://x.com/HamelHusain/status/2078346425621237935 ）。Bouchard 的原话是「To be honest, both tweets were jokes」，同时认为这个玩笑指向了真实的问题（https://louisbouchard.substack.com/p/graph-engineering-explained-what ，2026-07-22）。
- LangChain 官方随后给出定性：「Graph engineering isn't a new idea. It's the latest name for a well established approach to building reliable agents.」（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22）
- 学术界在一个月后跟进，综述把它列为继 Prompt、Context、Harness、Loop Engineering 之后的第五个工程范式（https://arxiv.org/abs/2608.21156 ，2026-08-21）。

### 1.3 含义

- 主流含义是 agent 工作流的控制图：节点是工作单元（agent、模型调用、普通代码、人工决定），边决定下一步执行什么，状态在节点之间传递。Turing Post 的定义为「a unit of work: an agent, a model call, a piece of ordinary code, or a human decision」（https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）；LangChain 的定义把节点分为确定性代码、单次 LLM 调用、工具调用与完整 agent 循环（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22）。
- 学术综述的含义更宽，把运行状态也纳入图：「Graph Engineering is a structure-centered engineering foundation for system intelligence: it uses graph structures as the core substrate for externalizing relationships among tasks, components, and runtime states」。它处理三类问题：任务组织（目标分解、依赖、并发、验证约束）、agent 协调（分工、通信、委派、结果合并）、运行状态管理（进度、并发更新、来源追溯、故障隔离与恢复）（https://arxiv.org/html/2608.21156v1 ，2026-08-21）。
- 传播中存在混用。Turing Post 列出同一时期被称为「graph」的四类东西：控制图（LangGraph、ADK）、知识图谱（Microsoft GraphRAG）、执行轨迹、改进图，并指出有文章把 GraphRAG、DSPy 与 Anthropic 的编排工作拼接成「全行业转向 graph engineering」，这属于误读（https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）。AI Builder Club 的指南明确把知识图谱与 GraphRAG 排除在 graph engineering 之外，定义为「wiring multiple specialized agents or steps into a graph - nodes that do the work, edges that route between them, and shared state flowing along those edges」（https://www.aibuilderclub.com/blog/graph-engineering-guide-2026 ，2026-07-20，二手来源）。
- 本次查到的一手与主要二手来源中，没有把 graph engineering 用作代码图谱（代码索引）含义的。

## 2. 核心主张与具体做法

### 2.1 核心主张

1. **由结构决定下一步，模型只负责需要判断的步骤。** LangChain：图让构建者「impose your preconceptions of how the system should work into more constrained paths, not relying solely on the judgement of the LLM」（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22）。Towards Data Science：「The model contributes judgment only at the steps that actually require it; the graph decides what happens next.」（https://towardsdatascience.com/graph-engineering-for-ai-agents-from-prompts-and-loops-to-workflows/ ，2026-09-14，二手来源）
2. **单个 loop 管不住多个 loop 的协作。** loop 是一个节点加一条指回自身的边；当多个 loop 需要协作时就出现协调问题，图是描述协调的通用方式（Akshay Pachaar，https://x.com/akshay_pachaar/status/2081089131808243999 ，2026-07-25；Bouchard：「A graph becomes useful when one loop is no longer enough.」，https://louisbouchard.substack.com/p/graph-engineering-explained-what ，2026-07-22）。
3. **单个 agent 的结构性瓶颈。** 综述认为单个 agent 让不同任务争抢同一个上下文，依赖操作只能串行，不同任务与 agent 的状态被塞进同一个共享上下文，导致并行浪费、角色混淆、确认偏差、错误沿后续步骤传播且难以局部修复（https://arxiv.org/html/2608.21156v1 ，2026-08-21）。
4. **生产用图有环。** 「Production agents need cycles: retrying failed tool calls, asking users for missing information, revising answers after validation…」，所以 agent 图通常带有环路，属于有向有环图（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22）。
5. **节点可以是完整 agent。** 早期节点多是确定性代码或单次 LLM 调用，现在节点里可以放完整的 agent 运行，图编排的对象从 LLM 调用变成 agent（同上）。
6. **代码负责可预测的路由，模型负责需要解释与判断的步骤。** Google 在 ADK 2.0 的设计说明中写道：LLM 常被用来做路由、调度、错误处理，「they are slow, expensive, and exhibit variance」；结构化流程把「transitions are evaluated programmatically in code」，在退款示例中 token 从 5,152 降到 2,265（https://developers.googleblog.com/why-we-built-adk-20/ ，2026-07-01）。

### 2.2 具体做法

- **先画图，再写状态结构。** Akshay 的建议：先熟练掌握单个 loop，编码前先画图，预先定义状态 schema，用锚定外部证据的 reviewer 节点，设置预算上限。他列出四个难点：节点是否值得单独存在、状态管理（typed schema 与访问控制）、路由可靠性（可预测的路径交给确定性代码，需要判断的交给模型）、agent 之间意见分歧（用不同模型、全新上下文的 reviewer 节点避免回音室）（https://x.com/akshay_pachaar/status/2081089131808243999 ，2026-07-25）。
- **在框架中声明图。** 用 LangGraph 的 `StateGraph`、ADK 2.0 的 `Workflow(edges=[...])`、Microsoft Agent Framework 的 `WorkflowBuilder` 声明节点与边（见第 3 节）。
- **让模型把图写成程序，由运行时执行。** Kotliarskyi 的做法是把手画的图交给 Codex，请它写 code mode 脚本并运行（https://x.com/alex_frantic/status/2080776965070496115 ，2026-07-24）。Claude Code 的 dynamic workflows 同样由 Claude 写 JavaScript 编排脚本、由运行时在后台执行，文档的对照表写明 workflow 中「Who decides what runs next: The script」（https://code.claude.com/docs/en/workflows ）。
- **把验证做成独立节点。** 典型形态是 maker 与 checker 分离、reviewer 用全新上下文，以及对抗式复核（Claude Code workflows 让其他 agent 尝试驳倒已有发现，https://claude.com/blog/introducing-dynamic-workflows-in-claude-code ，2026-05-28）。
- **用证据决定状态迁移。** 综述收录的 Proof-or-Stop 把 agent 输出当作「claims」，只有新鲜、绑定源码状态、可机械验证的证据通过对应检查时才允许生命周期迁移（https://arxiv.org/abs/2607.14890 ，2026-07-16）；ResearchLoop 把任务契约、证据对象、claim ledger 作为持久控制状态，研究活动只有在证据要求满足时才能推进（https://arxiv.org/abs/2605.28282 ，2026-05-27）。

### 2.3 适用范围

- 适合：流程结构可以预知（先分类再处理、先验证再执行）、需要并行、不同步骤要用不同模型、需要故障隔离（LangChain，https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22；Akshay，同上）。
- 不适合：高度涌现的任务，例如 deep research，其规划、委派、上下文管理应当在 harness 中自行产生；GPT Researcher 因此从 LangGraph 图改为 Deep Agents（LangChain，同上）。「If the workflow is linear, keep it linear.」（Turing Post，https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）

## 3. 2026 年主要图编排系统的版本与变化

| 系统 | 2026 年主要版本与日期 | 与图编排相关的变化 | 文档 |
| --- | --- | --- | --- |
| LangGraph（LangChain） | 1.1.0（2026-03-10）；1.2.0（2026-05-12）；当前 1.2.12（2026-09-21）；checkpoint 4.2.0（2026-08-07） | 类型安全的 stream/invoke v2；DeltaChannel、节点超时、节点级错误处理、优雅停止、stream_events v3；主管库归档 | https://docs.langchain.com/oss/python/releases/changelog |
| Deep Agents（LangChain） | 0.7.19（2026-09-24） | 官方推荐的默认起点，运行在 LangGraph 运行时之上 | https://docs.langchain.com/oss/python/deepagents/overview |
| Google ADK 2.0 | Python 2.0.0 GA（2026-05-19）；Go 2.0.0 GA（2026-06-30）；TypeScript 2.0.0 GA（2026-08-21） | 从层级 agent 执行器改为基于图的 Workflow Runtime；graph / dynamic / collaborative 三类工作流 | https://adk.dev/2.0/ |
| Microsoft Agent Framework | 1.0 GA（2026-04-03） | 基于图的 Workflow 稳定；五种多 agent 编排；Python 新增实验性的 functional workflow API | https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/ |
| Claude Code dynamic workflows（Anthropic） | Claude Code v2.1.154 引入，研究预览自 2026-05-28，官方博客现标注已 GA | 模型写 JavaScript 编排脚本，运行时执行，单次运行最多 1,000 个 agent | https://code.claude.com/docs/en/workflows |
| OpenAI | Codex subagents（2026-03-16 公布可用）；Agents SDK 更新（2026-04-15）；Symphony 开源规范（2026 年 4 月底公布） | Codex 的多 agent 工具稳定、code mode 开发中；Agents SDK 以 harness 与沙箱为主；Symphony 用任务看板驱动编排 | https://learn.chatgpt.com/docs/config-file/config-reference 、https://github.com/openai/symphony |

### 3.1 LangGraph、LangChain 与 Deep Agents

版本（来源：GitHub releases，https://github.com/langchain-ai/langgraph/releases ；官方 changelog，https://docs.langchain.com/oss/python/releases/changelog ）：

- **1.1.0（2026-03-10）**：`version="v2"` 的类型安全流式输出与 `invoke()`，`invoke()` 返回带 `.value` 与 `.interrupts` 的 `GraphOutput`，状态 schema 为 Pydantic 或 dataclass 时自动转换类型；修复父图与子图的 replay（time travel）。旧的字典式访问已标记弃用，计划在 v3.0 删除。
- **1.2.0（2026-05-12）**：
  - `DeltaChannel`（beta）：每一步只存增量，不再反复序列化完整累积值，面向长线程中不断增长的消息列表。
  - 节点超时：`add_node(timeout=...)`，支持 `run_timeout` 与 `idle_timeout`，超时抛出 `NodeTimeoutError`，清除该次尝试的写入，交给重试策略；只适用于异步节点。
  - 节点级错误处理：`add_node(error_handler=...)`，重试耗尽后收到 `NodeError`，可返回 `Command` 更新状态并改变路由，用于补偿流程；1.2.0 同时支持错误处理在宿主进程崩溃后持久恢复。
  - 优雅停止：`RunControl.request_drain()` 在当前 super-step 结束后停止运行并保留可恢复的检查点。
  - `stream_events(version="v3")`（beta）；`StateGraph.set_node_defaults()`。
- **当前版本**：1.2.12（2026-09-21）；checkpoint 4.2.0（2026-08-07）。
- **主管模式的变化**：`langgraph-supervisor-py` 仓库已归档（最后一次提交 2026-07-15），README 写明「We now recommend using the supervisor pattern directly via tools rather than this library for most use cases. The tool-calling approach gives you more control over context engineering」（https://github.com/langchain-ai/langgraph-supervisor-py ）。LangChain 多 agent 文档现在列出五种模式：Subagents（主 agent 把子 agent 当工具调用，路由全部经过主 agent）、Handoffs（工具调用改写状态变量来触发路由）、Skills（按需加载的专门提示与知识，单个 agent 保持控制）、Router（一个路由步骤分类输入并分派）、Custom workflow（用 LangGraph 混合确定性逻辑与 agent 行为），并建议需要内置多 agent 能力时使用 Deep Agents（https://docs.langchain.com/oss/python/langchain/multi-agent ）。
- **三层定位**：LangChain 2026-08-06 的博客把 LangGraph 定位为「agent runtime」（持久执行引擎、人工介入、容错），`create_agent` 是最小的 agent 循环，Deep Agents 是「off-the-shelf agent harness」；多数项目建议从 Deep Agents 开始，需要确定性步骤或流程不符合标准 agent 循环时用 LangGraph，LangGraph 可以「encode domain knowledge directly into the graph's topology」（https://www.langchain.com/blog/deep-agents-vs-langchain-vs-langgraph ，2026-08-06）。
- **Deep Agents**：内置任务规划、虚拟文件系统、沙箱 shell 与进程内 JavaScript 解释器、Skills、AGENTS.md 记忆、对话历史与大型工具结果的自动压缩、每次调用都创建全新上下文的子 agent（只向主 agent 返回一份最终报告），运行在 LangGraph 运行时之上（https://docs.langchain.com/oss/python/deepagents/overview ）。最新版本 0.7.19（2026-09-24，https://github.com/langchain-ai/deepagents/releases ）。
- **仍然成立的部分**：Graph API 的核心仍是共享状态、每个键独立的 reducer（默认覆盖，`operator.add` 或 `add_messages` 累加）、`MessagesState`、条件边、`Command`（同时更新状态与路由）、`Send`（运行时动态派生 worker）、Pregel 式 super-step 执行、checkpointer 加 `thread_id` 的线程持久化、跨线程的 Store。默认递归上限现为 1000 个 super-step（https://docs.langchain.com/oss/python/langgraph/graph-api ；https://docs.langchain.com/oss/python/langgraph/persistence ）。

### 3.2 Google ADK 2.0

- 发布：Python 2.0.0 GA 于 2026-05-19，Go 2.0.0 GA 于 2026-06-30，TypeScript 2.0.0 GA 于 2026-08-21。官方描述：「ADK 2.0 introduces the Workflow Runtime, transitioning ADK from a hierarchical agent executor to a graph-based execution engine」，agent、工具、函数都作为工作流图中的节点（https://adk.dev/2.0/ ）。
- 三类工作流：
  - **Graph workflows**：`Workflow(edges=[("START", a, b, c)])` 声明顺序；条件路由写成 `(router, {"BUG": handler_1, "CUSTOMER_SUPPORT": handler_2})`，router 节点通常用 LLM 分类，路由值到处理节点的映射由代码决定；节点输出通过 `event.output` 以带类型的值传给下一个节点（https://adk.dev/graphs/ ；https://adk.dev/graphs/data-handling/ ）。
  - **Dynamic workflows**：用 `@node(rerun_on_resume=True)` 修饰的异步函数，通过 `await ctx.run_node(...)` 调用子节点，用语言原生的循环、条件、递归、`asyncio.gather` 表达图难以表达的流程；运行时自动为每个节点执行建立检查点，恢复时跳过已成功的子节点（https://adk.dev/graphs/dynamic/ ）。
  - **Collaborative workflows**：coordinator agent 通过自动注入、以各子 agent 命名的委派工具，由模型决定委派给谁；子 agent 有 chat、task、single-turn 三种模式；每个 agent 只看到自己分支的事件（https://adk.dev/workflows/collaboration/ ）。
- 设计理由见 2.1 第 6 条（https://developers.googleblog.com/why-we-built-adk-20/ ，2026-07-01）。
- 破坏性变化：Event schema 增加 `node_info`、`output` 字段；1.x 中覆写抽象方法驱动执行的方式不再适用；框架自动捕获异常以支持自动重试、遥测与人工介入暂停（https://adk.dev/2.0/ ）。

### 3.3 Microsoft Agent Framework 1.0

- 2026-04-03 GA，.NET 与 Python，Go SDK 另有仓库。GA 内容包括基于图的 Agent Workflows、多 agent 编排（sequential、concurrent、handoff、group chat、Magentic-One）、YAML 声明式 agent 与工作流、A2A 与 MCP；所有编排模式都支持流式输出、检查点、人工审批与暂停恢复（https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/ ，2026-04-03）。
- 工作流由 executor 与 edge 组成，边带类型校验，执行模型是改良的 Pregel（super-step），检查点在每个 super-step 边界生成。Python 另有实验性的 functional API（`@workflow`、`@step`，原生控制流，按 step 缓存结果），与图 API 产生相同的可观测结果（https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/ ，页面日期 2026-07-30）。
- Magentic 编排：manager 维护 task ledger 与 progress ledger，每轮判断请求是否已满足、是否陷入循环、是否有进展、下一位发言者及给它的指令；连续无进展超过上限时自动重置并重新规划；可开启人工审阅计划（Python 默认关闭，.NET 默认开启）。文档注明「it is untested how well the Magentic orchestration will perform outside of the original Magentic-One design」（https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic ，页面日期 2026-09-04）。

### 3.4 Claude Code dynamic workflows（Anthropic）

- Claude Code v2.1.154 的更新日志写道：「Introducing dynamic workflows: ask Claude to create a workflow and it orchestrates work across tens to hundreds of agents in the background」（https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md ）。官方博客发布于 2026-05-28，开头注明现已 GA（https://claude.com/blog/introducing-dynamic-workflows-in-claude-code ）。
- 机制：Claude 写一个 JavaScript 脚本，运行时在隔离环境中执行；`agent()` 启动一个子 agent，`pipeline()` 对列表逐项启动，`parallel()` 并发执行；中间结果保存在脚本变量中，Claude 的上下文只接收最终答案。文档的对照表：subagents、skills、agent teams 由 Claude 或主 agent 逐轮决定下一步，workflow 由脚本决定。限制：运行中不能接收用户输入；脚本本身不能直接访问文件系统或 shell；默认最多 16 个并发 agent；单次运行最多 1,000 个 agent（https://code.claude.com/docs/en/workflows ）。
- Anthropic 没有发布名为 graph engineering 的学科或产品（Turing Post 的核查，https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）。

### 3.5 OpenAI

- **Codex**：多 agent 协作工具（`spawn_agent`、`send_input`、`resume_agent`、`wait_agent`、`close_agent`）标注为「stable; on by default」；code mode 标注为「This feature is under development and off by default」（官方配置参考，https://learn.chatgpt.com/docs/config-file/config-reference ）。Kotliarskyi 的「graph-max」做法依赖 code mode（https://x.com/alex_frantic/status/2080776965070496115 ，2026-07-24）。
- **Agents SDK**：2026-04-15 的更新重点是 harness 与沙箱（先支持 Python），报道提到 code mode 与 subagents 能力仍在开发（TechCrunch，https://techcrunch.com/2026/04/15/openai-updates-its-agents-sdk-to-help-enterprises-build-safer-more-capable-agents/ ，2026-04-15，二手来源；OpenAI 原文 https://openai.com/index/the-next-evolution-of-the-agents-sdk/ 未能读取）。SDK 文档把编排分为「via LLM」（agents as tools、handoffs）与「via code」（结构化输出分类后由代码选下一个 agent、链式调用、评估循环、并行）两类（https://openai.github.io/openai-agents-python/multi_agent/ ）。
- **Symphony**：开源规范与 Elixir 参考实现（仓库创建于 2026-02-26，公布于 2026 年 4 月底），把 Linear 之类的任务看板当作 coding agent 的控制面，每个 issue 在独立工作区里运行一个 agent 会话；规范写明「The orchestrator is the only component that mutates scheduling state」（https://github.com/openai/symphony/blob/main/SPEC.md ；公布时间见 https://tessl.io/blog/openai-open-sources-symphony-a-spec-for-orchestrating-codex-agents ，2026-04-29，二手来源）。

## 4. 确定性代码与 LLM 的分工

### 4.1 下一步由谁执行

| 方式 | 决定者 | 代表 |
| --- | --- | --- |
| 预先声明的图（静态边） | 开发者写好的边 | LangGraph 普通边；ADK `Workflow(edges=...)` 顺序行；MAF `WorkflowBuilder.add_edge` |
| 条件边 | 路由函数（代码），输入常来自 LLM 的分类结果 | LangGraph 条件边与 `Command(goto=...)`；ADK router 节点输出路由值、代码映射到处理节点；OpenAI Agents SDK「structured outputs 分类后由代码选择下一个 agent」 |
| LLM 路由 | 模型通过工具调用选择 | LangChain Subagents 与 Handoffs；ADK collaborative 的 coordinator；MAF handoff、group chat、Magentic manager；OpenAI Agents SDK handoffs 与 agents as tools；Codex `spawn_agent` |
| 动态生成的图 | 模型写出编排程序，运行时按程序执行；或运行时按数据派生节点 | Claude Code dynamic workflows；Codex code mode（开发中）；ADK dynamic workflows 与 MAF functional workflows（程序由开发者写）；LangGraph `Send` 按 LLM 规划结果派生 worker |

- 静态与条件边：LangGraph 文档把 prompt chaining、parallelization、routing、orchestrator-worker、evaluator-optimizer 归为「predetermined code paths」的 workflow，agent 则「define their own processes and tool usage」（https://docs.langchain.com/oss/python/langgraph/workflows-agents ）。这套划分沿用 Anthropic 2024-12-19 的「Building effective agents」（https://www.anthropic.com/engineering/building-effective-agents ）。
- LLM 路由在 2026 年的主流形态是「一个编排者持有完整上下文，按需派生隔离的子 agent，子 agent 只返回结果」。LangChain 归档主管库、改推工具调用式主管（https://github.com/langchain-ai/langgraph-supervisor-py ）；Cognition 2026-04-22 的文章称可行的形态是「map-reduce-and-manage」，并认为「the unstructured-swarm approach, arbitrary networks of agents negotiating with each other, is mostly a distraction」（https://cognition.com/blog/multi-agents-working ）。
- 动态生成的图是 2026 年最明显的新方向：模型一次性把流程写成代码，之后每一步由运行时按代码执行，模型不再逐轮决定。Claude Code 文档：「A workflow moves the plan into code… A workflow script holds the loop, the branching, and the intermediate results itself」（https://code.claude.com/docs/en/workflows ）。Turing Post 引用 Anthropic 的说法：「With the workflow encoded in code, the model spends fewer tokens repeatedly deciding what to do next」（https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）。为保证可重放，Claude Code 在脚本中禁用 `Date.now()`、`Math.random()` 与无参数的 `new Date()`（https://code.claude.com/docs/en/workflows ）。
- 研究层面还有由搜索或演化生成的图：AFlow 对可执行工作流代码做 LLM 引导的搜索，GPTSwarm 同时优化节点行为与边，DyFlow 按中间反馈生成后续子图，EvoFlow 在推理时并行演化多个工作流候选，MaAS 在「agentic supernet」中搜索结构（综述第 4 节，https://arxiv.org/html/2608.21156v1 ，2026-08-21）。

### 4.2 什么结果被写入状态、被接受为事实

- **LangGraph**：节点返回的更新经 reducer 直接合并进状态；并行节点写同一个键时逐个调用 reducer（https://docs.langchain.com/oss/python/langgraph/graph-api ）。框架层面的校验很少：Pydantic 状态「Run-time validation only occurs on inputs to the first node in the graph, not on subsequent nodes or outputs」（https://docs.langchain.com/oss/python/langgraph/use-graph-api ）。审批依靠 `interrupt()`：暂停并保存状态，人工用 `Command(resume=...)` 给出结果，再按结果路由到继续或取消（https://docs.langchain.com/oss/python/langgraph/interrupts ）。1.2 的节点超时会清除该次尝试的写入，错误处理可以写入补偿状态（https://docs.langchain.com/oss/python/releases/changelog ）。
- **Google ADK 2.0**：节点之间优先传递带类型的 `output`，`inputSchema` 与 `outputSchema` 约束数据；需要跨节点共享的数据写入 `ctx.state`，按 `app:`、`user:`、`temp:` 前缀区分范围（https://adk.dev/graphs/data-handling/ ）。节点可用 `RequestInput` 暂停等待人工输入（https://adk.dev/2.0/ ）。
- **Microsoft Agent Framework**：边带类型校验；executor 用 `QueueStateUpdateAsync` 写状态，写入者本身立即可见，其他 executor 从下一个 super-step 起可见（https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/state ，页面日期 2026-09-24）。审批依靠需要批准的工具与 request info；Magentic 可要求人工批准计划（https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/ ；https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic ）。
- **Claude Code dynamic workflows**：`agent()` 可带 JSON schema，运行前先检查 schema 是否自相矛盾，输出连续五次不符合 schema 则调用失败；结果只进入脚本变量；`/deep-research` 对每条结论投票、交叉核对，未通过的结论被剔除，因限流等原因无法核对的结论标为 unverified（https://code.claude.com/docs/en/workflows ）。
- **OpenAI Symphony**：编排器是唯一修改调度状态的组件，worker 只上报结果，由编排器转换为明确的状态迁移；任务看板是 issue 状态的权威来源（https://github.com/openai/symphony/blob/main/SPEC.md ）。
- **研究方向：输出是主张，证据决定迁移。** Proof-or-Stop：「Agent outputs may propose lifecycle claims, but do not themselves constitute lifecycle state」，在 10 个场景中做到零误报完成（https://arxiv.org/abs/2607.14890 ，2026-07-16）。ResearchLoop 用 claim ledger 记录每条主张的状态（planned、admitted、blocked、contradicted、forbidden）（https://arxiv.org/abs/2605.28282 ，2026-05-27）。「From Agent Output to Authorized Transition」提出证据必须绑定具体产物与冻结的策略基线，放行决定记录为回执，在合并、部署、发布之前再次检查授权（https://arxiv.org/abs/2609.28216 ，2026-09-23）。

### 4.3 每次调用的上下文如何组成

- **消息累加加压缩**：LangChain agent 的 `messages` 随对话增长，文档提供裁剪、删除、`SummarizationMiddleware` 摘要与自定义四种办法，并指出长上下文会让模型「get "distracted" by stale or off-topic content」（https://docs.langchain.com/oss/python/langchain/short-term-memory ）。Deep Agents 默认自动压缩对话历史与大型工具结果（https://docs.langchain.com/oss/python/deepagents/overview ）。ADK 按 token 阈值或轮次滑动窗口压缩会话事件，保留最近若干条原始事件，可指定摘要模型（https://adk.dev/context/compaction/ ）。
- **按节点重新装配**：ADK 2.0 的「Strict State Boundaries」只把后续 agent 节点需要的数据子集传给它，屏蔽无关执行历史；agent 用 `{Class.field}` 模板直接引用上游节点的结构化输出（https://developers.googleblog.com/why-we-built-adk-20/ ，2026-07-01；https://adk.dev/graphs/data-handling/ ）。Symphony 用 `WORKFLOW.md` 模板加 issue 字段和重试次数渲染每次运行的 prompt，未知变量直接报错（https://github.com/openai/symphony/blob/main/SPEC.md ）。
- **子 agent 隔离上下文**：Deep Agents 子 agent 每次调用都是全新上下文、只返回一份报告；ADK collaborative 中每个 agent 只看到自己分支的事件；MAF 工作流中每个 agent 默认有自己的线程；Claude Code workflow 的中间结果留在脚本变量；Codex 子 agent 用于「Keep your main context window clean」（上述各文档；Codex：https://x.com/OpenAIDevs/status/2033636701848174967 ）。
- **刻意隔离与刻意共享**：Cognition 的代码审查 agent 故意不共享编码 agent 的初始上下文，只看 diff，利用新鲜上下文避免「context rot」；「smart friend」则共享主模型完整上下文的一个分叉（https://cognition.com/blog/multi-agents-working ，2026-04-22）。

### 4.4 状态与会话是否持久

- **LangGraph**：checkpointer 按线程保存每个 super-step 的状态快照，支持对话延续、人工介入、time travel、容错；`thread_id` 标识线程；Store 保存跨线程的长期数据（用户偏好、事实、共享知识）；后端有 InMemory、Sqlite、Postgres（https://docs.langchain.com/oss/python/langgraph/persistence ）。从检查点恢复时，受影响的节点从函数开头重新执行，需要保证幂等（https://docs.langchain.com/oss/python/langgraph/graph-api ）。1.2 的 DeltaChannel 降低长线程的存储开销（https://docs.langchain.com/oss/python/releases/changelog ）。
- **Google ADK 2.0**：session、state、memory 三层；dynamic workflows 自动为每次节点执行建立检查点，`rerun_on_resume` 控制恢复时是重新进入编排函数还是直接交给被中断的节点（https://adk.dev/graphs/dynamic/ ；https://adk.dev/2.0/ ）。
- **Microsoft Agent Framework**：图工作流在 super-step 边界生成检查点，functional 工作流按 `@step` 缓存结果；agent 线程在同一个工作流实例的多次运行之间保留，文档提醒复用实例会造成不同任务之间的状态串用（https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/ ；https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/state ）。
- **Claude Code dynamic workflows**：运行时记录每个 agent 的结果，同一会话内可恢复；用 `claude --resume` 恢复的会话也能重放已保存的结果；重放时第一个 prompt 发生变化或失败的 agent 及其之后启动的所有 agent 都重新运行（https://code.claude.com/docs/en/workflows ）。
- **OpenAI Symphony**：不设持久的编排数据库，重启后不恢复重试计时器与运行中的会话，依靠任务看板与文件系统工作区恢复（https://github.com/openai/symphony/blob/main/SPEC.md ）。

### 4.5 与此前认识的对照

- 共享状态、消息累加（`add_messages`）、线程持久化（checkpointer 加 `thread_id`）在 LangGraph 1.2 中仍是核心机制，2026 年新增的是围绕它们的运行保障：DeltaChannel、节点超时、错误处理、优雅停止（3.1 节）。
- 「主管由 LLM 选择下一个节点」的形态已经变化：LangChain 归档 `langgraph-supervisor`，改为主 agent 用工具调用子 agent，子 agent 使用隔离上下文、只返回结果；多数场景建议从 Deep Agents 开始（3.1 节）。
- 2026 年新增的一类做法是把编排写成程序：模型写脚本（Claude Code、Codex code mode）或开发者用原生控制流写编排函数（ADK dynamic workflows、MAF functional API），运行时逐步执行并按节点记录结果以便重放（3.2 至 3.5 节）。

## 5. 批评与已知局限

- **名称炒作，内容已有。** Turing Post 称这是几周之内形成的术语热潮，「A loop is already a graph. It is simply a graph whose path returns to an earlier node」，并提醒大量关注者的帐号在命名上负有责任（https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it ，2026-07-20）。Bouchard 认为 prompt、context、harness、loop、graph engineering「overlap heavily」（https://louisbouchard.substack.com/p/graph-engineering-explained-what ，2026-07-22）。David Khourshid 指出 loop 与 graph 都是状态机（https://x.com/DavidKPiano/status/2079209887158989231 ，2026-07-20）。LangChain 自己也说这是已有做法的新名称（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22）。
- **概念混用与数据夸大。** Turing Post 核查：GraphRAG 是 RAG 的一种；DSPy 优化的是语言模型程序，与知识图谱无关；Anthropic 没有发布 graph engineering；流传的「准确率提升 18%、成本降低 85%」来自一项工业图纸的专门研究，被推广成了通用规律（同上）。
- **图把人的先验写死，不适合涌现型任务。** LangChain 承认 deep research 这类任务的规划、委派与上下文管理应当在 harness 中产生，GPT Researcher 因此从 LangGraph 改为 Deep Agents；LangChain 目前建议多数项目从 Deep Agents 开始（https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph ，2026-07-22；https://www.langchain.com/blog/deep-agents-vs-langchain-vs-langgraph ，2026-08-06）。
- **成本。** 多 agent 系统的 token 用量约为普通对话的 15 倍（Anthropic，https://www.anthropic.com/engineering/multi-agent-research-system ，2025-06-13；Akshay 在 2026-07-25 的文章中引用该数字）。Claude Code 文档提醒单次 workflow 可能比在对话中完成同一任务消耗多得多的 token，超过 25 个 agent 或预计 150 万 token 时显示警告（https://code.claude.com/docs/en/workflows ）。
- **多 agent 协调本身不可靠。** Anthropic 指出需要所有 agent 共享同一上下文、agent 之间依赖多的领域目前不适合多 agent，编码任务可并行的部分比研究少（https://www.anthropic.com/engineering/multi-agent-research-system ，2025-06-13）。Cognition 列出并行 agent 各自做出隐含决定、manager 缺乏代码库上下文时指令过细、agent 默认假设共享状态、agent 之间默认不沟通等问题，结论是「writes stay single-threaded」（https://cognition.com/blog/multi-agents-working ，2026-04-22）。微软文档注明 Magentic 在原始设计之外的效果未经验证（https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic ）。
- **检查点不等于持久执行。** Diagrid（Dapr 的商业公司，属于厂商观点）指出 LangGraph、CrewAI、ADK 的检查点只保存数据：没有故障检测、没有自动恢复、多个进程同时恢复同一线程时没有防重复执行，LangGraph 的一次运行只存在于一个进程中（https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows ，2026-02-25）。LangGraph 恢复时整个节点从头重跑，代码需要幂等（https://docs.langchain.com/oss/python/langgraph/interrupts ）。
- **框架层面对写入状态的校验有限。** LangGraph 的 Pydantic 校验只作用于第一个节点的输入（https://docs.langchain.com/oss/python/langgraph/use-graph-api ）。
- **动态 workflow 的限制。** Claude Code workflow 运行中不能接收用户输入，需要阶段性签字时要拆成多个 workflow；一个 agent 失败后重跑会连带重跑之后启动的所有 agent，包括已完成的（https://code.claude.com/docs/en/workflows ）。
- **适用边界。** 「If the workflow is linear, keep it linear. A box-and-arrow diagram does not make an agent more advanced.」（Turing Post，同上）；「If the next node genuinely needs everything the previous node saw, splitting them may not buy you much.」（Towards Data Science，https://towardsdatascience.com/graph-engineering-for-ai-agents-from-prompts-and-loops-to-workflows/ ，2026-09-14）。
- **学术综述列出的未解问题**：以图为原生设计的能力基础、能自我演化的图系统、面向图的 agent 操作系统、隐私与伦理；graph engineering 本身依赖明确的目标形成、agent 之间的共享语义、与世界模型的对应，以及尚无成熟方法的系统智能度量（https://arxiv.org/html/2608.21156v1 ，2026-08-21）。

## 来源

一手来源（作者原文、官方博客、官方文档、发布说明、论文、代码仓库）：

1. Peter Steinberger，「Are we still talking loops or did we shift to graphs yet?」，X，2026-07-18 00:34 UTC。https://x.com/steipete/status/2078277297791189132
2. Peter Steinberger，「am I a graph engineer now」，X，2026-07-24 22:19 UTC。https://x.com/steipete/status/2080779917130858598
3. Hamel Husain，「Loop Engineering Is Dead. Enter Graph Engineering」，X Article，2026-07-18 05:09 UTC。https://x.com/HamelHusain/status/2078346425621237935
4. Santiago（@svpino），「Loop Engineering is dead. Long live Graph Engineering!」，X，2026-07-18 16:26 UTC。https://x.com/svpino/status/2078516761318584774
5. Mike（@michaelmasson55），工程范式列表帖，X，2026-07-11 12:04 UTC。https://x.com/michaelmasson55/status/2075913998449701170
6. Itamar Friedman，「flow (/graph) engineering」帖，X，2024-02-29。https://x.com/itamar_mar/status/1763168555539812407
7. Alex Kotliarskyi，「How to graph-max with Codex and 5.6 Sol」，X，2026-07-24 22:07 UTC。https://x.com/alex_frantic/status/2080776965070496115
8. Akshay Pachaar，「Graph Engineering Clearly Explained」，X Article，2026-07-25。https://x.com/akshay_pachaar/status/2081089131808243999
9. David Khourshid，「State machines in 2 minutes」，X，2026-07-20。https://x.com/DavidKPiano/status/2079209887158989231
10. Tal Ridnik、Dedy Kredo、Itamar Friedman，「Code Generation with AlphaCodium: From Prompt Engineering to Flow Engineering」，arXiv，2024-01-16。https://arxiv.org/abs/2401.08500
11. Addy Osmani，「Loop engineering」，2026-06-07。https://addyosmani.com/blog/loop-engineering/
12. Sydney Runkle、Harrison Chase，「3 Years of Graph Engineering with LangGraph」，LangChain 博客，2026-07-22。https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph
13. Sydney Runkle，「The Art of Loop Engineering」，LangChain 博客，2026-06-16。https://www.langchain.com/blog/the-art-of-loop-engineering
14. Sydney Runkle，「Deep Agents vs LangChain vs LangGraph」，LangChain 博客，2026-08-06。https://www.langchain.com/blog/deep-agents-vs-langchain-vs-langgraph
15. Yuyuan Feng 等，「Graph Engineering in the Era of LLM Agents: From Individual Intelligence to System Intelligence」，arXiv:2608.21156，2026-08-21。https://arxiv.org/abs/2608.21156 ，HTML：https://arxiv.org/html/2608.21156v1 ，论文清单：https://github.com/DEEP-JLU/Awesome-Graph-Engineering
16. Jek Huang 等，「Proof-or-Stop: Don't Trust the Agent, Trust the Evidence」，arXiv:2607.14890，2026-07-16。https://arxiv.org/abs/2607.14890
17. Yihan Xia、Taotao Wang，「ResearchLoop: An Evidence-Gated Control Plane for AI-Assisted Research」，arXiv:2605.28282，2026-05-27。https://arxiv.org/abs/2605.28282
18. Christopher Koch，「From Agent Output to Authorized Transition」，arXiv:2609.28216，2026-09-23。https://arxiv.org/abs/2609.28216
19. LangGraph GitHub releases（1.1.0 于 2026-03-10，1.2.0 于 2026-05-12，1.2.12 于 2026-09-21，checkpoint 4.2.0 于 2026-08-07）。https://github.com/langchain-ai/langgraph/releases
20. LangChain 文档 Changelog。https://docs.langchain.com/oss/python/releases/changelog
21. LangGraph 文档 Graph API。https://docs.langchain.com/oss/python/langgraph/graph-api
22. LangGraph 文档 Use the graph API。https://docs.langchain.com/oss/python/langgraph/use-graph-api
23. LangGraph 文档 Persistence。https://docs.langchain.com/oss/python/langgraph/persistence
24. LangGraph 文档 Interrupts。https://docs.langchain.com/oss/python/langgraph/interrupts
25. LangGraph 文档 Workflows and agents。https://docs.langchain.com/oss/python/langgraph/workflows-agents
26. LangChain 文档 Multi-agent。https://docs.langchain.com/oss/python/langchain/multi-agent
27. LangChain 文档 Short-term memory。https://docs.langchain.com/oss/python/langchain/short-term-memory
28. Deep Agents 文档 Overview。https://docs.langchain.com/oss/python/deepagents/overview ；releases：https://github.com/langchain-ai/deepagents/releases
29. langgraph-supervisor-py 仓库（已归档）。https://github.com/langchain-ai/langgraph-supervisor-py
30. ADK 2.0 文档 Welcome to ADK 2.0。https://adk.dev/2.0/
31. ADK 文档 Graph workflows、Data handling、Dynamic workflows、Collaborative workflows、Context compaction。https://adk.dev/graphs/ 、https://adk.dev/graphs/data-handling/ 、https://adk.dev/graphs/dynamic/ 、https://adk.dev/workflows/collaboration/ 、https://adk.dev/context/compaction/
32. Swapnil Agarwal、Alan Blount、Frank Guan，「Why we built ADK 2.0」，Google Developers Blog，2026-07-01。https://developers.googleblog.com/why-we-built-adk-20/
33. Shawn Henry，「Microsoft Agent Framework Version 1.0」，2026-04-03。https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/
34. Microsoft Learn：Workflow concepts（2026-07-30）、Workflow capabilities（2026-07-29）、State（2026-09-24）、Orchestrations（2026-02-12）、Magentic（2026-09-04）。https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/ 、https://learn.microsoft.com/en-us/agent-framework/workflows/ 、https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/state 、https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/ 、https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic
35. Anthropic，「Introducing dynamic workflows」，2026-05-28。https://claude.com/blog/introducing-dynamic-workflows-in-claude-code
36. Claude Code 文档「Orchestrate subagents at scale with dynamic workflows」。https://code.claude.com/docs/en/workflows
37. Claude Code CHANGELOG（v2.1.154 引入 dynamic workflows）。https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
38. Erik S.、Barry Zhang，「Building effective agents」，Anthropic，2024-12-19。https://www.anthropic.com/engineering/building-effective-agents
39. Anthropic，「How we built our multi-agent research system」，2025-06-13。https://www.anthropic.com/engineering/multi-agent-research-system
40. OpenAI Codex 配置参考。https://learn.chatgpt.com/docs/config-file/config-reference
41. OpenAI Developers，「Subagents are now available in Codex」，X，2026-03-16。https://x.com/OpenAIDevs/status/2033636701848174967
42. OpenAI Agents SDK 文档 Orchestrating multiple agents。https://openai.github.io/openai-agents-python/multi_agent/
43. OpenAI Symphony 规范与仓库（仓库创建于 2026-02-26）。https://github.com/openai/symphony/blob/main/SPEC.md 、https://github.com/openai/symphony
44. Walden Yan，「Multi-Agents: What's Actually Working」，Cognition，2026-04-22。https://cognition.com/blog/multi-agents-working
45. Yaron Schneider，「Checkpoints Are Not Durable Execution」，Diagrid，2026-02-25（厂商观点）。https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows

二手来源（评论、报道、转述）：

46. Ksenia Se，「Is Graph Engineering Real? Why Everyone Is Talking About It」，Turing Post，2026-07-20。https://www.turingpost.com/p/is-graph-engineering-real-why-everyone-is-talking-about-it
47. Louis-François Bouchard，「Graph Engineering, Without the Hype」，2026-07-22。https://louisbouchard.substack.com/p/graph-engineering-explained-what
48. Nhu Hoang，「Graph Engineering for AI Agents: From Prompts and Loops to Workflows」，Towards Data Science，2026-09-14。https://towardsdatascience.com/graph-engineering-for-ai-agents-from-prompts-and-loops-to-workflows/
49. Shirley，「Graph Engineering Guide (2026)」，AI Builder Club，2026-07-20（2026-08-28 更新）。https://www.aibuilderclub.com/blog/graph-engineering-guide-2026
50. AI Builder Club，「Peter Steinberger's Loops or Graphs Tweet (2026)」（早期用法的线索来源）。https://www.aibuilderclub.com/blog/graph-engineering-peter-steinberger
51. Rafael Fernandes，「'Loop Engineering Is Dead' — and the Real Story Is Weirder Than the Obituary」，WiLine，2026-08-05。https://wec.wiline.com/docs/news/loop-engineering-graph-engineering-what-survives/
52. TechCrunch，「OpenAI updates its Agents SDK to help enterprises build safer, more capable agents」，2026-04-15。https://techcrunch.com/2026/04/15/openai-updates-its-agents-sdk-to-help-enterprises-build-safer-more-capable-agents/
53. Tessl，「OpenAI open-sources Symphony, a spec for orchestrating Codex agents」，2026-04-29。https://tessl.io/blog/openai-open-sources-symphony-a-spec-for-orchestrating-codex-agents
