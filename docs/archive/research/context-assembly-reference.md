# 上下文组装：参照调研

日期：2026-09-25。用途：为 [D25 语义系统](../requirements/semantic-system.md)「重点 TODO：上下文组装」专题提供参照。用户要求本专题参考 OMP 与 opencode 的实现。

来源：
- Yudao 现行实现：工作树提交 `1a808f3`，下文 Yudao 路径相对于仓库根目录。运行数据取自 `.yudao/stage2-validation/data/events.sqlite` 的 `run_0a2eff1aee184099`（2026-09-15，早于当前代码）。
- OMP（oh-my-pi）：`C:/project/codes/oh-my-pi` 提交 `fdfeef1f78`，路径相对于仓库根目录。
- opencode：`C:/project/codes/opencode` 提交 `0027387`，路径相对于 `packages/opencode/src/`，另有注明的除外。
- 公开资料：第 4 节逐条附链接；Letta 源码 tag 0.16.8（提交 `1131535`），Graphiti 提交 `47f6482`，ACE 提交 `82709de`。
- 阅读方式：本地仓库用 CodeGraph 与按文件读取；公开资料读取网页正文与论文。没有运行 OMP、opencode，没有复现任何实验。

## 1. Yudao 现行实现

### 1.1 每次请求的组成

`harness/context.py:151-402` 的 `ContextAssembler.assemble` 把全部部分拼成一条 developer 消息（每部分写作 `[source]` 加正文，343-344），之后接部门历史。顺序如下：

| 顺序 | 部分 | 形式 | 条件 |
| --- | --- | --- | --- |
| 1 | intend（用户原文逐次累加） | 全文 | 总是 |
| 2 | current_work（部门、阶段、工作文本、当前目标） | JSON，随阶段、专家请求、指导改写 | 总是 |
| 3 | project（项目上下文材料） | 全文 | 有项目上下文 |
| 4 | department_guidance | 指导全文 | 有待处理指导，只在激活的第一步 |
| 5 | department_rules（部门 Prompt） | 全文 | 总是 |
| 6 | input_progress | JSON | 总是 |
| 7-9 | input_handling、professional_completion、collaboration_rules | 固定规则文本 | 总是 |
| 10 | proposal_contract | 按部门固定的 JSON | 总是 |
| 11-13 | binding_refs、loop_limits、allowed_tools | JSON | 总是 |
| 14-15 | pending_inputs、validation_feedback | JSON | 有未处理输入或提案被拒 |
| 16-17 | current_contract、current_engineering_plan | 全文 JSON | 存在 |
| 18-20 | pending_request、request_results、guidance_results、latest_response | JSON | 有未结请求、指导或最近回应 |
| 21-22 | current_product_spec、current_product_decisions | 全文 JSON | 存在 |
| 23 | current_delivery_spec 或 prior_delivery | 全文 JSON | 工程与质检 |
| 24 | qa_defects | JSON | 质检要求返工时，产品与工程 |
| 25 | causal_chain（最近若干 spec、请求、回应、交付、评审、状态转换的编号与 hash） | JSON | 总是 |

- 各部分都不设上限，只有 causal_chain 按条数切片；清单的 `truncated` 固定为 False（386）。输入估算超出窗口时报错，编排器转为 context_overflow（`harness/orchestrator.py:949-950, 1027-1031`）。
- `department_work_text()`（`harness/context.py:141-144`）取出动态部分，每次激活的第一步把它作为 user 消息写入历史（`harness/orchestrator.py:951-962`）。第一步的请求中这些内容出现两次，此后每次激活都在历史中留下一份。

### 1.2 上下文清单

