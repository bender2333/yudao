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

4. Spec-driven small loops, Mission-owned big loop.
   OpenSpec-style artifacts drive bounded SpecChange loops: clarity, behavior contracts, implementation tasks, and verification evidence. Mission Core still owns long-running lifecycle state, routing history, feedback, relations, and learning.

5. Process Orchestrator is business-neutral.
   It behaves like an administrator. It manages rules, state, scheduling, routing, and gates, but does not judge business content.

6. Small loops are DAGs.
   Each stage loop is executed by EvoAgentX-style DAG runs. The broader Mission lifecycle can contain cycles, but each concrete run should remain bounded and traceable.

7. Product UI must make agent work observable.
   The Web Console should show mission progress, DAG runs, node status, transcripts, tool calls, artifacts, decisions, and runtime health.

8. Policy and gate details are reserved interfaces in v0.1.
   v0.1 should not overbuild enterprise governance, security policy, or complex approval workflows.

## 3. Top-Level Architecture

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
- `MissionState`
- `MissionGoal`
- `MissionMemory`
- `MissionBacklog`
- `MissionHealth`
- `FeedbackSignal`
- `Artifact`
- `Decision`
- `ApprovalRequest`

`MissionEvent` is append-only. The platform should be able to reconstruct why a Mission moved from one loop to another by reading events, artifacts, node results, and orchestration decisions.

### 3.3 OpenSpec-style Spec Artifact Layer

OpenSpec is a strong reference for bounded change work inside a Mission. It should be used as an artifact grammar for proposals, behavior specs, design notes, task lists, verification scenarios, and archival sync.

The platform should not treat OpenSpec as the Mission database, Mission big-loop state machine, or scheduler. Mission Core owns long-running state. Process Orchestrator owns routing. DAG Runtime owns execution. OpenSpec-style artifacts define the behavioral contract and change intent for one bounded SpecChange loop.

Reference mapping:

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

Use OpenSpec ideas for:

- spec-first change proposals
- behavior requirements and scenario-based acceptance
- clear separation between proposed change and canonical spec
- task checklist as implementation seed
- verification against declared scenarios
- archiving accepted changes back into stable specs

Do not use OpenSpec to replace:

- Mission lifecycle state
- Mission big-loop state machine
- Mission memory and learning
- Mission relation graph
- Process Orchestrator routing
- runtime scheduling
- runtime adapter protocols
- Web Console state
- approval and policy boundaries

### 3.4 Business-neutral Process Orchestrator

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

### 3.5 EvoAgentX-style Small-loop Runtime

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

### 3.6 Runtime Adapter Layer

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

### 3.7 Multica-style Web Console

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
- Spec Changes
- Runs and Timeline
- NodeRun transcript
- Artifacts and Decisions
- Approvals
- Agents
- Runtime Targets
- Autopilots
- Templates

The UI should show what agents are doing, why the system routed a Mission, which node produced which artifact, and where human input is required.

### 3.8 Evolution Loop

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

### 4.0 Mission Big Loop and SpecChange Small Loops

Mission is the long-running big loop. OpenSpec-style artifacts are better suited to bounded, one-change small loops inside that Mission.

A Mission can contain many SpecChanges over time:

```text
Mission
  -> SpecChange #1
  -> SpecChange #2
  -> Incident SpecChange
  -> Refactor SpecChange
  -> Feedback SpecChange
```

Each SpecChange can use OpenSpec-style artifacts to clarify, design, implement, verify, and archive one bounded change. The Mission big loop decides whether to create another SpecChange, route back to exploration, open a child Mission, wait for feedback, or continue operating.

Flow:

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

Practical role by loop:

- 需求探索与瓦解: create proposal, define behavior scope, write scenarios
- 设计与构建: turn accepted spec into design note and task seed
- 检查与验证: verify implementation against declared scenarios
- 运维与反馈: capture runtime drift and create follow-up spec changes

Rule:

```text
OpenSpec-style spec artifacts define what should change in one bounded SpecChange.
Mission Core defines what happened across the long-running Mission.
```

