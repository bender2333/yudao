# v0.1A 详细任务清单（goal 模式可逐 task 自动执行）

> **日期：** 2026-05-29
> **用途：** 供 goal / 自动执行模式逐 task 落地。每个 task 给出：目标、产出文件、关键实现要点（签名级）、单元测试用例（test 名称级）、验收门槛、边界。
> **关联：** 总览见 `2026-05-29-v01a-plan-revised.md`；闭环验收见 `2026-05-29-integration-test-children-story-site.md`；契约定义见原计划 `2026-05-28-v01a-full-loop-thin-slice.md`。

## 执行约定

- 每个 task 严格 TDD：先写测试 → 跑测试确认 RED → 实现 → 跑测试确认 GREEN → commit。
- 测试命令：`pnpm test <file>`；全量：`pnpm test`；构建校验：`pnpm build`。
- 类型契约以原计划 `domain.ts` 为准，本文件只标增量字段。
- 所有 ID 用 `makeId(prefix)`，时间用 `nowIso()`（见 testFactories）。
- 边界栏列出的"必须不发生"项，若出现即判定该 task 未通过。

## Task 依赖图

```text
T1 骨架(已完成)
  └─ T2 domain ── T2B 接缝(projectId必须;2、3可选)
        ├─ T3 event store + projections
        ├─ T4 template registry
        │     └─ T5 planner ── T5B situation classifier
        │           └─ T6A materializer ── T6B exec loop ── T6C route decider
        │                 └─ T7 runtime targets + local cli adapter
        │                       └─ T8 HTTP API
        │                             ├─ T9 web data client ── T10 UI
        │                             ├─ T11 feedback loop 测试
        │                             └─ T12 e2e 验收（依赖集成测试文档）
```

---

## Task 1：项目骨架（已完成）

已有 package.json / tsconfig.json / vite.config.ts / index.html / src/app/{main,App}.tsx / styles.css，依赖已装。无需重做。

---

## Task 2：Shared Domain Contracts

目标：定义全部公共类型契约，作为后端/前端/测试的唯一契约源。

产出文件：
- `src/shared/domain.ts`（全部类型，见原计划 428–681 行）
- `src/shared/eventTypes.ts`（已存在，校验 const 数组）
- `src/shared/testFactories.ts`（makeId / nowIso / makeMissionCommand 等）
- `tests/shared/domain.test.ts`

关键实现要点：
- `domain.ts` 类型完全照原计划 428–681 行落地，不改字段名。
- 契约增量（本修订新增，全自动 + 部署所需）：
  - `WorkflowTemplateId` 增加 `"DeployWorkflow"`
  - `NodeKind` 增加 `"deploy"`
  - `ArtifactKind` 增加 `"deploy_manifest"`
  - `RuntimeTarget` 增加 `role?: "worker" | "ops"`（见 Task 2B）
  - `Mission` 增加 `projectId: string`（见 Task 2B）
- `testFactories.ts` 用 `crypto.randomUUID()` 生成 id；导出 `makeId(prefix)`、`nowIso()`、`makeMissionCommand(input)`。
- eventTypes 用 `as const`，导出 `MissionEventType = (typeof missionEventTypes)[number]`。

单元测试用例（`tests/shared/domain.test.ts`）：
```text
makeId returns prefix-tagged unique ids
nowIso returns a valid ISO timestamp string
makeMissionCommand defaults source=web_console and autonomyMode=default_autonomous
makeMissionCommand respects provided source and autonomyMode
a Mission object satisfies the Mission interface shape
a MissionEvent accepts typed payload generic
```

验收门槛：`pnpm test tests/shared/domain.test.ts` 全绿。

边界（必须不发生）：
```text
domain.ts 不得 import 任何 server/app 模块（契约层零依赖）
testFactories 不得包含业务逻辑（只造数据）
```

---

## Task 2B：自举接缝预埋

目标：仅预留扩展点，自举逻辑全部留 v0.1B。接缝 1 必须；接缝 2、3 可选/可推迟；ops 角色字段因集成测试需要而纳入必须。

产出文件：
- 扩展 `src/shared/domain.ts`
- `tests/shared/bootstrapSeams.test.ts`

接缝 1 — Project / projectId（必须）：
```ts
export interface Project {
  id: string;
  name: string;
  kind: "self" | "external";   // self = 平台自身 repo
  repoRoot: string;            // 绝对路径
}
// Mission 新增：
//   projectId: string;   // 默认 "project_self"
export const DEFAULT_SELF_PROJECT: Project = {
  id: "project_self",
  name: "Mission Platform Self",
  kind: "self",
  repoRoot: process.cwd()
};
```