- `ContextManifest`（`harness/models.py:380-422`）记录放入的部分（名称、版本、token 估算、sha256）、排除的部分与原因、总估算、有效窗口、输出上限、压缩检查点、合同与计划 hash、Prompt 版本等。排除项固定为 4 项（`harness/context.py:359-364`）。
- 清单写入 CONTEXT_ASSEMBLED 事件（`harness/orchestrator.py:1043-1060`），完整请求与每个部分的全文另存为材料。
- 界面（`harness/web/static/context-view.js`）显示快照列表、四个重点部分与所选部分全文，不显示逐项 token 估算与排除列表。

### 1.3 历史与压缩

- 历史按部门从事件恢复，范围是本事项该部门的全部激活（`harness/orchestrator.py:1081-1110`）。
- 压缩检查点绑定合同、计划、输入版本与 Prompt 版本，任何一项变化即不使用（`harness/orchestrator.py:964-981`）。
- 压缩后的历史是一条 `[department_memory]` 摘要 user 消息加覆盖点之后的原始记录（`harness/compaction.py:84-95, 272-277`）。
- 近期保留区 `keep_budget = min(window//5, max(0, threshold - pinned - summary_limit))`（`harness/compaction.py:369-385`）。
- 历史与压缩不截断工具结果；截断只在工具内部：run_check、collect_evidence、run_command 输出 4000 字符，search 与 read_range 每页 4000 字符并分页，read_file 与 list_files 没有上限（`harness/tools.py`）。

### 1.4 提示缓存

- 三种协议的请求都没有 cache_control、prompt_cache_key 或 previous_response_id；只有 opencode-go 服务方案发送 `x-opencode-session` 头（`harness/providers/presets.py:113-120`）。
- 动态部分与固定规则交错排列（第 2 项动态，第 7-9 项固定），跨激活时只有 intend 保持不变。工具列表按阶段与请求逐次过滤（`harness/context.py:571-577`）。
- 运行数据：同一激活的第 2 至 5 步 developer 消息 hash 相同，上游报告的缓存读取为 9216、13824、14080 token；每次激活的第一步与压缩后的请求缓存读取为 0。

### 1.5 数值

- token 估算为字符数除以 4（`harness/models.py:148-151`）。运行数据中估算值约为上游报告值的 0.7 至 0.8。[模型管理设计说明](../design/model-management.md)第 8.2 节写的是按 UTF-8 字节数除以 4，代码尚未按设计修改。
- 事项默认窗口 32000（`harness/models.py:534`），有效窗口取事项窗口与模型窗口的较小值（`harness/orchestrator.py:827-840`）。
- 运行数据中的请求大小：产品第一步估算 2797 token（工具定义 987、提案合同 445、历史 465）；工程新一次激活估算 11833 token（历史 7183，其中 3 条激活输入副本分别为 4788、6471、8586 字符；工具定义 1333；ProductSpec 1070）。

### 1.6 按需取得

- 三个部门都有 read_file、list_files、search、read_range，范围只限工作区的公开文件树。
- 没有读取材料、查询事件或查询历史的工具。PRD.md 与 PLAN.md 写在材料目录，不在工作区（`harness/submissions.py:167-179`），部门只能从上下文部分取得合同、计划、ProductSpec 与决定。

## 2. OMP（提交 fdfeef1f78）

### 2.1 系统提示

- `packages/coding-agent/src/system-prompt.ts:683-1044` 的 `buildSystemPrompt` 由主模板、project-prompt 块等组成。主模板依次为约定、角色、工程要求、技能与规则、内部地址目录、工具清单、工具策略与工作流（`packages/coding-agent/src/prompts/system/system-prompt.md`）。project-prompt 块依次为环境信息、规则文件全文、下级目录 AGENTS.md 路径清单、工作区目录、附加内容（记忆与 MCP 说明）。
- 系统提示只在会话开始或签名变化时重建（`packages/coding-agent/src/session/session-tools.ts:1662-1696, 1738-1777`）。每次请求变化的日期与工作目录移到第一条 user 消息，变化后追加新的消息，已发送的消息不改（`packages/coding-agent/src/session/date-cwd-reminder.ts:1-117`）。

