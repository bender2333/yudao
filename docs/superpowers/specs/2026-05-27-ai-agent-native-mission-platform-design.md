# AI/Agent Native Mission Platform Design

Date: 2026-05-27
Status: Draft for review

## 1. Product Positioning

AI/Agent Native Mission Platform is a mission-first platform for software and product evolution. It is not a traditional project management tool with AI added on top, and it is not a one-off agent runner.

The platform treats a Mission as a long-running evolving object. Agents are the primary operators. Humans provide intent, constraints, corrections, and approvals when required. The platform owns mission state, execution history, artifacts, routing, feedback, and learning records.

The core product promise is:

```text
Turn product/software intent into an autonomous, observable, steerable Mission lifecycle.
```

## 2. Design Principles

1. Mission first, not task first.
   A task or PR is only one execution unit inside a longer Mission.

2. Agent native by default.
   Hermes, OpenClaw, Codex, Claude, and other agents are not plugins bolted onto a PM tool. They are execution participants in the lifecycle.

3. Closed loop, not linear SDLC.
   Requirements, design, build, validation, operations, and feedback can route back into each other.

4. Process Orchestrator is business-neutral.
   It behaves like an administrator. It manages rules, state, scheduling, routing, and gates, but does not judge business content.

5. Small loops are DAGs.
   Each stage loop is executed by EvoAgentX-style DAG runs. The broader Mission lifecycle can contain cycles, but each concrete run should remain bounded and traceable.

6. Product UI must make agent work observable.
   The Web Console should show mission progress, DAG runs, node status, transcripts, tool calls, artifacts, decisions, and runtime health.

7. Policy and gate details are reserved interfaces in v0.1.
   v0.1 should not overbuild enterprise governance, security policy, or complex approval workflows.

## 3. Top-Level Architecture

```text
AI / Agent Native Interaction Layer
  -> Mission Core
  -> Business-neutral Process Orchestrator
  -> EvoAgentX-style Small-loop Runtime
  -> Runtime Adapter Layer
  -> Multica-style Web Console
  -> Evolution Loop
```

### 3.1 AI / Agent Native Interaction Layer

This layer provides user and system entry points:

- Hermes
- OpenClaw agent
- Web Console
- Webhook
- Autopilot or schedule trigger
- Future CLI/API clients

All entry points submit structured `MissionCommand` objects to the platform backend. Conversation state in Hermes or OpenClaw is useful context, but it is not the source of truth.

### 3.2 Mission Core

Mission Core owns the durable product state:

- `Mission`
- `MissionThread`
- `MissionRelation`
- `MissionEvent`
- `Artifact`
- `Decision`
- `ApprovalRequest`

`MissionEvent` is append-only. The platform should be able to reconstruct why a Mission moved from one loop to another by reading events, artifacts, node results, and orchestration decisions.

### 3.3 Business-neutral Process Orchestrator

The Process Orchestrator is the lifecycle administrator.

It consumes structured facts such as:

- `status`
- `confidence`
- `risk_level`
- `missing_inputs`
- `artifacts`
- `test_result`
- `review_result`
- `approval_required`
- `recommended_next_action`

It decides:

- continue current loop
- route to another loop
- start a DAG run
- ask the user a blocking question
- create a child Mission
- require a gate
- pause or archive

It must not encode product/business semantics directly. Domain judgment belongs to agents, evaluators, users, and artifacts. The orchestrator only routes based on declared facts and configured rules.

### 3.4 EvoAgentX-style Small-loop Runtime

The platform should reuse EvoAgentX as a reference model for bounded DAG execution, not as the whole production platform.

Reference mapping:

```text
EvoAgentX WorkFlowGraph -> DAGTemplate / DAGRun
EvoAgentX WorkFlowNode  -> DAGNodeTemplate / NodeRun
EvoAgentX Agent         -> RoleAgent / RuntimeAgent
EvoAgentX Action        -> AgentActionRun
EvoAgentX Environment   -> RunMessage / ExecutionTrace
EvoAgentX Evaluator     -> EvaluationRecord / EvolutionLoop
```

Use EvoAgentX ideas for:

- DAG workflow structure
- Node input/output contracts
- Agent/action model
- execution message trace
- evaluator and benchmark concepts
- optimizer inspiration

Do not rely on EvoAgentX for:

- production scheduler
- persistent Mission state
- permissions and sandboxing
- platform approval system
- Web Console
- full backend lifecycle orchestration

### 3.5 Runtime Adapter Layer

Runtime adapters connect platform NodeRuns to real agent runtimes.

Contract:

```text
RuntimeAdapter.execute(NodeExecutionRequest) -> RuntimeSession
RuntimeSession.messages -> RunMessage stream
RuntimeSession.result -> RunResult
```

Initial adapter targets:

- `HermesAdapter`: ACP-style runtime protocol
- `OpenClawAdapter`: OpenClaw agent JSON protocol
- `CodexAdapter`: Codex app-server / JSON-RPC style execution
- `ClaudeAdapter`: Claude stream-json execution
- `MCPToolAdapter`: MCP tool execution