接缝 ops — RuntimeTarget 角色（必须，集成测试依赖）：
```ts
// RuntimeTarget 新增：
//   role?: "worker" | "ops";   // 缺省 worker；ops = 部署/健康观察 agent
// 说明：v0.1A 不实现 ops 自主决策，仅让集成测试能注册一个 ops 角色 target，
//       由它执行部署/健康探活命令。worker 跑任务，ops 跑运维。
```

接缝 2 — EvaluationRecord 落库（可选/可推迟）：
```ts
// 若实现：DAGRun 完成后 append 一条 EvaluationRecorded
// 最简 payload：{ id, missionId, dagRunId, verdict, nodeCount, artifactCount, createdAt }
```

接缝 3 — RouteDecided.gateRequired（可选/可推迟）：
```ts
// 若实现：RouteDecided payload 加 gateRequired: boolean（v0.1A 恒 false）
```

单元测试用例（`tests/shared/bootstrapSeams.test.ts`）：
```text
DEFAULT_SELF_PROJECT has kind=self and a non-empty repoRoot
a Mission carries a projectId field
Mission without explicit project resolves to project_self (helper)
RuntimeTarget accepts optional role field (worker | ops)
RuntimeTarget defaults to worker role when unset (helper)
[可选] EvaluationRecord shape references dagRunId and missionId
[可选] RouteDecided payload carries gateRequired boolean
```

验收门槛：接缝 1 与 ops 角色测试全绿；接缝 2、3 测试若未实现可标 `it.todo`。

边界（必须不发生）：
```text
不实现 project 注册 API（留 v0.1B）
不实现 ops agent 自主决策逻辑（仅角色字段 + 执行命令）
不实现 gate 判定 / EvaluationRecord replay / optimizer（留 v0.1B）
workspace 仍硬编码 .mission-workspaces/<missionId>/（B 档，留 v0.1B）
```

---

## Task 3：Event Store and Projections

目标：append-only 事件存储 + 可重建投影。投影不是事实源，必须能从事件流重建。

产出文件：
- `src/server/event-store/inMemoryEventStore.ts`
- `src/server/event-store/projections.ts`
- `tests/server/eventStore.test.ts`

关键实现要点：
```ts
// inMemoryEventStore.ts
export interface EventStore {
  append(event: MissionEvent): MissionEvent;
  allEvents(): MissionEvent[];
  eventsForMission(missionId: string): MissionEvent[];
}
export function createInMemoryEventStore(): EventStore;
// 内部用数组，append 返回写入的事件；保持插入顺序。

// projections.ts —— 纯函数，输入事件数组，输出视图
export function buildMissionSummaryView(events: MissionEvent[]): MissionSummaryView | undefined;
export function buildMissionDetailView(events: MissionEvent[]): MissionDetailView | undefined;
export function buildRunTraceView(events: MissionEvent[], dagRunId: string): RunTraceView | undefined;
// 从 payload 收集 specChange/artifact/plannerRun/dagRun 等子项。
```

单元测试用例（`tests/server/eventStore.test.ts`）：
```text
append stores an event and returns it
allEvents returns events in append order
eventsForMission filters by missionId
buildMissionSummaryView derives state from latest MissionStateChanged
buildMissionSummaryView sets lastEventType from latest event
buildMissionDetailView collects specChanges artifacts plannerRuns dagRuns
buildRunTraceView returns dagRun with its messages and artifacts
projection rebuilt from the same events is deterministic (idempotent)
buildMissionDetailView returns undefined for unknown mission
```

验收门槛：`pnpm test tests/server/eventStore.test.ts` 全绿；同一事件流重复 build 结果一致。

边界（必须不发生）：
```text
projection 不得缓存为唯一事实源（每次从事件重建）
event store 不得修改已写入事件（append-only）
```

---

## Task 4：Workflow Template Registry

目标：注册 8 个 WorkflowTemplate（含 DeployWorkflow），可按 id 查询；每个 template 携带 nodeTemplates。

产出文件：
- `src/server/templates/workflowTemplates.ts`
- `tests/server/templates.test.ts`

契约增量（对 Task 2 domain.ts 的补充，全自动部署所需）：
```ts
// WorkflowTemplateId 增加： "DeployWorkflow"
// NodeKind 增加：          "deploy"
// ArtifactKind 增加：       "deploy_manifest"
// LoopType 复用 operate_feedback（部署归运维循环）
```

