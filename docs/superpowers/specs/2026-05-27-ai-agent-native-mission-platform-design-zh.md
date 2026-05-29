# AI/Agent Native Mission Platform 设计

日期：2026-05-27
状态：评审草案

## 1. 产品定位

AI/Agent Native Mission Platform 是一个 Mission-first 的软件与产品演化平台。它不是在传统项目管理工具上叠加 AI，也不是一次性 agent runner。

平台将 Mission 视为一个长期演化的对象。Agent 是主要操作者。人在需要时提供意图、约束、纠偏和审批。平台负责 Mission 状态、执行历史、产物、路由、反馈和学习记录。

核心产品承诺：

```text
将产品/软件意图转化为自主、可观察、可干预的 Mission 生命周期。
```

## 2. 设计原则

1. Mission 优先，而不是任务优先。
   任务或 PR 只是长期 Mission 内部的一个执行单元。

2. 默认 Agent Native。
   Hermes、OpenClaw、Codex、Claude 和其他 agent 不是被附加到项目管理工具上的插件，而是生命周期中的执行参与者。

3. 闭环，而不是线性 SDLC。
   需求、设计、构建、验证、运维和反馈可以相互路由。

4. Spec-driven 小循环，Mission-owned 大循环。
   OpenSpec-style artifact 驱动有边界的 SpecChange 小循环：清晰度、行为契约、实现任务和验证证据。Mission Core 仍然拥有长期生命周期状态、路由历史、反馈、关系和学习。

5. Process Orchestrator 保持业务无关。
   它像管理员一样工作，负责规则、状态、调度、路由和 gate，但不判断业务内容。

6. 小循环用 DAG 表达。
   每个阶段循环由 EvoAgentX-style DAG run 执行。更大的 Mission 生命周期可以包含循环，但每次具体执行都应该是有边界、可追踪的。

7. 产品 UI 必须让 agent 工作可观察。
   Web Console 应展示 Mission 进度、DAG run、节点状态、transcript、tool call、artifact、decision 和 runtime health。

8. v0.1 只保留 policy 和 gate 的接口边界。
   v0.1 不应过度构建企业治理、安全策略或复杂审批流。

## 3. 顶层架构

```text
AI / Agent Native Interaction Layer
  -> Mission Core
  -> OpenSpec-style Spec Artifact Layer
  -> Business-neutral Process Orchestrator
  -> EvoAgentX-style Small-loop Runtime
  -> Runtime Adapter Layer
  -> Multica-style Web Console
  -> Evolution Loop
```

### 3.1 AI / Agent Native Interaction Layer

这一层提供用户和系统入口：

- Hermes
- OpenClaw agent
- Web Console
- Webhook
- Autopilot 或定时触发器
- 未来的 CLI/API client

所有入口都向平台后端提交结构化的 `MissionCommand`。Hermes 或 OpenClaw 中的对话状态是有用上下文，但不是状态源。

### 3.2 Mission Core

Mission Core 负责持久化产品状态：

- `Mission`
- `MissionThread`
- `MissionRelation`
- `MissionEvent`
- `MissionState`
- `MissionGoal`
- `MissionMemory`
- `MissionBacklog`
- `MissionHealth`
- `FeedbackSignal`
- `Artifact`
- `Decision`
- `ApprovalRequest`

`MissionEvent` 是 append-only 事实流。平台应能通过 event、artifact、node result 和 orchestration decision 重建 Mission 为什么从一个循环进入另一个循环。

### 3.3 OpenSpec-style Spec Artifact Layer

OpenSpec 很适合作为 Mission 内部有边界变更工作的参考。它应被用作 artifact grammar，用来表达 proposal、行为 spec、design note、task list、verification scenario 和 archive/sync history。

平台不应该把 OpenSpec 当成 Mission database、Mission 大循环状态机或 scheduler。Mission Core 负责长期状态，Process Orchestrator 负责路由，DAG Runtime 负责执行。OpenSpec-style artifact 定义一个有边界 SpecChange 小循环的行为契约和变更意图。

参考映射：

```text
openspec/specs/              -> canonical behavior specs
openspec/changes/<change>/   -> Mission-bound SpecChange
proposal.md                  -> Mission Brief / Why / What / Impact
specs/**/*.md                -> behavior requirements and scenarios
design.md                    -> Design Note / technical approach
tasks.md                     -> implementation checklist / DAG seed
verify                       -> Verification DAG input
archive/sync                 -> accepted behavior promoted to canonical specs
```

借鉴 OpenSpec 的部分：

- spec-first change proposal
- 行为需求与 scenario-based acceptance
- proposed change 与 canonical spec 的清晰分离
- task checklist 作为实现种子
- 按声明 scenario 进行验证
- 将已接受变更 archive 回稳定 specs

不使用 OpenSpec 替代：

- Mission lifecycle state
- Mission big-loop state machine
- Mission memory and learning
- Mission relation graph
- Process Orchestrator routing
- runtime scheduling
- runtime adapter protocol
- Web Console state
- approval 和 policy boundary

### 3.4 Business-neutral Process Orchestrator

Process Orchestrator 是生命周期管理员。

它消费结构化事实，例如：

- `status`
- `confidence`
- `risk_level`
- `missing_inputs`
- `artifacts`
- `test_result`
- `review_result`
- `approval_required`
- `recommended_next_action`

它决定：

- 继续当前循环
- 路由到另一个循环
- 启动一个 DAG run
- 向用户提出阻塞问题
- 创建 child Mission
- 要求 gate
- 暂停或归档

它不能直接编码产品/业务语义。领域判断属于 agent、evaluator、用户和 artifact。Orchestrator 只根据声明过的事实和配置规则进行路由。

### 3.5 EvoAgentX-style Small-loop Runtime

平台应该将 EvoAgentX 作为有边界 DAG 执行的参考模型，而不是把它当成完整生产平台。

参考映射：

```text
EvoAgentX WorkFlowGraph -> DAGTemplate / DAGRun
EvoAgentX WorkFlowNode  -> DAGNodeTemplate / NodeRun
EvoAgentX Agent         -> RoleAgent / RuntimeAgent
EvoAgentX Action        -> AgentActionRun
EvoAgentX Environment   -> RunMessage / ExecutionTrace
EvoAgentX Evaluator     -> EvaluationRecord / EvolutionLoop
```

