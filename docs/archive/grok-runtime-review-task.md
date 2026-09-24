# Grok Build：运行时验收修复

用户授权 Grok 为实现主力。本任务只处理以下已复现问题，不扩张系统范围，不重做已通过的 provider 探测。

## 必须修复的问题

1. 取消后迟到结果仍可被接受。审查在提案验证结束、提交开始前插入 cancel，cancel 返回 FAILED/cancelled，旧结果随后写入 spec_accepted 和 transition，最终出现 phase=ENGINEERING、outcome=failed、stop_reason=cancelled。取消和提案提交必须在控制层有一致的串行提交边界；不能持锁跨整个模型调用使取消失效。迟到错误也不能覆盖已确定的停止原因。以 barrier/event 确定性测试该交错，并验证 replay 的终态一致性。
2. 预算忽略实际 provider usage。审查设置 token_budget=5000、provider total_tokens=1000000，activate_once 后 token_used 仅91，且进入 Engineering。应使用实际完整 activation usage（包含内部多轮与缓存 token）修正预先计入的估算，避免漏计和重复计费。没有 provider usage 才使用明确估算值。超预算暂停后不得启动下一部门。增加确定性测试，回放得到相同预算状态。

   OMP 18.1.11 发布类型的确定事实：pi-catalog/dist/types/types.d.ts:73 定义 usage.input 为未命中缓存的输入，output 已含 reasoning/thinking、文本和工具参数，cacheRead/cacheWrite 是独立缓存桶；totalTokens 已含上述各桶以及提供方报告的 orchestration token。直接采用并累计各条 assistant 完整消息的 totalTokens 和 cost.total，不能把缓存或 reasoning 再加到 totalTokens 上，也不能把 cost.total 与 cost.input/output/cacheRead/cacheWrite 再相加。若需要展示完整会话输入，应表达为 input + cacheRead + cacheWrite；保留输入分桶语义，不能只显示 input 后声称包含缓存。源码旁证为 oh-my-pi packages/ai/src/providers/openai-shared.ts:440 的 calculateOpenAIUsageAccounting 和第3745行起的 Responses usage 规范化。

   最小计费入口采用 assistant 的 message_end：每完成一条模型响应只登记一次，再跨内部工具循环累加。message_start/message_update 是同一条响应的流式快照，agent_end.messages 又包含已经发过 message_end 的消息，均不再增加 token/cost。例如两条 assistant 的 totalTokens 为110和140，activation 应计250，而不是仅保留末条140或把结束帧再加一次变成500。错误/取消消息里已经报告的 usage 也要保留。测试包含多轮、缓存、reasoning子集、重复结束汇总、没有 responseId，以及首轮完整响应后下一轮失败；使观察过程中已入账的用量与 invoke 最终汇总不会再次相加。

   get_session_stats 不是无条件的全生命周期计费依据：packages/coding-agent/src/session/session-stats.ts:111 起统计当前 state.messages，并另加 activeModelUsageEntries；压缩/重置会改变有效窗口。底层一次 agentLoop 的消息列表也不包含所有独立维护调用。当前计费承诺应以可观测的主对话模型调用为依据；若启用自动压缩等独立模型调用，须通过现有 OMP 可观测数据证明这些调用被覆盖，不能仅把最后一帧或当前上下文统计命名为完整实际总账。
