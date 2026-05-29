# v0.1A Full-loop Thin Slice — 修订版实施计划

> **修订日期：** 2026-05-29
> **修订原因：** 基于 review 建议，调整任务边界、补充 situation classification 完整测试、拆分 Orchestrator 任务、添加验收测试
> **关联文档：** 原计划 `2026-05-28-v01a-full-loop-thin-slice.md`；设计 `../specs/2026-05-27-ai-agent-native-mission-platform-design-zh.md`

---

## 变更摘要

相比原始计划（2026-05-28），本版本做了以下调整：

1. **Task 6 拆分** — Orchestrator 职责过重，拆分为 6A（Materialization）、6B（Execution Loop）、6C（Route Decision）
2. **Task 5B 新增** — 补充完整的 situation classification 矩阵测试（原计划只覆盖 3 种）
3. **Task 11 新增** — FeedbackSignal 端到端循环测试
4. **Task 12 新增** — v0.1A 验收集成测试（儿童故事游戏场景）
5. **职责边界澄清** — Mission ↔ SpecChange 状态同步规则明确
6. **RuntimeRouter 选择逻辑** — 明确选择优先级与错误处理
7. **自举范围澄清** — 明确 v0.1A 与 v0.1B 的自举能力边界
8. **Task 2B 新增（自举接缝预埋）** — A 档 3 个接缝在 v0.1A 预埋字段级骨架：Mission.projectId/repoRoot + 默认 SelfProject、EvaluationRecord 落库、RouteDecided.gateRequired
9. **Task 6D 新增（全自动大循环）** — Autonomous Mission Driver + GoalCheck + DeployWorkflow/deploy 节点 + ops 角色，支撑黑盒全自动验收。v0.1A 只实装 full_autonomous 一种自主模式，其余三种保留配置位不实装逻辑（与设计稿 6.1 一致）。集成测试改为真黑盒 ATDD：用户只提交意图，系统自动产出可访问故事站。

---

## 架构职责边界（修订）

### Mission Planner 职责边界

```text
Planner 做：
  - 分类当前 situation
  - 从 WorkflowTemplate Registry 选择 templateId
  - 产出 WorkflowIntent + WorkflowGenerationReason + DAGRunPlanSeed

Planner 不做：
  - 创建 DAGRun（这是 Orchestrator 的工作）
  - 执行 NodeRun
  - 做最终路由决策
  - 详细的任务分解（这是 DAG nodes 的工作）
```

### Orchestrator 职责边界（拆分后）

```text
Orchestrator 6A — DAGRun Materialization：
  - 接收 DAGRunPlanSeed
  - 从 WorkflowTemplate Registry 查找 template
  - 创建完整的 DAGRun（含所有 NodeRun，状态 scheduled）
  - 不执行，只物化

Orchestrator 6B — Execution Loop：
  - 按顺序执行每个 NodeRun
  - 调用 RuntimeRouter.execute()
  - 写入 NodeRunStarted / NodeRunCompleted / NodeRunFailed 事件
  - 写入 RunMessageRecorded / ArtifactRecorded 事件

Orchestrator 6C — Route Decision：
  - 基于所有 NodeRun verdict 做路由决策
  - 写入 RouteDecided 事件
  - 写入 MissionStateChanged 事件
```

### Mission ↔ SpecChange 状态同步规则

```text
规则：Mission 状态由 Orchestrator 在 DAGRun 完成后写入；
     SpecChange 状态由 NodeRun artifact 携带，Orchestrator 读取后决定。

Template 完成 -> Mission 目标状态：
  ExplorationWorkflow     -> changing
  SpecChangeDraftWorkflow -> changing
  DesignWorkflow          -> verifying
  ImplementationWorkflow  -> verifying
  FixWorkflow             -> verifying
  VerificationWorkflow    -> operating
  RetrospectiveWorkflow   -> learning
  DeployWorkflow          -> operating（部署归运维循环，产出 deploy_manifest）

Template 完成 -> SpecChange 目标状态：
  ExplorationWorkflow     -> clarified
  DesignWorkflow          -> designed
  ImplementationWorkflow  -> implemented
  VerificationWorkflow(pass) -> verified
```