Loop mapping:

| Mission loop | OpenSpec artifact role | Mission output | Route back when |
| --- | --- | --- | --- |
| 需求探索与瓦解 | `proposal.md`, scenario draft, scope delta | Mission Brief, acceptance, assumptions | request unclear, scope too wide, scenario mismatch |
| 设计与构建 | `design.md`, `tasks.md` | implementation plan, patch, branch | spec gap, architecture gap, implementation drift |
| 检查与验证 | delta specs, `verify` evidence | validation verdict, fix request, archive decision | requirement conflict, design gap, bug |
| 运维与反馈 | archive/sync history, follow-up delta spec | retrospective, new SpecChange, learning record | runtime drift, incident, capacity issue |

Bounded SpecChange lifecycle:

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

Failure or feedback routes:

```text
draft / clarified        -> exploration loop
designed / planned       -> design/build loop
implemented / verified   -> verification loop
accepted / archived      -> ops/feedback loop
runtime drift            -> new SpecChange
```

The Mission event stream records every SpecChange state transition and every big-loop routing decision. The spec files provide human- and agent-readable intent, requirements, design, tasks, and evidence for the bounded change.

Mission big-loop state is separate:

```text
exploring
  -> changing
  -> verifying
  -> operating
  -> learning
  -> exploring / changing / child_mission / archived
```

The big loop is not a DAG and is not an OpenSpec change. It is a long-running lifecycle graph that composes many bounded DAG runs and SpecChange loops.

### 4.0.1 Dynamic Workflow Generation Boundary

OpenSpec-style Markdown is a strong fit for describing one bounded change:

- why the change is needed
- what behavior should change
- which acceptance scenarios apply
- what the technical design is
- which tasks should be executed
- what verification evidence exists
- whether the change can be archived into canonical specs

If a task can be completed in one pass, and one Workflow DAG can move from proposal/design/tasks/spec scenarios to verification and archive, it is a strong fit for an OpenSpec-style contract.

The Mission system is different at the big-loop level. A Mission may generate the next workflow dynamically because of validation conflicts, operations feedback, new user input, architecture risk, or runtime drift. The question of "what workflow should be generated next" belongs to the Mission layer, not to OpenSpec itself.

Responsibility boundary:

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

Mission Planner should consume:

- `MissionState`
- `MissionGoal`
- `MissionMemory`
- `MissionEvent`
- `FeedbackSignal`
- `SpecChange` state and verification result
- current artifacts
- workflow template registry
- autonomy mode
- policy/gate boundary

It outputs:

- `WorkflowIntent`
- `SpecChangeDraft` or `SpecChangeUpdate`
- selected `DAGTemplate`
- `DAGRunPlanSeed`
- `RouteRecommendation`
- `BlockingQuestion` or `Assumption`

Therefore, OpenSpec can be workflow generation context and one output format, but it should not be the dynamic workflow generator.

### 4.0.2 Mission Planner

Mission Planner is the lightweight next-step selector inside the Mission big loop. It does not execute tasks directly and does not replace the Process Orchestrator. Its responsibility is to decide which bounded workflow should run next, select the appropriate template, and record why that choice was made.

It answers:

```text
Given the current Mission state, what workflow should be generated next?
```

It does not answer:

```text
How should this workflow be executed?
Which runtime should run this node?
Should this gate be approved?
How should the full task tree inside this workflow be decomposed?
```

Key boundary:

```text
Mission Planner produces WorkflowIntent and planning rationale.
WorkflowTemplate / DAGRun define the structure of one bounded workflow.
NodeRuns inside the DAG perform concrete requirement decomposition, design decomposition, task decomposition, test selection, and failure classification.
Process Orchestrator schedules DAGRuns based on Planner output and policy/gate state.
```

The Planner is therefore not a full task decomposer. It may produce a seed for the next workflow, but it must not become a black box that compresses business judgment, engineering design, and execution planning into one component.

Responsibility boundary:

| Component | Owns | Does not own |
| --- | --- | --- |
| Mission Planner | next workflow intent, situation classification, template selection, planning rationale, bounded SpecChange action | runtime execution, final routing authority, policy approval, detailed task decomposition |
| Process Orchestrator | lifecycle routing, scheduling, gate decision, event routing | business judgment, spec authoring |
| OpenSpec-style artifacts | bounded change contract, scenario, design, tasks, verification evidence | dynamic workflow generation, Mission memory |
| EvoAgentX-style Runtime | execute generated DAG and NodeRuns | decide Mission strategy or own Mission lifecycle |

Mission Planner inputs:

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

Mission Planner outputs:

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

Basic flow for generating the next workflow:

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

`classify_current_situation` should identify at least:

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

This means Mission Planner can generate workflows repeatedly, but each generated workflow should remain bounded:

```text
Mission big loop owns continuity.
SpecChange owns one change contract.
DAGRun owns one bounded execution.
NodeRun owns the minimum control unit for concrete decomposition, execution, verification, and failure classification.
```

The Planner only decides what type of workflow should run next. The concrete decomposition of requirements, design, implementation, and verification inside that workflow belongs to the corresponding DAG nodes, and is written back to the Mission through artifacts, RunMessages, and route recommendations.

### 4.0.3 Workflow Template Registry

Mission Planner should not freely generate arbitrary workflows. v0.1 should use a `WorkflowTemplate Registry`: the Planner selects, parameterizes, or performs limited composition over registered templates based on current state.

This gives the system both dynamism and control:

```text
Dynamism: Mission Planner can generate the next workflow based on feedback.
Control: workflows mostly come from known templates instead of arbitrary synthesis.
```

v0.1 template types:

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

Template metadata:

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

Planner template selection flow:

```text
classify_current_situation
  -> match_trigger_conditions
  -> rank_candidate_templates
  -> check_required_inputs
  -> bind_specchange_or_create_draft
  -> bind_template_inputs
  -> produce_DAGRunPlanSeed
```

Allowed dynamic capabilities:

- select template
- fill template parameters
- trim template-level node sets based on SpecChange scope
- declare runtime/tool availability requirements
- decide whether to ask blocking questions based on autonomy mode
- provide decomposition context to DAG nodes

Disallowed in v0.1:

- free-form full workflow generation without templates
- generating a complete business task tree inside the Planner
- automatically introducing unregistered runtimes
- automatically weakening gate/policy
- automatically promoting optimizer candidates into production templates
- modifying workflow without Mission event records

When Planner cannot find a suitable template:

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

This means v0.1 dynamic workflow generation is:

```text
template selection + parameter binding + bounded node composition
```

not fully open workflow synthesis.

### 4.0.4 Mission Big-loop State Model

The Mission big loop needs its own long-running state model. It should not be inferred from OpenSpec change state, because OpenSpec focuses on one bounded change while Mission focuses on continuous evolution.

Core objects:

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

`MissionState` represents the current lifecycle position:

```text
exploring
changing
verifying
operating
learning
paused
archived
```

State is not linear. It can route back to any relevant stage based on feedback and verification results:

```text
operating -> learning -> exploring
operating -> changing
verifying -> exploring
verifying -> changing
learning -> child_mission
paused -> exploring / changing / operating
```

`MissionMemory` stores long-running context:

- confirmed goals and non-goals
- long-term constraints
- user preferences
- architecture decisions
- failure patterns
- historical assumptions
- important feedback
- runtime lessons
- closed and open risks

`MissionBacklog` stores items that should not enter the current SpecChange yet:

- follow-up idea
- deferred improvement
- unresolved question
- tech debt
- operational issue
- evolution candidate
- child mission proposal

`FeedbackSignal` is the standard input from operations and the external world into the Mission big loop:

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

Common `signal_type` values:

- user_feedback
- production_incident
- metric_regression
- test_flake
- performance_degradation
- security_alert
- requirement_change
- usage_observation
- agent_failure

Mission Planner uses these long-running objects to decide the next workflow instead of looking only at the current OpenSpec change.