借鉴 EvoAgentX 的部分：

- DAG workflow 结构
- Node input/output contract
- Agent/action model
- execution message trace
- evaluator 和 benchmark 概念
- optimizer 思路

不依赖 EvoAgentX 负责：

- 生产级 scheduler
- 持久 Mission 状态
- 权限和 sandbox
- 平台审批系统
- Web Console
- 完整后端生命周期编排

### 3.6 Runtime Adapter Layer

Runtime adapter 将平台 NodeRun 连接到真实 agent runtime。

契约：

```text
RuntimeAdapter.execute(NodeExecutionRequest) -> RuntimeSession
RuntimeSession.messages -> RunMessage stream
RuntimeSession.result -> RunResult
```

初始 adapter 目标：

- `HermesAdapter`：ACP-style runtime protocol
- `OpenClawAdapter`：OpenClaw agent JSON protocol
- `CodexAdapter`：Codex app-server / JSON-RPC style execution
- `ClaudeAdapter`：Claude stream-json execution
- `MCPToolAdapter`：MCP tool execution

ACP 是 runtime adapter 的协议细节，不是平台 API。

### 3.7 Multica-style Web Console

Multica 是 product shell、runtime connection、agent status、task transcript 和 autopilot-style trigger 的参考。

平台应该把这些思路翻译成 Mission-native 对象：

```text
Multica Issue       -> Mission
Multica AgentTask   -> DAGRun / NodeRun / ActionRun
Multica TaskMessage -> RunMessage
Multica ChatSession -> MissionThread
Multica Autopilot   -> MissionTrigger / Autopilot
```

v0.1 Console 主要界面：

- Mission Console
- Mission Detail
- Spec Changes
- Runs and Timeline
- NodeRun transcript
- Artifacts and Decisions
- Approvals
- Agents
- Runtime Targets
- Autopilots
- Templates

UI 应展示 agent 正在做什么、系统为什么路由 Mission、哪个节点产出了哪个 artifact，以及哪里需要人的输入。

### 3.8 Evolution Loop

Evolution Loop 将执行历史转化为平台改进。

```text
Run History
  -> Benchmark Dataset
  -> Evaluator
  -> Optimizer Candidate
  -> Sandbox Replay
  -> Promotion Gate
  -> New Template Version
```

v0.1 应记录足够的数据，让后续演化成为可能。Optimizer candidate 不是生产变更，必须经过 replay、对比和 promotion。

## 4. Mission 生命周期

Mission 有四个递归循环：

```text
1. 需求探索与瓦解
2. 设计与构建
3. 检查与验证
4. 运维与反馈
```

这些循环不是严格线性管道，而是生命周期图。Mission 可以前进、回退、创建 child Mission，或暂停等待输入。

### 4.0 Mission 大循环与 SpecChange 小循环

Mission 是长期运行的大循环。OpenSpec-style artifact 更适合 Mission 内部有边界、一次变更的小循环。

一个 Mission 可以随时间包含多个 SpecChange：

```text
Mission
  -> SpecChange #1
  -> SpecChange #2
  -> Incident SpecChange
  -> Refactor SpecChange
  -> Feedback SpecChange
```

每个 SpecChange 可以使用 OpenSpec-style artifact 来澄清、设计、实现、验证和归档一个有边界的变更。Mission 大循环决定是否创建另一个 SpecChange、路由回需求探索、打开 child Mission、等待反馈或继续运行。

流程：

```text
User intent
  -> MissionCommand
  -> Mission
  -> create or update bounded SpecChange
  -> SpecProposal / scenarios
  -> Exploration DAG for this SpecChange
  -> Design artifact + tasks
  -> Build DAG
  -> Verification scenarios + evidence
  -> Accept / archive / sync
  -> Ops feedback
  -> Mission decides next big-loop step
  -> New SpecChange / child Mission / pause / operate
```

按循环划分的实际作用：

- 需求探索与瓦解：创建 proposal，定义行为范围，编写 scenario
- 设计与构建：把已接受 spec 转成 design note 和 task seed
- 检查与验证：根据声明的 scenario 验证实现
- 运维与反馈：捕捉 runtime drift，并创建后续 spec change

规则：

```text
OpenSpec-style spec artifacts define what should change in one bounded SpecChange.
Mission Core defines what happened across the long-running Mission.
```

循环映射：

| Mission loop | OpenSpec artifact role | Mission output | Route back when |
| --- | --- | --- | --- |
| 需求探索与瓦解 | `proposal.md`、scenario draft、scope delta | Mission Brief、acceptance、assumptions | request unclear、scope too wide、scenario mismatch |
| 设计与构建 | `design.md`、`tasks.md` | implementation plan、patch、branch | spec gap、architecture gap、implementation drift |
| 检查与验证 | delta specs、`verify` evidence | validation verdict、fix request、archive decision | requirement conflict、design gap、bug |
| 运维与反馈 | archive/sync history、follow-up delta spec | retrospective、new SpecChange、learning record | runtime drift、incident、capacity issue |

有边界的 SpecChange 生命周期：

```text
draft
  -> clarified
  -> designed
  -> planned
  -> implemented
  -> verified
  -> accepted
  -> archived_to_canonical_spec
```

失败或反馈路由：

```text
draft / clarified        -> exploration loop
designed / planned       -> design/build loop
implemented / verified   -> verification loop
accepted / archived      -> ops/feedback loop
runtime drift            -> new SpecChange
```

Mission event stream 记录每一次 SpecChange 状态迁移和每一次大循环路由决策。spec 文件为有边界的变更提供人和 agent 都可读的意图、需求、设计、任务和证据。

Mission 大循环状态是独立的：

```text
exploring
  -> changing
  -> verifying
  -> operating
  -> learning
  -> exploring / changing / child_mission / archived
```

大循环不是 DAG，也不是 OpenSpec change。它是一个长期生命周期图，用来编织多个有边界的 DAG run 和 SpecChange 小循环。

### 4.0.1 动态 Workflow 生成边界

OpenSpec-style Markdown 很适合描述一次有边界变更：

- 为什么要做
- 要改变什么行为
- 有哪些 acceptance scenario
- 技术设计是什么
- 要执行哪些 task
- 验证证据是什么
- 是否可以 archive 到 canonical spec