关键实现要点：
```ts
export const workflowTemplates: Record<WorkflowTemplateId, WorkflowTemplate>;
export function getWorkflowTemplate(id: WorkflowTemplateId): WorkflowTemplate;
export function listWorkflowTemplates(): WorkflowTemplate[];
// 8 个：Exploration / SpecChangeDraft / Design / Implementation / Verification / Fix / Retrospective / Deploy
// 每个含 loopType、triggerConditions、producedArtifacts、nodeTemplates、riskLevel、version=1
// ExplorationWorkflow 至少 explore 类 node，并产出 mission_brief/assumption_set/acceptance_criteria
// ImplementationWorkflow 含 implement node（worker runner 生成站点文件）
// VerificationWorkflow 含 verify node
// DeployWorkflow 含 deploy node，由 ops 角色 runner 执行本地部署+启动+健康探活，产出 deploy_manifest
```

单元测试用例（`tests/server/templates.test.ts`）：
```text
registry contains all 8 template ids
getWorkflowTemplate returns the requested template
every template has at least one nodeTemplate
every template version is a positive integer
ExplorationWorkflow produces mission_brief and acceptance_criteria
ImplementationWorkflow contains an implement node
VerificationWorkflow contains a verify node
DeployWorkflow contains a deploy node and produces deploy_manifest
each nodeTemplate kind is a valid NodeKind
listWorkflowTemplates returns 8 entries
```

验收门槛：`pnpm test tests/server/templates.test.ts` 全绿。

边界（必须不发生）：
```text
template 不得包含运行时状态（只是静态定义）
template 不得引用具体 RuntimeTarget（运行时才绑定）
```

---

## Task 5：Mission Planner（基础）

目标：基于 Mission 状态选择下一个 workflow，产出 WorkflowIntent + WorkflowGenerationReason + DAGRunPlanSeed。只选择，不执行、不分解任务。

产出文件：
- `src/server/planner/missionPlanner.ts`
- `tests/server/planner.test.ts`

关键实现要点：
```ts
export interface PlanNextInput {
  mission: Mission;
  command?: MissionCommand;
  latestFeedback?: FeedbackSignal;
  latestVerificationVerdict?: "pass" | "defect" | "contradiction";
  existingSpecChange?: SpecChange;
}
export function planNext(input: PlanNextInput): MissionPlannerRun;
// 内部调用 Task 5B 的 classifySituation(...) 得到 classification，
// 再映射到 templateId（见总览决策矩阵），组装三件套。
// DAGRunPlanSeed.inputRefs 只放引用 id，不展开 nodeRuns。
```

单元测试用例（`tests/server/planner.test.ts`）：
```text
vague command selects ExplorationWorkflow
command containing fix selects FixWorkflow
feedback requirement_change selects ExplorationWorkflow
planner output has no nodeRuns or dagRun field (boundary)
planner emits WorkflowIntent reason and planSeed together
planSeed references missionId and a specChangeId
reason lists selectedTemplateId and rejectedTemplateIds
```

验收门槛：`pnpm test tests/server/planner.test.ts` 全绿；输出不含 nodeRuns。

边界（必须不发生）：
```text
planner 不得创建 DAGRun
planner 不得展开具体任务列表
planner 不得选择 RuntimeTarget（运行时职责）
```

---

## Task 5B：Situation Classifier（完整矩阵）

目标：把分类逻辑抽成独立纯函数，覆盖全部 7 种 situation，并实现优先级。

产出文件：
- `src/server/planner/situationClassifier.ts`
- `tests/server/situationClassifier.test.ts`

关键实现要点：
```ts
export interface ClassifyInput {
  commandText?: string;
  missionState: MissionState;
  latestFeedback?: FeedbackSignal;
  latestVerificationVerdict?: "pass" | "defect" | "contradiction";
  hasSpecDraft?: boolean;
}
export function classifySituation(input: ClassifyInput): SituationClassification;
// 优先级（高→低）：
//  1. latestVerificationVerdict: defect→implementation_defect, contradiction→verification_contradiction
//  2. feedback: requirement_change|user_feedback → requirement_unclear
//  3. 关键词: fix/bug/failed→implementation_defect; design/architecture→design_gap; verify/test→stable_progress
//  4. missionState=operating → runtime_drift
//  5. hasSpecDraft 且命令明确 → clear_bounded_change
//  6. 默认 → requirement_unclear
```

