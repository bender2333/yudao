# OMP 系统审查与第二阶段借鉴清单

日期：2026-09-06
Yudao 基线：`fced43e`（`harness_1`）
OMP 只读基线：`D:/codes/oh-my-pi`，`e3106be68f778635da3a17106835ce2e0e6992af`
状态：源码审查和设计建议，不修改 OMP，不把 OMP 作为 Yudao 运行依赖。

本文对应 `docs/stage-2-plan.md` 的第 3 项。D18 已经借鉴 OMP 的统一 Provider 目录、具体模型解析和部门绑定关系；本文不重新讨论该决定，而是审查 OMP 的 Provider/流、历史压缩、工具循环、Trace/用量和 Prompt 结构，找出对 Yudao 原生内核有直接价值的最小改进。

纠正记录：2026-09-06 复核发现旧版第 2 节曾把 Yudao `harness/compaction.py` 的行号和实现误写成 OMP 源码。固定 OMP 仓库对应的是 TypeScript `packages/agent/src/compaction/compaction.ts`，其中没有 `visible_history` 或 `plan_compaction`；本节已改为 OMP 实际存在的 Prompt、`generateSummary`、`findCutPoint`、`prepareCompaction` 和 `remotePreserveReusable` 证据。其余源码事实也按固定提交重新核对。

## 审查方法与总体判断

审查以固定提交的实际源码为证据，不以产品介绍或搜索摘要代替实现判断。OMP 的主要层次如下：

| OMP 层次 | 固定版本中的职责 | Yudao 对应层次 |
| --- | --- | --- |
| Catalog/Registry | Provider 身份、认证政策、模型能力和协议元数据 | `harness/provider_catalog.py`、`harness/adapters/` |
| Stream | 模型请求、内部恢复、流式事件、终态和 Provider 错误 | `ResponsesAdapter`、`ProviderError` |
| Agent loop | 上下文转换、工具校验/调度、取消和循环边界 | `harness/engine.py`、`harness/orchestrator.py` |
| Journal/Stats | 会话事实、用量派生、Trace 和查询 | `EventStore`、`ArtifactStore`、projection/views |
| Web/TUI | 事实的筛选、详情和时间线展示 | `harness/web/`、`harness/views.py` |

结论是：Yudao 的三层边界已经适合当前需求，后续应补齐“物理尝试级事实和只读查询”，而不是引入一个新的 Agent runtime。OMP 中值得采纳的共同原则是：请求、响应、工具和用量都要有稳定身份；失败和未完成必须成为可见状态；查询层负责派生，不负责推进运行。Provider 切换、自动发现、OAuth、远端压缩回退、复杂子 Agent 调度和独立 Stats 数据库均不属于当前最小闭环。

## 1. Provider、流式终态与错误

### OMP 源码事实

