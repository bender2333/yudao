# 黑板编排的参照调研

日期：2026-10-22。支持的文档：[D39 黑板编排](../requirements/blackboard-orchestration.md)、[ADR-0041](../adr/0041-two-orchestration-modes-share-control-core.md)、[黑板编排设计说明](../design/blackboard-orchestration.md)。用途：核对黑板模式的设计与已有系统的做法，给第 15 节的暂定默认值提供依据；回答用户的问题「AI4S 里哪些系统用了黑板」。

读取方式：每份材料读的是全文或全文的主要部分，来源列在第 7 节；没能读到的材料列在第 6 节，不据它们下结论。数字都是作者自报，没有独立复现。

## 1. 调研的问题

1. 经典黑板系统怎样决定下一个动作、怎样停止。
2. 近两年用黑板或共享状态协调大模型智能体的系统各怎么做，有什么证据。
3. AI4S 系统里有没有「部门自由发布与认领任务」的黑板。
4. 以上对黑板编排设计说明的哪些条目有影响。

## 2. 经典黑板系统

Hearsay-II（卡内基梅隆，1971 至 1976，语音理解）有三部分：分层的黑板，上面的假设带可信度评级；只通过黑板通信的知识源；调度器。知识源在议程上登记自己想执行的动作，调度器估计每个动作对解的改进，挑最有希望的一个执行，称为机会式调度，目的是避免搜索空间的组合爆炸。BB1（Hayes-Roth，斯坦福，1984）把控制决定也放到第二块黑板上，控制知识源监视求解是在推进还是停滞，停滞时切换策略。

两点与设计直接相关：

- 经典黑板从一开始就有三件东西，共享状态、知识源、控制。控制单独成层，并且被当作知识来表示。只有共享状态与知识源、没有控制的系统，在经典文献里就已经被认为不完整。
- 停止与进展由控制层按黑板状态判断，与具体知识源无关。

一份 2026 年的机制谱系综述把 AutoGen 与 AgentScope 对应到 Hearsay-II，评价是「有路由与共享状态的边界，没有按局部解价值运转的机会式议程」，并指出消息通道与黑板的区别：黑板的对象是演化中的局部解，消息通道只传话。

## 3. 大模型系统里的黑板与共享状态

| 系统 | 黑板是什么 | 谁决定下一步 | 怎么停 | 证据 |
| --- | --- | --- | --- | --- |
| LbMAS（Han 与 Zhang，2025-07） | 公共区与私有区的消息集合，含全部历史，替代各智能体的记忆 | 一个大模型控制单元每轮按黑板内容与角色描述选出要动作的智能体 | 决策者给出答案，或达到最大轮数 | 六个问答基准平均 81.68，ChatEval 80.56，差 1.1 分，没有方差；MATH 子集用 4.72M token，AFlow 16.7M；去掉控制单元后 token 升到 13.86M，正确率不变 |
| Google 数据发现黑板（Salemi 等，2025-09） | 请求板与回应板两块 | 主智能体发请求、不指名收件方；每个文件智能体自己决定要不要回应 | 主智能体的 ReAct 循环，上限 10 步，选择「作答」时结束 | Gemini 2.5 Pro 宏平均 28.53，主从式 24.01，RAG 18.51；每题费用是主从式的 1.8 倍、RAG 的 2.3 倍；时延相当 |
| AISAC（Bhattacharya 与 Som，2025-11，科学助手） | 数据库里按用户、任务、命名槽位划分的可变状态 | 路由器选协调者或规划者，委派深度上限 2 | 未说明 | 没有端到端评测 |
| PatchBoard（Zhang 等，2026-05） | 一份 JSON 状态 | 工作流规则按已提交的事件选下一个工作者；工作者只能提交 JSON Patch，确定性内核是唯一能改状态的部分 | 内核按规则 | ALFWorld 630 局成功 84.6%，纯黑板与结构化黑板都更低；故障注入里未授权写入 0 对 0.68，环中停机成功 0.96 对 0.12 |
| Magentic-One（微软，2024-11） | 编排者的任务账本（已核实的事实、待查、待推导、猜测、计划）与进度账本 | 编排者每步回答五个问题（完成了吗、在打转吗、有进展吗、下一个谁、让它做什么），停滞计数超过 2 就重新规划并清空所有智能体的上下文 | 编排者判断完成，或尝试次数与时间上限 | 最常见的失败是重复无效动作与验证不足 |
| Anthropic 研究系统（2025-06） | 主智能体的计划写进记忆；子智能体把产出写到文件系统，交回引用 | 主智能体规划并派发，同步执行 | 主智能体 | 比单智能体高 90.2%，token 是对话的 15 倍；早期子智能体「互相用过多的更新干扰」 |