单元测试用例（`tests/server/situationClassifier.test.ts`，对应总览 10 条）：
```text
classifies requirement_unclear for vague commands
classifies clear_bounded_change for specific commands with existing spec draft
classifies design_gap for design or architecture keywords
classifies implementation_defect for fix bug failed keywords
classifies implementation_defect from latestVerificationVerdict defect
classifies verification_contradiction from latestVerificationVerdict contradiction
classifies runtime_drift for operating missions without feedback
classifies stable_progress for verify test keywords in verifying state
feedback requirement_change overrides keyword classification
latestVerificationVerdict has highest priority over feedback and keywords
```

验收门槛：10 条全绿。

边界（必须不发生）：
```text
classifier 必须是纯函数（无 IO、无事件写入）
v0.1A 不实现 incident / capacity_issue / user_correction 三种 situation
```

---

## Task 6A：DAGRun Materialization

目标：把 DAGRunPlanSeed 物化成完整 DAGRun（含全部 NodeRun，状态 scheduled），不执行。

产出文件：
- `src/server/orchestrator/dagRunMaterializer.ts`
- 扩展 `tests/server/orchestrator.test.ts`

关键实现要点：
```ts
export function materializeDAGRun(seed: DAGRunPlanSeed): DAGRun;
// 从 getWorkflowTemplate(seed.templateId).nodeTemplates 生成 NodeRun[]，
// 每个 NodeRun: { id, dagRunId, nodeTemplateId, kind, label, status: "scheduled" }
// DAGRun: { id, missionId, specChangeId, templateId, status: "scheduled", nodeRuns, createdAt, updatedAt }
```

单元测试用例：
```text
creates DAGRun with nodeRuns from ExplorationWorkflow template
assigns the same dagRunId to all nodeRuns
sets all nodeRuns status to scheduled
preserves templateId missionId specChangeId from seed
nodeRun count equals template nodeTemplate count
```

验收门槛：上述全绿。

边界（必须不发生）：
```text
materializer 不得执行 node（不调用 runtime）
materializer 不得写事件（纯构造）
```

---

## Task 6B：Orchestrator Execution Loop

目标：顺序执行 DAGRun 的每个 NodeRun，通过 RuntimeRouter 调度，写入完整事件序列。

产出文件：
- `src/server/runtime/mockRuntimeAdapter.ts`
- `src/server/orchestrator/orchestrator.ts`
- 扩展 `tests/server/orchestrator.test.ts`

关键实现要点：
```ts
// mockRuntimeAdapter：确定性，按 nodeKind 产出固定 RunMessage + Artifact，返回 verdict=pass
export interface RuntimeAdapter {
  execute(request: NodeExecutionRequest): Promise<NodeRunResult>;
}
// orchestrator.runDAGRun(seed, deps): 
//   1. materializeDAGRun → 2. append DAGRunScheduled + DAGRunStarted
//   3. 逐 node: NodeRunStarted → execute → RunMessageRecorded* → ArtifactRecorded* → NodeRunCompleted/NodeRunFailed
//   4. append DAGRunCompleted → 交给 6C 做路由
```

单元测试用例：
```text
executes all nodeRuns in order
writes NodeRunStarted before each node execution
writes RunMessageRecorded for each runtime message
writes ArtifactRecorded for each produced artifact
writes NodeRunCompleted after each successful node
writes NodeRunFailed when runtime returns verdict fail
DAGRunStarted precedes the first NodeRunStarted
DAGRunCompleted is the last run-level event
```

验收门槛：上述全绿；事件顺序严格。

边界（必须不发生）：
```text
orchestrator 不得做业务判断（只调度 + 写事件）
mock adapter 不得产生随机输出（确定性）
```

---

## Task 6C：Route Decision Logic

目标：DAGRun 完成后基于 verdict 做路由，写 RouteDecided + MissionStateChanged；可选写 EvaluationRecorded（接缝 2）。

产出文件：
- `src/server/orchestrator/routeDecider.ts`
- 扩展 `tests/server/orchestrator.test.ts`

关键实现要点：
```ts
export function decideRoute(input: {
  dagRun: DAGRun;
  templateId: WorkflowTemplateId;
  anyNodeFailed: boolean;
}): { nextState: MissionState; gateRequired: boolean };
// template → MissionState 映射见总览同步规则。
// 任一 node 失败 → DAGRun.status=failed，路由回 fix/explore（不强制改 MissionState 前进）。
// gateRequired 恒 false（接缝 3，可选）。
// 写 RouteDecided（带 gateRequired）+ MissionStateChanged。
// 可选：append EvaluationRecorded（接缝 2）。
```