ACP is a runtime adapter protocol detail. It is not the platform API.

### 3.6 Multica-style Web Console

Multica is a reference for product shell, runtime connection, agent status, task transcript, and autopilot-style triggers.

The platform should translate those ideas into Mission-native objects:

```text
Multica Issue       -> Mission
Multica AgentTask   -> DAGRun / NodeRun / ActionRun
Multica TaskMessage -> RunMessage
Multica ChatSession -> MissionThread
Multica Autopilot   -> MissionTrigger / Autopilot
```

Main v0.1 Console surfaces:

- Mission Console
- Mission Detail
- Runs and Timeline
- NodeRun transcript
- Artifacts and Decisions
- Approvals
- Agents
- Runtime Targets
- Autopilots
- Templates

The UI should show what agents are doing, why the system routed a Mission, which node produced which artifact, and where human input is required.

### 3.7 Evolution Loop

The Evolution Loop turns execution history into platform improvement.

```text
Run History
  -> Benchmark Dataset
  -> Evaluator
  -> Optimizer Candidate
  -> Sandbox Replay
  -> Promotion Gate
  -> New Template Version
```

v0.1 should record enough data to make evolution possible later. Optimizer candidates are not production changes. They must go through replay, comparison, and promotion.

## 4. Mission Lifecycle

Mission has four recursive loops:

```text
1. 需求探索与瓦解
2. 设计与构建
3. 检查与验证
4. 运维与反馈
```

These loops are not a strict linear pipeline. They are a lifecycle graph. A Mission can move forward, route back, create child Missions, or pause for input.

### 4.1 需求探索与瓦解

Goal: turn vague input into actionable Mission structure.

Inputs:

- natural language request
- Hermes/OpenClaw conversation
- issue or PR feedback
- logs and screenshots
- repository context
- operations alerts

Outputs:

- `MissionBrief`
- `QuestionSet`
- `AssumptionSet`
- `ScopeBoundary`
- `AcceptanceCriteria`
- `ChildMissionProposal`

Self-loop conditions:

- blocking questions exist
- required context is missing
- assumptions are low confidence
- scope is unclear
- acceptance criteria are incomplete
- dependencies are unclear

Progression rule:

```text
readiness + autonomy_mode -> ask / proceed / gate / pause
```

In default autonomous mode, the system asks only necessary blocking questions. Non-blocking assumptions are recorded and the Mission can proceed.

### 4.2 设计与构建

Goal: convert the Mission Brief into design, plan, implementation, and patch artifacts.

Inputs:

- `MissionBrief`
- `ScopeBoundary`
- `AssumptionSet`
- `RiskSet`
- `AcceptanceCriteria`
- repository or service context
- autonomy mode and policy boundary

Typical DAG runs:

- `DesignRun`
- `PlanningRun`
- `ImplementationRun`
- `FixRun`

Outputs:

- `DesignNote`
- `ImplementationPlan`
- `PatchSet`
- `Branch`
- `ChangedFilesSummary`
- `LocalBuildResult`
- `PRDraft`
- `ReleaseNotesDraft`

If implementation reveals that requirements or scope assumptions are invalid, the orchestrator can route the Mission back to 需求探索与瓦解.

### 4.3 检查与验证

Goal: test, review, and classify the result. Validation failures should not all route to the same place.

Core failure routing:

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

Typical DAG nodes:

- `test_select`
- `test_run`
- `review_diff`
- `acceptance_check`
- `failure_classify`
- `verification_verdict`

The key design point is three-way classification:

1. Requirement unclear or validation contradiction -> 需求探索与瓦解
2. Boundary, architecture, or design gap -> 设计与构建
3. Functional bug or implementation defect -> implementation fix path

### 4.4 运维与反馈

Goal: make runtime signals part of Mission evolution.

Operations is not the end of the lifecycle. It can create new Mission input, reopen current Mission loops, or produce evolution records.

Typical DAG runs:

- `ReleaseRun`
- `PostDeployVerifyRun`
- `IncidentRun`
- `RollbackRun`
- `RetrospectiveRun`

Routing examples:

- requirement changed -> 需求探索与瓦解
- architecture, boundary, or capacity issue -> 设计与构建
- clear implementation defect -> implementation fix path
- production incident -> new Incident Mission
- high-risk release or rollback -> gate
- stable outcome -> learning/evaluation record

## 5. DAG and Node Granularity

The broader Mission lifecycle can contain cycles, but each loop execution should be a bounded DAG.

Hierarchy:

```text
Mission
  Loop
    DAGRun
      NodeRun
        AgentActionRun
          ToolCall
```

`NodeRun` is the minimum control unit.

A NodeRun can:

- retry
- skip
- insert supplemental node
- trigger gate
- route to another node
- write artifact
- classify failure
- emit route recommendation

Rule:

```text
NodeRun outputs route_recommendation.
Process Orchestrator makes the actual routing decision.
```