如果一个任务可以一次性完成，一个 Workflow DAG 就能从 proposal/design/tasks/spec scenarios 推进到验证和归档，这类任务非常适合 OpenSpec-style contract。

但 Mission 系统的大循环是动态的。一个 Mission 可能因为验证冲突、运维反馈、用户新输入、架构风险或运行时漂移，重新生成下一个 workflow。这个“下一次 workflow 怎么生成”的问题不属于 OpenSpec 本身，而属于 Mission 层。

职责边界：

```text
OpenSpec-style artifacts:
  describe one bounded SpecChange contract

Mission Planner:
  decide what workflow should be generated next

Process Orchestrator:
  schedule and route that workflow based on policy, state, and events

EvoAgentX-style Runtime:
  execute the generated Workflow DAG
```

Mission Planner 生成下一次 workflow 时应消费：

- `MissionState`
- `MissionGoal`
- `MissionMemory`
- `MissionEvent`
- `FeedbackSignal`
- `SpecChange` 状态和验证结果
- 当前 artifacts
- workflow template registry
- autonomy mode
- policy/gate boundary

它输出：

- `WorkflowIntent`
- `SpecChangeDraft` 或 `SpecChangeUpdate`
- `DAGTemplate` 选择
- `DAGRunPlanSeed`
- `RouteRecommendation`
- `BlockingQuestion` 或 `Assumption`

因此，OpenSpec 可以作为 workflow 生成的上下文和输出格式之一，但不应该成为动态 workflow 生成器。

#### 4.0.1.1 动态性分层（v0.1A 的范围说明）

要点：v0.1A 的"动态性"只存在于**大循环**，**小循环内部是静态的**。

```text
大循环动态（v0.1A 已具备）：
  Mission Planner 每一轮根据 MissionState / FeedbackSignal / verdict
  重新选择下一个 workflow template。
  对应组织类比：跨部门的流程在动态调整方向。

小循环动态（v0.1A 之后，evoagentx 式能力）：
  DAG 内部 node 结构可以根据资源、上下文动态生成与优化。
  对应组织类比："小部门内部根据自己的资源动态调整"。
```

v0.1A 中，DAGRun 是从固定的 WorkflowTemplate **静态物化**出来的，node 集合固定。"小部门内部按资源动态调整"这一层（evoagentx 式 DAG 动态生成/优化）属于 v0.1A 之后的能力，不在 thin slice 范围内。这样划分是有意的 MVP 取舍：先用静态 template 跑通可观察、可回环的大循环，再在小循环内部引入动态性。

### 4.0.2 Mission Planner

Mission Planner 是 Mission 大循环里的轻量“下一步选择器”。它不直接执行任务，也不替代 Process Orchestrator。它的职责是基于当前 Mission 状态，判断下一次应该进入哪个有边界 workflow，选择合适模板，并记录为什么这样选择。

它回答的问题是：

```text
基于当前 Mission 状态，下一次应该生成什么 workflow？
```

而不是：

```text
这个 workflow 应该怎么被执行？
这个节点应该由哪个 runtime 跑？
这个 gate 是否批准？
这个 workflow 内部的完整任务树应该怎样展开？
```

关键边界：

```text
Mission Planner 生成 WorkflowIntent 和选择理由。
WorkflowTemplate / DAGRun 定义一次 bounded workflow 的结构。
DAG 内部的 NodeRun 执行具体需求拆解、设计拆解、任务拆解、测试选择和失败分类。
Process Orchestrator 根据 Planner 输出和 policy/gate 状态调度 DAGRun。
```

因此 Planner 不是完整任务分解器。它可以提出下一次 workflow 的 seed，但不能成为把业务问题、工程设计和执行任务全部压在一起的黑盒。

职责边界：

| Component | Owns | Does not own |
| --- | --- | --- |
| Mission Planner | next workflow intent, situation classification, template selection, planning rationale, bounded SpecChange action | runtime execution, final routing authority, policy approval, detailed task decomposition |
| Process Orchestrator | lifecycle routing, scheduling, gate decision, event routing | business judgment, spec authoring |
| OpenSpec-style artifacts | bounded change contract, scenario, design, tasks, verification evidence | dynamic workflow generation, Mission memory |
| EvoAgentX-style Runtime | execute generated DAG and NodeRuns | decide Mission strategy or own Mission lifecycle |

Mission Planner 输入：

- `MissionState`
- `MissionGoal`
- `MissionMemory`
- `MissionEvent` history
- `MissionRelation`
- `FeedbackSignal`
- current `SpecChange` state
- verification verdict
- operation/incident signals
- artifact index
- available `DAGTemplate`
- autonomy mode
- policy/gate boundary

Mission Planner 输出：

- `WorkflowIntent`
- `WorkflowGenerationReason`
- `SpecChangeDraft`
- `SpecChangeUpdate`
- selected `DAGTemplate`
- `WorkflowTemplateBinding`
- `DAGRunPlanSeed`
- `RequiredInputs`
- `AssumptionSet`
- `RiskSet`
- `RouteRecommendation`

生成下一次 workflow 的基本流程：

```text
collect_mission_context
  -> classify_current_situation
  -> decide_next_loop
  -> decide_whether_existing_specchange_can_continue
  -> create_or_update_specchange
  -> select_workflow_template
  -> bind_template_inputs
  -> produce_dag_run_plan_seed
  -> emit_planning_event
```

`classify_current_situation` 至少需要识别：

- requirement unclear
- spec gap
- architecture/design gap
- implementation defect
- verification contradiction
- runtime drift
- incident
- capacity/performance issue
- user correction
- stable progress

这意味着 Mission Planner 可以重复生成 workflow，但每一次生成的 workflow 都应该是有边界的：

```text
Mission 大循环负责连续性。
SpecChange 负责一次变更的契约。
DAGRun 负责一次有边界执行。
NodeRun 负责具体拆解、执行、验证和失败分类的最小控制单元。
```

Planner 只决定“下一轮该跑什么类型的 workflow”。具体“这一轮 workflow 内部如何把需求、设计、实现和验证拆成可执行任务”，由对应 DAG 的节点完成，并通过 artifact、RunMessage 和 route recommendation 写回 Mission。

### 4.0.3 Workflow Template Registry