3. 新检查实现先 capture_tree、在交付目录运行、finally restore_tree，再把退出码绑定已还原的树，产生错误证据：检查把 app.py 的 BROKEN 改成 FIXED 并断言成功，还原 BROKEN 后原始 hash 却收到 exit=0 回执。另探针把 target.txt 替换成临时目录外部文件的硬链接，restore_tree.write_bytes 会覆写外部文件。设计修正：在可丢弃的工作副本运行检查，不对原交付目录执行事后还原；副本不能包含主机私有回执，链接不得带入检查副本。若检查改动了受测代码，不能把通过结果绑定原始快照。避免把该副本机制宣称为操作系统安全沙箱。覆盖修改代码后成功、硬链接替换、失败、超时和真实退出码的测试，删除过时的 capture/restore 实现而非保留兼容路径。
4. OMP 的 --no-rules 只令 options.rules=[]（oh-my-pi main.ts:1350），sdk.ts:1390 仍独立 discoverContextFiles。当前 OMP cwd 在仓库内，因此会读到仓库 AGENTS.md（架构师/不写代码/Grok 主力）等无关指令，与三部门角色冲突。已用发布版 OMP 18.1.11 和本地随机端口 Responses stub 证实：--no-rules/--no-skills/--no-extensions/--no-tools/--no-session/--no-lsp 不能阻止工作目录和 profile 的 AGENTS.md 注入。单独 --system-prompt 显式文本或文件也不能隔离；custom-system-prompt.md:13 自己渲染 contextFiles，system-prompt.ts:1041 清除的只是第二个 project footer 的重复副本。删除此前“显式 system prompt 会移除自动 contextFiles”的推断，不修改 OMP 源码。

   已验证的启动组合是：宿主控制的 --config overlay 禁用全部九个 context-files discovery provider，再传入宿主控制的 --system-prompt 文本或文件，继续保留上述六个 --no-* 开关和独立 profile。capability/index.ts:335 的 initializeWithSettings 会在 SDK 发现上下文前读取 disabledProviders；该文件第254行的 filterProviders 会统一过滤发现来源。模型 provider 使用独立名称，避免与这些 discovery provider id 重名。overlay 内容如下：

   ```yaml
   disabledProviders:
     - agents-md
     - claude-md
     - native
     - agents
     - codex
     - claude
     - gemini
     - github
     - opencode
   enabledProviders: []
   includeWorkspaceTree: false
   ```

   启动方式为 bun <已发布OMP的cli.js> --mode rpc --provider <模型provider> --model <模型id> --no-rules --no-skills --no-extensions --no-tools --no-session --no-lsp --no-title --config <宿主overlay文件> --system-prompt <宿主system提示文件>。应用必须自己提供和审计配置与提示来源；不得由交付目录里的文件覆盖这两个参数。显式系统提示仍包含 OMP 生成的环境/footer，因此将这些内容列入实际提示来源，不能宣称字节级上只有部门 manifest。本次 canary 没有注册 host tools；应用接入后仍须复验 host tools 协议可用，不能从本探针推断工具接入已经通过。

   本地复现命令（工作目录 D:\codes\yudao）：python .tmp/omp_context_canary_probe.py。探针固定使用发布版 OMP 和指定 Bun，只连接 127.0.0.1 随机端口、使用虚构密钥、临时 profile 和模拟用户目录，不读取 provider.md；只输出 canary 布尔值和字节统计，不保存请求正文。结果文件为 .tmp/omp_context_canary_result.json。各次运行路径长度可能使字节数略变；本次 JSON 编码后的 system/input/request 统计分别为：默认 12680/285/13105，单独显式 system prompt 3662/285/4087，禁用发现加显式 system prompt 692/285/1117。前两组工作目录与 profile canary=true；最后一组全部 canary=false。用户级 Claude/Codex 的独立正对照分别为 true，隔离配置下均为 false。RPC 对照也收到 ready、agent_end，退出码0，system/input/request 同为692/285/1117。保留该本地请求捕获测试作为接入验收，禁止用真实 provider 代替 canary 测试。

   修复 smoke-report 的误报：当前失败 run 仍可能显示 context_isolated=True，仅凭 manifest 的 excluded 项不能证明真实 system 已隔离。报告须分别陈述 manifest 装配边界、实际 OMP 启动策略，以及该策略对应的请求捕获验证依据；缺少实际验证依据时写明未验证，不得继续把它等价为隔离通过。模型调用失败与隔离结论也应分别保留，不能相互推导。