This separation keeps agent/runtime execution from becoming the lifecycle authority.

## 6. Autonomy Modes

The platform reserves four autonomy modes across loops and nodes:

```text
1. 人工主导
2. 半自主推荐
3. 默认自主
4. 全自主
```

v0.1 should implement and default to mode 3: 默认自主.

Default autonomous behavior:

- proceed when readiness is sufficient
- ask only blocking questions
- record non-blocking assumptions
- gate only when policy boundary or risk threshold requires it
- keep all decisions visible in Mission events

Modes 1, 2, and 4 should be represented in configuration so the model can evolve without changing core data structures.

## 7. Policy and Gate Boundary

v0.1 should reserve policy and gate interfaces without implementing a complete governance system.

Do:

- reserve gate interfaces
- store autonomy mode per loop or node
- record why a gate was triggered
- allow runtime and node outputs to request approval
- make routing decisions auditable as events

Do not:

- build enterprise approval workflow now
- hard-code every security policy
- encode business semantics in the orchestrator
- turn every gate into manual review
- block the MVP on complete governance

Minimal contracts:

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

## 8. Core Data Model

### Mission Core

- `Mission`
- `MissionThread`
- `MissionRelation`
- `MissionEvent`
- `Artifact`
- `Decision`
- `ApprovalRequest`

### Runtime Execution

- `DAGTemplate`
- `DAGNodeTemplate`
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

### Evolution

- `EvaluationRecord`
- `MetricSnapshot`
- `BenchmarkSample`
- `EvolutionCandidate`
- `ReplayRun`
- `TemplateVersion`
- `PromotionDecision`

## 9. API Surface v0.1

API groups:

- Command API
- Mission API
- Runtime API
- Orchestrator API
- Realtime API
- Config API

Principle:

```text
Commands mutate.
Queries project.
Events explain.
```

All external entry points should submit `MissionCommand`.

State source:

```text
Mission Platform Backend
```

Not state sources:

- Hermes conversation
- OpenClaw conversation
- Web UI local state
- webhook source

## 10. Web Console v0.1

The Web Console should be Multica-style in product feeling, but Mission-native in data model.

Primary screens:

1. Mission Console
   List Missions, status, loop, risk, next action, and owner agent.

2. Mission Detail
   Show brief, scope, acceptance, assumptions, decisions, artifacts, and related Missions.

3. Runs and Timeline
   Show DAGRun, NodeRun, ActionRun, messages, tool calls, failures, and route decisions.

4. Approvals
   Show pending gate requests and decision history.

5. Agents
   Configure role agents, skills, plugins, and environment assumptions.

6. Runtime Targets
   Configure Hermes, OpenClaw, Codex, Claude, MCP, credentials, and connection health.

7. Autopilots
   Configure webhook/schedule/ops triggers that create or update Missions.

8. Templates
   Manage DAG templates and template versions.

## 11. v0.1 Roadmap

### 11.1 v0.1A: Full-loop Thin Slice

Goal: prove the closed loop works.

Required flow:

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

Acceptance:

- entry agent creates `MissionThread` and `Mission`
- exploration DAG outputs brief, questions, assumptions, and acceptance criteria
- default autonomy asks necessary questions or auto-progresses
- design/build DAG outputs plan and patch
- verification DAG performs three-way routing
- Web Console shows Mission, DAGRun, NodeRun, and transcript
- all runs and nodes generate event, artifact, and evaluation records

### 11.2 v0.1B: Self-bootstrap

Goal: the platform can develop itself.

Definition:

```text
Platform registers its own repo as Self Project.
It uses its own Mission, DAG, Node, Web Console, and EvaluationRecord systems to develop itself.
```

Acceptance:

- self repo is registered
- at least one platform feature is initiated via Mission
- DAG/Node execution modifies platform code
- patch or PR draft is generated
- verification failure routes correctly
- core/security/runtime changes trigger a gate
- bootstrap produces retrospective artifact and evolution candidates

## 12. Explicit Non-goals for v0.1

v0.1 should not attempt to fully solve:

- enterprise governance
- deep permission matrix
- advanced security sandbox
- organization-wide workflow customization
- complete optimizer-driven auto-evolution
- full project management replacement
- complex billing, tenancy, or marketplace
- detailed business-domain rule authoring

These areas should have reserved interfaces and extension points where needed, but should not dominate the initial architecture.

## 13. Implementation Planning Confirmations

These are not unresolved architecture gaps. They are the confirmation points to settle before the implementation plan.

Recommended defaults for v0.1 planning:

1. Start as a local-first developer platform service that can later become a multi-user service.
2. Treat Hermes and OpenClaw as first-class entry agents through the same `MissionCommand` contract.
3. Implement one runtime adapter first, then add the second through the same adapter interface.
4. Scope self-bootstrap to this platform repository first, while keeping the `SelfProject` model generic.
5. Build the minimum Web Console around Mission Detail, Runs/Timeline, Node transcript, Agents, and Runtime Targets.
