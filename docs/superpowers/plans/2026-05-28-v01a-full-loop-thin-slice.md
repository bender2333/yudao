# v0.1A Full-loop Thin Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first Mission Platform thin slice that creates a Mission, plans the next bounded workflow, schedules and executes DAG runs, records events/artifacts, shows timeline and run trace, lets feedback trigger the next planning cycle, and validates the installed system by registering local Codex/Claude Code runners from the Web UI to build a children's story game.

**Architecture:** Use a TypeScript monorepo-style single app with shared domain contracts, a local in-memory event store, a lightweight Mission Planner, a Process Orchestrator, a MockRuntimeAdapter for deterministic tests, a LocalCliRuntimeAdapter for installed local runners, a Hono HTTP API, and a Vite React Web Console. The Planner only emits `WorkflowIntent`, `WorkflowGenerationReason`, and `DAGRunPlanSeed`; the Orchestrator materializes the seed into a schedulable `DAGRun` using the Workflow Template Registry and dispatches NodeRuns through the selected runtime target.

**Tech Stack:** pnpm, TypeScript, Vitest, Hono, @hono/node-server, Vite, React, Testing Library, Playwright for browser verification, Node `child_process` for local CLI runners.

---

## Scope

This plan implements only v0.1A from `docs/superpowers/specs/2026-05-27-ai-agent-native-mission-platform-design-zh.md`.

Included:
- Local-first developer service.
- In-memory event store and rebuildable projections.
- Mission Planner with lightweight boundary.
- Workflow Template Registry.
- Orchestrator materializing `DAGRunPlanSeed` into `DAGRun`.
- MockRuntimeAdapter.
- Runtime Target registration for local CLI runners.
- LocalCliRuntimeAdapter for Codex and Claude Code command execution.
- HTTP APIs listed in the spec.
- Web Console screens for Mission List, Mission Detail + Timeline, and Run / Node Trace.
- Web Console Runtime Targets registration screen.
- FeedbackSignal triggering a later `plan-next` call.
- Installed-system validation target: register local Codex or Claude Code from Web UI and build a children's story game through the Mission lifecycle.

Excluded:
- Persistent database.
- Authentication and multi-tenancy.
- Full production-grade Hermes/OpenClaw/Codex/Claude adapters. v0.1A only supports a minimal local CLI runner contract for Codex and Claude Code.
- Complete OpenSpec CLI compatibility.
- Self-bootstrap v0.1B.
- Enterprise policy engine.

## v0.1A Installed-system Validation Target

The release is not accepted until the installed app can run this path:

```text
Web UI
  -> register local runner: Codex or Claude Code
  -> create Mission: "做一个儿童故事游戏"
  -> Planner emits WorkflowIntent / WorkflowGenerationReason / DAGRunPlanSeed
  -> Orchestrator schedules bounded DAGRun
  -> registered local runner executes NodeRuns
  -> artifacts include MissionBrief, DesignNote, TaskPlan, PatchSummary, VerificationEvidence
  -> generated game files exist under the Mission workspace
  -> Web UI shows Mission timeline and Run Trace
  -> feedback can trigger a second plan-next
```

Current machine preflight observed on 2026-05-29:

```text
codex --version  -> codex-cli 0.134.0
claude --version -> 2.1.152 (Claude Code)
```

The automated CI-style integration test must not call paid or nondeterministic model CLIs. It should use a fake local runner with the same adapter contract. The deployment acceptance test must run against at least one real local runner, preferably Codex first and Claude Code second if available.

## File Structure

Create the application skeleton:

```text
package.json
pnpm-lock.yaml
tsconfig.json
vite.config.ts
index.html
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
    templates/
      workflowTemplates.ts
    orchestrator/
      orchestrator.ts
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
    templates.test.ts
    orchestrator.test.ts
    runtimeTargetRegistry.test.ts
    localCliRuntimeAdapter.test.ts
    api.test.ts
  e2e/
    childStoryGameMission.e2e.test.ts
  app/
    App.test.tsx
```

Boundary decisions:
- `src/shared/domain.ts` owns all public contracts used by backend, tests, and frontend.
- `src/server/event-store/*` owns facts and projections. Projections are rebuildable from events.
- `src/server/planner/missionPlanner.ts` owns only next-workflow choice and rationale.
- `src/server/orchestrator/orchestrator.ts` owns scheduling, DAG materialization, node execution loop, route decisions, and state changes.
- `src/server/runtime/mockRuntimeAdapter.ts` owns deterministic fake execution.
- `src/server/runtime/localCliRuntimeAdapter.ts` owns local command execution for registered Codex/Claude Code style runners.
- `src/server/runtime/runtimeTargetRegistry.ts` owns runtime target registration and health status.
- `src/server/runtime/runtimeRouter.ts` chooses the selected runtime target and uses the built-in MockRuntime only when no local CLI target is selected or the selected target is `runtime_mock`.
- `src/app/*` owns UI only and never invents Mission state locally.

---

### Task 1: Project Skeleton

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `vite.config.ts`
- Create: `index.html`
- Create: `src/app/main.tsx`
- Create: `src/app/App.tsx`
- Create: `src/app/styles.css`

- [ ] **Step 1: Create package and TypeScript config**

Write `package.json`:

```json
{
  "name": "ai-agent-native-mission-platform",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "api": "tsx src/server/index.ts",
    "test": "vitest run",
    "test:e2e": "playwright test",
    "test:watch": "vitest",
    "build": "tsc -p tsconfig.json && vite build",
    "preview": "vite preview --host 127.0.0.1 --port 5173"
  },
  "dependencies": {
    "@hono/node-server": "^1.14.0",
    "hono": "^4.7.0",
    "lucide-react": "^0.468.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@types/node": "^22.10.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.1",
    "tsx": "^4.19.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

Write `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "tests", "vite.config.ts"]
}
```

- [ ] **Step 2: Create Vite config**

Write `vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: []
  }
});
```

- [ ] **Step 3: Create minimal React entry**

Write `index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Mission Platform v0.1A</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/app/main.tsx"></script>
  </body>
</html>
```

Write `src/app/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

Write `src/app/App.tsx`:

```tsx
export function App() {
  return (
    <main className="app-shell">
      <h1>Mission Platform v0.1A</h1>
      <p>Full-loop thin slice</p>
    </main>
  );
}
```

Write `src/app/styles.css`:

```css
:root {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #17202a;
  background: #f6f7f9;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.app-shell {
  min-height: 100vh;
  padding: 24px;
}
```

- [ ] **Step 4: Install dependencies and verify baseline**

Run:

```powershell
pnpm install
pnpm test
pnpm build
```

Expected:

```text
No test files found
vite build completes without TypeScript errors
```

- [ ] **Step 5: Commit skeleton**

Run:

```powershell
git add package.json pnpm-lock.yaml tsconfig.json vite.config.ts index.html src/app
git commit -m "chore: scaffold mission platform v01a app"
```

---

### Task 2: Shared Domain Contracts

**Files:**
- Create: `src/shared/domain.ts`
- Create: `src/shared/eventTypes.ts`
- Create: `src/shared/testFactories.ts`
- Create: `tests/shared/domain.test.ts`

- [ ] **Step 1: Write domain contract tests**

Write `tests/shared/domain.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { makeMissionCommand } from "../../src/shared/testFactories";

describe("shared domain contracts", () => {
  it("creates a mission command with default autonomous mode", () => {
    const command = makeMissionCommand({ text: "Build a login flow" });

    expect(command.source).toBe("web_console");
    expect(command.autonomyMode).toBe("default_autonomous");
    expect(command.text).toBe("Build a login flow");
  });

  it("distinguishes planner seed from materialized DAG run", () => {
    const command = makeMissionCommand({ text: "Investigate flaky tests" });

    expect(command).not.toHaveProperty("dagRunPlan");
    expect(command).not.toHaveProperty("nodeRuns");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm test tests/shared/domain.test.ts
```

Expected:

```text
FAIL tests/shared/domain.test.ts
Cannot find module '../../src/shared/testFactories'
```

- [ ] **Step 3: Define shared domain types**

Write `src/shared/eventTypes.ts`:

```ts
export const missionEventTypes = [
  "MissionCreated",
  "MissionCommandReceived",
  "MissionStateChanged",
  "MissionMemoryRecorded",
  "FeedbackSignalReceived",
  "SpecChangeCreated",
  "SpecChangeUpdated",
  "SpecChangeStateChanged",
  "MissionPlannerRunStarted",
  "WorkflowPlanned",
  "WorkflowTemplateSelected",
  "DAGRunScheduled",
  "DAGRunStarted",
  "DAGRunCompleted",
  "NodeRunStarted",
  "NodeRunCompleted",
  "NodeRunFailed",
  "RunMessageRecorded",
  "ArtifactRecorded",
  "DecisionRecorded",
  "RouteDecided",
  "EvaluationRecorded"
] as const;

export type MissionEventType = (typeof missionEventTypes)[number];
```

Write `src/shared/domain.ts`:

```ts
import type { MissionEventType } from "./eventTypes";

export type MissionState =
  | "exploring"
  | "changing"
  | "verifying"
  | "operating"
  | "learning"
  | "paused"
  | "archived";

export type LoopType = "explore_decompose" | "design_build" | "check_verify" | "operate_feedback";

export type AutonomyMode =
  | "human_led"
  | "semi_autonomous"
  | "default_autonomous"
  | "full_autonomous";

export type MissionCommandSource = "web_console" | "hermes" | "openclaw" | "webhook";

export interface MissionCommand {
  id: string;
  source: MissionCommandSource;
  text: string;
  autonomyMode: AutonomyMode;
  createdAt: string;
}

export interface Mission {
  id: string;
  title: string;
  state: MissionState;
  createdAt: string;
  updatedAt: string;
}

export interface MissionEvent<TPayload = Record<string, unknown>> {
  id: string;
  missionId: string;
  eventType: MissionEventType;
  actorType: "user" | "agent" | "system" | "runtime";
  actorId: string;
  occurredAt: string;
  causationId?: string;
  correlationId?: string;
  loop?: LoopType;
  specChangeId?: string;
  dagRunId?: string;
  nodeRunId?: string;
  payload: TPayload;
}

export interface SpecChange {
  id: string;
  missionId: string;
  state: "draft" | "clarified" | "designed" | "planned" | "implemented" | "verified" | "accepted";
  title: string;
  proposal: string;
  createdAt: string;
  updatedAt: string;
}

export interface WorkflowTemplate {
  id: WorkflowTemplateId;
  name: string;
  loopType: LoopType;
  triggerConditions: string[];
  producedArtifacts: ArtifactKind[];
  nodeTemplates: NodeTemplate[];
  riskLevel: RiskLevel;
  version: number;
}

export type WorkflowTemplateId =
  | "ExplorationWorkflow"
  | "SpecChangeDraftWorkflow"
  | "DesignWorkflow"
  | "ImplementationWorkflow"
  | "VerificationWorkflow"
  | "FixWorkflow"
  | "RetrospectiveWorkflow";

export type NodeKind = "explore" | "design" | "implement" | "verify" | "fix" | "retrospective";

export interface NodeTemplate {
  id: string;
  kind: NodeKind;
  label: string;
  requiredInputs: string[];
  producedArtifacts: ArtifactKind[];
}

export type ArtifactKind =
  | "mission_brief"
  | "assumption_set"
  | "acceptance_criteria"
  | "design_note"
  | "task_plan"
  | "patch_summary"
  | "verification_evidence"
  | "retrospective";

export type RiskLevel = "low" | "medium" | "high";

export type RuntimeTargetKind = "mock" | "local_cli";

export type LocalRunnerKind = "codex" | "claude";

export interface RuntimeTarget {
  id: string;
  name: string;
  kind: RuntimeTargetKind;
  runnerKind?: LocalRunnerKind;
  command?: string;
  args: string[];
  cwd?: string;
  enabled: boolean;
  health: "unknown" | "healthy" | "unhealthy";
  createdAt: string;
  updatedAt: string;
}

export interface WorkflowIntent {
  id: string;
  missionId: string;
  nextLoop: LoopType;
  templateId: WorkflowTemplateId;
  summary: string;
}

export interface WorkflowGenerationReason {
  classification: SituationClassification;
  evidence: string[];
  selectedTemplateId: WorkflowTemplateId;
  rejectedTemplateIds: WorkflowTemplateId[];
  assumptions: string[];
  missingInputs: string[];
  gateRecommendation: "none" | "ask" | "gate";
  expectedOutputs: ArtifactKind[];
}

export type SituationClassification =
  | "requirement_unclear"
  | "clear_bounded_change"
  | "design_gap"
  | "implementation_defect"
  | "verification_contradiction"
  | "runtime_drift"
  | "stable_progress";

export interface DAGRunPlanSeed {
  id: string;
  missionId: string;
  specChangeId: string;
  templateId: WorkflowTemplateId;
  loopType: LoopType;
  autonomyMode: AutonomyMode;
  runtimeTargetId?: string;
  inputRefs: string[];
  createdAt: string;
}

export interface MissionPlannerRun {
  id: string;
  missionId: string;
  workflowIntent: WorkflowIntent;
  reason: WorkflowGenerationReason;
  planSeed: DAGRunPlanSeed;
  createdAt: string;
}

export type RunStatus = "scheduled" | "running" | "completed" | "failed";

export interface DAGRun {
  id: string;
  missionId: string;
  specChangeId: string;
  templateId: WorkflowTemplateId;
  status: RunStatus;
  nodeRuns: NodeRun[];
  createdAt: string;
  updatedAt: string;
}

export interface NodeRun {
  id: string;
  dagRunId: string;
  nodeTemplateId: string;
  kind: NodeKind;
  label: string;
  status: RunStatus;
  startedAt?: string;
  completedAt?: string;
}

export interface RunMessage {
  id: string;
  missionId: string;
  dagRunId: string;
  nodeRunId: string;
  role: "runtime" | "agent" | "system";
  text: string;
  createdAt: string;
}

export interface Artifact {
  id: string;
  missionId: string;
  specChangeId?: string;
  dagRunId?: string;
  nodeRunId?: string;
  kind: ArtifactKind;
  title: string;
  body: string;
  createdAt: string;
}

export interface FeedbackSignal {
  id: string;
  missionId: string;
  source: "web_console" | "ops" | "test" | "user";
  signalType: "user_feedback" | "production_incident" | "test_flake" | "requirement_change" | "agent_failure";
  severity: RiskLevel;
  evidence: string;
  receivedAt: string;
}

export interface MissionSummaryView {
  id: string;
  title: string;
  state: MissionState;
  lastEventType?: MissionEventType;
  nextAction?: string;
  updatedAt: string;
}

export interface MissionDetailView extends MissionSummaryView {
  events: MissionEvent[];
  specChanges: SpecChange[];
  artifacts: Artifact[];
  plannerRuns: MissionPlannerRun[];
  dagRuns: DAGRun[];
}

export interface RunTraceView {
  dagRun: DAGRun;
  messages: RunMessage[];
  artifacts: Artifact[];
}
```