单元测试用例：
```text
writes RouteDecided after DAGRun completes
writes MissionStateChanged to changing after ExplorationWorkflow
writes MissionStateChanged to verifying after DesignWorkflow
writes MissionStateChanged to verifying after FixWorkflow
writes MissionStateChanged to operating after VerificationWorkflow
writes MissionStateChanged to learning after RetrospectiveWorkflow
DAGRun status is failed when any nodeRun failed
RouteDecided carries gateRequired false (接缝 3，若实现)
appends one EvaluationRecorded after RouteDecided (接缝 2，若实现)
```

验收门槛：必选项全绿；接缝 2、3 项若未实现标 `it.todo`。

边界（必须不发生）：
```text
routeDecider 不得编码业务语义（只按 template→state 表路由）
gateRequired 在 v0.1A 不得为 true
```

---

## Task 6D：Autonomous Mission Driver（全自动大循环）

目标：full_autonomous 模式下自动驱动大循环，直到 Mission 目标达成（网站能跑）或暂停（blocked/exhausted）。无人工点击。详见设计稿 6.1。

产出文件：
- `src/server/orchestrator/missionDriver.ts`
- `src/server/orchestrator/goalCheck.ts`
- `tests/server/missionDriver.test.ts`
- `tests/server/goalCheck.test.ts`

关键实现要点：
```ts
// goalCheck.ts —— 纯函数，只读结构化事实
export type GoalStatus = "achieved" | "not_achieved" | "blocked";
export function checkGoal(input: {
  events: MissionEvent[];
  requiresDeploy: boolean;
  latestVerificationVerdict?: "pass" | "defect" | "contradiction";
  deployHealth?: "healthy" | "unhealthy" | "unknown";
}): GoalStatus;
// achieved: verdict=pass 且 (不需部署 或 deployHealth=healthy)
// blocked:  出现 blocking question / gateRequired
// 否则 not_achieved

// missionDriver.ts
export interface DriveResult {
  finalState: MissionState;
  outcome: "succeeded" | "blocked" | "exhausted";
  iterations: number;
}
export async function driveMission(input: {
  missionId: string;
  maxIterations: number;       // 安全阀，默认 8
  deps: { planNext; runDAGRun; eventStore; checkGoal; ... };
}): Promise<DriveResult>;
// 循环: plan-next → materialize+execute DAGRun → route → checkGoal
//   achieved → succeeded；blocked → blocked；达 maxIterations → exhausted；否则继续
// 每轮都写事件，全程可观察（timeline 能看到多轮 WorkflowPlanned/DAGRun）
```

单元测试用例（`goalCheck.test.ts`）：
```text
returns achieved when verdict pass and deploy not required
returns achieved when verdict pass and deployHealth healthy
returns not_achieved when verdict pass but deployHealth unhealthy
returns not_achieved when no verification verdict yet
returns blocked when a gate or blocking question is present
```

单元测试用例（`missionDriver.test.ts`，用 mock/fake runtime，确定性）：
```text
drives mission through multiple workflows until goal achieved
stops with succeeded when goalCheck returns achieved
stops with blocked when goalCheck returns blocked
stops with exhausted when maxIterations reached
each iteration appends a WorkflowPlanned and a DAGRun to the timeline
does not require any manual plan-next call (fully automatic)
respects autonomy mode (only auto-drives in full_autonomous)
```

验收门槛：上述全绿；驱动器能在 mock 下自动多轮推进直到 achieved。

边界（必须不发生）：
```text
driver 不得替代 Planner 选择或 Orchestrator 调度（只编排节奏）
driver 不得做业务判断（达标判定走 goalCheck 的结构化事实）
缺少 maxIterations 安全阀不得上线（防死循环）
full_autonomous 之外的模式不得被 driver 自动越过 gate
```

---

## Task 7：Runtime Targets and Local CLI Adapter

目标：RuntimeTarget 注册表（含内置 mock + 可注册 local_cli，支持 worker/ops 角色）、LocalCliRuntimeAdapter（子进程执行真实 runner）、RuntimeRouter（按 target 选适配器）、fake-local-runner 脚本。

