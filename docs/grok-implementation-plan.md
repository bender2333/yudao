# 给 Grok 的 Yudao 实施计划

## 执行规则

- 以 `docs/loop-system-mvp-design.md` 为架构基线。
- 直接替换旧的 `requirements` 角色命名为 `product`，不增加兼容层。
- 先用 fake adapter 跑通完整状态机，再接 OMP RPC；不要先做长期记忆、知识图谱或动态拓扑。
- 控制层不调用 LLM；LLM 只通过 adapter 提交结构化提案，所有状态提交先经过 schema、权限、版本和前置条件校验。
- 每个阶段结束都必须有可运行的测试和一个可观察的端到端样例。

## Phase 1：领域合同与确定性循环

交付：

- ProductSpec、DeliverySpec、AskRequest、ProductReaction、QAReview、ArtifactRef、ContextManifest；
- SQLite Event Store、事件规范化和内容哈希；
- Orchestrator 状态机及闭合停止原因；
- fake adapter 驱动的三部门循环；
- replay 命令和状态快照检查。

验收：fake 场景覆盖 happy path、ask accept/reply/reject、QA 回退产品/开发、非法工件、max cycles、budget exhausted、aborted、provider blocked。

## Phase 2：部门 session 与上下文边界

交付：

- Product、Engineering、Quality 三种角色的 session factory；
- ContextAssembler：每次激活从 State Projection 重新装配最小上下文；
- 部门工具白名单；
- session 生命周期、取消、超时和激活快照；
- context manifest 和 token 估算事件。

验收：同一 run 中连续返工不会把完整历史 transcript 注入下一部门；旧 spec 只能通过显式历史查询读取，并带 superseded/invalidated 标记。

## Phase 3：OMP RPC 与真实数据流

交付：

- OmpRpcAdapter；
- provider/model 配置映射；
- NDJSON request/response/event 转换；
- 流式输出、tool call、tool result、abort 和 provider 错误映射；
- 真实 workspace 的最小读写工具集。

验收：至少一个本地配置的 OMP provider 完成一次完整三部门 run；所有交接仍由 Yudao Orchestrator 决定；模型无法通过自然语言绕过 QA。

## Phase 4：可视化与观测

交付：

- REST 创建/取消命令和查询 API；
- SSE 事件订阅；
- Run Board、Spec Timeline、Evidence View、Context/Trace View；
- token、cost、latency、tool count、停止原因和返工次数的聚合；
- run 导出和 replay 入口。

验收：浏览器可提交新任务、观察阶段和事件变化、请求取消；命令由控制层处理，UI 不能直接修改权威状态。SSE 断开重连后从上次事件位置继续读取。

## Phase 5：停止审计与经验候选

交付：

- QA reject 后重新从当前状态装配隔离上下文；
- 从已有结构化缺陷、返工和停止事实记录受限的 lesson/经验候选；
- 候选可以追溯到 run、来源事件、spec 及相关检查证据，明确区分观察事实和待验证建议；
- 运行停止后仍可查询、导出、重放上述事实与候选。

验收：候选记录可审计，但不自动进入后续部门上下文、不修改规则或模型；没有证据时不编造经验。首版不增加独立 LLM 蒸馏过程。此范围以用户确认的“只记录可审计 lesson/经验候选”为准。

## 后续阶段，不进入本次实现

- 部门内部循环分型与有界子循环；
- 知识图谱、经验库、长期记忆；
- 异步 durable actor 和跨进程任务队列；
- 运维部门、规则维护部门和 Council；
- Meta-Controller、惊讶驱动检查点、动态拓扑；
- skill 巩固、模型适配器和权重更新。
- 经验候选评估、失效与受治理复用、Scorer 抽样、可继续执行的持久检查点。

## Grok 每阶段必须回报

- 修改的模块和依赖方向；
- 新增或删除的状态、事件和工件类型；
- 可运行的测试命令及结果；
- 一次端到端样例的事件摘要；
- 尚未解决的状态迁移、上下文边界或可观测性缺口。