Write `src/shared/testFactories.ts`:

```ts
import type { AutonomyMode, MissionCommand, MissionCommandSource } from "./domain";

export function makeId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID()}`;
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function makeMissionCommand(input: {
  text: string;
  source?: MissionCommandSource;
  autonomyMode?: AutonomyMode;
}): MissionCommand {
  return {
    id: makeId("cmd"),
    source: input.source ?? "web_console",
    text: input.text,
    autonomyMode: input.autonomyMode ?? "default_autonomous",
    createdAt: nowIso()
  };
}
```

- [ ] **Step 4: Run domain tests**

Run:

```powershell
pnpm test tests/shared/domain.test.ts
```

Expected:

```text
PASS tests/shared/domain.test.ts
```

- [ ] **Step 5: Commit domain contracts**

Run:

```powershell
git add src/shared tests/shared
git commit -m "feat: define mission platform domain contracts"
```

---

### Task 3: Event Store and Projections

**Files:**
- Create: `src/server/event-store/inMemoryEventStore.ts`
- Create: `src/server/event-store/projections.ts`
- Create: `tests/server/eventStore.test.ts`

- [ ] **Step 1: Write event store tests**

Write `tests/server/eventStore.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { InMemoryEventStore } from "../../src/server/event-store/inMemoryEventStore";
import { buildMissionDetailView, buildMissionSummaryView } from "../../src/server/event-store/projections";