产出文件：
- `src/server/runtime/runtimeTargetRegistry.ts`
- `src/server/runtime/localCliRuntimeAdapter.ts`
- `src/server/runtime/runtimeRouter.ts`
- `scripts/fake-local-runner.mjs`
- `tests/server/runtimeTargetRegistry.test.ts`
- `tests/server/localCliRuntimeAdapter.test.ts`

关键实现要点：
```ts
// registry: 内置一个 mock target（id=runtime_mock, role=worker）；
//   registerLocalCli({ name, runnerKind, command, args, cwd, role? }) → RuntimeTarget
//   list() / get(id)
// localCliRuntimeAdapter: 用 node:child_process spawn，
//   把 {workspace} 占位符替换为 missionWorkspace(request)，
//   workspace = `${cwd}/.mission-workspaces/${missionId}`（B 档硬编码，留 v0.1B 改 repoRoot）
//   解析 runner stdout，产出 RunMessage + Artifact，返回 NodeRunResult。
// runtimeRouter: 优先级见总览 —— 指定 id > runtime_mock/undefined > local_cli。
//   未找到 target 抛错。
// fake-local-runner.mjs: 读取 prompt+workspace，生成静态多页故事站三件套，
//   stdout 打印 JSON 摘要 + 文件清单（供集成测试第1层冒烟）。
```

ops 角色说明（接 Task 2B，deploy 节点执行）：
```text
registerLocalCli 接受 role: "worker" | "ops"，默认 worker。
worker target：执行 explore/design/implement/verify 节点（生成站点文件）。
ops target：执行 DeployWorkflow 的 deploy 节点 —— 本地部署 + 启动静态服务 + 健康探活，
  产出 deploy_manifest artifact（含可访问 URL、健康状态、进程信息）。
RuntimeRouter 选 adapter 时，deploy 节点路由到 ops target；其余节点路由到 worker target。
v0.1A 不实现 ops 自主决策，ops 只是能跑部署/探活命令的 local_cli target。
配套脚本 scripts/deploy-and-observe.mjs（见集成测试文档），支持 deploy/serve/health/teardown 阶段。
```

单元测试用例（`runtimeTargetRegistry.test.ts`）：
```text
registry has a built-in mock target with role worker
registerLocalCli adds a local_cli target
registerLocalCli accepts ops role
registered target defaults to worker role when role unset
list returns all targets including built-in mock
get returns target by id and undefined for unknown
```

单元测试用例（`localCliRuntimeAdapter.test.ts`，用 fake runner）：
```text
spawns fake runner and resolves a NodeRunResult
replaces {workspace} placeholder with mission workspace path
fake runner writes index.html stories.js style.css into workspace
adapter emits RunMessages parsed from runner output
adapter returns artifacts referencing produced files
non-zero exit code yields a failed NodeRunResult
```

RuntimeRouter 测试（并入 orchestrator 或单独）：
```text
uses MockRuntime when no runtimeTargetId specified
uses MockRuntime for runtime_mock target
uses LocalCliAdapter for local_cli target
throws when specified target not found
```

验收门槛：上述全绿；fake runner 真实在临时 workspace 生成三件套并被测试清理。

边界（必须不发生）：
```text
CI / 单元测试不得调用真实 codex/claude（只用 fake runner）
adapter 不得把 secrets 写入事件或 artifact body
spawn 命令参数必须数组化传入（不字符串拼接，防注入）
```

---

## Task 8：HTTP API

目标：Hono app 暴露 v0.1A API 面，把 command/query/event 三类操作接到 event store、planner、orchestrator、runtime registry。

产出文件：
- `src/server/api/app.ts`（createApp(deps) → Hono 实例）
- `src/server/api/http.ts`（startHttpServer(port)）
- `src/server/index.ts`（入口，读 PORT 默认 8787）
- `tests/server/api.test.ts`（用 app.request 直接打，无需起真实端口）

API 清单（与设计稿 9 节一致）：
```text
POST /api/missions               建 Mission（默认关联 project_self）→ MissionCreated
                                   body 可带 autonomyMode；full_autonomous 时由 driver 自动驱动
POST /api/missions/:id/commands  提交 MissionCommand
POST /api/missions/:id/plan-next 跑 planner → WorkflowPlanned 等（手动模式用）
POST /api/dag-runs               物化+执行 DAGRun → 全套 run 事件（手动模式用）
POST /api/events                 追加 MissionEvent
GET  /api/missions               列表 MissionSummaryView
GET  /api/missions/:id           Mission detail 投影
GET  /api/missions/:id/timeline  MissionTimelineView
GET  /api/missions/:id/status    ★ 黑盒轮询用：聚合 {state, outcome, goalStatus, deployUrl?}
GET  /api/dag-runs/:id           run/node trace
POST /api/missions/:id/feedback  提交 FeedbackSignal → FeedbackSignalReceived
POST /api/runtime-targets        注册 local_cli（含 role）
GET  /api/runtime-targets        列表 targets
```