Mission Planner 不应该自由生成任意 workflow。v0.1 应采用 `WorkflowTemplate Registry`：Planner 根据当前状态选择、参数化或有限组合已有模板。

这能让系统同时具备动态性和可控性：

```text
动态性：Mission Planner 可以根据反馈生成下一次 workflow。
可控性：workflow 主要来自已知模板，而不是任意生成。
```

v0.1 模板类型：

- `ExplorationWorkflow`
- `SpecChangeDraftWorkflow`
- `DesignWorkflow`
- `ImplementationWorkflow`
- `FixWorkflow`
- `VerificationWorkflow`
- `IncidentWorkflow`
- `RollbackWorkflow`
- `RetrospectiveWorkflow`
- `EvolutionCandidateWorkflow`

模板元数据：

```text
WorkflowTemplate {
  id
  name
  loop_type
  trigger_conditions
  required_inputs
  produced_artifacts
  node_templates
  default_agent_roles
  runtime_requirements
  risk_level
  gate_policy_ref
  version
}
```

Planner 选择模板的流程：

```text
classify_current_situation
  -> match_trigger_conditions
  -> rank_candidate_templates
  -> check_required_inputs
  -> bind_specchange_or_create_draft
  -> bind_template_inputs
  -> produce_DAGRunPlanSeed
```

允许的动态能力：

- 选择模板
- 填充模板参数
- 根据 SpecChange 裁剪模板级节点集合
- 声明 runtime/tool availability 需求
- 根据 autonomy mode 决定是否提出 blocking question
- 为 DAG 内部节点提供任务拆解上下文

v0.1 不允许的能力：

- 无模板自由生成完整 workflow
- 在 Planner 内部生成完整业务任务树
- 自动引入未注册 runtime
- 自动放宽 gate/policy
- 自动把 optimizer candidate 提升为生产模板
- 在没有 Mission event 记录的情况下修改 workflow

当 Planner 找不到合适模板时：

```text
if missing_inputs:
  ask blocking question

elif no_template_match:
  create WorkflowTemplateProposal
  route_to = human_gate / design_loop

elif high_risk:
  route_to = gate

else:
  select best effort template with recorded assumptions
```

这意味着 v0.1 的“动态 workflow 生成”本质上是：

```text
template selection + parameter binding + bounded node composition
```

而不是完全开放的 workflow synthesis。

### 4.0.4 Mission Big-loop State Model

Mission 大循环需要自己的长期状态模型。它不应该由 OpenSpec 的 change 状态推导出来，因为 OpenSpec 关注一次有边界变更，而 Mission 关注持续演化。

核心对象：

```text
MissionState
MissionGoal
MissionMemory
MissionBacklog
FeedbackSignal
MissionHealth
MissionRelation
EvolutionRecord
```

`MissionState` 表示 Mission 当前处于什么生命周期位置：

```text
exploring
changing
verifying
operating
learning
paused
archived
```

状态不是线性流。它可以根据反馈和验证结果回到任意相关阶段：

```text
operating -> learning -> exploring
operating -> changing
verifying -> exploring
verifying -> changing
learning -> child_mission
paused -> exploring / changing / operating
```

`MissionMemory` 保存长期上下文：

- 已确认的目标和非目标
- 长期约束
- 用户偏好
- 架构决策
- 失败模式
- 历史假设
- 重要反馈
- 运行时教训
- 已关闭和未关闭的风险

`MissionBacklog` 保存暂不进入当前 SpecChange 的事项：

- follow-up idea
- deferred improvement
- unresolved question
- tech debt
- operational issue
- evolution candidate
- child mission proposal

`FeedbackSignal` 是运维和外部世界进入 Mission 大循环的标准输入：

```text
FeedbackSignal {
  source
  signal_type
  severity
  evidence
  related_artifact
  related_specchange
  suggested_classification
  received_at
}
```

常见 `signal_type`：

- user_feedback
- production_incident
- metric_regression
- test_flake
- performance_degradation
- security_alert
- requirement_change
- usage_observation
- agent_failure

Mission Planner 使用这些长期对象决定下一次 workflow，而不是只看当前 OpenSpec change。

原则：

```text
SpecChange explains the bounded work.
MissionState explains where the long-running mission is.
MissionMemory explains why future workflows should be generated differently.
FeedbackSignal explains why the big loop should move again.
```

### 4.0.5 Mission Planner Decision Matrix

Mission Planner 不应该是黑盒。每次生成 workflow 时，都必须产出可审计的 `WorkflowGenerationReason`。

`WorkflowGenerationReason` 至少包含：

- current situation classification
- evidence
- selected workflow template
- rejected alternatives
- SpecChange action
- assumptions
- missing inputs
- gate recommendation
- expected outputs

基础决策矩阵：

| Situation | Next loop | Workflow template | SpecChange action | Gate behavior |
| --- | --- | --- | --- | --- |
| vague request / missing acceptance | exploring | `ExplorationWorkflow` | create draft | ask only blocking questions |
| clear bounded change | changing | `SpecChangeDraftWorkflow` + `DesignWorkflow` | create or update | no gate unless risk is high |
| design gap / architecture gap | changing | `DesignWorkflow` | update current SpecChange | gate if architecture/core boundary |
| implementation defect | changing | `FixWorkflow` | continue current SpecChange | no gate by default |
| verification contradiction | exploring | `ExplorationWorkflow` | revise SpecChange | ask or gate depending on autonomy |
| test failure with clear fix | verifying/changing | `FixWorkflow` -> `VerificationWorkflow` | continue current SpecChange | no gate by default |
| runtime drift | operating/learning | `RetrospectiveWorkflow` -> `SpecChangeDraftWorkflow` | create follow-up SpecChange | gate if production risk |
| production incident | operating/changing | `IncidentWorkflow` | create Incident SpecChange | gate for rollback/high-risk actions |
| stable outcome | learning | `RetrospectiveWorkflow` | archive accepted SpecChange | no gate unless promotion changes template |
| no template match | exploring/changing | `WorkflowTemplateProposal` | create proposal | gate required |

Planner 输出不直接执行。它只是提交计划：

```text
MissionPlannerRun
  -> WorkflowIntent
  -> WorkflowGenerationReason
  -> DAGRunPlanSeed
  -> OrchestrationDecision request
```

