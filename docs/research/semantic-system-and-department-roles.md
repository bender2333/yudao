# 语义系统与部门内多角色：参照调研

日期：2026-09-24。用途：为 [语义系统设计说明](../design/semantic-system.md) 与 [部门内多角色设计说明](../design/department-roles.md) 提供依据。网络来源的访问日期均为 2026-09-24；本地参考实现写明提交号。本文只记录阅读到的机制与数据，没有运行或复现这些系统。

标记：【官方】指厂商文档、官方博客或厂商自测数据；【论文】指论文中的实验结果；【观点】指作者的工程判断，没有对照实验。

## 1. 本地参考实现

### 1.1 OMP（`C:/project/codes/oh-my-pi` @ fdfeef1f78，下文 `ca/` 指 `packages/coding-agent/src`）

**子 Agent（task 工具）**

- 发起：工具名 `task`，参数含 `agent`、`task`、`outputSchema`、`tools`、`effort`；批量形态 `{context, tasks[]}` 中 `context` 是共享背景，每个条目起一个子 Agent（`ca/task/types.ts:114-183`）。
- 定义：Markdown 加 YAML frontmatter，项目 `.omp/agents/` 优先于用户目录与内置定义（`ca/task/discovery.ts:62-141`）。内置 scout（只读，@smol）、reviewer（@slow）、librarian、task（通用，@task）、sonic（@smol，机械工作）（`ca/task/agents.ts:44-74`）。
- 隔离：子 Agent 从空白开始，看不到父 Agent 的对话（`ca/prompts/tools/task.md:66`），使用独立的会话管理（`ca/task/executor.ts:3235-3240`）；只继承上下文文件、技能、规则与工作区目录（`ca/task/structured-subagent.ts:456-461`）。
- 交回：子 Agent 必须调用 `yield` 工具；有 schema 时交回结构化数据，校验失败在工具内重试 3 次（`ca/tools/yield.ts:281`）。父 Agent 收到的内联预览最多 5000 字符，全文以 `agent://<id>` 引用（`ca/task/result-summary.ts:15,41-77`）。
- 并行与嵌套：并发上限 `task.maxConcurrency` 默认 32（`ca/config/settings-schema.ts:5025`）；嵌套深度 `task.maxRecursionDepth` 默认 2，到上限时移除 task 工具（`settings-schema.ts:5058`，`executor.ts:3001-3018`）。
- 工具：frontmatter 的 `tools` 是白名单，工具全部属于只读集合的 Agent 标为只读（`ca/task/read-only-policy.ts:10-29`）。
- 步数：软请求预算默认 200，scout 与 sonic 为 100；超出后注入收尾提示，到 1.5 倍时强制要求交回，之后再过 5 次请求仍不交回即中止（`executor.ts:99-134`）。子任务运行时间默认不限（`settings-schema.ts:5076-5093`）。失败后是否重跑由父模型决定，没有自动重跑。

**模型角色与 vibe 模式**

- 内置 9 个模型角色：default、smol、slow、vision、plan、commit、tiny、task、advisor（`ca/config/model-roles.ts:22-54`）。smol、slow 未配置时继承 default（`ca/config/model-resolver.ts:1135-1152`）。
- 子 Agent 选模型：`task.agentModelOverrides[agent]` 优先，其次是 Agent 定义里的 `model`，最后是父 Agent 的模型（`ca/task/structured-subagent.ts:299-312`）。
- vibe 模式（`docs/vibe-mode.md`）：顶层会话变成「导演」，工具只剩 `read`、`todo` 与 `vibe_spawn`、`vibe_send`、`vibe_wait`、`vibe_kill`、`vibe_list`。工作者分 fast（sonic，@smol，机械执行与草稿）与 good（task，@task，设计、判断与审查 fast 的产出）两档；工作者看不到导演的对话，每个工作流一个持续的工作者以积累上下文；spawn 与 send 立即返回，结果异步送回导演；导演读取被修改的文件核实工作者的说法。原文：「worker completion means the turn settled, not that its claims are correct」。

**记忆与规则**

- 记忆后端默认关闭；local 后端在启动时分两阶段（先逐会话抽取，再合并）生成 MEMORY.md 与摘要，作为 Memory Guidance 注入系统提示，上限 5000 token；子 Agent 不运行这条流程（`docs/memory.md:22-28,68-84`）。
- 后端接入点包括 `preCompactionContext`：压缩前把额外上下文拼进摘要请求（`ca/memory-backend/types.ts:107-167`）。
- 压缩摘要固定小节：Goal、Constraints & Preferences、Progress（Done、In Progress、Blocked）、Key Decisions、Next Steps、Critical Context、Additional Notes（`packages/agent/src/compaction/prompts/compaction-summary.md:7-34`）。