全自动入口说明：
```text
黑盒测试只调两类端点（纯用户动作）：
  1. POST /api/missions {text, autonomyMode:"full_autonomous"} —— 提交意图
  2. GET  /api/missions/:id/status —— 轮询直到 outcome=succeeded（或超时）
创建 full_autonomous Mission 时，后端异步启动 Autonomous Mission Driver（Task 6D），
  driver 自动跑完 explore→...→deploy 多轮，无需测试再调 plan-next/dag-runs。
deployUrl 由 DeployWorkflow 的 deploy_manifest artifact 提供，供 Playwright 打开。
```

单元/集成测试用例（`tests/server/api.test.ts`）：
```text
POST /api/missions creates a mission with state exploring
created mission carries projectId project_self
POST /api/missions/:id/plan-next returns WorkflowIntent reason planSeed
POST /api/dag-runs executes and returns a completed DAGRun
GET /api/missions/:id/timeline lists events in order
GET /api/dag-runs/:id returns run trace with messages and artifacts
POST /api/missions/:id/feedback records FeedbackSignalReceived
POST /api/runtime-targets registers a local_cli target
POST /api/runtime-targets accepts ops role
GET /api/runtime-targets lists built-in mock plus registered
GET /api/missions/:id/status returns aggregated state outcome goalStatus
full_autonomous mission auto-starts the driver (status reaches succeeded with fake runtime)
status exposes deployUrl once DeployWorkflow produced a deploy_manifest
unknown mission id returns 404
```

验收门槛：`pnpm test tests/server/api.test.ts` 全绿。

安全注意：
```text
v0.1A 无鉴权 —— 文档显式标注：仅本地开发服务，不可直接暴露公网。
runtime-targets 注册接口能 spawn 本地命令，属高风险入口，
  v0.1B 必须加鉴权/白名单（此处留接口注释）。
```

边界（必须不发生）：
```text
API 不得返回 secrets / 环境变量原文
查询接口只读投影，不得写事件
```

---

## Task 9：Web Console Data Client

目标：前端 apiClient 封装所有 API 调用；App 基础渲染。

产出文件：
- `src/app/apiClient.ts`
- 更新 `src/app/App.tsx`
- `tests/app/App.test.tsx`（基础版）

关键实现要点：
```ts
// apiClient.ts: request(path, init) 基于 fetch，base /api；
//   listMissions / getMission / planNext / runDagRun / submitFeedback /
//   listRuntimeTargets / registerRuntimeTarget / getMissionTimeline / getRunTrace
```

单元测试用例：
```text
App renders the Mission Console heading
apiClient builds correct request path and method (mock fetch)
apiClient throws on non-ok response
```

验收门槛：`pnpm test tests/app/App.test.tsx` 全绿。

---

## Task 10：Mission Detail / Timeline / RunTrace / Runtime Targets UI

目标：补齐 v0.1A 控制台五大区域组件并接入 App。

产出文件：
- `src/app/components/{MissionList,MissionDetail,RuntimeTargets,Timeline,RunTrace}.tsx`
- 更新 `src/app/App.tsx`、`src/app/styles.css`
- 更新 `tests/app/App.test.tsx`

关键实现要点：
```text
NewMission（入口）：一个文本框 + 自主模式选择 + 「提交」按钮；
  提交 {text, autonomyMode:"full_autonomous"} → POST /api/missions；
  这是黑盒全自动的用户入口，提交后系统自动驱动，无需再点 Plan Next/Run Plan。
MissionList：列出 mission（title/state/outcome/lastEvent），点选切换当前 mission
MissionDetail：brief/state/outcome/goalStatus + deployUrl 链接（达标后出现）
  + 手动模式下的 Plan Next / Run Plan / Add Feedback 按钮
Timeline：按 occurredAt 顺序渲染事件（含多轮自动循环）
RunTrace：DAGRun + NodeRun 卡片 + RunMessage + Artifact
RuntimeTargets：列出 targets + 注册 Local Codex / Claude（worker）/ Ops Agent（ops）按钮
```