两份材料直接回答「黑板本身保证什么」：

- PatchBoard 的出发点是黑板式共享记忆「本身不判断一次更新是否类型正确、是否经授权、是否过期、是否可以提交」，所以它把全部写入收到一个确定性内核，每次提交记录工作者、触发事件、视图摘要、补丁与结果摘要，可以不重新采样模型就重建状态序列。
- AISAC 的黑板所有写入带作者与时间戳，同一槽位的并发写入由数据库的写入层串行化，不可变的执行轨迹经「单一集中写入路径」写入。

MAST（Cemri 等，2025，1642 条轨迹）给出失败的分布：步骤重复 15.7%，不知道终止条件 12.4%，推理与动作不一致 13.2%；验证类合计 23.5%（过早结束 6.2%，没有或不完整的验证 8.2%，错误的验证 9.1%）。作者的结论是「现有验证器的实现常常不够，只靠最后阶段的浅层检查不行」。

## 4. AI4S 系统里的共享状态

用户记得「一些 AI4S 用了这种模式」。查到的系统里没有一个让各方自由发布与认领任务；共享状态有三种形态。

| 系统 | 共享状态 | 任务从哪来 | 停止 |
| --- | --- | --- | --- |
| AI co-scientist（Google，2025-02，Nature 2026） | 持久的上下文记忆：智能体与系统的状态、主管定期算出的统计（生成数、待审数、比赛进度、各生成方法的效果） | 主管按研究计划建立任务队列；伪代码里后续任务由结果类型机械派生：新假设产生就建审阅任务，审阅完成就建入赛任务；队列空时主管按统计决定下一步（跑一批比赛、质量不再提高就进化、定期元审阅） | 想法数与每个想法的比赛数达到上限；状态定期写入记忆，失败后重启 |
| Kosmos（Edison Scientific，2025-11） | 结构化的世界模型；运行层面是多个沙箱共用的分布式文件系统 | 每个周期最多 10 个并行的文献检索与数据分析任务，周期结束把摘要并入世界模型，再由世界模型提出下一周期的任务 | 最长 12 小时；一次运行约 200 次智能体回合 |
| AlphaEvolve（DeepMind，2025-06） | 程序数据库（MAP-elites 与岛屿模型） | 提示采样器从数据库取样生成提示，大模型给出改动，评估器打分；只有经评估函数打分的候选才进入数据库；异步流水线 | 计算预算 |
| Virtual Lab（Zou 实验室，Nature 2025） | 会议记录 | 主持人智能体召集团队会议与单独会议 | 会议结束 |
| SciAgents（Buehler，2024-09） | 群聊与知识图谱上采样的路径 | 预编程顺序，或群聊管理者按上下文与角色描述选下一个发言者 | 评审与新颖性检查之后结束 |
| Robin（FutureHouse，2025） | notebook 里的固定流程 | 固定 | 固定 |

Kosmos 的报告准确率由专家评为 79.4%，其中综合与解释类陈述只有 57.9%；它的每条陈述都引用论文或 notebook，但作者写明「没有自动方法可靠地判断一条陈述是否准确」。