describe("in-memory event store", () => {
  it("appends events and projects mission summary", () => {
    const store = new InMemoryEventStore();
    const missionId = "mission_1";

    store.append({
      id: "event_1",
      missionId,
      eventType: "MissionCreated",
      actorType: "user",
      actorId: "web",
      occurredAt: "2026-05-28T00:00:00.000Z",
      payload: { title: "Build login", state: "exploring" }
    });

    const summaries = buildMissionSummaryView(store.allEvents());

    expect(summaries).toEqual([
      {
        id: missionId,
        title: "Build login",
        state: "exploring",
        lastEventType: "MissionCreated",
        nextAction: "Plan next workflow",
        updatedAt: "2026-05-28T00:00:00.000Z"
      }
    ]);
  });

  it("rebuilds detail view from event facts", () => {
    const store = new InMemoryEventStore();
    const missionId = "mission_2";

    store.append({
      id: "event_1",
      missionId,
      eventType: "MissionCreated",
      actorType: "user",
      actorId: "web",
      occurredAt: "2026-05-28T00:00:00.000Z",
      payload: { title: "Investigate tests", state: "exploring" }
    });

    store.append({
      id: "event_2",
      missionId,
      eventType: "ArtifactRecorded",
      actorType: "runtime",
      actorId: "mock",
      occurredAt: "2026-05-28T00:00:01.000Z",
      payload: {
        artifact: {
          id: "artifact_1",
          missionId,
          kind: "mission_brief",
          title: "Mission brief",
          body: "Clarify flaky test scope",
          createdAt: "2026-05-28T00:00:01.000Z"
        }
      }
    });

    const detail = buildMissionDetailView(store.allEvents(), missionId);

    expect(detail?.artifacts).toHaveLength(1);
    expect(detail?.events.map((event) => event.eventType)).toEqual(["MissionCreated", "ArtifactRecorded"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm test tests/server/eventStore.test.ts
```

Expected:

```text
FAIL tests/server/eventStore.test.ts
Cannot find module '../../src/server/event-store/inMemoryEventStore'
```

- [ ] **Step 3: Implement event store**

Write `src/server/event-store/inMemoryEventStore.ts`:

```ts
import type { MissionEvent } from "../../shared/domain";

export class InMemoryEventStore {
  private readonly events: MissionEvent[] = [];

  append(event: MissionEvent): MissionEvent {
    this.events.push(structuredClone(event));
    return event;
  }

  appendMany(events: MissionEvent[]): MissionEvent[] {
    for (const event of events) {
      this.append(event);
    }
    return events;
  }

  allEvents(): MissionEvent[] {
    return this.events.map((event) => structuredClone(event));
  }

  eventsForMission(missionId: string): MissionEvent[] {
    return this.events
      .filter((event) => event.missionId === missionId)
      .map((event) => structuredClone(event));
  }
}
```

Write `src/server/event-store/projections.ts`:

```ts
import type {
  Artifact,
  DAGRun,
  MissionDetailView,
  MissionEvent,
  MissionState,
  MissionSummaryView,
  RunMessage,
  RunTraceView,
  SpecChange
} from "../../shared/domain";

interface MissionAccumulator {
  id: string;
  title: string;
  state: MissionState;
  updatedAt: string;
  lastEventType?: MissionEvent["eventType"];
}

export function buildMissionSummaryView(events: MissionEvent[]): MissionSummaryView[] {
  const missions = new Map<string, MissionAccumulator>();

  for (const event of events) {
    const current = missions.get(event.missionId);

    if (event.eventType === "MissionCreated") {
      missions.set(event.missionId, {
        id: event.missionId,
        title: String(event.payload.title),
        state: event.payload.state as MissionState,
        updatedAt: event.occurredAt,
        lastEventType: event.eventType
      });
      continue;
    }

    if (!current) {
      continue;
    }

    if (event.eventType === "MissionStateChanged") {
      current.state = event.payload.state as MissionState;
    }

    current.updatedAt = event.occurredAt;
    current.lastEventType = event.eventType;
  }

  return Array.from(missions.values()).map((mission) => ({
    id: mission.id,
    title: mission.title,
    state: mission.state,
    lastEventType: mission.lastEventType,
    nextAction: nextActionForState(mission.state),
    updatedAt: mission.updatedAt
  }));
}

export function buildMissionDetailView(events: MissionEvent[], missionId: string): MissionDetailView | undefined {
  const missionEvents = events.filter((event) => event.missionId === missionId);
  const summary = buildMissionSummaryView(events).find((item) => item.id === missionId);

  if (!summary) {
    return undefined;
  }

  return {
    ...summary,
    events: missionEvents,
    specChanges: collectPayloadItems<SpecChange>(missionEvents, "specChange"),
    artifacts: collectPayloadItems<Artifact>(missionEvents, "artifact"),
    plannerRuns: collectPayloadItems(missionEvents, "plannerRun"),
    dagRuns: collectPayloadItems<DAGRun>(missionEvents, "dagRun")
  };
}

export function buildRunTraceView(events: MissionEvent[], dagRunId: string): RunTraceView | undefined {
  const dagRun = collectPayloadItems<DAGRun>(events, "dagRun").find((run) => run.id === dagRunId);

  if (!dagRun) {
    return undefined;
  }

  return {
    dagRun,
    messages: collectPayloadItems<RunMessage>(events, "message").filter((message) => message.dagRunId === dagRunId),
    artifacts: collectPayloadItems<Artifact>(events, "artifact").filter((artifact) => artifact.dagRunId === dagRunId)
  };
}

function collectPayloadItems<T>(events: MissionEvent[], key: string): T[] {
  return events
    .map((event) => event.payload[key])
    .filter((value): value is T => Boolean(value));
}

function nextActionForState(state: MissionState): string {
  switch (state) {
    case "exploring":
      return "Plan next workflow";
    case "changing":
      return "Run design/build workflow";
    case "verifying":
      return "Run verification workflow";
    case "operating":
      return "Wait for feedback";
    case "learning":
      return "Record retrospective";
    case "paused":
      return "Wait for input";
    case "archived":
      return "Archived";
  }
}
```

- [ ] **Step 4: Run event store tests**

Run:

```powershell
pnpm test tests/server/eventStore.test.ts
```

Expected:

```text
PASS tests/server/eventStore.test.ts
```

- [ ] **Step 5: Commit event store**

Run:

```powershell
git add src/server/event-store tests/server/eventStore.test.ts
git commit -m "feat: add mission event store projections"
```

---

### Task 4: Workflow Template Registry

**Files:**
- Create: `src/server/templates/workflowTemplates.ts`
- Create: `tests/server/templates.test.ts`

- [ ] **Step 1: Write template registry tests**

Write `tests/server/templates.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { getWorkflowTemplate, listWorkflowTemplates } from "../../src/server/templates/workflowTemplates";

describe("workflow template registry", () => {
  it("registers the v0.1A workflow templates", () => {
    const ids = listWorkflowTemplates().map((template) => template.id);

    expect(ids).toEqual([
      "ExplorationWorkflow",
      "SpecChangeDraftWorkflow",
      "DesignWorkflow",
      "ImplementationWorkflow",
      "VerificationWorkflow",
      "FixWorkflow",
      "RetrospectiveWorkflow"
    ]);
  });

  it("keeps task decomposition inside node templates", () => {
    const template = getWorkflowTemplate("ExplorationWorkflow");

    expect(template.nodeTemplates.map((node) => node.kind)).toEqual(["explore", "explore", "verify"]);
    expect(template.nodeTemplates[0].label).toBe("Clarify mission intent");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm test tests/server/templates.test.ts
```

Expected:

```text
FAIL tests/server/templates.test.ts
Cannot find module '../../src/server/templates/workflowTemplates'
```

- [ ] **Step 3: Implement registry**

Write `src/server/templates/workflowTemplates.ts`:

```ts
import type { WorkflowTemplate, WorkflowTemplateId } from "../../shared/domain";

const workflowTemplates: WorkflowTemplate[] = [
  {
    id: "ExplorationWorkflow",
    name: "Exploration Workflow",
    loopType: "explore_decompose",
    triggerConditions: ["requirement_unclear", "verification_contradiction", "user_feedback"],
    producedArtifacts: ["mission_brief", "assumption_set", "acceptance_criteria"],
    riskLevel: "low",
    version: 1,
    nodeTemplates: [
      {
        id: "explore.intent",
        kind: "explore",
        label: "Clarify mission intent",
        requiredInputs: ["mission_command"],
        producedArtifacts: ["mission_brief", "assumption_set"]
      },
      {
        id: "explore.acceptance",
        kind: "explore",
        label: "Draft acceptance criteria",
        requiredInputs: ["mission_brief"],
        producedArtifacts: ["acceptance_criteria"]
      },
      {
        id: "explore.readiness",
        kind: "verify",
        label: "Check exploration readiness",
        requiredInputs: ["acceptance_criteria"],
        producedArtifacts: ["verification_evidence"]
      }
    ]
  },
  {
    id: "SpecChangeDraftWorkflow",
    name: "SpecChange Draft Workflow",
    loopType: "explore_decompose",
    triggerConditions: ["clear_bounded_change"],
    producedArtifacts: ["mission_brief", "acceptance_criteria"],
    riskLevel: "low",
    version: 1,
    nodeTemplates: [
      {
        id: "specchange.draft",
        kind: "explore",
        label: "Create SpecChange draft",
        requiredInputs: ["mission_command"],
        producedArtifacts: ["mission_brief"]
      }
    ]
  },
  {
    id: "DesignWorkflow",
    name: "Design Workflow",
    loopType: "design_build",
    triggerConditions: ["design_gap", "clear_bounded_change"],
    producedArtifacts: ["design_note", "task_plan"],
    riskLevel: "medium",
    version: 1,
    nodeTemplates: [
      {
        id: "design.note",
        kind: "design",
        label: "Produce design note",
        requiredInputs: ["acceptance_criteria"],
        producedArtifacts: ["design_note"]
      },
      {
        id: "design.tasks",
        kind: "design",
        label: "Decompose implementation tasks",
        requiredInputs: ["design_note"],
        producedArtifacts: ["task_plan"]
      }
    ]
  },
  {
    id: "ImplementationWorkflow",
    name: "Implementation Workflow",
    loopType: "design_build",
    triggerConditions: ["clear_bounded_change"],
    producedArtifacts: ["patch_summary"],
    riskLevel: "medium",
    version: 1,
    nodeTemplates: [
      {
        id: "implementation.patch",
        kind: "implement",
        label: "Produce implementation patch summary",
        requiredInputs: ["task_plan"],
        producedArtifacts: ["patch_summary"]
      }
    ]
  },
  {
    id: "VerificationWorkflow",
    name: "Verification Workflow",
    loopType: "check_verify",
    triggerConditions: ["stable_progress"],
    producedArtifacts: ["verification_evidence"],
    riskLevel: "medium",
    version: 1,
    nodeTemplates: [
      {
        id: "verification.run",
        kind: "verify",
        label: "Run verification checks",
        requiredInputs: ["patch_summary"],
        producedArtifacts: ["verification_evidence"]
      },
      {
        id: "verification.classify",
        kind: "verify",
        label: "Classify verification result",
        requiredInputs: ["verification_evidence"],
        producedArtifacts: ["verification_evidence"]
      }
    ]
  },
  {
    id: "FixWorkflow",
    name: "Fix Workflow",
    loopType: "design_build",
    triggerConditions: ["implementation_defect"],
    producedArtifacts: ["patch_summary", "verification_evidence"],
    riskLevel: "medium",
    version: 1,
    nodeTemplates: [
      {
        id: "fix.patch",
        kind: "fix",
        label: "Fix implementation defect",
        requiredInputs: ["verification_evidence"],
        producedArtifacts: ["patch_summary"]
      }
    ]
  },
  {
    id: "RetrospectiveWorkflow",
    name: "Retrospective Workflow",
    loopType: "operate_feedback",
    triggerConditions: ["runtime_drift", "stable_progress"],
    producedArtifacts: ["retrospective"],
    riskLevel: "low",
    version: 1,
    nodeTemplates: [
      {
        id: "retro.summary",
        kind: "retrospective",
        label: "Record retrospective",
        requiredInputs: ["mission_events"],
        producedArtifacts: ["retrospective"]
      }
    ]
  }
];

export function listWorkflowTemplates(): WorkflowTemplate[] {
  return workflowTemplates.map((template) => structuredClone(template));
}

export function getWorkflowTemplate(id: WorkflowTemplateId): WorkflowTemplate {
  const template = workflowTemplates.find((item) => item.id === id);

  if (!template) {
    throw new Error(`Unknown workflow template: ${id}`);
  }

  return structuredClone(template);
}
```

- [ ] **Step 4: Run template tests**

Run:

```powershell
pnpm test tests/server/templates.test.ts
```

Expected:

```text
PASS tests/server/templates.test.ts
```

- [ ] **Step 5: Commit templates**

Run:

```powershell
git add src/server/templates tests/server/templates.test.ts
git commit -m "feat: register v01a workflow templates"
```

---

### Task 5: Lightweight Mission Planner

**Files:**
- Create: `src/server/planner/missionPlanner.ts`
- Create: `tests/server/planner.test.ts`

- [ ] **Step 1: Write planner boundary tests**

Write `tests/server/planner.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { planNextWorkflow } from "../../src/server/planner/missionPlanner";
import { makeMissionCommand } from "../../src/shared/testFactories";

describe("Mission Planner", () => {
  it("selects ExplorationWorkflow for a vague command and returns only a plan seed", () => {
    const command = makeMissionCommand({ text: "We need a better agent platform" });

    const result = planNextWorkflow({
      missionId: "mission_1",
      missionState: "exploring",
      command,
      events: [],
      specChanges: [],
      feedbackSignals: []
    });

    expect(result.workflowIntent.templateId).toBe("ExplorationWorkflow");
    expect(result.reason.classification).toBe("requirement_unclear");
    expect(result.planSeed.templateId).toBe("ExplorationWorkflow");
    expect(result).not.toHaveProperty("dagRunPlan");
    expect(result.planSeed).not.toHaveProperty("nodeRuns");
  });

  it("selects FixWorkflow for an implementation defect verdict", () => {
    const command = makeMissionCommand({ text: "Fix the failed login regression" });

    const result = planNextWorkflow({
      missionId: "mission_2",
      missionState: "verifying",
      command,
      events: [],
      specChanges: [
        {
          id: "spec_1",
          missionId: "mission_2",
          state: "verified",
          title: "Login regression",
          proposal: "Fix failed login regression",
          createdAt: "2026-05-28T00:00:00.000Z",
          updatedAt: "2026-05-28T00:00:00.000Z"
        }
      ],
      feedbackSignals: [],
      latestVerificationVerdict: "implementation_defect"
    });

    expect(result.workflowIntent.templateId).toBe("FixWorkflow");
    expect(result.reason.classification).toBe("implementation_defect");
  });

  it("selects ExplorationWorkflow after user feedback changes the requirement", () => {
    const command = makeMissionCommand({ text: "Continue mission" });

    const result = planNextWorkflow({
      missionId: "mission_3",
      missionState: "operating",
      command,
      events: [],
      specChanges: [],
      feedbackSignals: [
        {
          id: "feedback_1",
          missionId: "mission_3",
          source: "user",
          signalType: "requirement_change",
          severity: "medium",
          evidence: "The user wants the workflow to ask fewer questions.",
          receivedAt: "2026-05-28T00:00:00.000Z"
        }
      ]
    });

    expect(result.reason.classification).toBe("requirement_unclear");
    expect(result.workflowIntent.nextLoop).toBe("explore_decompose");
  });
});
```

- [ ] **Step 2: Run planner tests to verify failure**

Run:

```powershell
pnpm test tests/server/planner.test.ts
```

Expected:

```text
FAIL tests/server/planner.test.ts
Cannot find module '../../src/server/planner/missionPlanner'
```

- [ ] **Step 3: Implement lightweight planner**

Write `src/server/planner/missionPlanner.ts`:

```ts
import type {
  DAGRunPlanSeed,
  FeedbackSignal,
  MissionCommand,
  MissionEvent,
  MissionPlannerRun,
  MissionState,
  SituationClassification,
  SpecChange,
  WorkflowGenerationReason,
  WorkflowIntent,
  WorkflowTemplateId
} from "../../shared/domain";
import { makeId, nowIso } from "../../shared/testFactories";
import { getWorkflowTemplate, listWorkflowTemplates } from "../templates/workflowTemplates";

export interface MissionPlannerInput {
  missionId: string;
  missionState: MissionState;
  command: MissionCommand;
  events: MissionEvent[];
  specChanges: SpecChange[];
  feedbackSignals: FeedbackSignal[];
  latestVerificationVerdict?: SituationClassification;
}

export function planNextWorkflow(input: MissionPlannerInput): MissionPlannerRun {
  const classification = classifySituation(input);
  const templateId = selectTemplateId(classification);
  const template = getWorkflowTemplate(templateId);
  const specChangeId = input.specChanges.at(-1)?.id ?? makeId("spec");
  const createdAt = nowIso();

  const intent: WorkflowIntent = {
    id: makeId("intent"),
    missionId: input.missionId,
    nextLoop: template.loopType,
    templateId,
    summary: `Run ${template.name} for ${classification}`
  };

  const reason: WorkflowGenerationReason = {
    classification,
    evidence: buildEvidence(input, classification),
    selectedTemplateId: templateId,
    rejectedTemplateIds: listWorkflowTemplates()
      .map((item) => item.id)
      .filter((id) => id !== templateId),
    assumptions: classification === "requirement_unclear" ? ["Non-blocking ambiguity is recorded as an assumption."] : [],
    missingInputs: [],
    gateRecommendation: "none",
    expectedOutputs: template.producedArtifacts
  };

  const planSeed: DAGRunPlanSeed = {
    id: makeId("seed"),
    missionId: input.missionId,
    specChangeId,
    templateId,
    loopType: template.loopType,
    autonomyMode: input.command.autonomyMode,
    inputRefs: [input.command.id],
    createdAt
  };

  return {
    id: makeId("planner"),
    missionId: input.missionId,
    workflowIntent: intent,
    reason,
    planSeed,
    createdAt
  };
}

function classifySituation(input: MissionPlannerInput): SituationClassification {
  if (input.latestVerificationVerdict) {
    return input.latestVerificationVerdict;
  }

  if (input.feedbackSignals.some((signal) => signal.signalType === "requirement_change" || signal.signalType === "user_feedback")) {
    return "requirement_unclear";
  }

  const lower = input.command.text.toLowerCase();

  if (lower.includes("fix") || lower.includes("bug") || lower.includes("failed")) {
    return "implementation_defect";
  }

  if (lower.includes("design") || lower.includes("architecture")) {
    return "design_gap";
  }

  if (lower.includes("verify") || lower.includes("test")) {
    return "stable_progress";
  }

  if (input.missionState === "operating") {
    return "runtime_drift";
  }

  return "requirement_unclear";
}

function selectTemplateId(classification: SituationClassification): WorkflowTemplateId {
  switch (classification) {
    case "implementation_defect":
      return "FixWorkflow";
    case "design_gap":
      return "DesignWorkflow";
    case "stable_progress":
      return "VerificationWorkflow";
    case "runtime_drift":
      return "RetrospectiveWorkflow";
    case "clear_bounded_change":
      return "SpecChangeDraftWorkflow";
    case "verification_contradiction":
    case "requirement_unclear":
      return "ExplorationWorkflow";
  }
}

function buildEvidence(input: MissionPlannerInput, classification: SituationClassification): string[] {
  const evidence = [`Mission state: ${input.missionState}`, `Command: ${input.command.text}`, `Classification: ${classification}`];

  for (const signal of input.feedbackSignals) {
    evidence.push(`Feedback ${signal.signalType}: ${signal.evidence}`);
  }

  return evidence;
}
```

- [ ] **Step 4: Run planner tests**

Run:

```powershell
pnpm test tests/server/planner.test.ts
```

Expected:

```text
PASS tests/server/planner.test.ts
```

- [ ] **Step 5: Commit planner**

Run:

```powershell
git add src/server/planner tests/server/planner.test.ts
git commit -m "feat: add lightweight mission planner"
```

---

### Task 6: Orchestrator and Mock Runtime

**Files:**
- Create: `src/server/runtime/mockRuntimeAdapter.ts`
- Create: `src/server/orchestrator/orchestrator.ts`
- Create: `tests/server/orchestrator.test.ts`

- [ ] **Step 1: Write orchestrator tests**

Write `tests/server/orchestrator.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { InMemoryEventStore } from "../../src/server/event-store/inMemoryEventStore";
import { ProcessOrchestrator } from "../../src/server/orchestrator/orchestrator";
import { MockRuntimeAdapter } from "../../src/server/runtime/mockRuntimeAdapter";

describe("ProcessOrchestrator", () => {
  it("materializes a DAGRunPlanSeed into a DAGRun using the template registry", async () => {
    const store = new InMemoryEventStore();
    const orchestrator = new ProcessOrchestrator(store, new MockRuntimeAdapter());

    const dagRun = await orchestrator.scheduleAndRun({
      id: "seed_1",
      missionId: "mission_1",
      specChangeId: "spec_1",
      templateId: "ExplorationWorkflow",
      loopType: "explore_decompose",
      autonomyMode: "default_autonomous",
      inputRefs: ["cmd_1"],
      createdAt: "2026-05-28T00:00:00.000Z"
    });

    expect(dagRun.templateId).toBe("ExplorationWorkflow");
    expect(dagRun.nodeRuns.map((node) => node.nodeTemplateId)).toEqual([
      "explore.intent",
      "explore.acceptance",
      "explore.readiness"
    ]);
    expect(dagRun.status).toBe("completed");
  });

  it("writes events, artifacts, messages, route decision, and state change", async () => {
    const store = new InMemoryEventStore();
    const orchestrator = new ProcessOrchestrator(store, new MockRuntimeAdapter());

    await orchestrator.scheduleAndRun({
      id: "seed_2",
      missionId: "mission_2",
      specChangeId: "spec_2",
      templateId: "VerificationWorkflow",
      loopType: "check_verify",
      autonomyMode: "default_autonomous",
      inputRefs: ["cmd_2"],
      createdAt: "2026-05-28T00:00:00.000Z"
    });

    const eventTypes = store.allEvents().map((event) => event.eventType);

    expect(eventTypes).toContain("DAGRunScheduled");
    expect(eventTypes).toContain("NodeRunStarted");
    expect(eventTypes).toContain("RunMessageRecorded");
    expect(eventTypes).toContain("ArtifactRecorded");
    expect(eventTypes).toContain("RouteDecided");
    expect(eventTypes).toContain("MissionStateChanged");
  });
});
```

- [ ] **Step 2: Run orchestrator tests to verify failure**

Run:

```powershell
pnpm test tests/server/orchestrator.test.ts
```

Expected:

```text
FAIL tests/server/orchestrator.test.ts
Cannot find module '../../src/server/orchestrator/orchestrator'
```

- [ ] **Step 3: Implement MockRuntimeAdapter**

Write `src/server/runtime/mockRuntimeAdapter.ts`:

```ts
import type { Artifact, NodeRun, RunMessage, SpecChange } from "../../shared/domain";
import { makeId, nowIso } from "../../shared/testFactories";

export interface NodeExecutionRequest {
  missionId: string;
  specChange: SpecChange;
  dagRunId: string;
  nodeRun: NodeRun;
  runtimeTargetId?: string;
}

export interface NodeExecutionResult {
  messages: RunMessage[];
  artifacts: Artifact[];
  verdict: "pass" | "fail";
}

export interface RuntimeExecutor {
  execute(request: NodeExecutionRequest): Promise<NodeExecutionResult>;
}

export class MockRuntimeAdapter implements RuntimeExecutor {
  async execute(request: NodeExecutionRequest): Promise<NodeExecutionResult> {
    const createdAt = nowIso();
    const message: RunMessage = {
      id: makeId("msg"),
      missionId: request.missionId,
      dagRunId: request.dagRunId,
      nodeRunId: request.nodeRun.id,
      role: "runtime",
      text: `Mock executed ${request.nodeRun.label}`,
      createdAt
    };

    const artifact: Artifact = {
      id: makeId("artifact"),
      missionId: request.missionId,
      specChangeId: request.specChange.id,
      dagRunId: request.dagRunId,
      nodeRunId: request.nodeRun.id,
      kind: artifactKindForNode(request.nodeRun.kind),
      title: `${request.nodeRun.label} artifact`,
      body: `Deterministic output for ${request.nodeRun.nodeTemplateId}`,
      createdAt
    };

    return {
      messages: [message],
      artifacts: [artifact],
      verdict: "pass"
    };
  }
}

function artifactKindForNode(kind: NodeRun["kind"]): Artifact["kind"] {
  switch (kind) {
    case "explore":
      return "mission_brief";
    case "design":
      return "design_note";
    case "implement":
      return "patch_summary";
    case "verify":
      return "verification_evidence";
    case "fix":
      return "patch_summary";
    case "retrospective":
      return "retrospective";
  }
}
```

- [ ] **Step 4: Implement ProcessOrchestrator**

Write `src/server/orchestrator/orchestrator.ts`:

```ts
import type { DAGRun, DAGRunPlanSeed, MissionEvent, NodeRun, SpecChange } from "../../shared/domain";
import { makeId, nowIso } from "../../shared/testFactories";
import type { InMemoryEventStore } from "../event-store/inMemoryEventStore";
import { getWorkflowTemplate } from "../templates/workflowTemplates";
import type { RuntimeExecutor } from "../runtime/mockRuntimeAdapter";

export class ProcessOrchestrator {
  constructor(
    private readonly eventStore: InMemoryEventStore,
    private readonly runtime: RuntimeExecutor
  ) {}

  async scheduleAndRun(seed: DAGRunPlanSeed): Promise<DAGRun> {
    const template = getWorkflowTemplate(seed.templateId);
    const now = nowIso();
    const dagRun: DAGRun = {
      id: makeId("dag"),
      missionId: seed.missionId,
      specChangeId: seed.specChangeId,
      templateId: seed.templateId,
      status: "scheduled",
      createdAt: now,
      updatedAt: now,
      nodeRuns: template.nodeTemplates.map((nodeTemplate): NodeRun => ({
        id: makeId("node"),
        dagRunId: "pending",
        nodeTemplateId: nodeTemplate.id,
        kind: nodeTemplate.kind,
        label: nodeTemplate.label,
        status: "scheduled"
      }))
    };

    dagRun.nodeRuns = dagRun.nodeRuns.map((nodeRun) => ({ ...nodeRun, dagRunId: dagRun.id }));

    this.eventStore.append(event("DAGRunScheduled", seed.missionId, { dagRun }, seed.loopType, seed.specChangeId, dagRun.id));
    dagRun.status = "running";
    dagRun.updatedAt = nowIso();
    this.eventStore.append(event("DAGRunStarted", seed.missionId, { dagRun }, seed.loopType, seed.specChangeId, dagRun.id));

    const specChange: SpecChange = {
      id: seed.specChangeId,
      missionId: seed.missionId,
      state: "draft",
      title: `${template.name} SpecChange`,
      proposal: `Generated from ${seed.templateId}`,
      createdAt: seed.createdAt,
      updatedAt: seed.createdAt
    };

    for (const nodeRun of dagRun.nodeRuns) {
      nodeRun.status = "running";
      nodeRun.startedAt = nowIso();
      this.eventStore.append(event("NodeRunStarted", seed.missionId, { nodeRun }, seed.loopType, seed.specChangeId, dagRun.id, nodeRun.id));

      const result = await this.runtime.execute({
        missionId: seed.missionId,
        specChange,
        dagRunId: dagRun.id,
        nodeRun,
        runtimeTargetId: seed.runtimeTargetId
      });

      for (const message of result.messages) {
        this.eventStore.append(event("RunMessageRecorded", seed.missionId, { message }, seed.loopType, seed.specChangeId, dagRun.id, nodeRun.id));
      }

      for (const artifact of result.artifacts) {
        this.eventStore.append(event("ArtifactRecorded", seed.missionId, { artifact }, seed.loopType, seed.specChangeId, dagRun.id, nodeRun.id));
      }

      nodeRun.status = result.verdict === "pass" ? "completed" : "failed";
      nodeRun.completedAt = nowIso();
      this.eventStore.append(event(result.verdict === "pass" ? "NodeRunCompleted" : "NodeRunFailed", seed.missionId, { nodeRun }, seed.loopType, seed.specChangeId, dagRun.id, nodeRun.id));
    }

    dagRun.status = dagRun.nodeRuns.every((node) => node.status === "completed") ? "completed" : "failed";
    dagRun.updatedAt = nowIso();
    this.eventStore.append(event("DAGRunCompleted", seed.missionId, { dagRun }, seed.loopType, seed.specChangeId, dagRun.id));
    this.eventStore.append(event("RouteDecided", seed.missionId, { route: routeForTemplate(seed.templateId), dagRunId: dagRun.id }, seed.loopType, seed.specChangeId, dagRun.id));
    this.eventStore.append(event("MissionStateChanged", seed.missionId, { state: missionStateForTemplate(seed.templateId) }, seed.loopType, seed.specChangeId, dagRun.id));

    return dagRun;
  }
}

function event(
  eventType: MissionEvent["eventType"],
  missionId: string,
  payload: MissionEvent["payload"],
  loop?: MissionEvent["loop"],
  specChangeId?: string,
  dagRunId?: string,
  nodeRunId?: string
): MissionEvent {
  return {
    id: makeId("event"),
    missionId,
    eventType,
    actorType: "system",
    actorId: "process-orchestrator",
    occurredAt: nowIso(),
    loop,
    specChangeId,
    dagRunId,
    nodeRunId,
    payload
  };
}

function routeForTemplate(templateId: DAGRunPlanSeed["templateId"]): string {
  switch (templateId) {
    case "ExplorationWorkflow":
    case "SpecChangeDraftWorkflow":
      return "design_build";
    case "DesignWorkflow":
    case "ImplementationWorkflow":
    case "FixWorkflow":
      return "check_verify";
    case "VerificationWorkflow":
      return "operate_feedback";
    case "RetrospectiveWorkflow":
      return "learning";
  }
}

function missionStateForTemplate(templateId: DAGRunPlanSeed["templateId"]) {
  switch (templateId) {
    case "ExplorationWorkflow":
    case "SpecChangeDraftWorkflow":
      return "changing";
    case "DesignWorkflow":
    case "ImplementationWorkflow":
    case "FixWorkflow":
      return "verifying";
    case "VerificationWorkflow":
      return "operating";
    case "RetrospectiveWorkflow":
      return "learning";
  }
}
```

- [ ] **Step 5: Run orchestrator tests**

Run:

```powershell
pnpm test tests/server/orchestrator.test.ts
```

Expected:

```text
PASS tests/server/orchestrator.test.ts
```

- [ ] **Step 6: Commit orchestrator and mock runtime**

Run:

```powershell
git add src/server/runtime src/server/orchestrator tests/server/orchestrator.test.ts
git commit -m "feat: execute mock mission dag runs"
```

---

### Task 7: Runtime Targets and Local CLI Adapter

**Files:**
- Create: `src/server/runtime/runtimeTargetRegistry.ts`
- Create: `src/server/runtime/localCliRuntimeAdapter.ts`
- Create: `src/server/runtime/runtimeRouter.ts`
- Create: `scripts/fake-local-runner.mjs`
- Create: `tests/server/runtimeTargetRegistry.test.ts`
- Create: `tests/server/localCliRuntimeAdapter.test.ts`

- [ ] **Step 1: Write runtime target registry tests**

Write `tests/server/runtimeTargetRegistry.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { RuntimeTargetRegistry } from "../../src/server/runtime/runtimeTargetRegistry";

describe("RuntimeTargetRegistry", () => {
  it("registers a local Codex runner target", () => {
    const registry = new RuntimeTargetRegistry();

    const target = registry.registerLocalCli({
      name: "Local Codex",
      runnerKind: "codex",
      command: "codex",
      args: ["exec", "--json", "--cd", "{workspace}", "-"],
      cwd: "C:/project/yudao"
    });

    expect(target.kind).toBe("local_cli");
    expect(target.runnerKind).toBe("codex");
    expect(target.enabled).toBe(true);
    expect(registry.list()).toHaveLength(2);
  });

  it("keeps a built-in mock runner for deterministic tests", () => {
    const registry = new RuntimeTargetRegistry();

    expect(registry.get("runtime_mock")?.kind).toBe("mock");
  });
});
```

- [ ] **Step 2: Run registry test to verify it fails**

Run:

```powershell
pnpm test tests/server/runtimeTargetRegistry.test.ts
```

Expected:

```text
FAIL tests/server/runtimeTargetRegistry.test.ts
Cannot find module '../../src/server/runtime/runtimeTargetRegistry'
```

- [ ] **Step 3: Implement runtime target registry**

Write `src/server/runtime/runtimeTargetRegistry.ts`:

```ts
import type { LocalRunnerKind, RuntimeTarget } from "../../shared/domain";
import { makeId, nowIso } from "../../shared/testFactories";

export interface RegisterLocalCliTargetInput {
  name: string;
  runnerKind: LocalRunnerKind;
  command: string;
  args: string[];
  cwd?: string;
}

export class RuntimeTargetRegistry {
  private readonly targets = new Map<string, RuntimeTarget>();

  constructor() {
    const now = nowIso();
    this.targets.set("runtime_mock", {
      id: "runtime_mock",
      name: "Mock Runtime",
      kind: "mock",
      args: [],
      enabled: true,
      health: "healthy",
      createdAt: now,
      updatedAt: now
    });
  }

  registerLocalCli(input: RegisterLocalCliTargetInput): RuntimeTarget {
    const now = nowIso();
    const target: RuntimeTarget = {
      id: makeId("runtime"),
      name: input.name,
      kind: "local_cli",
      runnerKind: input.runnerKind,
      command: input.command,
      args: input.args,
      cwd: input.cwd,
      enabled: true,
      health: "unknown",
      createdAt: now,
      updatedAt: now
    };

    this.targets.set(target.id, target);
    return structuredClone(target);
  }

  list(): RuntimeTarget[] {
    return Array.from(this.targets.values()).map((target) => structuredClone(target));
  }

  get(id: string): RuntimeTarget | undefined {
    const target = this.targets.get(id);
    return target ? structuredClone(target) : undefined;
  }
}
```

- [ ] **Step 4: Add fake local runner script**

Write `scripts/fake-local-runner.mjs`:

```js
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const input = await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    data += chunk;
  });
  process.stdin.on("end", () => resolve(data));
});

const workspaceMatch = input.match(/workspace:\\s*(.+)/i);
const workspace = workspaceMatch ? workspaceMatch[1].trim() : path.join(process.cwd(), ".mission-workspaces", "fake-story-game");

await mkdir(workspace, { recursive: true });

await writeFile(
  path.join(workspace, "index.html"),
  `<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>月亮森林故事游戏</title></head>
<body>
  <main>
    <h1>月亮森林故事游戏</h1>
    <button id="start">开始故事</button>
    <section id="story">帮助小星星找到回家的路。</section>
  </main>
  <script src="./game.js"></script>
</body>
</html>
`
);

await writeFile(
  path.join(workspace, "game.js"),
  `const story = document.querySelector("#story");
document.querySelector("#start").addEventListener("click", () => {
  story.textContent = "小兔、云朵和孩子一起选择勇敢、善良和分享。";
});
`
);

await writeFile(
  path.join(workspace, "README.md"),
  `# 月亮森林故事游戏

一个儿童故事互动小游戏。

## 验收

- 有标题
- 有开始按钮
- 点击后故事会变化
- 主题适合儿童
`
);

console.log(JSON.stringify({
  status: "completed",
  summary: "Generated children story game",
  artifacts: [
    "index.html",
    "game.js",
    "README.md"
  ],
  workspace
}));
```

- [ ] **Step 5: Write local CLI adapter tests**

Write `tests/server/localCliRuntimeAdapter.test.ts`:

```ts
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LocalCliRuntimeAdapter } from "../../src/server/runtime/localCliRuntimeAdapter";

describe("LocalCliRuntimeAdapter", () => {
  it("executes a local runner command and captures generated story game artifacts", async () => {
    const workspace = path.join(process.cwd(), ".mission-workspaces", "test-story-game");
    rmSync(workspace, { recursive: true, force: true });
    const adapter = new LocalCliRuntimeAdapter({
      timeoutMs: 15_000
    });

    const result = await adapter.execute({
      target: {
        id: "runtime_fake",
        name: "Fake Local Runner",
        kind: "local_cli",
        runnerKind: "codex",
        command: process.execPath,
        args: ["scripts/fake-local-runner.mjs"],
        cwd: process.cwd(),
        enabled: true,
        health: "healthy",
        createdAt: "2026-05-28T00:00:00.000Z",
        updatedAt: "2026-05-28T00:00:00.000Z"
      },
      prompt: `mission: 做一个儿童故事游戏\nworkspace: ${workspace}`,
      workspace,
      missionId: "mission_story",
      dagRunId: "dag_story",
      nodeRunId: "node_story"
    });

    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("Generated children story game");
    expect(existsSync(path.join(workspace, "index.html"))).toBe(true);
    expect(existsSync(path.join(workspace, "game.js"))).toBe(true);
    expect(existsSync(path.join(workspace, "README.md"))).toBe(true);
  });
});
```

- [ ] **Step 6: Run local CLI adapter test to verify failure**

Run:

```powershell
pnpm test tests/server/localCliRuntimeAdapter.test.ts
```

Expected:

```text
FAIL tests/server/localCliRuntimeAdapter.test.ts
Cannot find module '../../src/server/runtime/localCliRuntimeAdapter'
```

- [ ] **Step 7: Implement local CLI adapter**

Write `src/server/runtime/localCliRuntimeAdapter.ts`:

```ts
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import type { RuntimeTarget } from "../../shared/domain";

export interface LocalCliExecutionRequest {
  target: RuntimeTarget;
  prompt: string;
  workspace: string;
  missionId: string;
  dagRunId: string;
  nodeRunId: string;
}

export interface LocalCliExecutionResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export class LocalCliRuntimeAdapter {
  constructor(private readonly options: { timeoutMs: number }) {}

  async execute(request: LocalCliExecutionRequest): Promise<LocalCliExecutionResult> {
    if (!request.target.command) {
      throw new Error(`Runtime target ${request.target.id} has no command`);
    }

    const args = request.target.args.map((arg) => arg.replaceAll("{workspace}", request.workspace));
    const cwd = (request.target.cwd ?? process.cwd()).replaceAll("{workspace}", request.workspace);
    mkdirSync(request.workspace, { recursive: true });

    return new Promise((resolve, reject) => {
      const child = spawn(request.target.command!, args, {
        cwd,
        shell: process.platform === "win32",
        stdio: ["pipe", "pipe", "pipe"]
      });

      let stdout = "";
      let stderr = "";
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error(`Runtime target ${request.target.id} timed out after ${this.options.timeoutMs}ms`));
      }, this.options.timeoutMs);

      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString();
      });
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on("close", (exitCode) => {
        clearTimeout(timer);
        resolve({
          exitCode: exitCode ?? 1,
          stdout,
          stderr
        });
      });

      child.stdin.end(request.prompt);
    });
  }
}
```

- [ ] **Step 8: Implement runtime router**

Write `src/server/runtime/runtimeRouter.ts`:

```ts
import type { RuntimeTarget } from "../../shared/domain";
import type { NodeExecutionRequest, NodeExecutionResult, RuntimeExecutor } from "./mockRuntimeAdapter";
import { MockRuntimeAdapter } from "./mockRuntimeAdapter";
import { LocalCliRuntimeAdapter } from "./localCliRuntimeAdapter";

