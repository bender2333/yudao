# Yudao Loop System MVP 总设计

## 1. 目标

第一阶段交付一个可视化的三部门 Loop System Runtime，让产品、开发、质检在原生循环内通过结构化 spec 交接，分别保有职责与上下文边界，并解决两类核心失效：

1. ReAct 模型把局部完成误判为整个任务完成，导致提前停止；
2. 无关信息、旧版本和长时间局部推理持续堆积，导致上下文容量下降和任务偏离。

第一阶段的成功标准不是“模型说完成”，而是：循环状态、交接依据、验证证据、停止原因和上下文边界都能被运行时机械判定，并在界面中实时看到、在事件日志中重放。

## 2. 范围与非目标

### 本阶段包含

- `product`、`engineering`、`quality` 三个固定部门；
- 版本化、带父链和内容哈希的 spec；
- 工程部发起 `ask`，产品部作出 `accept / reply / reject` 的 `react`；
- 质检独立检查，能够把问题退回产品或工程；
- 每个部门独立 session，跨部门只传允许的结构化工件；
- 事件持久化、状态投影、重放和基础实时可视化；
- 带来源事件和证据的 lesson/经验候选记录，仅供审计与后续评估；
- 通过单次模型适配器接入真实 LLM，模型与工具的循环由 Yudao 驱动；保留同边界的确定性 fake provider 做测试。

### 本阶段不包含

- 运维部门、规则维护部门和其他动态角色；
- 知识图谱、向量库、长期经验库和跨项目记忆；
- 部门内部递归分型、无界子 Agent、动态拓扑；
- 自动修改 prompt、skill、模型权重或生产规则；
- 自动把经验候选注入后续部门上下文、独立 LLM 蒸馏或候选评价系统；
- 复杂的异步分布式调度；
- 以 novelty 或单次运行结果宣称已经实现 RSI。

## 3. 顶层分层

```text
可视化层
  Dashboard / REST 命令与查询 / SSE 事件流

控制层
  Orchestrator / 状态机 / 停止判定 / spec 校验 / 权限与循环上限

状态层
  Event Store / State Projection / Artifact Store / Replay

会话层
  Context Assembler / Department Session / Native Loop

执行层
  Model Provider / Tool Registry / Workspace Runtime
```

依赖只能从上到下读取权威状态；部门只能通过结构化提交请求状态变化。原生循环每次调用模型前装配上下文，状态提交函数不执行网络调用。具体边界与本轮验收见 [原生三部门循环设计](native-loop-design.md)。

## 4. 部门边界

### Product

负责目标、用户价值、范围、约束、验收标准和不可接受结果。只能读取原始任务、公开代码和公开检查，不能修改交付代码，也不能直接放行。

产物是 `ProductSpec`。产品对 `ask` 的响应可以接受方案、补充决策、拒绝方案或改写 spec；每次改变生成新版本，旧版本失效。

### Engineering

负责依据当前有效 `ProductSpec` 修改代码、运行允许的检查并提交 `DeliverySpec`。遇到无法从 spec 推导的取舍，或发现更优方案，必须提交 `AskRequest`，不能静默代替产品决策。

### Quality

负责独立读取当前有效 `ProductSpec`、`DeliverySpec` 和真实代码，亲自运行检查并提交 `QAReview`。它不能读取工程部私有对话，也不能只凭交付单中的测试文字放行。

## 5. 核心循环

```text
CREATED
  -> PRODUCT_SPEC
  -> ENGINEERING
       -> ASK_PRODUCT -> PRODUCT_REACT -> ENGINEERING
       -> DELIVERY
  -> QUALITY
       -> REWORK_PRODUCT -> PRODUCT_SPEC
       -> REWORK_ENGINEERING -> ENGINEERING
       -> RELEASE -> DONE
```

以下事实由控制层决定：

- Agent 自然语言中的“完成”不改变状态；
- 只有合法的 `QAReview.release` 且证据与当前 spec、代码快照绑定，才允许 `DONE`；
- 非法工件留在当前部门并返回字段级错误；
- 部门循环或模型步骤次数耗尽进入 PAUSED，保留事件和工件并要求研发者介入；provider 用量只作只读记录；
- provider 错误、上下文超限和取消进入 FAILED，并记录具体停止原因；
- 触及上限不能自动猜测继续，更不能被解释为任务完成。

## 6. 工件模型

所有跨部门工件都有 `id`、`run_id`、`kind`、`revision`、`parent_hash`、`content_hash`、`issuer`、`status` 和 `created_event_id`。内容哈希只对规范化 payload 计算，不包含时间戳和本地路径。