1. `packages/ai/src/registry/registry.ts:21-37` 从认证政策生成唯一 Provider 注册表，并按 Provider id 查找。注册表集中承载身份和传输钩子，登录列表、刷新分派等结构从它派生，而不是由角色各自复制 Provider 配置。
2. `packages/catalog/src/types.ts:1053-1122`、`:1188-1192` 的 `Model` 同时携带模型 id、Provider、API、地址、上下文窗口、输出上限和兼容性记录；协议处理器读取已经解析的能力，不在发送阶段猜测。
3. `packages/coding-agent/src/config/custom-models.ts:65-103` 将 Provider 默认配置与模型级覆盖合成为最终模型，`:113-148` 再物化为完整 `Model`。这解释了 OMP 为什么可以让同一 Provider 下的不同模型共享连接基础，同时保留模型自己的协议能力。
4. `packages/ai/src/types.ts:446-452` 定义了 `maxRetryDelayMs`，但它只是 `StreamOptions` 的可选字段，是否消费由具体 Provider 决定；例如 Anthropic client 会使用它，OpenAI Responses 的 `OpenAIStreamRequestInit` 不接收该字段。`:529-543` 同时定义了三类不同钩子：`onPayload` 可以替换发送前的请求正文，`onResponse` 观察响应元数据，`onSseEvent` 观察原始 SSE。不能把三者都当成只读诊断；`onSseEvent` 明确是诊断观察且 `readSseJson` 会吞掉其异常，`onResponse` 则由 `notifyProviderResponse` await，回调异常可能使请求失败。`:545-572` 定义首事件和流间隔超时，同样由具体传输实现消费。
5. `packages/ai/src/providers/openai-responses.ts:721-843` 在成功接纳前要求识别到终态响应事件；没有终态的流被视为不完整。可重放输出之前的瞬时流失败，最多在该 Responses 调用内部再重试一次（`:172`、`:804-842`，退避 `500ms`）；外层还会对符合条件的空完成重试（`packages/ai/src/utils/empty-completion-retry.ts:89-180`）。此外，`packages/ai/src/utils/openai-http.ts:5-13`、`:30-39`、`:90-123` 的 `postOpenAIStream` 使用 `fetchWithRetry`，Responses 请求最多 6 次 transport attempt，且在进入 `fetchWithRetry` 前把 `init.body` 序列化为同一份 JSON；`packages/utils/src/fetch-retry.ts:273-345` 的 `maxDelayMs` 默认是 `60s`，`Retry-After` 超过上限时直接返回当前响应。`openResponsesStreamWithFallbacks` 还可能针对 strict-tools、reasoning effort 和陈旧 `previous_response_id` 重建请求。输出已经不可安全重放后，流失败才交给上层。
6. 上述重试分属 OMP 的传输层和 replay-safe 请求层：`postOpenAIStream` 的 transport retry 明确重发单次序列化的同一请求正文，replay-safe retry 保持同一 model/context 目标并只在输出尚未提交时重发。它们都不等同于 Yudao D17 的逻辑尝试：D17 每次实际尝试要重新装配上下文、重新准入并计入步骤。评审必须记录这些层次、次数和取消边界，不能把 OMP 的内部 retry 当成 Yudao 的 attempt 模板。
7. `packages/ai/src/utils/event-stream.ts:169-218` 将 `done`/`error` 视为最终结果，结果 Promise、消费者和队列同时封口；无终态结束会以 Provider envelope 错误拒绝，而不是无限等待。
8. `packages/ai/src/error/retryable.ts:11-60` 把 408、429、5xx、瞬时传输/流错误与认证、配额和一般 4xx 分开。配额耗尽不因同属网络层而自动重试。
9. OMP 的“角色绑定”还在 coding-agent 配置层：`packages/coding-agent/src/config/model-roles.ts:24-63` 定义 `default`、`smol`、`slow`、`vision`、`plan`、`commit`、`tiny`、`task`、`advisor` 等角色；`packages/coding-agent/src/config/model-resolver.ts:1401-1525`、`:1644-1670` 通过角色值、模式和优先级解析具体模型。`:1525-1642` 的 `resolveModelOverrideWithAuthFallback` 还会在子任务目标无认证时回退到父会话模型。它证明了 OMP 的 Provider → Model → role selector 链路，但不是三部门冻结绑定；角色别名、优先级和认证回退必须单独评估。

### Yudao 已有等价能力

`ProviderCatalog` 已统一保存 Provider、模型、协议、地址和能力，任务创建时冻结部门绑定；`ResponsesAdapter` 使用显式配置和 `max_retries=0`，由内核执行 D17 的三次有界尝试。`ModelObservation` 已区分请求 JSON、输出 item、usage 和 message，`orchestrator._record_observation` 已把脱敏后的 SDK 请求保存为 `sdk_request` 工件及 `MODEL_REQUEST_SERIALIZED` 事件。D18 还明确区分 `requested_model` 和实际返回模型，实际未知时不回填配置模型。

这比直接把 OMP 的 Provider 层移植过来更符合 Yudao 的责任边界：适配器只执行一次请求，`engine.py` 决定是否继续，领域事件决定结果是否有效。

### 建议采用的小改进

**A. 补齐一次物理尝试的原始证据。** 当前请求 JSON 已有采集，但 D21 还要求保存已取得的 Provider 响应对象、必要的流式原文和单次开始/结束时间。改进边界应是：适配器负责发出脱敏的 `request`、`response metadata`、`raw stream` 观察；编排器负责把观察绑定到当前 `activation_id/step_id/attempt` 并写入 `ArtifactStore`；查询层只返回引用和受控内容。不能让 Web 直接读取 SDK 对象或自行拼接一份“原始响应”。

**B. 将终态证据和失败分类保持在同一适配器契约。** `ProviderError.reason/retryable/diagnostics` 已足够承载 D17，但每个失败事实还应明确是“已准备未发出、请求已序列化、收到部分流、收到终态失败、取消”中的哪一类。此信息属于适配器观察和编排器事件，不属于 Prompt 或页面状态机。