5. OmpRpcAdapter.abort(session_id) 当前未校验 session id。取消另一个遗留非终态 run 可能中止当前 run。适配器只响应当前 activation 对应的 session 取消，测试错误 session id 不会中断活跃请求。
6. 实际 run_35c3f2c75d4e4292 的产品阶段 seq6/7 都记录 submit_product_spec，同一次 host_tool_call 与 tool_execution_end 疑似重复计为两次工具调用。应按 toolCallId 合并或清楚区分生命周期，工具次数统计必须对应实际执行次数。检查 usage 同样不能因 message_end/agent_end 重复帧而重计。保持简单，不引入新观测系统。

   标识事实：发布版 pi-coding-agent/dist/types/modes/rpc/rpc-types.d.ts:681 的 host_tool_call 同时有 id 与 toolCallId；id 用于 host_tool_result 响应关联，toolCallId 才与 tool_execution_start/update/end 关联。同一次执行以 activation + toolCallId 对齐，不能把宿主请求与 OMP 结束通知统计为两次执行。发布版 pi-ai/dist/types/types.d.ts:779 的 AssistantMessage 没有通用必填消息id，只有可选 responseId 和 timestamp；有 responseId 时可按 activation/provider/model/responseId 辅助关联，不得把 timestamp 或正文hash 当作保证唯一的提供方消息标识。没有 responseId 也必须保留两个内容相同但确实先后发生的模型调用。按第2项只在完整 assistant message_end 入账，可直接避免结束汇总导致的重复计费，不需要为了兼容虚构的必填id引入新协议。

   结束帧事实：packages/agent/src/agent-loop.ts:537 的 newMessages 从本次 prompt 开始；continue 分支第606行重新从空列表开始，第991行将本轮 newMessages 放进 agent_end。它是本次底层 loop 的新增消息汇总，包含此前已发的完整 assistant/toolResult 消息，不是整个部门 session 的全部历史，也不保证包含稍后重试/继续轮次。packages/coding-agent/src/session/agent-session.ts:3156 以 isTerminal 标记是否还会继续；第2384行会延迟公开 agent_end，后续维护轮的结束可能替换待发的旧结束帧。因此不能只依赖最终 agent_end.messages 计算整次 activation。18.1.11 发布类型、发布 cli.js 与当前源码均没有 agent_settled 事件；不要把它当该版本的完成依据。收到 agent_end.isTerminal=false 时继续接收后续事件，按实际协议的终态结束帧处理完成，再由控制层裁定提案是否允许推进业务状态。
7. run_35c3f2c75d4e4292 的工程 activation 超时后只剩 context_assembled 和 run_failed，期间已完成的 host 工具执行、模型输出、usage 随异常丢失。另一次真实 Ask 运行的工程阶段持续数分钟仍只能观察到 context_assembled，原因是整个 invoke 返回后才一次性落盘观察结果。已完成的工具执行应在 activation 仍进行时就能经事件流被观察，并在后续 provider 失败后继续保留；这与失败证据保留是同一条观察边界。采用实际工具执行、完整模型消息、usage 等成熟粒度，不为每个token新增事件；由控制层接收 adapter 提供的观察并记录，adapter 不能直接改变任务状态。让失败 activation 保留已经发生的执行证据和用量，再进入明确停止状态，不在失败路径生成成功提案，也不丢弃失败前的观察结果。用阻塞在第二次模型响应的确定性测试证明第一轮已完成工具/消息/usage在 invoke 返回前可见，随后制造 provider 超时，确认这些事件和用量仍在、停止原因明确，最终结果不会把已发布的观察重复入账。

## 验收边界

- 不修改终态含义：上限是 PAUSED，取消/错误是 FAILED，只有独立 QA release 是 DONE。
- 不通过忽略非法事件来掩盖控制层提交竞态。
- 保留工作区已有改动，不提交 git。
- 另一个 Grok 负责 Web，禁止修改 harness/web/**、harness/__main__.py、harness/tests/test_web.py。
- 真实 provider 凭据只通过环境变量，禁止输出 provider.md 或环境变量值。
- 修复后运行相关测试与完整 harness/tests，并更新中文 jour.md，报告实际证据。