Principle:

```text
SpecChange explains the bounded work.
MissionState explains where the long-running mission is.
MissionMemory explains why future workflows should be generated differently.
FeedbackSignal explains why the big loop should move again.
```

### 4.0.5 Mission Planner Decision Matrix

Mission Planner should not be a black box. Every generated workflow must produce an auditable `WorkflowGenerationReason`.

`WorkflowGenerationReason` includes at least:

- current situation classification
- evidence
- selected workflow template
- rejected alternatives
- SpecChange action
- assumptions
- missing inputs
- gate recommendation
- expected outputs

Baseline decision matrix:

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

Planner output does not execute directly. It submits a plan:

```text
MissionPlannerRun
  -> WorkflowIntent
  -> WorkflowGenerationReason
  -> DAGRunPlanSeed
  -> OrchestrationDecision request
```

Then the Process Orchestrator decides whether to schedule, ask, gate, pause, or route.

This matrix is the initial v0.1 strategy, not fixed business rules. It can evolve later through EvaluationRecord, ReplayRun, and TemplateVersion.

### 4.0.6 Mission Event Stream and Projections

The Mission big loop must be driven by an append-only event stream. Current database state is a projection, not the only source of truth.

Principle:

```text
Commands request change.
Events record facts.
Projections support reading.
Planner uses projections plus event history.
Orchestrator writes routing decisions as events.
```

Standard event structure:

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

Core event types:

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

Typical event chain:

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

Projection model:

| Projection | Purpose |
| --- | --- |
| `MissionSummaryView` | Mission list, status, risk, next action |
| `MissionTimelineView` | user-readable timeline |
| `MissionPlannerContextView` | Planner input for next decision |
| `SpecChangeView` | current proposal/design/tasks/scenario state |
| `RunTraceView` | DAGRun, NodeRun, ActionRun, ToolCall trace |
| `FeedbackInboxView` | operations and user feedback entry |
| `ApprovalInboxView` | gate requests and decisions |
| `BacklogView` | follow-ups, deferred items, child mission proposals |
| `EvolutionDatasetView` | replay, evaluation, optimizer samples |

Event stream and projection boundary:

```text
Event Stream:
  durable fact history, append-only, replayable

Projection:
  query optimization, UI state, planner context, rebuildable
```

v0.1 does not need a complete event sourcing infrastructure, but it must preserve these constraints:

- every workflow generation has `WorkflowPlanned`
- every route has `RouteDecided`
- every gate has request/decision events
- every artifact is linked to mission/specchange/run/node
- every automatic assumption is recorded
- projections can be rebuilt and should not be the only source of truth

This is also the foundation for bootstrap and evolution: without events, there is no replay; without replay, there is no reliable Evolution Loop.

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
- OpenSpec-style `SpecChange` draft
- requirement scenarios

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

OpenSpec role:

- create or update `proposal.md`
- draft behavior requirement scenarios under the change
- identify gaps between requested behavior and canonical specs
- turn accepted clarification into a Mission-bound `SpecChange`

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
- updated `design.md`
- updated `tasks.md`

If implementation reveals that requirements or scope assumptions are invalid, the orchestrator can route the Mission back to 需求探索与瓦解.

OpenSpec role:

- use `design.md` as the technical approach artifact
- use `tasks.md` as a seed for DAG nodes or implementation checklist
- keep implementation aligned with declared scenarios
- avoid changing canonical specs until verification accepts the change

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

OpenSpec role:

- verify code/tests against requirement scenarios
- classify whether failure is a spec ambiguity, design gap, or implementation defect
- record verification evidence against the relevant `SpecChange`
- promote accepted behavior only after validation passes

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

OpenSpec role:

- use runtime feedback to create or update a `SpecChange`
- capture production-learned behavior as future scenarios
- archive accepted changes into canonical specs
- keep spec history connected to Mission events and retrospectives

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

Rule:

```text
Mission Planner selects the next workflow type.
DAGRun owns one bounded workflow execution.
NodeRun owns detailed decomposition inside that bounded workflow.
NodeRun outputs route_recommendation.
Process Orchestrator makes the actual routing decision.
```