随后由 Process Orchestrator 决定是否调度、询问、gate、暂停或路由。

这个矩阵是 v0.1 的初始策略，不是固定业务规则。未来可以通过 EvaluationRecord、ReplayRun 和 TemplateVersion 演化。

### 4.0.6 Mission Event Stream and Projections

Mission 大循环必须由 append-only event stream 驱动。数据库里的当前状态只是投影，不是唯一事实来源。

原则：

```text
Commands request change.
Events record facts.
Projections support reading.
Planner uses projections plus event history.
Orchestrator writes routing decisions as events.
```

标准事件结构：

```text
MissionEvent {
  id
  mission_id
  event_type
  actor_type
  actor_id
  occurred_at
  causation_id
  correlation_id
  loop
  specchange_id
  dag_run_id
  node_run_id
  payload
}
```

核心事件类型：

- `MissionCreated`
- `MissionStateChanged`
- `MissionGoalUpdated`
- `MissionMemoryRecorded`
- `MissionBacklogItemAdded`
- `FeedbackSignalReceived`
- `SpecChangeCreated`
- `SpecChangeUpdated`
- `SpecChangeStateChanged`
- `WorkflowPlanned`
- `WorkflowTemplateSelected`
- `DAGRunScheduled`
- `DAGRunStarted`
- `DAGRunCompleted`
- `NodeRunStarted`
- `NodeRunCompleted`
- `NodeRunFailed`
- `ArtifactRecorded`
- `DecisionRecorded`
- `GateRequested`
- `GateDecided`
- `RouteDecided`
- `EvaluationRecorded`

典型事件链：

```text
MissionCommandReceived
  -> MissionPlannerRunStarted
  -> WorkflowPlanned
  -> WorkflowTemplateSelected
  -> SpecChangeCreated / SpecChangeUpdated
  -> DAGRunScheduled
  -> NodeRunStarted
  -> ArtifactRecorded
  -> NodeRunCompleted
  -> DAGRunCompleted
  -> RouteDecided
  -> MissionStateChanged
```

投影模型：

| Projection | Purpose |
| --- | --- |
| `MissionSummaryView` | Mission 列表、状态、风险、下一步 |
| `MissionTimelineView` | 用户可读时间线 |
| `MissionPlannerContextView` | Planner 下一次决策输入 |
| `SpecChangeView` | 当前 change 的 proposal/design/tasks/scenario 状态 |
| `RunTraceView` | DAGRun、NodeRun、ActionRun、ToolCall 追踪 |
| `FeedbackInboxView` | 运维和用户反馈入口 |
| `ApprovalInboxView` | gate 请求和决策 |
| `BacklogView` | follow-up、延期事项、child mission proposal |
| `EvolutionDatasetView` | replay、evaluation、optimizer 的训练/评估样本 |

事件流和投影的边界：

```text
Event Stream:
  durable fact history, append-only, replayable

Projection:
  query optimization, UI state, planner context, rebuildable
```

v0.1 不需要完整事件溯源基础设施，但必须保持这些约束：

- 所有 workflow 生成都有 `WorkflowPlanned`
- 所有路由都有 `RouteDecided`
- 所有 gate 都有 request/decision event
- 所有 artifact 都有关联 mission/specchange/run/node
- 所有自动假设都必须记录
- projection 可以重建，不应该成为唯一事实来源

这也是平台未来自举和演化的基础：没有事件流，就没有 replay；没有 replay，就没有可靠的 Evolution Loop。

### 4.1 需求探索与瓦解

目标：将模糊输入转化为可执行的 Mission 结构。

输入：

- 自然语言请求
- Hermes/OpenClaw 对话
- issue 或 PR feedback
- log 和 screenshot
- repository context
- operations alert

输出：

- `MissionBrief`
- `QuestionSet`
- `AssumptionSet`
- `ScopeBoundary`
- `AcceptanceCriteria`
- `ChildMissionProposal`
- OpenSpec-style `SpecChange` draft
- requirement scenarios

自循环条件：

- 存在阻塞问题
- 缺少必要上下文
- 假设置信度低
- scope 不清晰
- acceptance criteria 不完整
- dependency 不清晰

推进规则：

```text
readiness + autonomy_mode -> ask / proceed / gate / pause
```

默认自主模式下，系统只询问必要阻塞问题。非阻塞假设会被记录，Mission 可以继续推进。

OpenSpec 作用：

- 创建或更新 `proposal.md`
- 在 change 下草拟行为需求 scenario
- 识别用户请求行为与 canonical specs 之间的差距
- 将已确认澄清转化为 Mission-bound `SpecChange`

### 4.2 设计与构建

目标：将 Mission Brief 转化为设计、计划、实现和 patch artifact。

输入：

- `MissionBrief`
- `ScopeBoundary`
- `AssumptionSet`
- `RiskSet`
- `AcceptanceCriteria`
- repository 或 service context
- autonomy mode 和 policy boundary

典型 DAG run：

- `DesignRun`
- `PlanningRun`
- `ImplementationRun`
- `FixRun`

输出：

- `DesignNote`
- `ImplementationPlan`
- `PatchSet`
- `Branch`
- `ChangedFilesSummary`
- `LocalBuildResult`
- `PRDraft`
- `ReleaseNotesDraft`
- updated `design.md`
- updated `tasks.md`

如果实现过程发现需求或 scope 假设无效，orchestrator 可以将 Mission 路由回 需求探索与瓦解。

OpenSpec 作用：

- 使用 `design.md` 作为技术方案 artifact
- 使用 `tasks.md` 作为 DAG node 或 implementation checklist 的种子
- 让实现持续对齐已声明的 scenario
- 在验证接受之前，不把变更写入 canonical specs

### 4.3 检查与验证

目标：测试、审查并分类结果。验证失败不应全部路由到同一个地方。

核心失败路由：

```text
if requirement_unclear or acceptance_conflict:
  return_to = explore_decompose

elif boundary_gap or architecture_gap or design_incomplete:
  return_to = design_architecture

elif implementation_bug or test_failure_with_clear_fix:
  return_to = implementation_fix

elif high_risk or unclassified_conflict:
  return_to = human_gate

else:
  proceed_to = ops_feedback / release
```

典型 DAG node：