### 1.2 OpenCode（`C:/project/codes/opencode` @ 0027387，路径相对于 `packages/opencode/src`）

- Agent 定义：字段含 mode、prompt、model、temperature、permission、steps（`agent/agent.ts:35-55`）。build、plan 为 primary；general、explore 为 subagent；explore 先拒绝全部工具，再只放开 grep、glob、list、bash、webfetch、websearch、read（`agent/agent.ts:140-265`）。
- task 工具：嵌套深度默认 1（`tool/task.ts:104-117`）；子 Agent 默认不能再派生子任务（`agent/subagent-permissions.ts:14-27`）；子会话只收到任务说明这一条消息，从全新上下文开始（`tool/task.txt:16`）；交回子会话最后一段文本（`tool/task.ts:64-79`）；并行靠同一条消息中的多个工具调用（`tool/task.txt:13`）；没有超时，上限只有 steps。
- 模型：子 Agent 配置了就用自己的，否则沿用父消息的模型（`tool/task.ts:181-184`）。
- 记忆：没有长期记忆功能；指令文件（AGENTS.md 等）每一步重新装配进系统提示，不参与压缩（`session/instruction.ts`，`session/prompt.ts:1257-1269`）。
- 压缩：小节为 Objective、Important Details、Work State（Completed、Active、Blocked）、Next Move、Relevant Files（`core/src/session/compaction.ts:16-46`）；另有可选的 prune：清除 40k token 之外的旧工具输出（`compaction.ts:273-317`）。

## 2. 语义记忆系统

| 系统 | 数据模型 | 写入 | 读取与注入 | 数据与局限 |
| --- | --- | --- | --- | --- |
| Zep / Graphiti [S1][S2] | episode（原文）、实体、事实边、社区摘要三层；事实边记录进入与离开系统的时间，以及现实中成立的区间 | 每条 episode 进入后抽取；实体去重先用向量加全文找候选，再由模型确认；新事实与相近旧事实矛盾时，旧事实写入失效时间，保留不删除 | 余弦相似度、BM25、图遍历三路召回后重排；事实连同有效区间写成文本注入 | 【论文】LongMemEval 准确率 71.2%，全文基线 60.2%，注入约 1.6k token；单会话助手类问题下降 17.7%；数据为 Zep 自测 |
| Mem0 [S3][S4][S5] | 论文版：抽取的记忆条目，图变体为实体关系三元组 | 论文版：取最相似的已有条目，由模型在新增、更新、删除、不变中选择一项；图变体把冲突关系标为无效。v3 改为只新增，原话「nothing is overwritten or deleted」 | 语义、关键词、实体三路打分融合 | 【官方】v3 只新增后，会变化的属性新旧并存（GitHub issue #4956，2026-04 开启未处理）[S6] |
| Letta / MemGPT [S7][S8][S9] | 主上下文分系统指令、可读写的工作块、消息队列；外部存储分完整消息库与向量文本库 | 上下文用到 70% 时提醒模型自行保存要点，100% 时移出约一半消息并重写递归摘要；sleep-time 代理在后台合并重复、拆分过大的块，可以设为应用前由主代理复核 | 记忆块始终在上下文中，带字符上限 | 【论文】DMR 上 GPT-4 从 32.1% 到 92.5% |
| Anthropic [S10][S11][S12][S13] | memory tool：客户端实现的记忆目录；context editing：清除旧工具结果 | 模型自行读写记忆目录 | 按需检索，平时只放轻量标识；context editing 默认输入 100k token 时触发，保留最近 3 次工具调用，被清除的结果换成占位文本，完整历史由客户端保留；清除会让提示缓存失效 | 【官方】记忆加 context editing 内部评测提高 39%，只用 context editing 提高 29%，评测细节未公开 |
| Claude Code [S14][S15] | MEMORY.md 与主题文件 | 自动记忆 | MEMORY.md 只加载前 200 行或 25KB；压缩后从磁盘重新注入 CLAUDE.md 与自动记忆，重新读取最近修改的至多 5 个文件 | 【官方】规则之间矛盾时，模型可能随意选一条 |
| GraphRAG [S16] | 实体图与分层社区摘要 | 离线抽取并预先生成各层社区摘要 | map-reduce 回答整体主题类问题 | 【论文】没有时间有效性 |
| A-MEM [S17] | 带关键词、标签、描述与链接的笔记 | 新笔记进入时由模型决定链接，并改写近邻笔记的描述 | 近邻检索 | 【论文】改写旧笔记不保留版本 |

## 3. 多角色组织