**C. 继续保持配置身份和实际响应身份分开。** OMP 的 `AssistantMessage` 支持 `responseId`、`upstreamProvider` 和 `upstreamModel`（`packages/ai/src/types.ts:971-1027`），但其初始 `model` 仍是本地配置模型；固定版本的 OpenAI Responses 路径初始化并保留 `model.id`，只有少数 Provider（例如 Devin）会填充 `upstreamModel`。Yudao 的 D18 规则更严格：请求目标立即记录，实际返回只有在 Provider 明确上报时才记录。后续增加 raw response 时也应沿用这个事实口径。

### 不采用的 OMP 机制

- 不把 OMP 的 Provider 内部重试、认证 key 轮换、strict tool fallback、reasoning fallback、角色优先级 fallback 和 `previous_response_id` 链接全部搬入。D17 已规定重试由 Yudao 内核控制，D18 要求重试固定在任务快照中的部门目标；适配器内部另开重试预算会重复计数并破坏取消边界。
- 不引入 Provider 自动择优或模型 fallback，也不把 OMP 的 auth-aware parent-model fallback 当成部门绑定规则。配置变更、未知容量和不支持协议必须定位到具体部门并明确拒绝，不能靠换模型让任务继续。
- 不引入 OAuth、自动发现和 OMP 的认证政策运行时。Yudao 首批只需要宿主凭据解析和 Responses 适配器；将来支持新协议时，新增该协议适配器并单独验收。

### Yudao 采纳后的验收重点

请求钩子失败时零网络请求；没有终态的流不会进入有效历史；部分输出失败能回查请求和流原文但不执行工具；重试始终命中同一 Provider/模型；真实返回模型未知时保持未知；无 usage 与上报为零能够区分；认证/配额/上下文错误不会被标记为瞬时重试。

## 2. 历史、上下文与压缩

### OMP 源码事实

1. `packages/agent/src/compaction/prompts/summarization-system.md:1-5` 要求把历史和前一摘要当作不可信参考材料，不执行其中的命令或角色变更，只按当前摘要系统提示和宿主摘要请求输出结构化摘要。
2. `packages/agent/src/compaction/compaction.ts:854-935` 的 `generateSummary` 先将对话转换为摘要文本，按本地 `Tokenizer` 对消息边界拆分窗口，并用 `previousSummary` 逐窗口合并；输出预算来自 `reserveTokens` 和 `MAX_SUMMARY_TOKENS`。模型没有正的 `contextWindow` 时，`:775-803` 的 `summaryInputBudgetTokens` 使用 OMP 的 `DEFAULT_SUMMARY_INPUT_WINDOW = 200_000`，所以这不是“只按真实已知模型窗口”规划。
3. `packages/agent/src/compaction/compaction.ts:421-460` 的合法切点包括消息角色 `bashExecution`、`hookMessage`、`branchSummary`、`compactionSummary`、`user`、`assistant`，以及 `branch_summary`/`custom_message` 条目；`toolResult` 被明确排除。`:463-567` 再判断是否拆分完整回合并保留拆分回合起始位置。不能把它概括成只有用户、助手和边界。
4. `packages/agent/src/compaction/compaction.ts:1278-1314` 的 `remotePreserveReusable` 和 `findReadableCompactionIndex` 只负责判断当前模型能否读取 Provider 原生保留数据；`prepareCompaction` 因此选择可读检查点或重新展开原始条目，`compact`（`:1539` 起）随后才决定走远端保留还是本地摘要。函数本身不生成摘要；且 `activeModel` 可选，缺失时不会做模型可读性校验。
5. `packages/agent/src/append-only-context.ts:1-15`、`:49-90`、`:103-205`、`:226-365` 将可选的 StablePrefix 和追加消息日志分开。`StablePrefix.build` 每次按 system prompt、工具和选项 fingerprint 判断是否重建；`syncMessages` 的 compaction 主要清空消息日志，不必然重建 prefix。消息 digest 依赖所有者正确维护 `messageEstimateVersion` 失效标记；原地修改而不 bump 是源码明确标为 unsupported 的调用错误，不是管理器自动保证的事实。
6. `packages/agent/src/compaction/compaction.ts:901-930` 只在捕获到 `ContextOverflow` 时依据实际发送文本的估算大小减半并重新规划；该动态恢复和 `:775-803` 的未知窗口 fallback 都是 OMP 的宽松策略，不能被当成任意模型容量已知，也不能替代 D18 的未知容量拒绝。

### Yudao 已有等价能力

`ContextAssembler` 已把 intend、当前工作、部门 Prompt、有效合同/计划、同部门历史和协作材料分成有来源的 `ContextPart`，`ContextManifest` 保存 digest、估算、有效窗口和输出预留。`plan_compaction`/`finish_compaction` 保存连续片段、检查点、覆盖 digest 和摘要输出限制，失败流不会进入有效历史；D18 已让压缩沿用实际执行部门的冻结 Provider/模型及其容量。