### 2.2 规则与记忆的放入

- 上下文文件（AGENTS.md、CLAUDE.md 等）从工作目录向上查找，全部放入（`system-prompt.ts:451-485`）。
- 规则分三种（`packages/coding-agent/src/capability/rule-buckets.ts:42-76`）：始终适用的规则全文放入系统提示；有描述的规则只列名称、适用路径与描述，全文由模型通过 `rule://<name>` 读取；带条件的规则由 TTSR 在输出过程中匹配编辑工具参数中的路径与内容，触发后中断并插入规则，或附在该工具结果前面，默认只触发一次（`docs/ttsr-injection-lifecycle.md`）。
- 下级目录的 AGENTS.md 只列路径，要求模型编辑前自行阅读（`prompts/system/project-prompt.md:19-25`）。
- 记忆后端默认关闭。sharpshooter 把全部决策文件放入，上限 15000 token（`sharpshooter/backend.ts:117-126`）；local 放入摘要与课程，上限 5000 token（`memories/index.ts:277-294`）；召回类后端只在开始时按首轮提示召回一次。
- 技能只列名称与描述。

### 2.3 按需取得

- 工具：read、grep、glob、ast_grep、lsp、github、web_search，以及记忆后端的 recall、reflect、retain、memory_edit。
- 内部地址目录（`system-prompt.md:55-75`）：`skill://`、`rule://`、`memory://`、`agent://<id>`（子 Agent 输出）、`history://<id>`（只读的会话记录）、`artifact://<id>` 等。超长工具输出末尾写明用 `artifact://N` 取回全文（`tools/output-meta.ts:425`）。

### 2.4 旧工具结果

`packages/agent/src/compaction/pruning.ts`：
- 默认保护最近 40000 token 的工具输出，可节省量不少于 20000 token 才裁剪；技能读取与计划文件读取受保护。
- 占位文本：`[Output truncated - N tokens]`、`[Superseded by a newer read of this file]`、`[Uneventful result elided]`。
- 同一文件被重新读取后，旧的读取结果可以换成占位；为保护缓存，只在候选之后的消息不超过 8000 token 或空闲超过 90 分钟时改写（`session/session-maintenance.ts:192-200`）。
- shake（`packages/agent/src/compaction/shake.ts:46-75`）把工具结果与大块内容换成 `[shaken ~N tokens — recover: artifact://ID (region k)]`，原文存为 artifact；自动压缩时保护最近 16000 token。

### 2.5 提示缓存

- Anthropic 协议共 4 个断点：最后一个工具、最后一个系统块、最近两条消息（`packages/ai/src/providers/anthropic.ts:3477-3562`）。OpenAI 兼容协议在最后一个文本部分加断点。
- 系统块首次生成后原样重放；工具增减不改写工具数组，新工具延迟加载并追加控制块（`anthropic.ts:3693-3808`）；可以开启前段冻结、消息只追加（`packages/agent/src/append-only-context.ts:1-146`）。

### 2.6 子 Agent

- 子 Agent 从空白开始，不继承父对话（`prompts/tools/task.md:66`）。系统提示按子 Agent 重建，插入子 Agent 块：角色说明、父 Agent 传入的批次上下文、已批准计划全文（`task/executor.ts:3361-3381`）；user 消息是任务说明。上下文文件中去掉 AGENTS.md（提交 d8d9a89d58）。
- 交回：通过 yield 提交；父 Agent 看到的预览最多 5000 字符，全文用 `agent://<id>` 取回（`task/result-summary.ts:14-75`）。

### 2.7 待办与请求记录

- 待办不在每次请求重复放入。改动类工具调用达到 12 次时提醒未完成项数；模型停止但仍有未完成项时，追加列出全部未完成项的消息，最多 3 次（`session/todo-tracker.ts`）。
- 没有逐请求的上下文清单，只有手动导出（`/dump`）与按类别估算占用（`/context`）。