单元测试用例：
```text
App renders NewMission Mission List Mission Detail and Runtime Targets regions
NewMission submits text with full_autonomous mode
MissionList renders mission titles states and outcome
MissionDetail shows deployUrl link when present
Timeline renders events in chronological order
RunTrace renders nodeRuns with their status
RuntimeTargets renders register buttons including ops
clicking a mission selects it (state updates)
```

验收门槛：`pnpm test tests/app` 全绿；`pnpm build` 通过。

边界（必须不发生）：
```text
UI 不得持有权威状态（state 源自后端投影）
UI 不得直接拼命令字符串发给 runner
```

---

## Task 11：FeedbackSignal 端到端循环测试

目标：验证 FeedbackSignal → plan-next → 新 WorkflowIntent 闭环（仍用 mock/fake，确定性）。

产出文件：
- `tests/server/feedbackLoop.test.ts`

单元/集成测试用例：
```text
feedback submission records FeedbackSignalReceived event
feedback triggers requirement_unclear classification in plan-next
second plan-next after feedback creates a new plannerRun with different planSeed id
feedback with user_feedback signalType also triggers re-exploration
two WorkflowPlanned events appear in timeline after two plan-next calls
```

验收门槛：5 条全绿。

边界（必须不发生）：
```text
本 task 不依赖真实 runner（mock/fake 即可）
```

---

## Task 12：v0.1A 验收集成测试（接入集成测试文档）

目标：实现 `2026-05-29-integration-test-children-story-site.md` 定义的两层测试。第 1 层 fake runner 冒烟（CI）；第 2 层真实部署 + 真实 runner + Playwright 渲染（验收门，手动/标记）。

产出文件：
- `tests/e2e/childStoryGameMission.e2e.test.ts`（第 1 层，fake runner，CI 可跑）
- `tests/e2e/childStorySiteDeployment.acceptance.test.ts`（第 2 层，真实 runner + Playwright，默认 skip，需环境变量启用）
- `scripts/deploy-and-observe.mjs`（ops agent 用：起后端/前端进程 + serve 故事站 + 健康探活）

测试用例（第 1 层，CI，fake runner）：
```text
registers local runner via API (kind local_cli runnerKind codex)
creates mission and writes MissionCreated event (state exploring)
planner generates ExplorationWorkflow (classification requirement_unclear)
orchestrator executes DAGRun with fake runner and produces artifacts
mission state changes to changing after ExplorationWorkflow
timeline shows all required event types
run trace shows dagRun messages artifacts
fake runner produced index.html stories.js style.css in workspace
feedback signal triggers second plan-next
second plan-next also selects ExplorationWorkflow due to feedback
```

测试用例（第 2 层，验收门，黑盒全自动 + 真实 runner + Playwright，详见集成测试文档）：
```text
（测试只做用户动作：提交意图 + 轮询 status + 浏览器验收，不调内部编排接口）
user submits intent via API/UI with full_autonomous mode
system auto-drives the mission without any manual plan-next/dag-runs call
status polling reaches outcome succeeded within timeout
status exposes a reachable deployUrl
served site renders home page (Playwright)
story list is visible with at least 3 stories
entering a story shows content and a working pager
no console errors on the served site
[降级] if codex unavailable, system completes using claude runner
[失败处理] if outcome is blocked/exhausted, test fails -> 修系统而非改测试
```

验收门槛：
- 第 1 层在 CI 全绿（`pnpm test:e2e` + `VITE_FAKE_RUNNER=1`）。
- 第 2 层在装有 codex/claude 的机器跑通（`ACCEPTANCE=1`）：黑盒提交意图后系统全自动产出可访问故事站且 Playwright 渲染通过，即闭环成立标志。

边界（必须不发生）：
```text
第 1 层不得调用真实 LLM CLI
第 2 层测试不得调用 plan-next / dag-runs 等内部编排接口（必须黑盒）
第 2 层不得在无真实 runner 的 CI 环境强制执行（默认 skip）
不得把 runner 输出的 secrets 写入测试日志
测试失败时修系统，不得为了过测试而放宽断言
```

---

## 完成判定（可切 goal 模式的信号）

```text
Task 2~11 全部单元/集成测试绿 + pnpm build 通过
Task 12 第 1 层 CI 绿
Task 12 第 2 层在真实机器跑通一次（儿童故事网站真实生成 + Playwright 渲染通过 + 一轮 feedback）
```

满足以上即闭环成立，后续可用 goal 模式自动推进 v0.1B 自举。