- `test_select`
- `test_run`
- `review_diff`
- `acceptance_check`
- `failure_classify`
- `verification_verdict`

关键设计点是三向分类：

1. 需求不清或验证矛盾 -> 需求探索与瓦解
2. 边界、架构或设计缺口 -> 设计与构建
3. 功能 bug 或实现缺陷 -> implementation fix path

OpenSpec 作用：

- 按 requirement scenario 验证代码和测试
- 分类失败到底是 spec ambiguity、design gap 还是 implementation defect
- 将验证证据记录到对应 `SpecChange`
- 只有验证通过后才提升 accepted behavior

### 4.4 运维与反馈

目标：让运行时信号成为 Mission 演化的一部分。

运维不是生命周期终点。它可以创建新的 Mission 输入，重新打开当前 Mission 循环，或产出演化记录。

典型 DAG run：

- `ReleaseRun`
- `PostDeployVerifyRun`
- `IncidentRun`
- `RollbackRun`
- `RetrospectiveRun`

路由示例：

- requirement changed -> 需求探索与瓦解
- architecture、boundary 或 capacity issue -> 设计与构建
- 明确 implementation defect -> implementation fix path
- production incident -> new Incident Mission
- high-risk release 或 rollback -> gate
- stable outcome -> learning/evaluation record

OpenSpec 作用：

- 用运行时反馈创建或更新 `SpecChange`
- 将生产中学到的行为捕获为未来 scenario
- 将已接受变更 archive 到 canonical specs
- 保持 spec history 与 Mission event、retrospective 的连接

## 5. DAG 与 Node 粒度

更大的 Mission 生命周期可以包含循环，但每个 loop execution 应该是有边界的 DAG。

层级：

```text
Mission
  Loop
    DAGRun
      NodeRun
        AgentActionRun
          ToolCall
```

`NodeRun` 是最小控制单元。

NodeRun 可以：

- refine requirements within the bounded workflow
- decompose design or implementation tasks
- select tests or verification checks
- retry
- skip
- insert supplemental node
- trigger gate
- route to another node
- write artifact
- classify failure
- emit route recommendation

规则：

```text
Mission Planner selects the next workflow type.
DAGRun owns one bounded workflow execution.
NodeRun owns detailed decomposition inside that bounded workflow.
NodeRun outputs route_recommendation.
Process Orchestrator makes the actual routing decision.
```

这种分离能避免 agent/runtime execution 变成生命周期权威。

这也意味着任务分解不应集中在 Mission Planner。需求澄清发生在 `ExplorationWorkflow` 的节点内；设计拆解发生在 `DesignWorkflow` 的节点内；实现任务拆解发生在 `ImplementationWorkflow` 或 `FixWorkflow` 的节点内；测试选择和失败归因发生在 `VerificationWorkflow` 的节点内。Planner 只负责选择下一次进入哪个 workflow，并说明选择依据。

## 6. 自主模式

平台在 loop 和 node 级别预留四种自主模式：

```text
1. 人工主导
2. 半自主推荐
3. 默认自主
4. 全自主
```

v0.1 应实现并默认使用模式 3：默认自主。

默认自主行为：

- readiness 充分时继续推进
- 只询问阻塞问题
- 记录非阻塞假设
- 只有 policy boundary 或 risk threshold 要求时才 gate
- 所有 decision 都在 Mission event 中可见

模式 1、2、4 应在配置中表示出来，使模型未来可以演化，而不用改变核心数据结构。

### 6.1 全自主模式与 Autonomous Mission Driver

模式 4（全自主）是"黑盒全自动"用户体验的基础：用户只在入口提交一句意图（例如"做一个儿童故事网站"）并选择 `full_autonomous`，之后**不再手动触发任何一步**，系统自动把大循环转起来，直到目标达成或遇到必须停下的情况。

这正是"大循环是自己要研发的，负责流程管控和观察"的落地：大循环不碰具体任务，但它要自己驱动流程、自己判断是否达标。

驱动器（Autonomous Mission Driver）行为：

```text
loop:
  1. plan-next        -> Mission Planner 选下一个 workflow
  2. 物化 + 执行 DAGRun -> Orchestrator 调度，runtime 执行
  3. route            -> RouteDecided + MissionStateChanged
  4. GoalCheck        -> 判断 Mission 目标是否达成
  5. 决定:
       - 目标达成        -> 结束(succeeded)
       - 遇 blocking question / gate -> 暂停(blocked)，等人介入
       - 达 max 迭代上限  -> 暂停(exhausted)，防死循环
       - 否则           -> 回到 1，继续下一轮
```

GoalCheck（目标达成判定）是大循环"观察"职责的一部分，业务中立：

```text
GoalCheck 消费结构化事实，不做业务内容判断：
  - 最近一次 verification verdict 是否 pass
  - 声明的 acceptance criteria 是否都有对应 evidence artifact
  - 若 Mission 含 deploy 目标：部署健康探活是否 healthy、产物是否可访问
判定结果:
  achieved | not_achieved | blocked
```

关键边界：

```text
驱动器只编排大循环节奏，不替代 Planner 选择、不替代 Orchestrator 调度、不做业务判断。
GoalCheck 只读结构化事实(verdict / evidence / health)，acceptance criteria 的内容由 DAG node 产出。
max 迭代上限是必需的安全阀，防止无限自动循环。
full_autonomous 下仍保留 gate 接口:命中 gate 即暂停为 blocked，不自动越过。
```

## 7. Policy 与 Gate 边界

v0.1 应保留 policy 和 gate 接口，但不实现完整治理系统。

要做：

- 保留 gate interface
- 在 loop 或 node 上存储 autonomy mode
- 记录 gate 被触发的原因
- 允许 runtime 和 node output 请求 approval
- 将 routing decision 作为 event 审计

不做：

- 现在就构建企业审批流
- 硬编码所有安全策略
- 在 orchestrator 中编码业务语义
- 把每个 gate 都变成人工 review
- 让完整治理阻塞 MVP

最小契约：

```text
GateRequest {
  mission_id
  loop
  node_run_id
  reason
  risk_level
  autonomy_mode
  required_decision
  recommended_action
}

GateDecision {
  approve | reject | ask | route | pause
  decided_by
  rationale
}
```

## 8. 核心数据模型