## 3. opencode（提交 0027387）

### 3.1 系统提示

- 每一步重新组装（`session/prompt.ts:1257-1271`）：环境、规则文件、MCP 说明、技能清单；最终拼接为 Agent 提示或按模型选择的提示，加上述内容，加该条消息自带的系统内容（`session/llm/request.ts:56-78`）。
- 环境块包括模型名、工作目录、平台、日期与项目参考目录（`session/system.ts:69-105`）。

### 3.2 规则的放入

- 启动时全部放入：全局 AGENTS.md 或 CLAUDE.md，从当前目录向上查找的项目规则文件，配置中列出的文件与 URL（`session/instruction.ts:110-169`）。
- 按路径附加：read 工具读取文件时，从该文件所在目录向上走到项目根，找到尚未加载的 AGENTS.md 或 CLAUDE.md，附在读取结果末尾；已加载的、历史读取结果中已有的、同一条消息已附加的不再附加（`session/instruction.ts:17-32, 179-221`；`tool/read.ts:300, 355-357`）。旧读取结果被裁剪后，对应规则文件可以再次附加。
- 没有记忆与笔记。

### 3.3 按需取得

- 工具：read、glob、grep、webfetch、websearch、skill、task；没有查询历史或会话的工具。
- 模型通过技能清单、参考目录清单、task 工具描述中的子 Agent 列表知道有什么可取；工具输出超过 2000 行或 50KB 时全文存入截断目录，提示用 grep、read 或 task 读取（`tool/truncate.ts`）。

### 3.4 旧工具结果

- 裁剪默认关闭（`packages/core/src/v1/config/config.ts:154-156`）。开启后在运行循环结束时执行：跳过最近 2 个 user 轮次，保护 40000 token，可节省量超过 20000 token 才执行，技能工具受保护（`session/compaction.ts:271-317`）。
- 被裁剪的结果发送时换成 `[Old tool result content cleared]`（`session/message-v2.ts:297-300`）。

### 3.5 提示缓存

- Anthropic 类模型给前 2 条系统消息与最后 2 条非系统消息加缓存标记；不支持内联标记的服务用会话 ID 作为 prompt_cache_key（`provider/transform.ts:358-407, 1325-1335`）。
- 工具按名称排序（`session/llm/request.ts:184`）。

### 3.6 子 Agent、提醒与请求记录

- 子会话只包含父 Agent 在 prompt 参数中写的内容，系统提示按同一套规则组装，不含父会话的对话（`tool/task.ts:200-212`）；交回子会话最后一段文字。
- 计划模式的提醒每一步追加到最新一条 user 消息，只在内存中添加（`session/reminders.ts:15-90`）。
- 没有逐请求的上下文清单。

## 4. 公开资料

### 4.1 Anthropic

- 上下文工程的目标是「找到最小的一组高信号 token，使期望结果的可能性最大」；输入越长，模型准确回忆上下文内容的能力越低（context rot）。<https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- 混合策略：Claude Code 开始时放入 CLAUDE.md，文件用 glob、grep 即时取得。上下文只保存轻量标识符（路径、查询、链接），运行时再取得；标识符的元数据本身也是信号。代价是运行时探索更慢，缺少引导时会浪费上下文。
- Agent Skills 三级披露：启动时只放名称与描述，相关时读取全文，附带文件按需读取。<https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- 工具结果清理（context editing，`clear_tool_uses_20250919`）：默认在输入达到 100000 token 时触发，保留最近 3 次工具调用与结果，从最旧的开始换成占位，可以设置每次至少清除的量以抵消缓存失效，可以排除指定工具；客户端保留完整历史。与 memory tool 一起使用时，agentic search 提升 39%，只用清理提升 29%。<https://platform.claude.com/docs/en/build-with-claude/context-editing>，<https://claude.com/blog/context-management>
- 结构化笔记：长时运行的 harness 用进度文件、功能清单（JSON，每项带通过或未通过）、初始化脚本与 git 历史在上下文窗口之间交接状态；选 JSON 的理由是模型较少误改 JSON 文件。<https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
- 子 Agent 各自探索，交回 1000 至 2000 token 的浓缩结果。多 Agent 研究系统中，每个子 Agent 的任务说明包含目标、输出格式、可用的工具与来源、任务边界；子 Agent 把产出写入外部系统，只把引用交回。<https://www.anthropic.com/engineering/built-multi-agent-research-system>
- 工具只返回高信号信息，用有语义的名称代替随机标识符；提供简洁与详细两档输出；Claude Code 默认把工具返回限制在 25000 token。<https://www.anthropic.com/engineering/writing-tools-for-agents>
- 长文档放在提示前部，问题与指令放在末尾，测试中回答质量最多提升 30%。<https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices>