中文检索（AI4S、多智能体、黑板）没有找到黑板架构的系统；上海 AI Lab 的 Intern·Agent 与清华的 SRHarness 都是固定流程的多智能体。

结论：AI4S 里最接近「任务池」的是 AI co-scientist 的主管加异步任务队列，但它的任务由结果类型按代码规则派生，主管只做资源分配与停止判断；Kosmos 是共享状态加周期性集中规划；AlphaEvolve 是只经评估函数写入的数据库。三者都把「下一步做什么」留在控制层或评估层，没有交给工作智能体自己。

## 5. 对黑板编排设计说明的影响

对照设计说明的章节逐条说明。

1. **控制层不能省（第 4.3、8.1 节）。** LbMAS 去掉控制单元后 token 翻两倍而正确率不变；Hearsay-II 的调度器就是为了避免组合爆炸；MAST 里「不知道终止条件」占 12.4%。设计说明由流程编排触发认领、结束条件是黑板状态的条件，与这些一致。暂定默认值第 1 条（标签重叠时几个部门各开始一轮工作、先认领的成功）保留，但对照的报告要单独列出「没认领到的轮次」的模型用量。
2. **自选认领的价值与代价（第 4.2、10 节）。** Google 的数据发现实验是自选认领唯一的量化证据：相对主从式高 18.8%，每题费用高 80%。价值来自主控不必知道每个帮手的能力，在帮手数量大、能力重叠时才显现；三个部门标签互不重叠时没有这项收益。第 10 节的对照必须含费用。
3. **回应与请求分开（第 5.3 节）。** Google 的系统把回应写在单独的板上，理由是「避免子智能体互相影响」并让主智能体独占读取；Anthropic 的子智能体把产出写到文件系统、交回引用，早期版本因为互相更新过多而互相干扰。设计说明第 5.3 节黑板摘要只给未完成任务的元信息、结果载荷按依赖拉取，与此一致；暂定默认值第 3 条保留。
4. **黑板不保证结构，内核保证（第 3.3、6 节）。** PatchBoard 与 AISAC 都把写入收到唯一的路径并记录每次写入的作者与依据；PatchBoard 的故障注入显示没有内核校验的黑板放过了 68% 的未授权写入。ADR-0041 让黑板模式保留写入口、状态迁移的核对与工具许可，正是这一层。任务字段固定（第 3.1 节）而非自由文本，同一理由。
5. **载荷分层（第 3.1 节）。** Magentic-One 的任务账本把已核实的事实、待查、待推导、猜测分开；黑板评论文章点名「把观察到的事实、诊断与计划混在一个文件里，推测会固化成事实」。设计说明的结果与验证结果两个字段保持分开，验证结果只接受主机回执的引用。
6. **按结果类型派生任务是一个可选项（第 4.1 节）。** AI co-scientist 的后续任务由结果类型机械派生，不由工作智能体决定。黑板模式可以在事项种类定义里写可选的派生规则，例如「implement 任务完成时自动发布一个 verify 任务，定向给能力标签覆盖 verify 的部门」。它是定义里的数据，默认为空；填了以后不要求验证者与作者分开，只保证验证任务一定会被发布。是否加入由用户决定。
7. **停止条件（第 8.1、8.2 节）。** AI co-scientist 以计数上限停止；社区重实现列出五种：预算、时长、排名稳定、空闲、外部。设计说明的结束条件（根任务完成且黑板清空）、任务数与时间上限、用户取消覆盖了这五种中的四种，「排名稳定」对应收敛状态的检测。
8. **验证是开环时的度量（第 10 节）。** MAST 里验证类失败占 23.5%，Kosmos 综合类陈述准确率 57.9%。黑板模式把完成交给认领方自述，对照报告要为它列出「自述完成但隐藏检查未通过」的比例，与成果驱动模式的质检误放行并列。已写入设计说明第 10 节。
9. **存储（ADR-0041）。** AISAC 的执行轨迹用 SQLite，co-scientist 的社区重实现用 SQLite 做持久队列，AlphaEvolve 的流水线用 asyncio。没有材料显示这个规模的黑板需要 PostgreSQL 或 Redis。