### 建议采用的小改进

**A. 增加只读的“当前历史视图”查询。** W3 需要从 Context 直接看到摘要、覆盖范围、近期完整回合和被排除材料。查询应复用现有 projection/ArtifactStore，返回 `summary_ref`、`covered_through_event_id`、`covered_digest`、`partial_event_id/offset`、`recent_event_ids`、`active_target` 和 `readable`，不能在查询时重新执行摘要，也不能根据当前目录重新推导旧任务的模型。

**B. 将工具回合边界作为压缩验收的不变量。** 当前压缩规划已经有边界检查；W1/W3 应把“没有切在 tool call 与 tool result 之间、失败工具结果不会变成已完成动作、摘要来源能够覆盖所有连续片段”做成查询和 smoke 审计条件。模块边界留在 `compaction.py` 与 `context.py`，不在 Web 复制一套切分算法。

**C. 保留摘要可读性判断。** 若将来支持第二种协议或 Provider，应沿 OMP 的“当前活动目标能否读摘要”原则判断；当前 D18 只有 Responses，暂时只需核对 `snapshot_id/provider/model/protocol` 与压缩记录完全相同。

### 不采用的 OMP 机制

- 不引入 OMP 的远端 V1/V2 compaction、provider-native replacement history 和失败后的多级回退。D18 要求压缩首批使用部门同一个 Provider/模型；远端回退会让请求归属、容量和可观察事实变复杂，也会掩盖真实协议不支持。
- 不引入 Snapcompact、分支摘要和 append-only KV 缓存作为第二套事实来源。稳定前缀可以作为未来性能优化，但不能改变 ContextManifest 的实际输入和 D21 的原始输入证据。
- 不照搬 OMP 对未知窗口的宽松默认。Yudao D18 已要求绑定模型的容量必须明确，未知时拒绝，不借用其他模型容量。

### 该项的验收重点

压缩前后原始历史可回查；摘要覆盖连续且没有漏掉工具回合；窄窗口使用当前部门的有效窗口和输出上限；压缩请求可取消并计入步骤；Provider/模型变化不会复用不可读摘要；失败摘要既不进入有效历史，也不触发工具执行。

## 3. 工具调用、循环和取消

### OMP 源码事实

1. `packages/agent/src/types.ts:473-531` 把 `beforeToolCall` 放在调度前，负责参数校验后的阻止或改写；改写后的参数会写回工具调用，使历史、事件、并发调度和实际执行看到同一份数据。但这只是正常校验路径，工具还可以显式声明宽松校验。
2. `packages/agent/src/types.ts:782-830` 为工具声明 `concurrency`、`interruptible` 和 intent 处理规则。源码文档建议只有能安全观察取消信号的等待类工具才声明 `interruptible`；类型和运行时并不强制这一点。实际 hard abort/skip 还受 `interruptMode="immediate"` 控制；对于队列 steering/IRC，非 interruptible 工具收到的是 cooperative soft signal，但外部用户 abort signal 仍会传给它。
3. `packages/agent/src/agent-loop.ts:2282-2365` 允许声明 `lenientArgValidation` 的工具在 schema 校验失败后继续把清理过的原始参数交给 `execute`；因此非法参数不必然先被阻断，Yudao 不应从 `beforeToolCall` 的时序推导统一安全结论。
4. `packages/agent/src/agent-loop.ts:2367-2459` 先为整个工具批次准备调用，再为每一调用决定是否可中断、使用哪一类 signal 和如何排队，避免在部分调用已经执行后改变批次语义。
5. `packages/agent/src/agent-loop.ts:2478-2517` 将非消费式 steering 检查与实际取消息分开；`:2560-2779` 区分未启动跳过、运行中取消、正常完成、错误和阻止，并在工具结果已经完成时保留真实副作用结果。
6. `packages/agent/src/agent-loop.ts:447-517` 在工具结果进入持久化和循环前做结构化归一化，防止第三方工具返回坏结构污染会话。

### Yudao 已有等价能力

`engine.run_department` 不让适配器执行工具，先校验响应，再通过 `begin_tool` 经过部门权限、合同/计划和路径范围准入；`ToolRuntime` 执行实际动作，`TOOL_STARTED`、`TOOL_CALLED`、`TOOL_SKIPPED` 保存调用、结果和跳过原因。D17 的 `stopped()` 检查负责取消、新输入、合同/计划变化和步骤边界，失败模型输出不会绕过准入进入工具。