### 4.2 Manus

<https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus>（2025-07-18）；研讨会记录 <https://rlancemartin.github.io/2025/10/15/manus/>（2025-10-15）。

- KV 缓存命中率是生产环境中最重要的指标；一个 token 的差别就使其后的缓存失效。做法：前段稳定（不在系统提示开头放精确到秒的时间），只追加，序列化保持确定，断点至少包含系统提示末尾。
- 工具定义在迭代中途不增删，用状态机在解码时屏蔽不可用的工具；工具名使用统一前缀以便按组限制。
- 文件系统作为上下文：保留路径或 URL 就可以丢弃内容，需要时再读取，压缩因此可以恢复。每个工具结果有完整与紧凑两种表示，较旧的结果换成紧凑表示（只保留引用）。
- 反复改写待办清单，把目标复述到上下文末尾；研讨会记录约三分之一的动作用于更新待办清单，之后改为 planner 调用 executor 子 Agent。
- 保留失败的动作与错误信息，模型看到后会减少重复同类动作。
- 上下文过于一致时模型会模仿自己的历史，需要在序列化中加入少量结构变化。

### 4.3 Letta / MemGPT

- MemGPT 主上下文分为只读的系统说明、固定大小可读写的工作上下文、先进先出的消息队列（第一条是被移出消息的递归摘要）；提示达到约 70% 时警告模型，达到 100% 时移出约一半消息。<https://arxiv.org/abs/2310.08560>
- core memory block：每个 block 有标签、内容、字符上限、描述与只读标记，渲染时显示当前字符数与上限（`letta/schemas/memory.py:143`）；模型主要根据描述决定何时读写。多个 Agent 可以挂载同一个 block。<https://docs.letta.com/guides/core-concepts/memory/memory-blocks>
- archival 与 recall 不常驻上下文，只能按需搜索；block 用于需要一直可见的信息与当前工作状态。<https://docs.letta.com/guides/core-concepts/memory/archival-memory>

### 4.4 Zep / Graphiti

- 检索分搜索（语义、全文、图上广度优先）、重排、构造三步；事实带现实中成立的时间与系统中写入、失效的时间；LongMemEval 上上下文从约 115000 token 降到约 1600 token。<https://arxiv.org/abs/2501.13956>
- 交给 Agent 的文本：开头说明有效时间的含义，之后是事实（附有效起止）、实体（名称与摘要）、原始片段与社区摘要（`graphiti_core/search/search_helpers.py:27`）。Zep 的规则：结束时间为 present 的事实当前有效，结束时间在过去的事实当前无效。<https://help.getzep.com/advanced-context-block-construction>
- Zep 建议把上下文块放在对话历史之后、最新请求之前，使前面的内容在各轮之间不变，缓存前缀得以保持。<https://help.getzep.com/retrieving-context>
- 按中心节点距离重排：与中心节点直接相连的记距离 1，不相连记为无穷，只区分一跳相邻与不相邻（`search/search_utils.py:1793-1852`）。<https://help.getzep.com/graphiti/working-with-data/searching>