### Mission Core

- `Mission`
- `MissionThread`
- `MissionRelation`
- `MissionEvent`
- `Artifact`
- `Decision`
- `ApprovalRequest`

### Spec Artifacts

- `SpecChange`
- `SpecProposal`
- `BehaviorSpec`
- `SpecScenario`
- `SpecDesign`
- `SpecTask`
- `SpecVerification`
- `SpecArchiveRecord`

### Runtime Execution

- `DAGTemplate`
- `DAGNodeTemplate`
- `WorkflowTemplate`
- `WorkflowTemplateProposal`
- `WorkflowTemplateVersion`
- `NodeTemplate`
- `DAGRun`
- `NodeRun`
- `ActionRun`
- `ToolCall`
- `RunMessage`

### Orchestration

- `Policy`
- `AutonomyModeConfig`
- `OrchestrationDecision`
- `LoopState`
- `RouteRule`
- `GatePolicy`
- `RetryPolicy`
- `MissionPlannerRun`
- `WorkflowIntent`
- `WorkflowGenerationReason`
- `DAGRunPlanSeed`
- `DAGRunPlan`
- `WorkflowTemplateBinding`

### Agent and Runtime Config

- `AgentRole`
- `AgentProfile`
- `Skill`
- `Plugin`
- `RuntimeTarget`
- `RuntimeCredentialRef`
- `ToolPolicy`

### Product Shell

- `MissionCommand`
- `MissionTrigger`
- `Notification`
- `InboxItem`
- `SavedView`
- `TimelineCursor`
- `UserPreference`
- `BacklogView`
- `FeedbackInbox`

### Evolution

- `EvaluationRecord`
- `MetricSnapshot`
- `BenchmarkSample`
- `EvolutionCandidate`
- `ReplayRun`
- `TemplateVersion`
- `PromotionDecision`

## 9. v0.1 API 面

API 分组：

- Command API
- Mission API
- Spec API
- Runtime API
- Orchestrator API
- Realtime API
- Config API

原则：

```text
Commands mutate.
Queries project.
Events explain.
```

所有外部入口都应提交 `MissionCommand`。

状态源：

```text
Mission Platform Backend
```

不是状态源：

- Hermes conversation
- OpenClaw conversation
- Web UI local state
- webhook source

## 10. v0.1 Web Console

Web Console 的产品体验可以参考 Multica，但数据模型必须是 Mission-native。

主要页面：

1. Mission Console
   展示 Mission 列表、status、loop、risk、next action 和 owner agent。

2. Mission Detail
   展示 brief、scope、acceptance、assumption、decision、artifact 和 related Mission。

3. Spec Changes
   展示 proposal、delta specs、scenarios、design、tasks、verification evidence 和 archive status。

4. Runs and Timeline
   展示 DAGRun、NodeRun、ActionRun、message、tool call、failure 和 route decision。

5. Approvals
   展示 pending gate request 和 decision history。

6. Agents
   配置 role agent、skill、plugin 和 environment assumption。

7. Runtime Targets
   配置 Hermes、OpenClaw、Codex、Claude、MCP、credential 和 connection health。

8. Autopilots
   配置 webhook/schedule/ops trigger，用于创建或更新 Mission。

9. Templates
   管理 DAG template 和 template version。

## 11. v0.1 路线图

### 11.1 v0.1A：Full-loop Thin Slice

目标：证明闭环能跑通。

必要流程：

```text
Hermes/OpenClaw entry
  -> Mission
  -> exploration DAG
  -> orchestrator routing
  -> design/build DAG
  -> verification DAG
  -> feedback record
  -> Web Console visibility
  -> EvaluationRecord
```

验收：

- entry agent 创建 `MissionThread` 和 `Mission`
- exploration DAG 输出 brief、question、assumption 和 acceptance criteria
- exploration DAG 创建或更新 Mission-bound SpecChange
- 默认自主模式询问必要问题或自动推进
- design/build DAG 输出 plan、patch、design artifact 和 task artifact
- verification DAG 执行三向路由
- verification 按 spec scenario 检查实现
- Web Console 展示 Mission、DAGRun、NodeRun 和 transcript
- 所有 run 和 node 生成 event、artifact、spec evidence 和 evaluation record

#### 11.1.1 v0.1A Implementation Slice

v0.1A 的目标不是做完整平台，而是跑通一条可观察、可审计、可回环的 Mission thin slice。

最小用户路径：

```text
Web Console / Hermes / OpenClaw
  -> submit MissionCommand
  -> create Mission
  -> append MissionCreated event
  -> Mission Planner generates WorkflowIntent and WorkflowGenerationReason
  -> create SpecChange draft
  -> select WorkflowTemplate
  -> produce DAGRunPlanSeed
  -> Orchestrator schedules DAGRun
  -> execute NodeRuns with mocked or simple runtime adapter
  -> record Artifacts and RunMessages
  -> verification node emits verdict
  -> Orchestrator writes RouteDecided
  -> MissionState changes
  -> Web Console shows timeline and trace
  -> FeedbackSignal can trigger next workflow
```

第一批核心实体：

- `Mission`
- `MissionState`
- `MissionEvent`
- `MissionMemory`
- `SpecChange`
- `WorkflowTemplate`
- `MissionPlannerRun`
- `DAGRun`
- `NodeRun`
- `Artifact`
- `FeedbackSignal`
- `EvaluationRecord`

第一批 API：

| API | Purpose |
| --- | --- |
| `POST /missions` | create Mission from entry command |
| `POST /missions/{id}/commands` | submit MissionCommand |
| `POST /missions/{id}/plan-next` | run Mission Planner |
| `POST /dag-runs` | schedule DAGRun from Orchestrator-materialized DAGRunPlan |
| `POST /events` | append MissionEvent |
| `GET /missions` | list MissionSummaryView |
| `GET /missions/{id}` | read Mission detail projection |
| `GET /missions/{id}/timeline` | read MissionTimelineView |
| `GET /dag-runs/{id}` | read run/node trace |
| `POST /missions/{id}/feedback` | submit FeedbackSignal |

第一批 Web Console 页面：

1. `Mission List`
   展示 Mission、state、risk、next action、last event。

2. `Mission Detail + Timeline`
   展示目标、当前 state、SpecChange、artifact、decision、event timeline。