### RuntimeRouter 选择逻辑（明确版）

```text
选择优先级：
  1. planSeed.runtimeTargetId 明确指定 -> 使用指定 target
  2. runtimeTargetId = "runtime_mock" 或 undefined -> 使用 MockRuntime
  3. target.kind = "local_cli" -> 使用 LocalCliRuntimeAdapter

错误处理：
  - target 不存在 -> 抛出错误，写入 NodeRunFailed
  - local CLI 超时 -> 写入 NodeRunFailed，exitCode 非 0
```

---

## Situation Classification 完整矩阵（修订）

| Situation | 触发条件 | Next Loop | 选用 Template |
|---|---|---|---|
| `requirement_unclear` | 命令模糊、无验收标准、feedback = requirement_change/user_feedback | explore_decompose | ExplorationWorkflow |
| `clear_bounded_change` | 命令明确、已有 SpecChange 草稿 | design_build | SpecChangeDraftWorkflow |
| `design_gap` | 命令含 design/architecture、设计 artifact 缺失 | design_build | DesignWorkflow |
| `implementation_defect` | 命令含 fix/bug/failed，或 verification verdict = defect | design_build | FixWorkflow |
| `verification_contradiction` | verification verdict = contradiction | explore_decompose | ExplorationWorkflow |
| `runtime_drift` | missionState = operating 且无特定 feedback | operate_feedback | RetrospectiveWorkflow |
| `stable_progress` | 命令含 verify/test，missionState = verifying | check_verify | VerificationWorkflow |

分类优先级（从高到低）：

```text
1. latestVerificationVerdict（defect / contradiction）— 最高优先级
2. feedback signalType（requirement_change / user_feedback）
3. 命令关键词（fix/bug、design/architecture、verify/test）
4. missionState（operating -> runtime_drift）
5. 默认 -> requirement_unclear
```

> 注：v0.1A 不实现 incident / capacity_issue / user_correction 三种 situation，留给 v0.1B。

---

## 文件结构（最终，标注新增模块）

```text
src/
  shared/
    domain.ts
    eventTypes.ts
    testFactories.ts

  server/
    api/
      app.ts
      http.ts
    event-store/
      inMemoryEventStore.ts
      projections.ts
    planner/
      missionPlanner.ts
      situationClassifier.ts        <- 新增：独立分类模块
    templates/
      workflowTemplates.ts
    orchestrator/
      orchestrator.ts               <- 调用 materializer + executor + routeDecider
      dagRunMaterializer.ts         <- 新增：Seed -> DAGRun
      routeDecider.ts               <- 新增：verdict -> RouteDecided
    runtime/
      mockRuntimeAdapter.ts
      localCliRuntimeAdapter.ts
      runtimeTargetRegistry.ts
      runtimeRouter.ts
    index.ts

  app/
    apiClient.ts
    App.tsx
    main.tsx
    styles.css
    components/
      MissionList.tsx
      MissionDetail.tsx
      RuntimeTargets.tsx
      Timeline.tsx
      RunTrace.tsx

scripts/
  fake-local-runner.mjs

tests/
  shared/
    domain.test.ts
  server/
    eventStore.test.ts
    planner.test.ts
    situationClassifier.test.ts     <- 新增（Task 5B）
    templates.test.ts
    orchestrator.test.ts
    runtimeTargetRegistry.test.ts
    localCliRuntimeAdapter.test.ts
    api.test.ts
    feedbackLoop.test.ts            <- 新增（Task 11）
  e2e/
    childStoryGameMission.e2e.test.ts  <- 新增（Task 12）
  app/
    App.test.tsx
```

---

## 任务列表（修订版）

### Task 1: 项目骨架 — 已完成