### 4.5 子 Agent 的上下文交接

- Cognition（2025-06-12）：共享完整的上下文与轨迹；动作带有隐含的决定，互相冲突的决定导致坏结果。<https://cognition.com/blog/dont-build-multi-agents>
- Cognition（2026-04-22）：可行的结构是多个 Agent 提供判断、写入保持单线程；审查 Agent 只看 diff，使用完全干净的上下文，平均每个 PR 发现约 2 个问题；管理者缺少代码库上下文时，给出的指示往往过细而适得其反。<https://cognition.com/blog/multi-agents-working>

### 4.6 经验与洞见的放入

- ExpeL：从成功与失败的轨迹中提炼洞见，每条带重要度计数；任务开始时放入全部洞见，不做筛选，另按任务相似度取成功轨迹作为示例。<https://arxiv.org/abs/2308.10144>
- ACE：playbook 由带编号与「有用、有害」计数的条目组成，生成时放入全部条目并要求模型写出用到的条目编号；整体改写会使上下文从 18282 token 缩到 122 token，准确率从 66.7% 降到 57.1%（context collapse）。<https://arxiv.org/abs/2510.04618>
- Dynamic Cheatsheet：整理过的备忘单优于直接追加完整历史（AIME 2024 上 50% 对 26.7%），未经整理的历史会稀释关键内容。<https://arxiv.org/abs/2504.07952>
- Agent Workflow Memory：按网站放入该网站的全部工作流，不做检索；把工作流作为可调用动作只提升 1.3 点。<https://arxiv.org/abs/2409.07429>

### 4.7 长度、位置与表现

- Lost in the Middle：相关信息在开头或结尾时表现最好，在中间时明显下降。<https://arxiv.org/abs/2307.03172>
- Chroma Context Rot（18 个模型）：简单任务的表现也随输入长度变化；干扰项越多下降越多；只含相关部分的约 300 token 提示在所有模型上都显著优于约 113000 token 的完整提示。<https://www.trychroma.com/research/context-rot>
- NoLiMa：问题与目标信息没有字面重合时，13 个模型中有 11 个在 32000 token 长度下低于其短上下文基线的一半。<https://arxiv.org/abs/2502.05167>
- 即使完美取得全部相关信息，仅输入变长就使表现下降 13.9% 至 85%。<https://arxiv.org/abs/2510.05381>
- 要求分散在多轮给出时平均下降 39%；模型偏重第一轮与最后一轮。<https://arxiv.org/abs/2505.06120>

## 5. 共同做法与 Yudao 现状的差距

| 做法 | 出处 | Yudao 现状 |
| --- | --- | --- |
| 常驻部分只放每次都要用的内容，其余按需取得 | Claude Code、OMP、opencode、Letta | 全部由主机推送，没有按需取得材料与历史的工具 |
| 用名称与描述的目录告诉模型有什么可以取得 | Agent Skills、OMP 规则清单与内部地址、opencode 技能清单 | 没有 |
| 按正在接触的文件附加相关内容 | opencode 读取时附加 AGENTS.md，OMP 按编辑路径注入规则 | 没有 |
| 常驻内容设上限，并让模型看到用量 | OMP 记忆 15000 与 5000 token，Letta 字符上限 | 各部分都不设上限 |
| 前段稳定，只追加，动态内容放在末尾 | Manus、OMP、Zep | 动态与固定内容交错，跨激活只有 intend 不变 |
| 显式缓存断点或缓存键 | OMP、opencode | 没有 |
| 旧工具结果换成带取回地址的占位 | OMP、opencode、Anthropic、Manus | 没有 |
| 子 Agent 从空白开始，只看写明的任务说明，交回浓缩结果与取回地址 | OMP、opencode、Anthropic、Cognition 审查 Agent | D26 设计已按此思路编写，尚未实施 |
| 每次请求放入的内容留下记录 | 两个参照仓库都没有 | 已有上下文清单 |