export class RuntimeRouter implements RuntimeExecutor {
  constructor(
    private readonly mockRuntime: MockRuntimeAdapter,
    private readonly localCliRuntime: LocalCliRuntimeAdapter,
    private readonly registry: { get(id: string): RuntimeTarget | undefined }
  ) {}

  async execute(request: NodeExecutionRequest): Promise<NodeExecutionResult> {
    const target = request.runtimeTargetId ? this.registry.get(request.runtimeTargetId) : this.registry.get("runtime_mock");

    if (!target) {
      throw new Error(`Runtime target not found: ${request.runtimeTargetId ?? "runtime_mock"}`);
    }

    if (target.kind === "mock") {
      return this.mockRuntime.execute(request);
    }

    const result = await this.localCliRuntime.execute({
      target,
      missionId: request.missionId,
      dagRunId: request.dagRunId,
      nodeRunId: request.nodeRun.id,
      workspace: missionWorkspace(request),
      prompt: buildPrompt(request)
    });

    return {
      messages: [
        {
          id: `msg_${crypto.randomUUID()}`,
          missionId: request.missionId,
          dagRunId: request.dagRunId,
          nodeRunId: request.nodeRun.id,
          role: "runtime",
          text: result.stdout || result.stderr,
          createdAt: new Date().toISOString()
        }
      ],
      artifacts: [
        {
          id: `artifact_${crypto.randomUUID()}`,
          missionId: request.missionId,
          specChangeId: request.specChange.id,
          dagRunId: request.dagRunId,
          nodeRunId: request.nodeRun.id,
          kind: request.nodeRun.kind === "verify" ? "verification_evidence" : "patch_summary",
          title: `${target.name} output`,
          body: result.stdout || result.stderr,
          createdAt: new Date().toISOString()
        }
      ],
      verdict: result.exitCode === 0 ? "pass" : "fail"
    };
  }
}