### 建议采用的小改进

**A. 在 W1 查询中显式关联工具调用与模型尝试。** 每个工具调用至少需要 `tool_call_id`、发出它的 `attempt_id/step_id`、`TOOL_STARTED` 事件、结果工件、状态和时间。查询层应能回答“该工具由哪次请求提出、是否真的开始、为何跳过、结果是否错误”，而不是只看工具名称和当前部门。

**B. 统一工具终态词义。** 现有事件已经保存 started/called/skipped，W1 只需在 projection 中派生 `blocked`、`validation_error`、`aborted`、`completed` 等消费者状态，避免增加独立工具运行器。派生状态必须来自事件和结果，不从模型文字猜测。

**C. 保留副作用完成与取消竞态。** 如果取消到达时工具已经完成，查询应显示真实结果及“取消未改变已发生副作用”；如果工具尚未启动，应显示 skipped/aborted 且不能留下假的成功结果。这是 OMP 工具信号设计对 D17 的直接启发，具体控制仍由 `orchestrator.py` 负责。

### 不采用的 OMP 机制

- 不在当前阶段引入 OMP 的并行工具批次、协作 steering、IRC 中断、deferrable 工具、`xd://` 设备目录或 computer-use 工具。Yudao 当前单任务执行和部门权限边界更简单，任意中途打断写入、删除或移动会增加未知副作用合同。
- 不把 Prompt 中的工具策略当成安全控制。OMP 自己也把 `beforeToolCall`、schema 校验和执行 signal 放在代码边界；Yudao 应继续由 `begin_tool` 和 `ToolRuntime` 保持最终权威。

### 该项的验收重点

同一模型尝试所发出的同一个 `tool_call_id` 只能实际执行一次；无权限、计划外、参数错误和已停止调用不会执行副作用；工具结果与模型尝试准确配对；取消前已完成的副作用保留真实结果；取消后迟到结果不推进已关闭激活；失败模型输出中的工具调用不被执行。

## 4. Trace、请求采集与用量

### OMP 源码事实

1. `packages/agent/src/telemetry.ts:1-23` 定义了 `invoke_agent` 包裹 `chat` 和 `execute_tool` 的 span 层次；chat 与 execute_tool 是 invoke_agent 下的同级操作，并且 Telemetry 默认关闭，未开启时不查 tracer。
2. `packages/agent/src/telemetry.ts:72-164` 将 Provider、请求模型、响应模型、响应 id、终态、TTFT、usage、工具、错误和网关信息分成明确属性。chat 开始时的请求侧属性在 `:693-720` 记录；但响应侧 gen_ai.response.model 在 `:1199-1207` 取的是 message.model，不是通用的 upstreamModel，后者不会自动成为 Telemetry 属性。`:780-798` 按 none/summary/full 控制内容采集；默认是 none，summary 还受 `:45-52` 的消息数、数组、对象深度、键数和文本长度上限约束，只有 full 才写完整 OTEL 消息内容。
3. `packages/agent/src/telemetry.ts:1113-1195` 分别处理有最终 AssistantMessage 的成功/错误结果和没有最终消息的失败；`:1209-1227` 只有在 usage 存在时才写 input、output、缓存、推理和服务端工具 token。没有最终消息或没有 usage 的失败不会凭 Telemetry 自动补出真实响应和用量。
4. `packages/agent/src/run-collector.ts:180-242` 在 chat 开始时记录配置侧 model/provider，并在结束时按 message.usage 汇总 token、成本和耗时；usage 缺失时 input、output、缓存、推理和 total 都用 0，`:242-263` 的失败 chat 也用配置侧 model/provider 和全零 usage。`:315-431` 再生成运行摘要和覆盖范围，摘要不是从 UI 解析出来的，但它不是 requested/actual 身份和缺失 usage 的严格事实模型。
5. OMP Stats 的 `packages/stats/src/parser.ts:154-227` 对旧版本、崩溃截断和外部会话做宽松解析：缺少 model/provider/api 或完整 usage 对象的记录会跳过；usage 对象存在但 input/output/cacheRead/cacheWrite/totalTokens 等字段缺失时，`:191-207` 明确用 0 补齐并使用默认零成本，缺失 stopReason 也会推导为 error 或 aborted。`packages/stats/src/trace.ts:211-229` 的 activeChain 只选最后一条 parentId 链，但 session/header 等非链元数据仍会单独扫描；`:255-393` 扫描模型和终态，`:482-575` 将 tool call 与结果拼成 span，并将未闭合调用标记为 `unterminated`。
6. `packages/stats/src/shared-types.ts:490-588` 的 Trace 数据把 turn/model/tool/subagent/background 分成不同 span，保留 entryId、tokens、cost、TTFT、error 和 unterminated；摘要中的 modelMs/toolMs 主要是 main track 汇总，不能直接当所有 child track 的总耗时。`packages/stats/src/server.ts:202-320` 提供 stats、recent/errors、request detail、session trace 和 entry 只读 API；这些 stats/recent/request 接口读取 SQLite，/api/sync 才扫描 JSONL。Trace 的 ETag（`:293-305`）只用于 session trace 的 HTTP 缓存，不等于实时事件流或运行事实订阅。
7. OMP 当前 `packages/stats/src/aggregator.ts:500-516` 的 getRequestDetails 只返回一个 assistant entry，并留有 TODO: Get parent/context messages?；它的入口使用 `packages/stats/src/db.ts:1148-1154` 的 SQLite 自增 messages.id，而不是稳定的 (session_file, entry_id)。它适合展示已有统计，不足以直接作为 D21 的完整 Context/Request/Response 详情模式，也不应把 numeric row id 当 Yudao 的 logical_call/attempt 身份。
8. OMP Stats 的 `packages/stats/src/db.ts:153-245` 使用 SQLite 派生表、唯一键和索引，`:247-339` 含列检查、回填和重建逻辑，说明它解决的是跨会话统计产品，而不是运行领域事件的唯一事实问题。