This separation keeps agent/runtime execution from becoming the lifecycle authority.

This also means task decomposition should not be centralized in Mission Planner. Requirement clarification happens inside `ExplorationWorkflow` nodes; design decomposition happens inside `DesignWorkflow` nodes; implementation task decomposition happens inside `ImplementationWorkflow` or `FixWorkflow` nodes; test selection and failure attribution happen inside `VerificationWorkflow` nodes. Planner only selects which workflow should run next and records why.

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

## 9. API Surface v0.1

API groups:

- Command API
- Mission API
- Spec API
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

3. Spec Changes
   Show proposal, delta specs, scenarios, design, tasks, verification evidence, and archive status.

4. Runs and Timeline
   Show DAGRun, NodeRun, ActionRun, messages, tool calls, failures, and route decisions.

5. Approvals
   Show pending gate requests and decision history.

6. Agents
   Configure role agents, skills, plugins, and environment assumptions.

7. Runtime Targets
   Configure Hermes, OpenClaw, Codex, Claude, MCP, credentials, and connection health.

8. Autopilots
   Configure webhook/schedule/ops triggers that create or update Missions.

9. Templates
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
- exploration DAG creates or updates a Mission-bound SpecChange
- default autonomy asks necessary questions or auto-progresses
- design/build DAG outputs plan, patch, design artifact, and task artifact
- verification DAG performs three-way routing
- verification checks implementation against spec scenarios
- Web Console shows Mission, DAGRun, NodeRun, and transcript
- all runs and nodes generate event, artifact, spec evidence, and evaluation records

#### 11.1.1 v0.1A Implementation Slice

v0.1A is not the complete platform. Its goal is to prove one observable, auditable, loop-capable Mission thin slice.

Minimum user path:

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

First core entities:

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

First APIs:

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

First Web Console screens:

1. `Mission List`
   Show Mission, state, risk, next action, last event.

2. `Mission Detail + Timeline`
   Show goal, current state, SpecChange, artifact, decision, event timeline.

3. `Run / Node Trace`
   Show DAGRun, NodeRun, ActionRun, RunMessage, Artifact, verification verdict.

First WorkflowTemplates:

- `ExplorationWorkflow`
- `SpecChangeDraftWorkflow`
- `DesignWorkflow`
- `ImplementationWorkflow`
- `VerificationWorkflow`
- `FixWorkflow`
- `RetrospectiveWorkflow`

v0.1A can start with a mocked runtime adapter:

```text
MockRuntimeAdapter:
  accepts NodeExecutionRequest
  emits RunMessages
  writes deterministic Artifact
  returns RunResult
```

But the interface must be shaped like a real runtime adapter so it can later be replaced by Hermes/OpenClaw/Codex/Claude.

v0.1A acceptance criteria:

- can create a Mission from an entry point
- Mission creation writes to the event stream
- Planner can generate `WorkflowIntent`, `WorkflowGenerationReason`, and `DAGRunPlanSeed`
- Planner can select WorkflowTemplate
- Orchestrator can materialize `DAGRunPlanSeed` into a schedulable `DAGRunPlan` or `DAGRun`
- can create or update SpecChange
- can execute at least one DAGRun
- DAGRun includes at least exploration, implementation, and verification NodeRuns
- NodeRun can write RunMessage and Artifact
- verification node can emit pass/fail/verdict
- Orchestrator can write `RouteDecided` from verdict
- failure can route to exploration/fix/design
- Web Console can show Mission timeline and run trace
- FeedbackSignal can trigger the next planning run
- all automatic assumptions are recorded as event/artifact

v0.1A explicit non-goals:

- multi-tenancy
- complete permission model
- real production deployment
- full agent marketplace
- autonomous optimizer promotion
- complex approval workflow
- full OpenSpec CLI compatibility
- multi-runtime concurrent scheduling optimization

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
- accepted bootstrap changes can be archived back into canonical specs

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