function buildPrompt(request: NodeExecutionRequest): string {
  return [
    `mission: ${request.specChange.proposal}`,
    `node: ${request.nodeRun.label}`,
    `workspace: ${missionWorkspace(request)}`,
    "Build or update the requested artifact. Return a concise summary and generated files."
  ].join("\n");
}

function missionWorkspace(request: NodeExecutionRequest): string {
  return `${process.cwd()}/.mission-workspaces/${request.missionId}`;
}
```

- [ ] **Step 9: Run runtime tests**

Run:

```powershell
pnpm test tests/server/runtimeTargetRegistry.test.ts tests/server/localCliRuntimeAdapter.test.ts
```

Expected:

```text
PASS tests/server/runtimeTargetRegistry.test.ts
PASS tests/server/localCliRuntimeAdapter.test.ts
```

- [ ] **Step 10: Commit runtime target support**

Run:

```powershell
git add src/server/runtime scripts/fake-local-runner.mjs tests/server/runtimeTargetRegistry.test.ts tests/server/localCliRuntimeAdapter.test.ts
git commit -m "feat: add local cli runtime targets"
```

---

### Task 8: HTTP API

**Files:**
- Create: `src/server/api/app.ts`
- Create: `src/server/api/http.ts`
- Create: `src/server/index.ts`
- Create: `tests/server/api.test.ts`

- [ ] **Step 1: Write API tests**

Write `tests/server/api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createApiApp } from "../../src/server/api/app";