| 来源 | 角色与通信 | 上下文传递 | 并行与结束 | 数据与失败 |
| --- | --- | --- | --- | --- |
| Anthropic 多 Agent 研究系统 [R1] | 主代理制定策略并创建子代理；子代理只向主代理汇报，互不交流 | 子代理的任务说明写明目标、产出格式、工具与来源、边界；建议子代理把产物写入外部存储，主代理只拿引用，减少转述失真 | 通常 3 至 5 个子代理同时运行；每批结果返回后主代理决定是否继续；按问题复杂度规定子代理数量与工具调用次数 | 【官方】多 Agent token 用量约为普通对话的 15 倍；早期版本对简单问题创建 50 个子代理、无休止地搜索；分工模糊时多个子代理重复调查；依赖多的任务（多数编程任务）不适合 |
| Magentic-One [R2][R3] | Orchestrator 规划、跟踪、重新规划，每轮选择下一个执行者 | 任务账本：已验证事实、待查事实、待推导事实、有根据的猜测与分步计划；进展账本每轮回答：请求是否满足、是否在重复、是否有进展、下一个由谁、给什么指令 | 停滞计数超过阈值（实验中为 2，AutoGen 默认 3）后重新规划，并清空各代理的上下文 | 【论文】去掉账本后性能下降 31%；最常见错误是重复低效动作，其次是未充分验证就标记完成 |
| MetaGPT [R4] | 产品经理、架构师、项目经理、工程师、QA，按 SOP 交换结构化文档；共享消息池按职责订阅 | 文档交接，作者用「传话游戏」说明自由对话造成信息损失 | 串行；工程师按测试结果最多重试 3 次 | 【论文】逐个增加角色后可执行性从 1.0 升到 4.0 |
| ChatDev [R5] | CEO、CTO、程序员、审查员、测试员，每个子任务由一对角色多轮对话 | 阶段内保留对话，跨阶段只传递上一阶段的方案 | 代码连续两次没有变化或对话达到 10 轮时结束 | 【论文】去掉角色提示后性能下降最大；与 MetaGPT 各自报告优于对方，评测不同 |
| OpenAI Agents SDK [R6] | agents-as-tools：经理保持控制，子代理只收到结构化输入、只返回最终输出；handoff：控制权转移，接收方默认看到完整历史 | 见左 | 并行由调用方代码实现 | — |
| LangChain 基准 [R7] | supervisor 与 swarm 对比 | supervisor 转述子代理回复时出错；改为原文转发后成绩提升近 50% | — | 【官方】单 Agent 性能随无关领域增多明显下降 |
| MAST [R8] | 7 个框架、1600 余条标注轨迹，14 种失败 | — | — | 【论文】系统设计问题 43.8%（步骤重复 15.7%，不知道终止条件 12.4%，违反任务规格 11.8%）；协作失误 32.15%；验证问题 24.05%。在 ChatDev 上改进角色规格 +9.4%，增加高层验证 +15.6% |
| Cognition [R9] | 推荐单线程 Agent | 代理之间应共享完整轨迹，并行代理的隐含决策会互相冲突 | — | 【观点】 |
| Anthropic 多 Agent 使用时机 [R10] | 多 Agent 适合上下文保护、并行、专门化三种情况 | 反对按规划、实现、测试、审查这类工种拆分角色，推荐按上下文拆分 | — | 【官方】token 用量通常是单 Agent 的 3 至 10 倍 |

## 4. 关于上下文内容的研究证据

- Xie 等（ICLR 2024）[E1]：外部证据中同时有与模型自身知识一致的部分时，模型表现出强烈的确认偏差。
- ConflictBank（NeurIPS 2024）[E2]：把随时间变化造成的冲突列为独立的冲突类别。
- FreshLLMs [E3]：给每条证据标注来源与日期并按从旧到新排列，GPT-4 严格准确率从 28.6% 提高到 75.6%；按时间排列比随机排列最多高 2.2%。
- Lost in the Middle（TACL 2024）[E4]：答案位于 20 篇文档中间时，准确率低于不给任何文档。
- Chroma Context Rot（2025-07）[E5]：18 个模型的表现都随输入变长而更不可靠；LongMemEval 上约 300 token 的精简输入明显好于约 113k token 的完整输入；作者说明没有分开任务难度与输入长度的影响。

## 5. 对设计的影响