- `ProductSpec`：目标、需求、边界、约束、验收标准、致命条件、非目标。
- `DeliverySpec`：修改摘要、文件引用、检查名称及退出结果、已知风险、代码树摘要。
- `AskRequest`：问题、背景、候选方案、影响、建议、需要产品决定的字段。
- `ProductReaction`：`accept / reply / reject`、决策说明、是否产生新 spec。
- `QAReview`：检查项、实际证据、缺陷、严重度、退回目标或 release。
- `ArtifactRef`：代码快照、测试回执、日志、报告等外部对象的内容哈希和路径引用。
- `ContextManifest`：本次模型调用实际注入的段落来源、版本、token 估算、截断和排除原因。

每次上下文先带用户 intend 原文和当前工作，再呈现有效 spec、部门规则、工具定义及本部门历史。部门历史跨激活延续，保留过去收到的工作、模型输出和工具结果。当前有效合同优先于旧历史；其他部门的完整私有历史不共享。

参考 OMP 在临近窗口上限时自动压缩该部门的模型输入，摘要保存来源与覆盖范围，原始历史不删除。模型使用摘要和近期完整回合继续工作；固定 intend 原文与当前工作本身无法容纳时明确停止。具体规则见 [D08](requirements/department-history.md)、[D09](requirements/execution-limits.md)和 [D10](requirements/context-compaction.md)。

## 7. 事件与状态主权

Event Store 是唯一事实来源。事件至少记录：`event_id`、`run_id`、`role`、`type`、`parent_event_id`、`state_before`、`state_after`、相关工件哈希、session id、provider/model、工具调用摘要、token/cost/latency、context digest、停止原因和错误信息。

状态投影从事件重建当前 run、当前有效 spec、待处理 ask、活动 session、交付物和 QA 结论。投影损坏时可以删除后从事件重放；模型不会直接写投影。

首版采用本地 SQLite 事件库和 run 目录下的 artifact 文件。SQLite 解决追加、查询和并发写入，artifact 文件保存大对象；不接向量数据库。

## 8. 原生循环与模型适配器的边界

Yudao 控制层拥有任务状态、角色权限、停止条件、spec 校验和最终验收；原生调用驱动管理每一步模型与工具往返。每个部门分别装配上下文和工具权限：

- Product：只读工具和 spec 输出工具；
- Engineering：读、写和公开检查工具；
- Quality：只读、检查和证据采集工具，不提供写工具。

模型适配器只完成一次请求，负责 provider 通信、流式解析、错误和取消，不拥有工具执行或对话历史。Yudao 在每步调用前构造并记录完整上下文，收到部门提交后立即校验和交接。OMP 仅供代码级参考，不作为运行依赖；fake 使用同一模型响应边界。

## 9. 可视化与可观测性

Dashboard 从状态投影和事件流展示事实。浏览器可以提交新任务和取消请求，由控制层处理；界面不能直接修改 spec、投影或最终状态。这与用户确认的“本地 Web 控制台作为首个入口”一致。MVP 需要四个视图：

1. **Run Board**：当前阶段、活动部门、等待原因、循环次数和最终状态；
2. **Spec Timeline**：当前有效 spec、版本因果链、ask/react 请求与响应、失效版本；
3. **Evidence View**：交付文件、检查回执、QA 缺陷、返工目标和 release 证据；
4. **Context/Trace View**：每次模型调用的 context manifest、实际输入工件、注入来源、排除内容、token/耗时/provider、工具调用和停止原因。

后端提供 REST 创建/取消命令、查询和 SSE 实时事件流。首版一次运行一个任务，其他创建请求明确说明已有任务在执行；不引入分布式调度。事件卡片显示结构化摘要，完整 transcript 通过显式查看动作读取，不默认塞入主视图。

## 10. MVP 验收门

- 一个真实任务能够完成 `product -> engineering -> quality -> done`；
- 工程部发起 ask 后，产品的 accept/reply/reject 都能形成可验证的后续路由；
- QA reject 能准确回到 product 或 engineering，QA release 才能结束；
- 模型输出“完成”但没有合法终态工件时，run 不得进入 DONE；
- 任意事件落盘后，重启并 replay 能恢复相同状态；
- 每次 session 激活都能显示 context manifest，并证明没有注入其他部门完整 transcript；
- UI 能看到当前阶段、spec 版本、ask/react 链、证据、停止原因和 token/耗时；
- fake adapter 测试覆盖所有状态迁移、非法工件、循环与步骤上限、provider 错误和取消；
- 原生循环 smoke 完成真实 provider 三部门任务，并能核对每次模型输入、工具结果、检查回执与重放状态。