### Yudao 已有等价能力与缺口

Yudao 的 EventStore 已按 run/seq 保存事件，ArtifactStore 保存输入、模型消息、SDK 请求和用量，projection 已区分部门协作请求、模型请求、Provider/模型配置身份和实际返回身份；Web 已有实时事件读取和只读投影。

D21/W1 的主要缺口是：当前模型请求仍需要一个可直接查询的逻辑调用/物理尝试组合；每次实际尝试的开始、结束、部分返回和原始 Provider 事件还需要统一归属；请求详情不能只取最后一条 `MODEL_MESSAGE`；同一筛选条件下的列表、详情、用量和导出必须使用同一口径。

### 建议采用的小改进

**A. 建立一个纯查询的 Model Call read model。** 以事件和工件为输入，按如下三级关系派生：

```text
任务
  └─ 部门激活（正常工作或协作处理）
       └─ 逻辑模型调用（run + department + activation + root_step + purpose）
            └─ 物理尝试（step_id + attempt + retry_of_step_id）
```

部门协作请求通过现有 `request_id` 与相关工作建立可选关联；普通工作没有协作请求，仍有完整的模型调用与尝试。协作请求不是所有模型调用的必经父对象，也不能充当模型调用或 Provider 请求的身份。

物理尝试的 `requested` 记录 Provider id/name、协议、请求模型、snapshot id、凭据引用/版本、有效窗口和输出上限；`actual` 只来自 Provider 响应，未返回就是 `null`。每个尝试还关联 `context_ref`、`sdk_request_ref`、可用的 `raw_response_ref/raw_stream_refs`、失败分类、开始/结束时间、duration 和 usage coverage。该 read model 放在 `views.py` 或单独的查询模块；它不向 EventStore 写回事实。

**B. 让列表和汇总复用同一 FilterSpec。** 查询至少支持 `department`、`status`、`provider`、`requested_model`、`actual_model`、`purpose`、`attempt` 和时间范围。列表返回 cursor、匹配总数或明确的 unknown total；用量汇总对同一匹配集合聚合，不只统计当前页。Provider usage 缺失、部分字段缺失和明确的零分别返回 coverage/source，不用零填补缺失。

**C. 以事件序列作为刷新游标。** EventStore 已有 `after_seq` 查询，W1 可将 `run_id + after_seq` 作为实时刷新边界；查询响应同时返回当前最后 seq 或 projection version。断线恢复重新取快照和缺口，不重新执行模型。若以后增加 HTTP 缓存，可用 projection version 生成 ETag，但不把墙钟时间作为责任顺序。

**D. 原始内容按引用分层返回。** 列表只返回摘要和工件 id；详情返回脱敏 Request、Response、SSE/内部事件原文的来源和范围；超长内容通过已有 ArtifactStore 分页或下载读取。密钥、认证头、带凭据 URL 和不可获取的内部推理永不进入响应。

### W1 最小接口建议

实现上不需要再建 Stats 服务，先提供四个纯查询能力即可：