describe("Mission API", () => {
  it("creates a mission from an entry command", async () => {
    const app = createApiApp();

    const response = await app.request("/api/missions", {
      method: "POST",
      body: JSON.stringify({ text: "Build a software mission platform", source: "web_console" }),
      headers: { "content-type": "application/json" }
    });

    expect(response.status).toBe(201);
    const body = await response.json();
    expect(body.title).toBe("Build a software mission platform");
    expect(body.state).toBe("exploring");
  });

  it("plans next workflow and schedules a DAGRun", async () => {
    const app = createApiApp();

    const created = await app.request("/api/missions", {
      method: "POST",
      body: JSON.stringify({ text: "We need a stronger agent system", source: "web_console" }),
      headers: { "content-type": "application/json" }
    });
    const mission = await created.json();

    const planResponse = await app.request(`/api/missions/${mission.id}/plan-next`, { method: "POST" });
    const plan = await planResponse.json();

    expect(plan.planSeed.templateId).toBe("ExplorationWorkflow");
    expect(plan).not.toHaveProperty("dagRunPlan");

    const runResponse = await app.request("/api/dag-runs", {
      method: "POST",
      body: JSON.stringify({ planSeed: plan.planSeed }),
      headers: { "content-type": "application/json" }
    });
    const run = await runResponse.json();

    expect(run.status).toBe("completed");
    expect(run.nodeRuns.length).toBeGreaterThan(0);
  });

  it("records feedback and exposes mission timeline", async () => {
    const app = createApiApp();

    const created = await app.request("/api/missions", {
      method: "POST",
      body: JSON.stringify({ text: "Create a mission console", source: "web_console" }),
      headers: { "content-type": "application/json" }
    });
    const mission = await created.json();

    const feedbackResponse = await app.request(`/api/missions/${mission.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        source: "user",
        signalType: "requirement_change",
        severity: "medium",
        evidence: "The flow should ask fewer questions by default."
      }),
      headers: { "content-type": "application/json" }
    });

    expect(feedbackResponse.status).toBe(201);

    const timelineResponse = await app.request(`/api/missions/${mission.id}/timeline`);
    const timeline = await timelineResponse.json();

    expect(timeline.events.map((event: { eventType: string }) => event.eventType)).toContain("FeedbackSignalReceived");
  });

  it("registers and lists local runtime targets", async () => {
    const app = createApiApp();

    const registerResponse = await app.request("/api/runtime-targets", {
      method: "POST",
      body: JSON.stringify({
        name: "Local Codex",
        runnerKind: "codex",
        command: "codex",
        args: ["exec", "--json", "--cd", "{workspace}", "-"],
        cwd: process.cwd()
      }),
      headers: { "content-type": "application/json" }
    });

    expect(registerResponse.status).toBe(201);
    const target = await registerResponse.json();
    expect(target.kind).toBe("local_cli");
    expect(target.runnerKind).toBe("codex");

    const listResponse = await app.request("/api/runtime-targets");
    const targets = await listResponse.json();
    expect(targets.map((item: { name: string }) => item.name)).toContain("Local Codex");
  });
});
```

- [ ] **Step 2: Run API tests to verify failure**

Run:

```powershell
pnpm test tests/server/api.test.ts
```

Expected:

```text
FAIL tests/server/api.test.ts
Cannot find module '../../src/server/api/app'
```

- [ ] **Step 3: Implement API app**

Write `src/server/api/app.ts`:

```ts
import { Hono } from "hono";
import type { DAGRunPlanSeed, FeedbackSignal, MissionCommand, MissionEvent } from "../../shared/domain";
import { makeId, makeMissionCommand, nowIso } from "../../shared/testFactories";
import { InMemoryEventStore } from "../event-store/inMemoryEventStore";
import { buildMissionDetailView, buildMissionSummaryView, buildRunTraceView } from "../event-store/projections";
import { ProcessOrchestrator } from "../orchestrator/orchestrator";
import { planNextWorkflow } from "../planner/missionPlanner";
import { LocalCliRuntimeAdapter } from "../runtime/localCliRuntimeAdapter";
import { MockRuntimeAdapter } from "../runtime/mockRuntimeAdapter";
import { RuntimeRouter } from "../runtime/runtimeRouter";
import { RuntimeTargetRegistry } from "../runtime/runtimeTargetRegistry";

export function createApiApp() {
  const eventStore = new InMemoryEventStore();
  const runtimeTargets = new RuntimeTargetRegistry();
  const runtimeRouter = new RuntimeRouter(new MockRuntimeAdapter(), new LocalCliRuntimeAdapter({ timeoutMs: 120_000 }), runtimeTargets);
  const orchestrator = new ProcessOrchestrator(eventStore, runtimeRouter);
  const app = new Hono();
  let lastCommandByMission = new Map<string, MissionCommand>();
  let feedbackByMission = new Map<string, FeedbackSignal[]>();

  app.post("/api/missions", async (context) => {
    const body = await context.req.json<{ text: string; source?: MissionCommand["source"] }>();
    const missionId = makeId("mission");
    const command = makeMissionCommand({ text: body.text, source: body.source ?? "web_console" });
    lastCommandByMission.set(missionId, command);

    eventStore.append(event("MissionCommandReceived", missionId, { command }, "user", "web_console"));
    eventStore.append(event("MissionCreated", missionId, { title: command.text, state: "exploring" }, "user", "web_console"));

    const summary = buildMissionSummaryView(eventStore.allEvents()).find((item) => item.id === missionId);
    return context.json(summary, 201);
  });

  app.post("/api/missions/:id/commands", async (context) => {
    const missionId = context.req.param("id");
    const body = await context.req.json<{ text: string; source?: MissionCommand["source"] }>();
    const command = makeMissionCommand({ text: body.text, source: body.source ?? "web_console" });
    lastCommandByMission.set(missionId, command);
    eventStore.append(event("MissionCommandReceived", missionId, { command }, "user", command.source));
    return context.json(command, 201);
  });

  app.post("/api/missions/:id/plan-next", (context) => {
    const missionId = context.req.param("id");
    const command = lastCommandByMission.get(missionId);
    const detail = buildMissionDetailView(eventStore.allEvents(), missionId);

    if (!command || !detail) {
      return context.json({ error: "Mission not found" }, 404);
    }

    eventStore.append(event("MissionPlannerRunStarted", missionId, {}, "system", "mission-planner"));

    const plannerRun = planNextWorkflow({
      missionId,
      missionState: detail.state,
      command,
      events: detail.events,
      specChanges: detail.specChanges,
      feedbackSignals: feedbackByMission.get(missionId) ?? []
    });

    eventStore.append(event("WorkflowPlanned", missionId, { plannerRun }, "system", "mission-planner"));
    eventStore.append(event("WorkflowTemplateSelected", missionId, { templateId: plannerRun.workflowIntent.templateId }, "system", "mission-planner"));

    return context.json(plannerRun, 201);
  });

  app.post("/api/dag-runs", async (context) => {
    const body = await context.req.json<{ planSeed: DAGRunPlanSeed }>();
    const dagRun = await orchestrator.scheduleAndRun(body.planSeed);
    return context.json(dagRun, 201);
  });

  app.get("/api/runtime-targets", (context) => {
    return context.json(runtimeTargets.list());
  });

  app.post("/api/runtime-targets", async (context) => {
    const body = await context.req.json<{
      name: string;
      runnerKind: "codex" | "claude";
      command: string;
      args: string[];
      cwd?: string;
    }>();

    const target = runtimeTargets.registerLocalCli(body);
    return context.json(target, 201);
  });

  app.get("/api/missions", (context) => {
    return context.json(buildMissionSummaryView(eventStore.allEvents()));
  });

  app.get("/api/missions/:id", (context) => {
    const detail = buildMissionDetailView(eventStore.allEvents(), context.req.param("id"));
    return detail ? context.json(detail) : context.json({ error: "Mission not found" }, 404);
  });

  app.get("/api/missions/:id/timeline", (context) => {
    const detail = buildMissionDetailView(eventStore.allEvents(), context.req.param("id"));
    return detail ? context.json({ events: detail.events }) : context.json({ error: "Mission not found" }, 404);
  });

  app.get("/api/dag-runs/:id", (context) => {
    const trace = buildRunTraceView(eventStore.allEvents(), context.req.param("id"));
    return trace ? context.json(trace) : context.json({ error: "DAGRun not found" }, 404);
  });

  app.post("/api/missions/:id/feedback", async (context) => {
    const missionId = context.req.param("id");
    const body = await context.req.json<Omit<FeedbackSignal, "id" | "missionId" | "receivedAt">>();
    const signal: FeedbackSignal = {
      id: makeId("feedback"),
      missionId,
      source: body.source,
      signalType: body.signalType,
      severity: body.severity,
      evidence: body.evidence,
      receivedAt: nowIso()
    };

    feedbackByMission.set(missionId, [...(feedbackByMission.get(missionId) ?? []), signal]);
    eventStore.append(event("FeedbackSignalReceived", missionId, { signal }, "user", signal.source));
    return context.json(signal, 201);
  });

  return app;
}

function event(
  eventType: MissionEvent["eventType"],
  missionId: string,
  payload: MissionEvent["payload"],
  actorType: MissionEvent["actorType"],
  actorId: string
): MissionEvent {
  return {
    id: makeId("event"),
    missionId,
    eventType,
    actorType,
    actorId,
    occurredAt: nowIso(),
    payload
  };
}
```

Write `src/server/api/http.ts`:

```ts
import { serve } from "@hono/node-server";
import { createApiApp } from "./app";

export function startHttpServer(port = 8787) {
  return serve({
    fetch: createApiApp().fetch,
    hostname: "127.0.0.1",
    port
  });
}
```

Write `src/server/index.ts`:

```ts
import { startHttpServer } from "./api/http";

const port = Number(process.env.PORT ?? 8787);
startHttpServer(port);

console.log(`Mission Platform API listening on http://127.0.0.1:${port}`);
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
pnpm test tests/server/api.test.ts
```

Expected:

```text
PASS tests/server/api.test.ts
```

- [ ] **Step 5: Commit API**

Run:

```powershell
git add src/server/api src/server/index.ts tests/server/api.test.ts
git commit -m "feat: expose mission platform api"
```

---

### Task 9: Web Console Data Client

**Files:**
- Create: `src/app/apiClient.ts`
- Create: `tests/app/App.test.tsx`

- [ ] **Step 1: Write API client unit test**

Write `tests/app/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../src/app/App";

describe("App shell", () => {
  it("renders the Mission Console title", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Mission Console" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run UI test to verify failure**

Run:

```powershell
pnpm test tests/app/App.test.tsx
```

Expected:

```text
FAIL tests/app/App.test.tsx
Unable to find role="heading" and name "Mission Console"
```

- [ ] **Step 3: Create API client**

Write `src/app/apiClient.ts`:

```ts
import type {
  DAGRun,
  DAGRunPlanSeed,
  LocalRunnerKind,
  MissionDetailView,
  MissionPlannerRun,
  MissionSummaryView,
  RunTraceView,
  RuntimeTarget
} from "../shared/domain";

const apiBase = "/api";

export async function createMission(text: string): Promise<MissionSummaryView> {
  return request("/missions", {
    method: "POST",
    body: JSON.stringify({ text, source: "web_console" })
  });
}

export async function listMissions(): Promise<MissionSummaryView[]> {
  return request("/missions");
}

export async function getMission(id: string): Promise<MissionDetailView> {
  return request(`/missions/${id}`);
}

export async function planNext(missionId: string): Promise<MissionPlannerRun> {
  return request(`/missions/${missionId}/plan-next`, { method: "POST" });
}

export async function scheduleDagRun(planSeed: DAGRunPlanSeed): Promise<DAGRun> {
  return request("/dag-runs", {
    method: "POST",
    body: JSON.stringify({ planSeed })
  });
}

export async function listRuntimeTargets(): Promise<RuntimeTarget[]> {
  return request("/runtime-targets");
}

export async function registerRuntimeTarget(input: {
  name: string;
  runnerKind: LocalRunnerKind;
  command: string;
  args: string[];
  cwd?: string;
}): Promise<RuntimeTarget> {
  return request("/runtime-targets", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function getRunTrace(dagRunId: string): Promise<RunTraceView> {
  return request(`/dag-runs/${dagRunId}`);
}

export async function submitFeedback(missionId: string, evidence: string) {
  return request(`/missions/${missionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      source: "user",
      signalType: "requirement_change",
      severity: "medium",
      evidence
    })
  });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init.headers
    }
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}
```

- [ ] **Step 4: Replace App with console shell**

Write `src/app/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import type { MissionSummaryView } from "../shared/domain";
import { createMission, listMissions } from "./apiClient";

export function App() {
  const [missions, setMissions] = useState<MissionSummaryView[]>([]);
  const [text, setText] = useState("Build an AI/agent native mission platform");

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    setMissions(await listMissions());
  }

  async function submitMission() {
    await createMission(text);
    setText("");
    await refresh();
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Mission Console</h1>
          <p>v0.1A full-loop thin slice</p>
        </div>
      </header>

      <section className="mission-create">
        <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label="Mission command" />
        <button type="button" onClick={submitMission}>
          Create Mission
        </button>
      </section>

      <section className="mission-list" aria-label="Mission list">
        {missions.map((mission) => (
          <article className="mission-row" key={mission.id}>
            <strong>{mission.title}</strong>
            <span>{mission.state}</span>
            <small>{mission.nextAction}</small>
          </article>
        ))}
      </section>
    </main>
  );
}
```

- [ ] **Step 5: Update CSS for shell**

Append to `src/app/styles.css`:

```css
.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.topbar h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0;
}

.topbar p {
  margin: 6px 0 0;
  color: #647084;
}

.mission-create {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  margin-bottom: 18px;
}

.mission-create textarea {
  min-height: 86px;
  resize: vertical;
  border: 1px solid #c8d0dc;
  border-radius: 8px;
  padding: 12px;
  font: inherit;
}

.mission-create button {
  align-self: stretch;
  border: 0;
  border-radius: 8px;
  background: #2f6fed;
  color: #fff;
  padding: 0 18px;
  font-weight: 700;
}

.mission-list {
  display: grid;
  gap: 10px;
}

.mission-row {
  display: grid;
  grid-template-columns: 1fr 120px 180px;
  gap: 12px;
  align-items: center;
  padding: 14px;
  border: 1px solid #d9dee8;
  border-radius: 8px;
  background: #fff;
}
```

- [ ] **Step 6: Run UI test**

Run:

```powershell
pnpm test tests/app/App.test.tsx
```

Expected:

```text
PASS tests/app/App.test.tsx
```

- [ ] **Step 7: Commit API client and shell**

Run:

```powershell
git add src/app tests/app/App.test.tsx
git commit -m "feat: add mission console shell"
```

---

### Task 10: Mission Detail, Timeline, Run Trace, and Runtime Targets UI

**Files:**
- Create: `src/app/components/MissionList.tsx`
- Create: `src/app/components/MissionDetail.tsx`
- Create: `src/app/components/RuntimeTargets.tsx`
- Create: `src/app/components/Timeline.tsx`
- Create: `src/app/components/RunTrace.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/styles.css`
- Modify: `tests/app/App.test.tsx`

- [ ] **Step 1: Extend UI test for full-loop controls**

Replace `tests/app/App.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../src/app/App";

vi.mock("../../src/app/apiClient", () => ({
  createMission: async () => ({
    id: "mission_1",
    title: "Mock Mission",
    state: "exploring",
    nextAction: "plan_next",
    updatedAt: "2026-05-28T00:00:00.000Z"
  }),
  getMission: async () => ({
    id: "mission_1",
    title: "Mock Mission",
    state: "exploring",
    events: [],
    specChanges: []
  }),
  getRunTrace: async () => ({
    dagRun: {
      id: "dag_1",
      missionId: "mission_1",
      specChangeId: "spec_1",
      templateId: "ExplorationWorkflow",
      status: "completed",
      createdAt: "2026-05-28T00:00:00.000Z",
      updatedAt: "2026-05-28T00:00:00.000Z",
      nodeRuns: []
    },
    messages: [],
    artifacts: []
  }),
  listMissions: async () => [],
  listRuntimeTargets: async () => [
    {
      id: "runtime_mock",
      name: "Mock Runtime",
      kind: "mock",
      args: [],
      enabled: true,
      health: "healthy",
      createdAt: "2026-05-28T00:00:00.000Z",
      updatedAt: "2026-05-28T00:00:00.000Z"
    }
  ],
  planNext: async () => ({
    id: "planner_1",
    missionId: "mission_1",
    workflowIntent: {
      templateId: "ExplorationWorkflow",
      loopType: "explore_decompose",
      goal: "Explore the mission"
    },
    reason: {
      classification: "requirement_unclear",
      evidence: ["test"],
      createdAt: "2026-05-28T00:00:00.000Z"
    },
    planSeed: {
      id: "seed_1",
      missionId: "mission_1",
      specChangeId: "spec_1",
      templateId: "ExplorationWorkflow",
      loopType: "explore_decompose",
      autonomyMode: "default_autonomous",
      inputRefs: ["cmd_1"],
      createdAt: "2026-05-28T00:00:00.000Z"
    },
    createdAt: "2026-05-28T00:00:00.000Z"
  }),
  registerRuntimeTarget: async () => ({
    id: "runtime_codex",
    name: "Local Codex",
    kind: "local_cli",
    runnerKind: "codex",
    command: "codex",
    args: ["exec", "--json", "--cd", "{workspace}", "-"],
    enabled: true,
    health: "unknown",
    createdAt: "2026-05-28T00:00:00.000Z",
    updatedAt: "2026-05-28T00:00:00.000Z"
  }),
  scheduleDagRun: async () => ({
    id: "dag_1",
    missionId: "mission_1",
    specChangeId: "spec_1",
    templateId: "ExplorationWorkflow",
    status: "completed",
    createdAt: "2026-05-28T00:00:00.000Z",
    updatedAt: "2026-05-28T00:00:00.000Z",
    nodeRuns: []
  }),
  submitFeedback: async () => ({})
}));

describe("App shell", () => {
  it("renders core v0.1A console regions", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Mission Console" })).toBeInTheDocument();
    expect(screen.getByLabelText("Mission command")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Mission" })).toBeInTheDocument();
    expect(screen.getByLabelText("Mission list")).toBeInTheDocument();
    expect(screen.getByLabelText("Mission detail")).toBeInTheDocument();
    expect(screen.getByLabelText("Run trace")).toBeInTheDocument();
    expect(screen.getByLabelText("Runtime targets")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register Codex" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register Claude Code" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run UI test to verify failure**

Run:

```powershell
pnpm test tests/app/App.test.tsx
```

Expected:

```text
FAIL tests/app/App.test.tsx
Unable to find an accessible element with the label "Mission detail"
```

- [ ] **Step 3: Create UI components**

Write `src/app/components/MissionList.tsx`:

```tsx
import type { MissionSummaryView } from "../../shared/domain";

interface MissionListProps {
  missions: MissionSummaryView[];
  selectedMissionId?: string;
  onSelect: (id: string) => void;
}

export function MissionList({ missions, selectedMissionId, onSelect }: MissionListProps) {
  return (
    <section className="mission-list" aria-label="Mission list">
      {missions.map((mission) => (
        <button
          className={mission.id === selectedMissionId ? "mission-row selected" : "mission-row"}
          key={mission.id}
          type="button"
          onClick={() => onSelect(mission.id)}
        >
          <strong>{mission.title}</strong>
          <span>{mission.state}</span>
          <small>{mission.nextAction}</small>
        </button>
      ))}
    </section>
  );
}
```

Write `src/app/components/Timeline.tsx`:

```tsx
import type { MissionEvent } from "../../shared/domain";

interface TimelineProps {
  events: MissionEvent[];
}

export function Timeline({ events }: TimelineProps) {
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <span>{event.eventType}</span>
          <time>{new Date(event.occurredAt).toLocaleTimeString()}</time>
        </li>
      ))}
    </ol>
  );
}
```

Write `src/app/components/RunTrace.tsx`:

```tsx
import type { RunTraceView } from "../../shared/domain";

interface RunTraceProps {
  trace?: RunTraceView;
}

export function RunTrace({ trace }: RunTraceProps) {
  return (
    <section className="panel" aria-label="Run trace">
      <h2>Run Trace</h2>
      {!trace ? (
        <p className="muted">No DAGRun selected.</p>
      ) : (
        <div className="trace-grid">
          {trace.dagRun.nodeRuns.map((node) => (
            <article className="node-card" key={node.id}>
              <strong>{node.label}</strong>
              <span>{node.status}</span>
              <small>{node.kind}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
```

Write `src/app/components/MissionDetail.tsx`:

```tsx
import type { MissionDetailView, MissionPlannerRun } from "../../shared/domain";
import { Timeline } from "./Timeline";

interface MissionDetailProps {
  mission?: MissionDetailView;
  latestPlan?: MissionPlannerRun;
  onPlanNext: () => void;
  onRunPlan: () => void;
  onFeedback: () => void;
}

export function MissionDetail({ mission, latestPlan, onPlanNext, onRunPlan, onFeedback }: MissionDetailProps) {
  return (
    <section className="panel" aria-label="Mission detail">
      <div className="panel-heading">
        <h2>Mission Detail</h2>
        {mission && <span>{mission.state}</span>}
      </div>

      {!mission ? (
        <p className="muted">Select a mission to inspect its lifecycle.</p>
      ) : (
        <>
          <h3>{mission.title}</h3>
          <div className="action-row">
            <button type="button" onClick={onPlanNext}>
              Plan Next
            </button>
            <button type="button" onClick={onRunPlan} disabled={!latestPlan}>
              Run Plan
            </button>
            <button type="button" onClick={onFeedback}>
              Add Feedback
            </button>
          </div>
          {latestPlan && (
            <div className="plan-card">
              <strong>{latestPlan.workflowIntent.templateId}</strong>
              <p>{latestPlan.reason.classification}</p>
              <small>Seed: {latestPlan.planSeed.id}</small>
            </div>
          )}
          <Timeline events={mission.events} />
        </>
      )}
    </section>
  );
}
```

Write `src/app/components/RuntimeTargets.tsx`:

```tsx
import type { RuntimeTarget } from "../../shared/domain";

interface RuntimeTargetsProps {
  targets: RuntimeTarget[];
  selectedTargetId?: string;
  onSelectTarget: (targetId: string) => void;
  onRegisterCodex: () => void;
  onRegisterClaude: () => void;
}

export function RuntimeTargets({ targets, selectedTargetId, onSelectTarget, onRegisterCodex, onRegisterClaude }: RuntimeTargetsProps) {
  return (
    <section className="panel" aria-label="Runtime targets">
      <div className="panel-heading">
        <h2>Runtime Targets</h2>
      </div>
      <div className="action-row">
        <button type="button" onClick={onRegisterCodex}>
          Register Codex
        </button>
        <button type="button" onClick={onRegisterClaude}>
          Register Claude Code
        </button>
      </div>
      <div className="target-list">
        {targets.map((target) => (
          <article className="target-card" key={target.id}>
            <label>
              <input
                type="radio"
                name="runtime-target"
                checked={selectedTargetId === target.id}
                onChange={() => onSelectTarget(target.id)}
              />
              <strong>{target.name}</strong>
            </label>
            <span>{target.runnerKind ?? target.kind}</span>
            <small>{target.command ?? "built-in"}</small>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Wire components in App**

Replace `src/app/App.tsx` with:

```tsx
import { useEffect, useState } from "react";
import type { MissionDetailView, MissionPlannerRun, MissionSummaryView, RunTraceView, RuntimeTarget } from "../shared/domain";
import {
  createMission,
  getMission,
  getRunTrace,
  listMissions,
  listRuntimeTargets,
  planNext,
  registerRuntimeTarget,
  scheduleDagRun,
  submitFeedback
} from "./apiClient";
import { MissionDetail } from "./components/MissionDetail";
import { MissionList } from "./components/MissionList";
import { RuntimeTargets } from "./components/RuntimeTargets";
import { RunTrace } from "./components/RunTrace";

export function App() {
  const [missions, setMissions] = useState<MissionSummaryView[]>([]);
  const [selectedMission, setSelectedMission] = useState<MissionDetailView | undefined>();
  const [latestPlan, setLatestPlan] = useState<MissionPlannerRun | undefined>();
  const [runTrace, setRunTrace] = useState<RunTraceView | undefined>();
  const [runtimeTargets, setRuntimeTargets] = useState<RuntimeTarget[]>([]);
  const [selectedRuntimeTargetId, setSelectedRuntimeTargetId] = useState<string | undefined>();
  const [text, setText] = useState("Build an AI/agent native mission platform");

  useEffect(() => {
    void refreshMissions();
    void refreshRuntimeTargets();
  }, []);

  async function refreshMissions() {
    setMissions(await listMissions());
  }

  async function refreshRuntimeTargets(preferredTargetId = selectedRuntimeTargetId) {
    const targets = await listRuntimeTargets();
    setRuntimeTargets(targets);
    if (!preferredTargetId) {
      setSelectedRuntimeTargetId(targets.find((target) => target.kind === "mock")?.id);
    }
  }

  async function selectMission(id: string) {
    setSelectedMission(await getMission(id));
    setLatestPlan(undefined);
    setRunTrace(undefined);
  }

  async function submitMission() {
    const mission = await createMission(text);
    setText("");
    await refreshMissions();
    await selectMission(mission.id);
  }

  async function handlePlanNext() {
    if (!selectedMission) return;
    setLatestPlan(await planNext(selectedMission.id));
    setSelectedMission(await getMission(selectedMission.id));
  }

  async function handleRunPlan() {
    if (!selectedMission || !latestPlan) return;
    const run = await scheduleDagRun({
      ...latestPlan.planSeed,
      runtimeTargetId: selectedRuntimeTargetId
    });
    setRunTrace(await getRunTrace(run.id));
    setSelectedMission(await getMission(selectedMission.id));
    await refreshMissions();
  }

  async function handleFeedback() {
    if (!selectedMission) return;
    await submitFeedback(selectedMission.id, "The user changed the requirement during review.");
    setSelectedMission(await getMission(selectedMission.id));
  }

  async function handleRegisterCodex() {
    const useFakeRunner = import.meta.env.VITE_FAKE_RUNNER === "1";
    const target = await registerRuntimeTarget({
      name: "Local Codex",
      runnerKind: "codex",
      command: useFakeRunner ? "node" : "codex",
      args: useFakeRunner ? ["scripts/fake-local-runner.mjs"] : ["exec", "--json", "--cd", "{workspace}", "-"],
      cwd: "."
    });
    setSelectedRuntimeTargetId(target.id);
    await refreshRuntimeTargets(target.id);
  }

  async function handleRegisterClaude() {
    const target = await registerRuntimeTarget({
      name: "Local Claude Code",
      runnerKind: "claude",
      command: "claude",
      args: ["--print", "--output-format", "json", "--permission-mode", "dontAsk"],
      cwd: "."
    });
    setSelectedRuntimeTargetId(target.id);
    await refreshRuntimeTargets(target.id);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Mission Console</h1>
          <p>v0.1A full-loop thin slice</p>
        </div>
      </header>

      <section className="mission-create">
        <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label="Mission command" />
        <button type="button" onClick={submitMission}>
          Create Mission
        </button>
      </section>

      <section className="workspace-grid">
        <MissionList missions={missions} selectedMissionId={selectedMission?.id} onSelect={selectMission} />
        <MissionDetail
          mission={selectedMission}
          latestPlan={latestPlan}
          onPlanNext={handlePlanNext}
          onRunPlan={handleRunPlan}
          onFeedback={handleFeedback}
        />
        <RunTrace trace={runTrace} />
      </section>

      <RuntimeTargets
        targets={runtimeTargets}
        selectedTargetId={selectedRuntimeTargetId}
        onSelectTarget={setSelectedRuntimeTargetId}
        onRegisterCodex={handleRegisterCodex}
        onRegisterClaude={handleRegisterClaude}
      />
    </main>
  );
}
```

- [ ] **Step 5: Replace CSS with stable console layout**

Replace `src/app/styles.css` with:

```css
:root {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #17202a;
  background: #f6f7f9;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

button,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  padding: 24px;
}

.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.topbar h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0;
}

.topbar p,
.muted {
  margin: 6px 0 0;
  color: #647084;
}

.mission-create {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  margin-bottom: 18px;
}

.mission-create textarea {
  min-height: 86px;
  resize: vertical;
  border: 1px solid #c8d0dc;
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}

.mission-create button,
.action-row button {
  border: 0;
  border-radius: 8px;
  background: #2f6fed;
  color: #fff;
  padding: 0 18px;
  min-height: 40px;
  font-weight: 700;
}

.mission-create button:disabled,
.action-row button:disabled {
  background: #aab4c3;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(260px, 360px) minmax(360px, 1fr) minmax(320px, 460px);
  gap: 14px;
  align-items: start;
}

.mission-list,
.panel {
  display: grid;
  gap: 10px;
}

.mission-row,
.panel,
.node-card,
.plan-card,
.target-card {
  border: 1px solid #d9dee8;
  border-radius: 8px;
  background: #fff;
}

.mission-row {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
  text-align: left;
  padding: 14px;
}

.mission-row.selected {
  border-color: #2f6fed;
  box-shadow: 0 0 0 2px rgba(47, 111, 237, 0.12);
}

.panel {
  padding: 16px;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel h2,
.panel h3 {
  margin: 0;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.plan-card,
.node-card,
.target-card {
  padding: 12px;
}

.timeline {
  display: grid;
  gap: 8px;
  padding: 0;
  margin: 12px 0 0;
  list-style: none;
}

.timeline li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid #edf0f5;
  padding-top: 8px;
}

.trace-grid {
  display: grid;
  gap: 10px;
}

.node-card {
  display: grid;
  gap: 6px;
}

.target-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.target-card {
  display: grid;
  gap: 6px;
}

.target-card label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

@media (max-width: 980px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .app-shell {
    padding: 16px;
  }

  .mission-create {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 6: Run UI test**

Run:

```powershell
pnpm test tests/app/App.test.tsx
```

Expected:

```text
PASS tests/app/App.test.tsx
```

- [ ] **Step 7: Commit UI detail**

Run:

```powershell
git add src/app tests/app/App.test.tsx
git commit -m "feat: show mission timeline and run trace"
```

---

### Task 11: Children's Story Game Runner Integration Test

**Files:**
- Create: `playwright.config.ts`
- Create: `tests/e2e/childStoryGameMission.e2e.test.ts`
- Modify: `docs/v01a-local-run.md`

- [ ] **Step 1: Write Playwright config**

Write `playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure"
  },
  webServer: [
    {
      command: "pnpm api",
      url: "http://127.0.0.1:8787/api/missions",
      reuseExistingServer: true,
      timeout: 30_000
    },
    {
      command: "pnpm dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 30_000
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
```

- [ ] **Step 2: Write installed-flow E2E test with fake local runner**

Write `tests/e2e/childStoryGameMission.e2e.test.ts`:

```ts
import { expect, test } from "@playwright/test";
import { existsSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";

test("Web UI registers a local runner and completes a children's story game Mission", async ({ page }) => {
  rmSync(path.join(process.cwd(), ".mission-workspaces"), { recursive: true, force: true });

  await page.goto("/");

  await page.getByRole("button", { name: "Register Codex" }).click();
  await expect(page.getByLabel("Runtime targets")).toContainText("Local Codex");

  await page.getByLabel("Mission command").fill("做一个儿童故事游戏，适合 6-8 岁儿童，包含开始按钮、故事文本和一个简单选择互动。");
  await page.getByRole("button", { name: "Create Mission" }).click();
  await expect(page.getByLabel("Mission list")).toContainText("儿童故事游戏");

  await page.getByRole("button", { name: /儿童故事游戏/ }).click();
  await page.getByRole("button", { name: "Plan Next" }).click();
  await expect(page.getByLabel("Mission detail")).toContainText("ExplorationWorkflow");
  await expect(page.getByLabel("Mission detail")).toContainText("requirement_unclear");

  await page.getByRole("button", { name: "Run Plan" }).click();
  await expect(page.getByLabel("Run trace")).toContainText("completed");
  await expect(page.getByLabel("Mission detail")).toContainText("DAGRunScheduled");
  await expect(page.getByLabel("Mission detail")).toContainText("ArtifactRecorded");
  await expect(page.getByLabel("Mission detail")).toContainText("RouteDecided");

  await page.getByRole("button", { name: "Add Feedback" }).click();
  await expect(page.getByLabel("Mission detail")).toContainText("FeedbackSignalReceived");

  expect(findGeneratedStoryGame()).toMatchObject({
    hasIndex: true,
    hasGameScript: true,
    hasReadme: true
  });
});

function findGeneratedStoryGame() {
  const root = path.join(process.cwd(), ".mission-workspaces");
  expect(existsSync(root)).toBe(true);

  const missionDirs = readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory());
  for (const dir of missionDirs) {
    const files = readdirSync(path.join(root, dir.name));
    const result = {
      hasIndex: files.includes("index.html"),
      hasGameScript: files.includes("game.js"),
      hasReadme: files.includes("README.md")
    };
    if (result.hasIndex && result.hasGameScript && result.hasReadme) {
      return result;
    }
  }

  return {
    hasIndex: false,
    hasGameScript: false,
    hasReadme: false
  };
}
```

This test should run against the deterministic fake local runner in automated verification. The `Register Codex` button must use the fake runner when `VITE_FAKE_RUNNER=1` is set. Browser code cannot use `process.execPath`, so the fake runner registration uses the portable `node` command:

```ts
const useFakeRunner = import.meta.env.VITE_FAKE_RUNNER === "1";
await registerRuntimeTarget({
  name: "Local Codex",
  runnerKind: "codex",
  command: useFakeRunner ? "node" : "codex",
  args: useFakeRunner ? ["scripts/fake-local-runner.mjs"] : ["exec", "--json", "--cd", "{workspace}", "-"],
  cwd: "."
});
```

- [ ] **Step 3: Run E2E test**

Run:

```powershell
$env:VITE_FAKE_RUNNER='1'
pnpm test:e2e tests/e2e/childStoryGameMission.e2e.test.ts
```

Expected:

```text
1 passed
```

- [ ] **Step 4: Write local run and real runner acceptance documentation**

Write `docs/v01a-local-run.md`:

```markdown
# v0.1A Local Run

## API

Run:

```powershell
pnpm api
```

Expected:

```text
Mission Platform API listening on http://127.0.0.1:8787
```

## Web Console

In a second terminal, run:

```powershell
pnpm dev
```

Open:

```text
http://127.0.0.1:5173/
```

## Manual Mission Loop

1. Create a Mission from the text box.
2. Select the created Mission.
3. Click `Plan Next`.
4. Confirm the plan card shows `ExplorationWorkflow`.
5. Click `Run Plan`.
6. Confirm the Run Trace shows completed NodeRuns.
7. Click `Add Feedback`.
8. Click `Plan Next` again.
9. Confirm the timeline includes `FeedbackSignalReceived` and a later `WorkflowPlanned`.

## Installed Runner Acceptance: Children's Story Game

Preflight:

```powershell
codex --version
claude --version
```

Observed on 2026-05-29:

```text
codex-cli 0.134.0
2.1.152 (Claude Code)
```

Acceptance path:

1. Run `pnpm api`.
2. Run `pnpm dev`.
3. Open `http://127.0.0.1:5173/`.
4. Click `Register Codex`.
5. Confirm `Local Codex` appears in `Runtime Targets`.
6. Create this Mission:

```text
做一个儿童故事游戏，适合 6-8 岁儿童，包含开始按钮、故事文本和一个简单选择互动。
```

7. Select the Mission.
8. Click `Plan Next`.
9. Confirm the plan shows `WorkflowIntent`, `WorkflowGenerationReason`, and `DAGRunPlanSeed`.
10. Click `Run Plan`.
11. Confirm Run Trace contains completed NodeRuns.
12. Confirm timeline includes `WorkflowPlanned`, `WorkflowTemplateSelected`, `DAGRunScheduled`, `NodeRunStarted`, `ArtifactRecorded`, `RouteDecided`, and `MissionStateChanged`.
13. Confirm files exist under `.mission-workspaces/<mission-id>/` and include at least `index.html`, a script file, and a README or equivalent explanation.
14. Open the generated `index.html` and confirm the children's story game has a visible title, story text, start/choice interaction, and child-safe copy.
15. Add feedback from the Web UI.
16. Click `Plan Next` again.
17. Confirm the new planner reason includes the feedback evidence.

Claude Code parity path:

Repeat the same flow with `Register Claude Code`. This is a parity check, not a blocker if Claude Code authentication or account policy blocks execution. If it fails because auth is unavailable, record the failure reason in the final verification notes.
```

- [ ] **Step 5: Commit E2E verification**

Run:

```powershell
git add playwright.config.ts tests/e2e/childStoryGameMission.e2e.test.ts docs/v01a-local-run.md
git commit -m "test: verify child story game runner flow"
```

---

### Task 12: Full-loop Verification

**Files:**
- Modify: `package.json`
- Create: `tests/server/fullLoop.test.ts`
- Modify: `docs/v01a-local-run.md`

- [ ] **Step 1: Add full-loop integration test**

Write `tests/server/fullLoop.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createApiApp } from "../../src/server/api/app";

describe("v0.1A full-loop thin slice", () => {
  it("runs mission creation, planning, DAG execution, timeline projection, and feedback-triggered replanning", async () => {
    const app = createApiApp();

    const created = await app.request("/api/missions", {
      method: "POST",
      body: JSON.stringify({ text: "Build the first mission platform loop", source: "web_console" }),
      headers: { "content-type": "application/json" }
    });
    const mission = await created.json();

    const firstPlanResponse = await app.request(`/api/missions/${mission.id}/plan-next`, { method: "POST" });
    const firstPlan = await firstPlanResponse.json();
    expect(firstPlan.workflowIntent.templateId).toBe("ExplorationWorkflow");
    expect(firstPlan.planSeed).not.toHaveProperty("nodeRuns");

    const runResponse = await app.request("/api/dag-runs", {
      method: "POST",
      body: JSON.stringify({ planSeed: firstPlan.planSeed }),
      headers: { "content-type": "application/json" }
    });
    const run = await runResponse.json();
    expect(run.status).toBe("completed");

    const timelineResponse = await app.request(`/api/missions/${mission.id}/timeline`);
    const timeline = await timelineResponse.json();
    expect(timeline.events.map((event: { eventType: string }) => event.eventType)).toEqual(
      expect.arrayContaining(["WorkflowPlanned", "DAGRunScheduled", "ArtifactRecorded", "RouteDecided", "MissionStateChanged"])
    );

    await app.request(`/api/missions/${mission.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        source: "user",
        signalType: "requirement_change",
        severity: "medium",
        evidence: "Route back to exploration because acceptance changed."
      }),
      headers: { "content-type": "application/json" }
    });

    const secondPlanResponse = await app.request(`/api/missions/${mission.id}/plan-next`, { method: "POST" });
    const secondPlan = await secondPlanResponse.json();
    expect(secondPlan.reason.evidence.join(" ")).toContain("Route back to exploration");
  });
});
```

- [ ] **Step 2: Run all tests**

Run:

```powershell
pnpm test
```

Expected:

```text
PASS tests/shared/domain.test.ts
PASS tests/server/eventStore.test.ts
PASS tests/server/templates.test.ts
PASS tests/server/planner.test.ts
PASS tests/server/orchestrator.test.ts
PASS tests/server/api.test.ts
PASS tests/server/fullLoop.test.ts
PASS tests/app/App.test.tsx
```

- [ ] **Step 3: Build**

Run:

```powershell
pnpm build
```

Expected:

```text
vite build completes without TypeScript errors
```

- [ ] **Step 4: Append final verification commands to local run documentation**

Append to `docs/v01a-local-run.md`:

```markdown
## Automated Verification

Run the deterministic verification suite before installed-runner acceptance:

```powershell
pnpm test
pnpm build
$env:VITE_FAKE_RUNNER='1'
pnpm test:e2e tests/e2e/childStoryGameMission.e2e.test.ts
```

Expected:

```text
All Vitest suites pass
Vite build completes
Playwright child story game Mission test passes
```

## Final Verification Notes

Record:

- Real runner used: `codex` or `claude`.
- Runner version output.
- Mission id.
- Generated workspace path.
- Whether `index.html`, `game.js`, and `README.md` exist.
- Whether the Web UI timeline contains the required PRD event chain.
- Any Claude Code parity blocker, especially authentication or account policy.
```

- [ ] **Step 5: Browser verification**

Run in two PowerShell windows:

```powershell
pnpm api
```

```powershell
pnpm dev
```

Open:

```text
http://127.0.0.1:5173/
```

Verify with Playwright:
- Desktop viewport `1440x900`: create Mission, plan, run, add feedback, replan.
- Mobile viewport `390x844`: no text overlap, no clipped buttons, all primary regions visible through vertical scroll.

- [ ] **Step 6: Commit verification docs**

Run:

```powershell
git add package.json tests/server/fullLoop.test.ts docs/v01a-local-run.md
git commit -m "test: verify v01a full mission loop"
```

---

## Final Verification

Run:

```powershell
pnpm test
pnpm build
$env:VITE_FAKE_RUNNER='1'
pnpm test:e2e tests/e2e/childStoryGameMission.e2e.test.ts
```

Expected:

```text
All tests pass
Vite build completes
Playwright child story game Mission test passes with the fake local runner
```

Manual browser acceptance:

```text
Mission created
Planner returns WorkflowIntent, WorkflowGenerationReason, and DAGRunPlanSeed
Planner response does not include nodeRuns
Orchestrator schedules and completes DAGRun
NodeRuns record messages and artifacts
Timeline shows WorkflowPlanned, DAGRunScheduled, ArtifactRecorded, RouteDecided, MissionStateChanged
FeedbackSignalReceived appears after feedback
Second plan-next includes feedback evidence
```

Installed runner acceptance:

```text
Register Codex from the Web UI
Run the children's story game Mission
Confirm generated files exist under .mission-workspaces/<mission-id>/
Record Claude Code parity result if authentication allows it
```

## Self-review Checklist

- Spec coverage: v0.1A entities, APIs, mock runtime, event stream, projections, planner boundary, DAG execution, feedback, and Web Console visibility are covered.
- Planner boundary: tests assert Planner returns `DAGRunPlanSeed` and does not return `nodeRuns` or materialized `DAGRunPlan`.
- No persistent database is introduced.
- Only minimal local CLI runtime target support is introduced; no production-grade Codex, Claude Code, Hermes, or OpenClaw adapter is introduced.
- No auth, tenancy, marketplace, or self-bootstrap work is included.
- UI shows Mission List, Mission Detail + Timeline, and Run Trace.