3. `Run / Node Trace`
   展示 DAGRun、NodeRun、ActionRun、RunMessage、Artifact、verification verdict。

第一批 WorkflowTemplate：

- `ExplorationWorkflow`
- `SpecChangeDraftWorkflow`
- `DesignWorkflow`
- `ImplementationWorkflow`
- `VerificationWorkflow`
- `FixWorkflow`
- `RetrospectiveWorkflow`

v0.1A 可以用模拟 runtime adapter 起步：

```text
MockRuntimeAdapter:
  accepts NodeExecutionRequest
  emits RunMessages
  writes deterministic Artifact
  returns RunResult
```

但接口必须按真实 runtime adapter 设计，后续可替换为 Hermes/OpenClaw/Codex/Claude。

v0.1A 验收标准：

- 能从入口创建 Mission
- Mission 创建写入 event stream
- Planner 能生成 `WorkflowIntent`、`WorkflowGenerationReason` 和 `DAGRunPlanSeed`
- Planner 能选择 WorkflowTemplate
- Orchestrator 能将 `DAGRunPlanSeed` 物化为可调度的 `DAGRunPlan` 或 `DAGRun`
- 能创建或更新 SpecChange
- 能执行至少一个 DAGRun
- DAGRun 至少包含 exploration、implementation、verification 三类 NodeRun
- NodeRun 能写入 RunMessage 和 Artifact
- verification node 能输出 pass/fail/verdict
- Orchestrator 能根据 verdict 写入 `RouteDecided`
- 失败能路由到 exploration/fix/design 之一
- Web Console 能展示 Mission timeline 和 run trace
- FeedbackSignal 能触发下一次 planning
- 所有自动假设都记录为 event/artifact

v0.1A 明确不做：

- 多租户
- 完整权限
- 真实生产部署
- 完整 agent marketplace
- 自主 optimizer promotion
- 复杂审批流
- 完整 OpenSpec CLI 兼容
- 多 runtime 并发调度优化

### 11.2 v0.1B：Self-bootstrap

#### 11.2.0 v0.1A 自举接缝预埋

自举逻辑全部留在 v0.1B，但 v0.1A 必须在正确的接缝处预留扩展点，否则 v0.1B 会被迫回头修改 v0.1A 的核心数据模型和事件结构。接缝分两档：

A 档 — Mission 模型级接缝，不预埋则 v0.1B 必须回改 Mission 模型和大量事件，**必须在 v0.1A 预埋**：

```text
1. Project / projectId 抽象（必须）
   Mission 关联 projectId + repoRoot。
   v0.1A 内置一条默认 SelfProject 记录（指向平台自身 repo）。
   自举的定义就是把平台自己的 repo 注册为 SelfProject，
   不预埋则 v0.1B 要回改 Mission 模型和所有相关事件。
```

A- 档 — 事件级接缝，回改量较小，**v0.1A 可选/可推迟到 v0.1B**：

```text
2. EvaluationRecord 落库（可选）
   每个 DAGRun 完成时 append 一条 EvaluationRecorded 事件。
   字段可以最简，但若做则必须真实写入事件流。
   没有事件流就没有 replay，没有 replay 就没有 Evolution Loop。
   推迟代价：v0.1B 补一条事件类型 + 在 DAGRun 完成处补一次 append，
   不污染 Mission 模型，回改量小。

3. RouteDecided.gateRequired 字段（可选）
   RouteDecided 事件携带 gateRequired: boolean。
   v0.1A 恒为 false；v0.1B 才填充 core/security/runtime 变更触发 gate 的逻辑。
   推迟代价：v0.1B 给 RouteDecided 加一个布尔字段，
   旧事件按缺省 false 解读即可，回改量小。
```

B 档 — 流程层，v0.1B 改 runner/adapter 即可，**不回改数据模型，可留 v0.1B**：

```text
4. workspace 来自 project.repoRoot
   v0.1A 硬编码 .mission-workspaces/<missionId>/。
   只要 A-1 的 projectId 预埋了，v0.1B 改 adapter 取 project.repoRoot 即可。

5. OpenSpec artifact 落盘为 openspec/changes/<change>/ 结构
   v0.1A 由 fake runner 写 game 文件即可。
   自举需要 proposal/design/tasks 落成 OpenSpec 结构，
   这是 runner prompt + artifact filePath 的事，不动核心模型。
```

结论：接缝 1（projectId）必须在 v0.1A 预埋（污染 Mission 模型，回改贵）；接缝 2、3 为事件级，v0.1A 可选、推迟到 v0.1B 回改量小；B 档 2 个留 v0.1B 纯增量接上。

#### 11.2.1 v0.1B 目标

定义：

```text
Platform registers its own repo as Self Project.
It uses its own Mission, DAG, Node, Web Console, and EvaluationRecord systems to develop itself.
```

验收：

- self repo 已注册
- 至少一个平台 feature 通过 Mission 发起
- DAG/Node execution 修改平台代码
- 生成 patch 或 PR draft
- verification failure 能正确路由
- core/security/runtime 变更触发 gate
- bootstrap 产出 retrospective artifact 和 evolution candidate
- 已接受的 bootstrap 变更可以 archive 回 canonical specs

## 12. v0.1 明确不做项

v0.1 不尝试完整解决：

- enterprise governance
- deep permission matrix
- advanced security sandbox
- organization-wide workflow customization
- complete optimizer-driven auto-evolution
- full project management replacement
- complex billing, tenancy, or marketplace
- detailed business-domain rule authoring

这些领域只在必要时保留接口和扩展点，但不应主导初始架构。

## 13. 实现计划前确认项

这些不是未解决的架构缺口，而是进入实现计划前需要确认的默认选择。

v0.1 planning 推荐默认值：

1. 先做 local-first developer platform service，未来再演化为 multi-user service。
2. Hermes 和 OpenClaw 都通过同一个 `MissionCommand` contract 作为一等入口 agent。
3. 先实现一个 runtime adapter，再通过同一 adapter interface 增加第二个。
4. self-bootstrap 先限定为当前平台 repo，同时保持 `SelfProject` model 泛化。
5. v0.1A 最小 Web Console 包含 Mission Detail、Runs/Timeline、Node transcript、Agents 和 Runtime Targets。