## 6. 没能读到的材料

- Nii《Blackboard Systems》（AI Magazine，1986）与 Hearsay-III 的 AAAI-80 论文：网页为空或扫描件没有文字层。第 2 节的经典部分依据维基百科条目、机制谱系综述与黑板评论文章的转述。
- Hayes-Roth《A blackboard architecture for control》（1985）：付费。
- LbMAS 的代码仓库只有「coming soon」，控制单元的提示词没有公开。
- AI co-scientist 的 Nature 版本需要登录，读的是 arXiv 2502.18864 的全文与补充说明 8 的伪代码。
- Virtual Lab 与 Robin 只读了二手来源与仓库说明。

## 7. 来源

- Han, Zhang. Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture. [arXiv:2507.01701](https://arxiv.org/abs/2507.01701)。读全文（HTML）。
- Salemi 等. LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science. [arXiv:2510.01285v2](https://arxiv.org/abs/2510.01285)，[Google Research 页面](https://research.google/pubs/blackboard-multi-agent-systems-for-information-discovery-in-data-science/)。读全文（HTML）。
- Bhattacharya, Som. AISAC: An Integrated multi-agent System for Transparent, Retrieval-Grounded Scientific Assistance. [arXiv:2511.14043](https://arxiv.org/abs/2511.14043)。读全文（HTML）。
- Zhang 等. PatchBoard: Schema-Grounded State Mutation for Reliable and Auditable LLM Multi-Agent Collaboration. [arXiv:2605.29313](https://arxiv.org/abs/2605.29313)。读全文（HTML）。
- Fourney 等. Magentic-One. [arXiv:2411.04468](https://arxiv.org/abs/2411.04468)。读前 10 万字符。
- Cemri 等. Why Do Multi-Agent LLM Systems Fail? [arXiv:2503.13657v3](https://arxiv.org/abs/2503.13657)。读前 10 万字符。
- Anthropic. [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)。读全文。
- Gottweis 等. Towards an AI co-scientist. [arXiv:2502.18864](https://arxiv.org/abs/2502.18864)。读方法一节与补充说明 8。[Nature 2026 版本](https://www.nature.com/articles/s41586-026-10644-y)需要登录。社区重实现 [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist)，读 README。
- Edison Scientific. Kosmos: An AI Scientist for Autonomous Discovery. [arXiv:2511.02824](https://arxiv.org/abs/2511.02824)，读前 10 万字符；[How We Built Kosmos](https://advances.edisonscientific.com/research/how-we-built-kosmos/)，读全文。
- Novikov 等. AlphaEvolve. [arXiv:2506.13131](https://arxiv.org/abs/2506.13131)。读前 10 万字符。
- Ghafarollahi, Buehler. SciAgents. [arXiv:2409.05556](https://arxiv.org/abs/2409.05556)。读前 10 万字符。
- Virtual Lab：[bioRxiv 预印本](https://www.biorxiv.org/content/10.1101/2024.11.11.623004.full.pdf)与 [zou-group/virtual-lab](https://github.com/zou-group/virtual-lab)，只读检索摘要。Robin：[FutureHouse 介绍](https://intuitionlabs.ai/articles/futurehouse-ai-agents-platform)，二手来源。
- 机制谱系综述. From Cognitive Architectures to Language Agents. [arXiv:2607.23942](https://arxiv.org/abs/2607.23942)。读前 10 万字符。
- [Blackboard system，维基百科](https://en.wikipedia.org/wiki/Blackboard_system)。读全文。
- [The Blackboard Is Back](https://tianpan.co/blog/2026/07/02/the-blackboard-is-back)（评论文章，2026-07）。读全文；它的论点作为观点引用，不作为证据。