| 设计规则 | 依据 |
| --- | --- |
| 语义单元保留来源事件，失效只写入结束位置与更替者，旧单元保留 | Graphiti 的失效不删除；Mem0 只新增后新旧并存的反例 |
| 更替与失效由模型提出、主机校验后写入事件，语义记录是事件的投影 | Yudao 的状态主权与事件溯源原则；Graphiti、Mem0 由模型决定更新 |
| 请求中只放当前有效单元与从旧到新、带日期的简短更替链 | Xie 等、ConflictBank、FreshLLMs；用户此前的结论「当前态加不超过 10 行的更替链」 |
| 整理放在一段工作结束与压缩之前，不在每一步进行 | Letta sleep-time 在若干步之后或压缩时整理；OMP 的 `preCompactionContext` |
| 已整理的旧工具结果在请求中换成带事件引用的占位文本 | Anthropic context editing；OpenCode prune |
| 语义视图有固定上限 | Claude Code 记忆加载 25KB；OMP 记忆注入 5000 token |
| 部门经理只协调与核对，不编写产物；角色通过工具调用接受分派，只返回结构化结果 | OMP vibe 导演；OpenAI agents-as-tools；Magentic-One Orchestrator |
| 经理提交部门成果时引用角色产物原文，不转述 | LangChain 原文转发提升近 50%；Anthropic 的外部存储加引用；MetaGPT 的文档交接 |
| 部门账本分任务与进展两部分，每轮进展判断作为结构化字段记录 | Magentic-One 账本（去掉后下降 31%） |
| 按上下文划分角色：每个部门一个持有主要工作上下文的连续角色，另设探索者承担噪声大的查证 | Anthropic 按上下文拆分；Cognition 的共享轨迹论点；OMP vibe 的持续工作者 |
| 只有互相独立的查证任务并行，同时进行的探索者设上限 | Anthropic 通常 3 至 5 个；50 个子代理的失败；Cognition 的并行决策冲突 |
| 角色任务的分派说明包含目标、产出、可用材料与边界 | Anthropic 任务说明要求；MAST 中违反任务规格 11.8% |
| 连续无进展时重新规划并以新的角色视图重新开始 | Magentic-One 停滞处理；MAST 步骤重复 15.7% |
| 提交前由经理按数据流核对，工程另设评审者 | MAST 验证问题 24.05%、增加验证 +15.6%；Magentic-One 未验证即完成的错误 |

## 6. 来源

- [S1] Zep 论文 https://arxiv.org/html/2501.13956
- [S2] Graphiti 仓库 https://github.com/getzep/graphiti
- [S3] Mem0 论文 https://arxiv.org/html/2504.19413
- [S4] Mem0 开源版提示词 https://raw.githubusercontent.com/mem0ai/mem0/main/mem0/configs/prompts.py
- [S5] Mem0 v3 迁移文档 https://docs.mem0.ai/migration/platform-v2-to-v3
- [S6] Mem0 issue #4956 https://github.com/mem0ai/mem0/issues/4956
- [S7] MemGPT 论文 https://arxiv.org/html/2310.08560
- [S8] Letta 记忆块 https://docs.letta.com/guides/agents/memory-blocks
- [S9] Letta sleep-time https://docs.letta.com/guides/agents/architectures/sleeptime
- [S10] Anthropic context engineering https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- [S11] Anthropic memory tool https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- [S12] Anthropic context editing https://platform.claude.com/docs/en/build-with-claude/context-editing
- [S13] Anthropic context management https://claude.com/blog/context-management
- [S14] Claude Code memory https://code.claude.com/docs/en/memory
- [S15] Claude Code context window https://code.claude.com/docs/en/context-window
- [S16] GraphRAG 论文 https://arxiv.org/html/2404.16130
- [S17] A-MEM 论文 https://arxiv.org/html/2502.12110
- [R1] https://www.anthropic.com/engineering/multi-agent-research-system
- [R2] Magentic-One 论文 https://arxiv.org/html/2411.04468
- [R3] AutoGen teams 参数 https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.teams.html
- [R4] MetaGPT 论文 https://arxiv.org/html/2308.00352
- [R5] ChatDev 论文 https://arxiv.org/html/2307.07924
- [R6] OpenAI Agents SDK https://openai.github.io/openai-agents-python/multi_agent/
- [R7] LangChain 多 Agent 基准 https://www.langchain.com/blog/benchmarking-multi-agent-architectures
- [R8] MAST https://arxiv.org/abs/2503.13657
- [R9] Cognition https://cognition.com/blog/dont-build-multi-agents
- [R10] Anthropic 多 Agent 使用时机 https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them
- [E1] https://arxiv.org/abs/2305.13300
- [E2] https://proceedings.neurips.cc/paper_files/paper/2024/hash/baf4b960d118f838ad0b2c08247a9ebe-Abstract-Datasets_and_Benchmarks_Track.html
- [E3] https://arxiv.org/html/2310.03214
- [E4] https://arxiv.org/html/2307.03172
- [E5] https://www.trychroma.com/research/context-rot

未能打开：LangGraph hierarchical_agent_teams 教程（重定向后 404）；docs.letta.com/concepts/memgpt 只显示 SDK 弃用说明。