已创建 package.json、tsconfig.json、vite.config.ts、index.html、src/app/*。

### Task 2: Shared Domain Contracts

文件：`src/shared/domain.ts`、`eventTypes.ts`、`testFactories.ts`、`tests/shared/domain.test.ts`
验收：`pnpm test tests/shared/domain.test.ts` 通过。

### Task 2B: 自举接缝预埋（新增）

目的：仅预留扩展点，自举逻辑全部留 v0.1B。详见设计稿 11.2.0。
- 接缝 1（projectId）**必须**：不预埋则 v0.1B 回改 Mission 模型和大量事件。
- 接缝 2、3 **可选/可推迟**：事件级，推迟到 v0.1B 回改量小。

接缝 1 — Project / projectId 抽象（必须）：
```text
domain.ts 新增 Project 接口：
  interface Project {
    id: string;
    name: string;
    kind: "self" | "external";   // self = 平台自身 repo
    repoRoot: string;            // 绝对路径
  }
Mission 接口新增字段：
  projectId: string;   // 默认指向内置 SelfProject
内置一条默认 SelfProject 记录（id = "project_self"，repoRoot = 平台 repo 根）。
v0.1A 不实现 project 注册 API，仅保证 Mission 必带 projectId。
```

接缝 2 — EvaluationRecord 落库（可选/可推迟）：
```text
domain.ts 已有 EvaluationRecord 类型，本任务确保流程真实写入：
  DAGRun 完成（RouteDecided 之后）append 一条 EvaluationRecorded 事件。
最简字段：
  { id, missionId, dagRunId, verdict, nodeCount, artifactCount, createdAt }
不实现 replay / optimizer，仅保证事件流里有这条记录。
```

接缝 3 — RouteDecided.gateRequired 字段（可选/可推迟）：
```text
RouteDecided 事件 payload 新增：
  gateRequired: boolean;   // v0.1A 恒为 false
v0.1A 不实现 gate 判定逻辑，仅保证字段存在、类型正确。
```

测试用例：
```text
Mission always carries a projectId pointing to a valid project
default SelfProject exists with kind=self and a repoRoot
DAGRun completion appends exactly one EvaluationRecorded event
EvaluationRecord references its dagRunId and missionId
RouteDecided event always carries gateRequired field (false in v0.1A)
```

验收：
- 创建 Mission 时若未指定 project，自动关联默认 SelfProject
- 每次 DAGRun 完成事件流恰好多一条 EvaluationRecorded
- 每个 RouteDecided 事件都带 gateRequired = false
- 以上不引入任何 gate / replay / 自我修改逻辑（留 v0.1B）

边界（必须不发生）：
```text
v0.1A 不得实现 project 注册 API（留 v0.1B）
v0.1A 不得实现 gate 判定逻辑（gateRequired 恒 false）
v0.1A 不得实现 EvaluationRecord 的 replay 或 optimizer 消费
workspace 仍硬编码 .mission-workspaces/<missionId>/（B 档，留 v0.1B）
```

### Task 3: Event Store and Projections

文件：`src/server/event-store/inMemoryEventStore.ts`、`projections.ts`、`tests/server/eventStore.test.ts`
验收：append / allEvents / eventsForMission，以及 projection 可从事件重建。

### Task 4: Workflow Template Registry

文件：`src/server/templates/workflowTemplates.ts`、`tests/server/templates.test.ts`
验收：8 个 template（含 DeployWorkflow）全部注册并可按 id 查询。

### Task 5: Mission Planner — 基础

文件：`src/server/planner/missionPlanner.ts`、`tests/server/planner.test.ts`
验收：
- 模糊命令 -> ExplorationWorkflow
- 含 fix 命令 -> FixWorkflow
- feedback = requirement_change -> ExplorationWorkflow
- Planner 输出不含 dagRunPlan / nodeRuns（边界保持）

### Task 5B: Situation Classifier — 完整矩阵（新增）

文件：`src/server/planner/situationClassifier.ts`、`tests/server/situationClassifier.test.ts`
目的：把分类逻辑从 missionPlanner.ts 提取为独立模块，覆盖全部 7 种 situation。

测试用例：
```text
classifies requirement_unclear for vague commands
classifies clear_bounded_change for specific commands with existing spec draft
classifies design_gap for design/architecture keywords
classifies implementation_defect for fix/bug/failed keywords
classifies implementation_defect from latestVerificationVerdict = defect
classifies verification_contradiction from latestVerificationVerdict = contradiction
classifies runtime_drift for operating missions without feedback
classifies stable_progress for verify/test keywords in verifying state
feedback requirement_change overrides keyword classification
latestVerificationVerdict has highest priority over feedback and keywords
```
验收：10 个测试全部通过。

### Task 6A: DAGRun Materialization（拆分新增）

文件：`src/server/orchestrator/dagRunMaterializer.ts`、扩展 `tests/server/orchestrator.test.ts`
职责：接收 DAGRunPlanSeed，从 template 创建完整 DAGRun（不执行）。

测试用例：
```text
creates DAGRun with correct nodeRuns from ExplorationWorkflow template
assigns dagRunId to all nodeRuns
sets all nodeRuns status to scheduled
preserves templateId / missionId / specChangeId from seed
```

### Task 6B: Orchestrator Execution Loop（拆分新增）

文件：`src/server/runtime/mockRuntimeAdapter.ts`、`src/server/orchestrator/orchestrator.ts`、扩展 `tests/server/orchestrator.test.ts`

测试用例：
```text
executes all nodeRuns in order
writes NodeRunStarted before each node execution
writes RunMessageRecorded for each message
writes ArtifactRecorded for each artifact
writes NodeRunCompleted after each node execution
handles NodeRunFailed when runtime returns verdict = fail
```

### Task 6C: Route Decision Logic（拆分新增）

文件：`src/server/orchestrator/routeDecider.ts`、扩展 `tests/server/orchestrator.test.ts`

测试用例：
```text
writes RouteDecided event after DAGRun completes
writes MissionStateChanged to changing after ExplorationWorkflow
writes MissionStateChanged to verifying after DesignWorkflow
writes MissionStateChanged to verifying after FixWorkflow
writes MissionStateChanged to operating after VerificationWorkflow
writes MissionStateChanged to learning after RetrospectiveWorkflow
DAGRun status is failed when any nodeRun failed
appends EvaluationRecorded after RouteDecided (接缝 2)
RouteDecided carries gateRequired = false (接缝 3)
```

### Task 6D: Autonomous Mission Driver（全自动大循环，新增）

文件：`src/server/orchestrator/missionDriver.ts`、`goalCheck.ts`、`tests/server/missionDriver.test.ts`、`goalCheck.test.ts`
目的：full_autonomous 模式下自动驱动大循环（plan-next→执行→路由→GoalCheck→循环），直到目标达成或暂停。详见详细任务文档 Task 6D、设计稿 6.1。

测试用例：
```text
goalCheck returns achieved when verdict pass and deploy healthy
goalCheck returns blocked when a gate or blocking question present
driver drives mission through multiple workflows until goal achieved
driver stops succeeded/blocked/exhausted correctly
driver appends WorkflowPlanned + DAGRun each iteration
driver does not require any manual plan-next call
driver only auto-drives in full_autonomous mode
```
验收：全绿；mock 下能自动多轮推进直到 achieved。

### Task 7: Runtime Targets and Local CLI Adapter

文件：`runtimeTargetRegistry.ts`、`localCliRuntimeAdapter.ts`、`runtimeRouter.ts`、`scripts/fake-local-runner.mjs`、对应测试。

RuntimeRouter 选择优先级测试：
```text
uses MockRuntime when no runtimeTargetId specified
uses MockRuntime for runtime_mock target
uses LocalCliAdapter for local_cli target
throws when specified target not found
```
验收：fake-local-runner.mjs 能实际生成游戏文件。

### Task 8: HTTP API

文件：`src/server/api/app.ts`、`http.ts`、`src/server/index.ts`、`tests/server/api.test.ts`
验收：创建/计划/执行/反馈/查询 API 全部通过。

### Task 9: Web Console Data Client

文件：`src/app/apiClient.ts`、`tests/app/App.test.tsx`（基础版）
验收：App 渲染 Mission Console 标题。

### Task 10: Mission Detail, Timeline, Run Trace, Runtime Targets UI

文件：`MissionList.tsx`、`MissionDetail.tsx`、`RuntimeTargets.tsx`、`Timeline.tsx`、`RunTrace.tsx`、更新 `App.tsx` 与 `App.test.tsx`
验收：App 包含所有 v0.1A 控制面板区域。

### Task 11: FeedbackSignal 端到端循环测试（新增）

文件：`tests/server/feedbackLoop.test.ts`
目的：验证 FeedbackSignal -> plan-next -> 新 WorkflowIntent 的完整闭环。

测试用例：
```text
feedback submission records FeedbackSignalReceived event
feedback triggers requirement_unclear classification in plan-next
second plan-next after feedback creates a new plannerRun (planSeed id 不同)
feedback with user_feedback signalType also triggers re-exploration
```
验收：4 个测试全部通过。

### Task 12: v0.1A 验收集成测试（新增）

文件：`tests/e2e/childStoryGameMission.e2e.test.ts`
目的：模拟完整"儿童故事游戏"验收场景，使用 fake-local-runner.mjs（不依赖真实 LLM）。

测试用例：
```text
registers local runner via API (kind=local_cli, runnerKind=codex)
creates mission and writes MissionCreated event (state=exploring)
planner generates ExplorationWorkflow (classification=requirement_unclear)
orchestrator executes DAGRun with fake runner and produces artifacts
mission state changes to changing after ExplorationWorkflow
timeline shows all required event types
run trace shows dagRun + messages + artifacts
feedback signal triggers second plan-next
second plan-next also selects ExplorationWorkflow due to feedback
```

事件流断言（执行 DAGRun 后必须包含）：
```text
DAGRunScheduled, DAGRunStarted
NodeRunStarted (x3), NodeRunCompleted (x3)
ArtifactRecorded, RunMessageRecorded
DAGRunCompleted, RouteDecided, MissionStateChanged
```

CI 注意：所有 e2e 测试用 fake-local-runner.mjs，绝不调用付费/不确定的真实模型 CLI。真实 runner 验收仅在 deployment acceptance 阶段手动执行。
验收：9 个测试全部通过。

---

## 验证测试标准

### 单元测试覆盖

| 模块 | 覆盖要求 |
|---|---|
| domain contracts | 所有类型可经 testFactories 实例化 |
| 自举接缝（Task 2B） | Mission 必带 projectId、默认 SelfProject、EvaluationRecorded 落库、gateRequired 字段 |
| eventTypes | 所有事件类型存在且为 const |
| InMemoryEventStore | append / allEvents / eventsForMission |
| projections | summaryView / detailView / runTraceView 可重建 |
| SituationClassifier | 7 种 situation x 多触发条件（10 用例） |
| WorkflowTemplateRegistry | 8 个 template（含 Deploy）可查询 |
| MissionPlanner | 3+ 场景（含 feedback），边界保持 |
| DAGRunMaterializer | seed -> DAGRun 结构完整 |
| Orchestrator Execution | nodeRun 顺序 + 事件写入 |
| RouteDecider | 每种 template 的 MissionState 映射 |
| RuntimeTargetRegistry | mock 内置 + local_cli 注册 |
| LocalCliRuntimeAdapter | fake runner 执行 + artifact 生成 |
| RuntimeRouter | 3 种选择路径 + 未找到抛错 |
| HTTP API | 创建/计划/执行/反馈/查询 |
| React App | 关键 UI 区域渲染 |

### v0.1A 功能验收清单

```text
可以从 Web Console 或 API 创建 Mission
Mission 创建写入 MissionCreated 事件
Planner 生成 WorkflowIntent + WorkflowGenerationReason + DAGRunPlanSeed
Planner 输出不含 dagRunPlan / nodeRuns（边界保持）
Orchestrator 从 DAGRunPlanSeed 物化出完整 DAGRun
DAGRun 至少含 explore/implement/verify 类型 NodeRun
NodeRun 可写入 RunMessage 和 Artifact
Orchestrator 写入 RouteDecided 事件
路由决策导致 MissionStateChanged 事件
Web Console 可查看 Mission timeline
Web Console 可查看 RunTrace（DAGRun + NodeRun + Artifact）
FeedbackSignal 可触发下一次 plan-next
可从 Web Console 注册 local runner
注册的 fake runner 可实际执行并生成文件
每个 Mission 关联 projectId（默认 SelfProject）— 接缝 1
每次 DAGRun 完成写入一条 EvaluationRecorded 事件 — 接缝 2
每个 RouteDecided 事件带 gateRequired=false 字段 — 接缝 3
```

### 边界验收（必须不发生）

```text
Planner 输出不得包含具体任务列表
Planner 不得直接创建 DAGRun
Orchestrator 不得做业务判断（只路由）
Projection 不得是唯一事实来源（必须可从事件重建）
```

---

## 部署验收测试（手动，仅 acceptance 阶段）

使用真实本机 runner（codex 或 claude），不在 CI 中执行。

前提：`codex --version`（0.134.0）/ `claude --version`（2.1.152）

流程：
```text
1. pnpm api（后端 8787）+ pnpm dev（前端 5173）
2. Web Console -> Runtime Targets -> Register Local Codex
3. 创建 Mission：text = 做一个儿童故事游戏
4. Plan Next -> 验证 ExplorationWorkflow 被选中
5. Run Plan -> 验证 Codex 实际执行
6. 等待 DAGRun 完成
7. 验证 timeline 显示完整事件链
8. 验证 RunTrace 显示 NodeRun 和 Artifact
9. 验证 .mission-workspaces/<missionId>/ 下有游戏文件
10. 提交 Feedback -> Plan Next -> 验证新的 WorkflowPlanned 出现
```

通过标准：步骤 1-10 全部无错误；游戏文件存在；timeline 含所有必须事件；第二次 plan-next 产生新 plannerRun。

---

## 自举范围澄清（v0.1A vs v0.1B）

v0.1A 已包含的自举能力：
```text
可注册本地 runner 执行任意任务
可生成代码文件（fake-local-runner 验证 + 真实 runner 验收）
记录完整 execution history（事件流 + artifact）
事件流可重建（projection rebuildable）
WorkflowTemplate 可版本化（metadata 含 version）
```

v0.1B 才有的自举能力（不在 v0.1A 范围）：
```text
平台代码的自我修改（需 SelfProject 注册机制）
Evolution Loop 自动化（需 EvaluationRecord + optimizer）
Template 自动优化（需 ReplayRun + PromotionDecision）
多 runtime 并发调度优化
```

---

## 执行顺序

```text
Task 1   项目骨架（已完成）
Task 2   Shared Domain Contracts
Task 2B  自举接缝预埋（A 档 3 个，新增）
Task 3   Event Store and Projections
Task 4   Workflow Template Registry
Task 5   Mission Planner 基础
Task 5B  Situation Classifier 完整矩阵（新增）
Task 6A  DAGRun Materialization（拆分）
Task 6B  Orchestrator Execution Loop（拆分）
Task 6C  Route Decision Logic（拆分）
Task 6D  Autonomous Mission Driver（全自动大循环，新增）
Task 7   Runtime Targets + Local CLI Adapter
Task 8   HTTP API
Task 9   Web Console Data Client
Task 10  Mission Detail / Timeline / RunTrace UI
Task 11  FeedbackSignal 端到端测试（新增）
Task 12  v0.1A 验收集成测试（新增）
[手动]   部署验收（真实 runner）
```

每个任务开始前遵循 TDD：先写测试 -> 跑测试确认失败 -> 实现 -> 跑测试确认通过 -> git commit。