| 能力 | 最小输入 | 最小输出 |
| --- | --- | --- |
| `query_model_calls` | `run_id + FilterSpec + cursor/page_size` | 逻辑调用摘要、尝试数量/状态、requested/actual identity、usage coverage、next cursor |
| `get_model_call` | `run_id + logical_call_id` | 逻辑调用、所有尝试、重试关系、Context/Request/Response/工具/压缩引用 |
| `get_attempt_artifacts` | `run_id + attempt_id + artifact_kind` | 脱敏工件内容或分页引用，来源和 digest |
| `summarize_model_usage` | 与列表完全相同的 `FilterSpec` | 按部门/Provider/请求模型/实际模型分组的小计、缺失覆盖、进行中数量 |

`attempt_id` 应由 `run_id/activation_id/root_step_id/step_id/attempt` 稳定生成或由事件中已有身份组合生成；不能使用协作 `request_id` 代替。查询只读，切换尝试、查看失败和导出都不能触发模型或工具调用。W2/W3 再将这些结果接到原型中的列表、详情和 Context 跳转。

### 不采用的 OMP 机制

- 不把 OTEL span 作为 Yudao 领域事件、QA 状态或 Provider 请求事实的唯一来源。Span 适合运维关联和可选导出，无法替代失败输出隔离、合同接纳和摘要覆盖关系。
- 不复制 OMP Stats 的独立数据库、列回填和迁移链。Yudao 当前规则要求事件/工件为真相，且不保留旧接口兼容层；先用纯 projection 验证查询口径，确有跨 run 性能问题时再单独评估派生索引。
- 不照搬 OMP 的全量内容写入 span。完整 Request/Response 应进脱敏工件，span 或列表只放 bounded summary 和引用，避免内容泄漏与高基数属性。
- 不把 OMP 当前只返回单 assistant entry 的 `getRequestDetails` 当成完整请求详情；D21 明确要求 Context、尝试、重试、原始请求和响应互相可回查。

### W1 验收矩阵

| 场景 | 必须证明 |
| --- | --- |
| 无响应失败 | 能定位 requested Provider/模型、快照、协议和请求工件；actual model 为未知；usage 为未上报而不是零 |
| 部分流后失败 | 失败尝试有独立 raw stream/输出证据；失败内容不进入有效历史、工具或摘要 |
| 重试成功 | 一个逻辑调用下有多个物理尝试；重试关系准确；只有成功回合进入有效历史；每次已上报 usage 各计一次 |
| 压缩 | 压缩调用归属实际部门同一冻结目标；摘要 source refs、窗口和输出限制可回查；失败摘要不成为检查点 |
| 取消/新输入 | 旧尝试显示取消或不再接纳；迟到结果仍挂在旧 attempt；不启动过时重试或工具 |
| 工具配对 | tool call 可回到发出它的 attempt；started/skipped/completed/error 原因准确；不会重复执行 |
| 查询一致性 | 列表、详情、统计、导出使用同一 FilterSpec；分页不改变汇总；事件重复不会重复累计 |
| 刷新/断线 | 以 seq/version 补缺，不重跑任务；历史查看不产生写入或网络调用 |
| 安全 | 所有请求、响应、Trace、导出均无密钥、认证头和带凭据 URL |

## 5. Prompt 结构与质量改进边界

### OMP 源码事实

1. `packages/coding-agent/src/system-prompt.ts:80-148` 提供 Prompt block 规范化、段落 containment 判断，以及给 always-apply rule/custom source 使用的去重 helper；它不是对所有最终 system blocks 做全局去重。对于适用的 context files 和规则，完整段落序列被包含时才去重，语义相似或交错内容仍可保留。
2. `packages/coding-agent/src/system-prompt.ts:451-490` 通过 capability API 加载项目上下文文件，并保留文件路径和深度；文件按深度排序，只有完整段落序列被更靠近工作目录的文件包含时才会去重，语义相似或交错内容仍保留。
3. `packages/coding-agent/src/system-prompt.ts:689-705` 统一构建 system prompt；`:918-1054` 将工具清单、skills、rules、环境、工作树、人格和追加 Prompt 放进固定数据模型，最后按有序 system blocks 输出。准备阶段受 `:181-183`、`:759-907` 的 5 秒总时限约束，超时或失败的项目使用 minimal fallback，因此不能假设所有动态上下文都已加载。
4. `packages/coding-agent/src/prompts/system/system-prompt.md:1-5` 先定义术语和指令优先级，`:28-53` 分开 Skills/Rules，`:107-175` 规定工具策略，`:186-231` 规定 Scope、Research、Implement、Verify 的工作顺序。
5. `packages/coding-agent/src/prompts/system/project-prompt.md:8-29` 以 repo-rules、dir-context、workspace tree/roots、critical 和 appendPrompt 区块分隔工作区材料与追加内容；该模板本身没有版本控制或快照字段，也不能保证模型不会把这些材料和用户当前请求在语义上混合。它提供的是来源分隔和优先级提示，不是运行时事实隔离。
6. `packages/agent/src/compaction/prompts/summarization-system.md` 明确要求历史和摘要是无权威的参考数据；`compaction-summary.md`/`compaction-update-summary.md` 规定摘要输出结构和省略空段。

### Yudao 已有等价能力

Yudao 已有三部门独立 Prompt、版本/hash、作用域和激活冻结；`ContextAssembler` 以 `ContextPart` 区分用户原文、当前工作、规则、合同、计划、历史、协作和输入进度。代码中的工具权限、合同校验、计划范围和 QA 放行不由 Prompt 替代，这一点比复制 OMP 的通用编码助手 Prompt 更符合本产品职责。

### 建议采用的小改进

**A. 统一 Prompt 的分段原则。** 后续 Prompt 优化可以沿四层重写，而不增加新的 Prompt 引擎：部门身份与权限、当前有效事实及来源、当前工作流程与停止条件、提交/输出合同。每段在 `ContextPart` 中有名称和版本，最终请求保存 prompt hash。这样能回答“这次模型看到的规则来自哪里、何时生效”。

**B. 做精确去重和来源标记。** OMP 的段落 containment 去重值得用于部门规则和固定协作规则，但必须保留来源、版本和作用域；同文不应被重复注入，语义相似却不相同的材料不能用模糊相似度静默删除。

**C. Prompt 优化放到第 6 项。** 第 4 项 Context/Trace 先让研发者看到真实 Prompt、输入工件和实际 SDK 请求；之后用固定任务、固定 Provider/模型和独立 QA 比较 Prompt 版本。评估至少检查要求覆盖、计划合规、工具准入、返工重复错误和成本，不能以模型自评或单次成功证明改善。

### 不采用的 OMP 机制

- 不把 OMP 的通用编码工作流、skills/rules 自动发现、人格、工作树、环境探针和内部 URL 目录全部注入三部门 Prompt。产品、工程和质检的职责边界不同，且大段环境内容会挤占 D18 的有效窗口。
- 不让 Prompt 中的 MUST/NEVER 文本承担安全或完成判定。Yudao 的 `begin_tool`、合同/计划检查和 QA 事实仍是代码权威；Prompt 只负责让模型理解这些边界。
- 不引入 OMP 的 managed skills/auto-learn 作为本阶段 Prompt 优化。它们依赖 OMP 的技能发现、存储和自治流程，超出六项前置工作的范围。

### 该项的验收重点

同一激活的每次普通请求和压缩请求使用同一已冻结 Prompt 版本；下一次激活才采用修改后的版本；查询能看到每段来源和 hash；重复规则不重复注入；Prompt 变化不改变代码层工具权限；固定任务上的改版能被独立 QA 和成本统计复核。

## 6. 采纳顺序与归档边界

| 结论 | 处理时机 | 责任模块 | 独立验收 |
| --- | --- | --- | --- |
| Provider raw response/SSE、单次耗时和终态阶段 | W1 | adapter + orchestrator + ArtifactStore | 无响应、部分流、终态失败、取消、脱敏 |
| 逻辑模型调用/物理尝试 read model | W1 | projection/views | 重试、压缩、跨部门、未知 actual、usage coverage |
| 工具与 attempt 精确配对 | W1/W3 | engine 事件 + query projection | 一次执行、跳过、取消竞态、迟到结果 |
| 历史视图/摘要来源查询 | W3 | context/compaction query | 连续覆盖、工具边界、Provider 目标一致 |
| 原型化 Trace 时间线和筛选 | W3/W4 | Web query + UI | 列表/详情/统计同口径、断线补缺、移动端 |
| Prompt 分段去重与效果比较 | 第 6 项 | department prompts + evaluation | 固定任务、独立 QA、成本和重复错误 |
| OTel 导出、Stats 派生库、远端压缩、复杂并行 Agent | 归档，另行评估 | 不进入当前 Stage2 前置闭环 | 只有出现明确需求和独立选型后再开题 |

本文不创建一个泛化的“待处理研究清单”。被采纳的前三项直接落到 W1/W3 的具体验收；其余机制明确归档，避免在 Provider 真实验收、第一阶段真实验收和 Context/Trace 尚未完成时扩大运行时边界。
