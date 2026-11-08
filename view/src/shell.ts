// 壳（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」的「壳与回链」、「画面合同」的回调、
// 「回链的细内容在页面」；应用层与接口层 docs/design/app-and-interface.md「能力清单」与「命令」）。
//
// 壳只做连接：把同步层的数据交给翻译层，把翻译层的输出交给画面层，把画面层的回调变成现有的命令或 Yudao 页面的地址。
//   - 命令只从能力清单里发现：只发清单里列出的命令，带这次连接的身份；同一个 command_id 重发只生效一次。
//     能力清单里没有某条命令时，对应的物件不可操作，并写进缺口清单。
//   - 点开回链：画面交出哪个元件、哪个事项，壳从当前状态取到位置，得出 Yudao 页面现有带位置的地址
//     （#/p/<项目>/overview?at=<位置>&w=<事项>），只写路径、同一来源，在新的标签页打开；细内容在页面上看。
//   - 跳转与聚焦：楼、楼层、房间之间的切换在壳里做，不经页面。
//   - 接口版本与连接状态的提示由壳写出来（画布以外的文字，不属于画面合同）。
//
// 场景的挂载：三个场景组件把画布容器与建立画面的函数交给 attachHost；数据变化只走 setState/jump，
// 不重建画面（同一场景对象挂载一次）。单元测试用假的地面与假的像素画面驱动这一层。

import type {
  Capabilities, DecisionList, DecisionView, DepartmentWorkspaceResult, EventObject, ProjectList, ProjectLoopResult,
  ProjectRow, RunAsksResult,
} from "./api/generated/types.gen.ts";
import type { CommandOutcome } from "./sync/connection.ts";
import type {
  DecisionFace, FactElement, FloorModel, LoopItem, PixelAction, PixelState, SourceRef,
} from "./pixel/contract.ts";
import type { DecisionAnswer, DecisionResult } from "./pixel/floor/card.ts";
import type { Clock } from "./pixel/clock.ts";
import { buildingActions, buildingState, toBuildingEvent } from "./translate/building.ts";
import { belongsTo, floorActions, floorCards, floorInterrupted, floorState, streamText, toFloorEvent } from "./translate/floor.ts";
import * as room from "./translate/room.ts";
import { DEPARTMENT_NAMES } from "./translate/face.ts";
import { classOf, COVERAGE, OVERLAY_LABELS, overlayProblems, SCENES, type Scene } from "./translate/coverage.ts";
import type { SyncEngine, SyncState, ViewSync } from "./sync/sync.ts";
import { SyncEngine as DefaultSyncEngine } from "./sync/sync.ts";

// ---------------------------------------------------------------------------
// 场景与画面之间的接口

/** 画面自己的三个场景。 */
export type SceneKind = "building" | "floor" | "room";

/** 当前在哪个场景：楼（项目与它们的楼层）、楼层（一个项目）、房间（一个部门）。 */
export type SceneRef =
  | { kind: "building" }
  | { kind: "floor"; projectId: string; workItemId: string | null }
  | { kind: "room"; projectId: string; department: string; workItemId: string | null };

/** 画面层会给壳的一个对象：像素画面（楼、楼层或房间）。只用到画面合同里的四件事。 */
export interface SceneSurface {
  jump(state: PixelState): void;
  setState(state: PixelState): void;
  play(action: PixelAction): void;
  setDecisions?(faces: DecisionFace[]): void;
  stream?(who: { room: string | null; role: string | null }, text: string): void;
  destroy?(): void;
}

/** 建立像素画面的函数：场景组件把画布容器与时钟交给它，返回画面对象。 */
export type SceneFactory = (options: { host: HTMLElement; clock: Clock }) => Promise<SceneSurface>;

/** 壳要交给场景组件的东西：命令行、回链、场景切换与状态。 */
export type ShellState = {
  status: SyncState;
  scene: SceneRef;
  /** 缺口清单：能力清单里缺少的命令与查询、画面还不认识的事件与覆盖层。 */
  gap: string[];
  /** 画面生成类型时的接口版本与服务的接口版本；还没连上时为空。 */
  versions: { view: number; server: number } | null;
  /** 接口版本不一致时的一句话；一致时为空。 */
  versionNote: string | null;
  /** 大厅决定板的选项此刻可操作：能力清单里有回答决定的命令。 */
  decisionsOperable: boolean;
  /** 面包屑：楼 / 项目名 / 部门名，每一项都能回到那一层（不经页面）。 */
  crumbs: { label: string; scene: SceneRef }[];
  /** 画面还没有数据时的一句话（读不出来、没有项目、服务少一条查询）。 */
  note: string | null;
};

/** 壳的依赖：默认用画面自己的同步引擎与浏览器的新标签页。单元测试注入替身。 */
export type ShellDeps = {
  engine?: SyncEngine;
  /** 打开页面地址：默认在新标签页打开（只写路径，同一来源）。 */
  openPage?: (url: string) => void;
  now?: () => number;
  newCommandId?: () => string;
};

/** 画面的查询（与页面读同一组；服务端不为画面加查询）。 */
const QUERIES = {
  projects: "projects.list",
  loop: "project.loop",
  decisions: "decisions.list",
  workspace: "department.workspace",
  asks: "run.asks",
} as const;

/** 画面要发的命令（只发能力清单里列出的；以后拖包裹调优先级时加在这里）。 */
const COMMANDS = {
  answer: "decision.answer",
} as const;

/** 画面要用的查询与少了它时不画的部分（缺口清单用）。 */
const NEEDED_QUERIES: { name: string; what: string }[] = [
  { name: QUERIES.projects, what: "楼与楼层的项目名" },
  { name: QUERIES.loop, what: "楼层与楼里的事项" },
  { name: QUERIES.decisions, what: "大厅决定板上的卡片" },
  { name: QUERIES.workspace, what: "部门房间里的角色与状态" },
  { name: QUERIES.asks, what: "楼层传信管里等待回答的询问" },
];

/** 画面要用的命令与少了它时不可操作的物件（缺口清单用）。 */
const NEEDED_COMMANDS: { name: string; what: string }[] = [
  { name: COMMANDS.answer, what: "大厅决定板上的选项" },
];

/** 生成一个命令标识（RFC 4122 第 4 版）：crypto.getRandomValues 在任何访问方式下都有。 */
export function newCommandId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [hex.slice(0, 4).join(""), hex.slice(4, 6).join(""), hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""), hex.slice(10, 16).join("")].join("-");
}

/** 场景的标识：同一场景对象（同一个项目、同一个部门）复用同一个绑定，数据变化不重建画面。 */
export function sceneKey(ref: SceneRef): string {
  if (ref.kind === "building") return "building";
  if (ref.kind === "floor") return `floor:${ref.projectId}`;
  return `room:${ref.projectId}:${ref.department}`;
}

/**
 * Yudao 页面的地址（只写路径，画面与页面同一来源）：页面现有带位置的写法是
 * #/p/<项目>/overview?at=<位置>&w=<事项>（参数顺序与页面 shell/routing.ts 的 overviewAt 一致）。
 * 位置为空时不带 at（回不到具体那一刻时只看项目概览），事项为空时不带 w。
 */
export function pagePathFor(target: { projectId: string; workItemId: string | null; position: number | null }): string {
  const query = new URLSearchParams();
  if (target.position !== null && Number.isFinite(target.position)) {
    query.set("at", String(target.position));
  }
  if (target.workItemId) {
    query.set("w", target.workItemId);
  }
  const suffix = query.toString();
  return `/#/p/${target.projectId}/overview${suffix ? `?${suffix}` : ""}`;
}

/** 版本不一致时的一句话：只写两边各是第几版与做不到什么，不报错退出。 */
export function versionNote(versions: { view: number; server: number } | null): string | null {
  if (versions === null || versions.server === versions.view) return null;
  const head = `接口版本：画面第 ${versions.view} 版，Yudao 第 ${versions.server} 版`;
  if (versions.server > versions.view) {
    return `${head}；Yudao 比画面新，画面照常显示，多出来的事件与字段列进缺口清单`;
  }
  return `${head}；Yudao 缺画面要用的查询或命令，那部分不画`;
}

/** 一个场景对象的绑定：像素画面挂在这里；数据变化只交给它，不重建。 */
interface Binding {
  ref: SceneRef;
  surface: SceneSurface | null;
  host: HTMLElement | null;
  /** 这个场景对象被挂载过几次（同一场景对象只该是 1；测试与排查用）。 */
  mounts: number;
  /** 被卸下过几次（换项目、换部门、离开这个场景）。 */
  destroys: number;
  /** 建立画面失败时的原因。 */
  error: string | null;
}

const emptyBinding = (ref: SceneRef): Binding => ({ ref, surface: null, host: null, mounts: 0, destroys: 0, error: null });

/**
 * 壳：连接同步层、翻译层与画面层；画面层交出的回调在这里变成现有的命令或页面的地址。
 * 同一个画面对象（场景组件）只挂载一次；数据变化走 setState，重新同步与打开画面走 jump。
 */
export class Shell {
  private readonly engine: SyncEngine;
  private readonly openPage: (url: string) => void;
  private readonly now: () => number;
  private readonly newId: () => string;
  private readonly bindings = new Map<string, Binding>();
  private readonly stateListeners = new Set<(state: ShellState) => void>();
  private readonly answers = new Map<string, Promise<CommandOutcome>>();
  private readonly answerIds = new Map<string, string>();
  private readonly unknownEvents = new Set<string>();
  private status: SyncState = { kind: "connecting" };
  private capabilities: Capabilities | null = null;
  private versions: { view: number; server: number } | null = null;
  private scene: SceneRef = { kind: "building" };
  private model: PixelState | null = null;
  private decisions: DecisionFace[] = [];
  private gap: string[] = [];
  private note: string | null = null;
  // 楼：projects.list 与每个项目的 project.loop
  private projects: ProjectRow[] = [];
  private projectPosition = 0;
  private readonly loops = new Map<string, ProjectLoopResult>();
  private readonly loopPositions = new Map<string, number>();
  // 楼层：project.loop、大厅的决定请求与这次运行的询问链
  private loop: ProjectLoopResult | null = null;
  /** 最近一次读到的楼层（换场景时留着：从楼层进房间时按它取正在工作的事项）。 */
  private lastLoop: ProjectLoopResult | null = null;
  private loopPosition = 0;
  private decisionRows: DecisionView[] = [];
  private decisionPosition = 0;
  private asks: RunAsksResult | null = null;
  private askPosition = 0;
  private asksRunId = "";
  // 房间：department.workspace
  private workspace: DepartmentWorkspaceResult | null = null;
  private workspacePosition = 0;

  constructor(deps: ShellDeps = {}) {
    this.engine = deps.engine ?? new DefaultSyncEngine();
    this.openPage = deps.openPage ?? ((url: string) => {
      window.open(url, "_blank", "noopener");
    });
    this.now = deps.now ?? (() => Date.now());
    this.newId = deps.newCommandId ?? newCommandId;
    this.engine.subscribeState((state) => this.onSyncState(state));
    this.engine.subscribeEvents((event) => this.onEvent(event));
    this.engine.subscribeResync(() => this.jumpLatest());
  }

  /** 同步引擎（场景组件不用它；测试与排查用它读已打开的视图、推进合并查询）。 */
  get sync(): SyncEngine {
    return this.engine;
  }

  /** 当前状态：连接状态、场景、缺口清单、版本与面包屑。 */
  get state(): ShellState {
    return {
      status: this.status,
      scene: this.scene,
      gap: this.gap,
      versions: this.versions,
      versionNote: versionNote(this.versions),
      decisionsOperable: this.decisionsOperable,
      crumbs: this.crumbs(),
      note: this.note,
    };
  }

  /** 大厅决定板的选项此刻可操作：能力清单里有回答决定的命令。 */
  get decisionsOperable(): boolean {
    return this.capabilities?.commands.some((command) => command.name === COMMANDS.answer) ?? false;
  }

  /** 这次连接的身份（局域网访问方式的令牌；本机访问方式为空串）。命令都带着它发出。 */
  get identity(): string {
    return this.engine.currentAccess?.identity ?? "";
  }

  /** 订阅状态：壳上的连接状态、缺口清单、场景与面包屑都从这里刷新。 */
  subscribe(listener: (state: ShellState) => void): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  /** 连上画面自己的来源（地址就是画面自己的来源；局域网访问方式下带上令牌）。 */
  async open(address: string, token = ""): Promise<void> {
    await this.engine.open(address, token);
  }

  /** 断开：停止事件流与已打开的视图（壳重建时用）。 */
  close(): void {
    this.closeSceneViews();
    this.engine.close();
  }

  // -------------------------------------------------------------------------
  // 场景：楼 → 楼层 → 房间，不经页面

  /** 回到楼。 */
  goBuilding(): void {
    this.setScene({ kind: "building" });
  }

  /** 进入一个项目的楼层（画面上的楼层被点中时由壳调用；也可以从面包屑回来）。 */
  goFloor(projectId: string, workItemId: string | null = null): void {
    this.setScene({ kind: "floor", projectId, workItemId });
  }

  /** 进入一个部门的房间（楼层上的屋被点中时由壳调用）。 */
  goRoom(department: string): void {
    const projectId = this.sceneProjectId();
    if (projectId === null) return;
    const workItemId = this.scene.kind === "building" ? null : this.scene.workItemId;
    this.setScene({ kind: "room", projectId, department, workItemId });
  }

  private sceneProjectId(): string | null {
    return this.scene.kind === "building" ? null : this.scene.projectId;
  }

  private setScene(next: SceneRef): void {
    if (sceneKey(next) === sceneKey(this.scene)) return;
    this.closeSceneViews();
    this.scene = next;
    // 换场景对象：清掉上一个对象的模型与决定卡片，新对象的画面挂上来以前不会拿到旧数据
    this.model = null;
    this.decisions = [];
    this.note = null;
    this.openSceneViews();
    this.notify();
  }

  // -------------------------------------------------------------------------
  // 画面回调 → 命令

  /**
   * 画面里选择了决定选项：发回答决定的命令（带身份；同一个 command_id 重发只生效一次）。
   * 能力清单里没有这条命令时选项不可操作：不发命令，回一句缺口清单里写着的话。
   */
  async decide(payload: DecisionAnswer): Promise<DecisionResult> {
    if (!this.decisionsOperable) {
      return { accepted: false, message: missingCommandText(COMMANDS.answer) };
    }
    const key = [payload.decision_id, payload.option, String(payload.base_version)].join("\u0000");
    const known = this.answers.get(key);
    if (known) {
      // 同一个回答重发（连点、画面重发）：不再发一次，返回第一次的结果
      return toResult(await known);
    }
    const commandId = this.answerIds.get(key) ?? this.newId();
    this.answerIds.set(key, commandId);
    const body: Record<string, unknown> = {
      command_id: commandId,
      decision_id: payload.decision_id,
      option: payload.option,
      base_version: payload.base_version,
    };
    if (payload.note !== undefined && payload.note !== null && payload.note !== "") {
      body.note = payload.note;
    }
    const pending = this.send(COMMANDS.answer, body, commandId);
    this.answers.set(key, pending);
    const outcome = await pending;
    if (!outcome.ok) {
      // 被拒绝（或这一条没有发出去）：不把这次结果算作已经生效，用户可以再点一次；
      // command_id 留着——服务按同一个标识认这一次操作，重发只生效一次
      this.answers.delete(key);
    }
    return toResult(outcome);
  }

  /**
   * 发出一个命令：只发能力清单里列出的；同一个 command_id 只发一次，重发返回第一次的结果。
   * 服务说这条 command_id 之前已经受理过（duplicate）时效果也只有第一次那一次。
   */
  private send(name: string, body: Record<string, unknown>, commandId: string): Promise<CommandOutcome> {
    const sent = this.sentCommands.get(commandId);
    if (sent) return sent;
    if (!this.capabilities?.commands.some((command) => command.name === name)) {
      return Promise.resolve({ ok: false, message: missingCommandText(name) });
    }
    const pending = this.engine.command(name, body).catch((error: unknown): CommandOutcome => ({
      ok: false,
      message: error instanceof Error ? error.message : String(error),
    }));
    this.sentCommands.set(commandId, pending);
    return pending;
  }

  /** 已发出的命令（按 command_id）：同一个标识重发时不再发一次。 */
  private readonly sentCommands = new Map<string, Promise<CommandOutcome>>();

  // -------------------------------------------------------------------------
  // 画面回调 → 页面地址（点开回链）

  /**
   * 点开回链：画面交出哪个事项、哪个元件，壳从当前楼层状态取到位置，
   * 得出 Yudao 页面的地址并在新标签页打开。返回打开的地址（测试与排查用）。
   */
  openFactLink(workItemId: string, element: FactElement): string | null {
    const projectId = this.sceneProjectId();
    if (projectId === null) return null;
    return this.openPageLink({ projectId, workItemId, position: this.factPosition(workItemId, element) });
  }

  /** 决定卡片上的一个页面链接（页面现有写法：以 # 开头的路径）：在新标签页打开页面。 */
  openPageTarget(target: string): void {
    // 只认页面的路径（# 之后的写法）；别的地址不打开，画面不把用户带到服务以外的地方
    if (!target.startsWith("#/") && !target.startsWith("/#")) return;
    const hash = target.startsWith("#") ? target : target.slice(1);
    this.openPage(`/${hash}`);
  }

  /** 来源卡片上的「在时间轴上查看」：页面概览按位置打开。 */
  openTimelineLink(position: number): void {
    const projectId = this.sceneProjectId();
    if (projectId === null) return;
    this.openPageLink({ projectId, workItemId: this.sceneWorkItemId(), position });
  }

  /** 打开一个 Yudao 页面的地址（只写路径，同一来源；细内容在页面上看）。 */
  openPageLink(target: { projectId: string; workItemId: string | null; position: number | null }): string {
    const path = pagePathFor(target);
    this.openPage(path);
    return path;
  }

  private sceneWorkItemId(): string | null {
    return this.scene.kind === "building" ? null : this.scene.workItemId;
  }

  private factPosition(workItemId: string, element: FactElement): number | null {
    const model = this.model as FloorModel | null;
    const item = model?.items?.find((row: LoopItem) => row.work_item_id === workItemId);
    const ref = item?.refs?.[element] as SourceRef | null | undefined;
    return ref && typeof ref.position === "number" ? ref.position : null;
  }

  // -------------------------------------------------------------------------
  // 画面挂载

  /**
   * 场景组件挂载画布时调用：建立像素画面并接上当前的模型与决定卡片；
   * 返回卸载函数。数据变化不经过这里（画面不重建），只有换场景对象才重新挂载。
   */
  attachHost(host: HTMLElement, clock: Clock, factory: SceneFactory): () => void {
    const binding = this.binding(this.scene);
    binding.host = host;
    binding.mounts += 1;
    binding.error = null;
    let cancelled = false;
    void factory({ host, clock }).then((surface) => {
      if (cancelled) {
        binding.destroys += 1;
        surface.destroy?.();
        return;
      }
      binding.surface = surface;
      this.applyCurrent(binding);
    }).catch((error: unknown) => {
      binding.error = error instanceof Error ? error.message : String(error);
      this.note = `画面加载失败：${binding.error}`;
      this.notify();
    });
    return () => {
      cancelled = true;
      if (binding.host === host) binding.host = null;
      if (binding.surface !== null) {
        binding.destroys += 1;
        binding.surface.destroy?.();
        binding.surface = null;
      }
    };
  }

  /** 一个场景对象的挂载读数（测试与排查用）。 */
  inspectBinding(ref: SceneRef = this.scene): { mounts: number; destroys: number; attached: boolean; error: string | null } {
    const binding = this.bindings.get(sceneKey(ref)) ?? emptyBinding(ref);
    return { mounts: binding.mounts, destroys: binding.destroys, attached: binding.surface !== null, error: binding.error };
  }

  private binding(ref: SceneRef): Binding {
    const key = sceneKey(ref);
    const existing = this.bindings.get(key);
    if (existing) return existing;
    const created = emptyBinding(ref);
    this.bindings.set(key, created);
    return created;
  }

  /** 新挂上的画面：打开场景用 jump（不补播），并贴上当前的实时内容。 */
  private applyCurrent(binding: Binding): void {
    const surface = binding.surface;
    if (surface === null) return;
    if (this.model !== null) surface.jump(this.model);
    surface.setDecisions?.(this.decisions);
  }

  /** 重新同步、从后台切回：清空时间线，直接显示最新的状态（不补播）。 */
  private jumpLatest(): void {
    const binding = this.bindings.get(sceneKey(this.scene));
    if (binding?.surface && this.model !== null) binding.surface.jump(this.model);
  }

  // -------------------------------------------------------------------------
  // 同步层与翻译层 → 画面

  private onSyncState(state: SyncState): void {
    this.status = state;
    if (state.kind === "connected") {
      const capabilitiesChanged = state.capabilities !== this.capabilities;
      this.capabilities = state.capabilities;
      this.versions = state.versions;
      this.gap = this.gapLines(state.capabilities);
      if (capabilitiesChanged) {
        // 换上新的能力清单：重新打开当前场景的视图（上一次连接留下的登记不重建）
        this.openSceneViews();
      }
    } else if (state.kind === "unauthorized" || state.kind === "failed") {
      this.closeSceneViews();
    }
    this.notify();
  }

  /** 缺口清单：能力清单里缺少的命令与查询、画面还不认识的事件与覆盖层。 */
  private gapLines(capabilities: Capabilities): string[] {
    const lines: string[] = [];
    const commands = new Set(capabilities.commands.map((command) => command.name));
    for (const needed of NEEDED_COMMANDS) {
      if (!commands.has(needed.name)) lines.push(missingCommandText(needed.name, needed.what));
    }
    const queries = new Set(capabilities.queries.map((query) => query.name));
    for (const needed of NEEDED_QUERIES) {
      if (!queries.has(needed.name)) lines.push(`能力清单里没有查询 ${needed.name}：${needed.what}不画`);
    }
    const unknown = this.unknownEventLines(capabilities);
    lines.push(...unknown);
    lines.push(...overlayProblems((capabilities.overlays ?? []).map((overlay) => overlay.name), OVERLAY_LABELS)
      .map((problem) => `${problem}，这个覆盖层不画`));
    return lines;
  }

  /** 画面还不认识的事件：每种事件在三个场景里要么有归属、要么列在这里（按场景写几个）。 */
  private unknownEventLines(capabilities: Capabilities): string[] {
    const lines: string[] = [];
    const counts: string[] = [];
    for (const scene of SCENES) {
      const types = new Set(capabilities.event_types.filter((type) => classOf(COVERAGE, scene, type) === null));
      for (const type of types) this.unknownEvents.add(`${scene}:${type}`);
      const extra = [...this.unknownEvents].filter((entry) => entry.startsWith(`${scene}:`)).length;
      if (extra > 0) counts.push(`${sceneName(scene)} ${extra} 种`);
    }
    if (counts.length > 0) {
      lines.push(`画面还不认识的事件：${counts.join("、")}；不画，列在缺口清单里`);
    }
    return lines;
  }

  private onEvent(event: EventObject): void {
    const binding = this.bindings.get(sceneKey(this.scene));
    if (!binding?.surface) return;
    const surface = binding.surface;
    const scene = this.scene;
    if (scene.kind === "building") {
      this.noteUnknown("building", event.type);
      for (const action of buildingActions(toBuildingEvent(event))) surface.play(action);
      return;
    }
    if (scene.kind === "floor") {
      const floorEvent = toFloorEvent(event);
      if (!belongsTo(floorEvent, scene.projectId)) return;
      this.noteUnknown("floor", event.type);
      const stream = streamText(floorEvent);
      if (stream !== null) {
        surface.stream?.({ room: stream.room, role: stream.role }, stream.text);
        return;
      }
      for (const action of floorActions(floorEvent, this.roleContext())) surface.play(action);
      return;
    }
    const roomEvent = room.eventOf(event, event.position);
    if (roomEvent.department !== null && roomEvent.department !== undefined && roomEvent.department !== scene.department) {
      return;
    }
    this.noteUnknown("room", event.type);
    const stream = room.streamOfEvent(roomEvent);
    if (stream !== null) {
      surface.stream?.(stream.who, stream.text);
      return;
    }
    for (const action of room.actions(roomEvent, scene.department, this.roleContext())) surface.play(action);
  }

  /** 运行时收到画面还不认识的事件：缺口清单多一行，不打断画面。 */
  private noteUnknown(scene: Scene, type: string): void {
    if (classOf(COVERAGE, scene, type) !== null) return;
    if (this.unknownEvents.has(`${scene}:${type}`)) return;
    this.unknownEvents.add(`${scene}:${type}`);
    if (this.capabilities !== null) this.gap = this.gapLines(this.capabilities);
    this.notify();
  }

  /** 翻译层说话时用的角色名（房间里的角色；楼层上没有角色表时返回空）。 */
  private roleContext(): { roleName: (role: string | null) => string | null } {
    const roles = this.workspace?.room?.roles ?? [];
    return {
      roleName: (id: string | null): string | null => {
        if (!id) return null;
        const hit = roles.find((role) => role.id === id || role.kind === id || role.name === id);
        return hit ? hit.name : null;
      },
    };
  }

  // -------------------------------------------------------------------------
  // 三个场景的视图与状态

  private closeSceneViews(): void {
    const views = this.engine.viewSync;
    if (!views) return;
    for (const viewId of views.openViewIds) views.close(viewId);
    this.loops.clear();
    this.loopPositions.clear();
    this.loop = null;
    this.asks = null;
    this.asksRunId = "";
    this.workspace = null;
    this.decisionRows = [];
  }

  private openSceneViews(): void {
    const views = this.engine.viewSync;
    if (!views) return;
    this.closeSceneViews();
    const capabilities = this.capabilities;
    if (capabilities === null) return;
    if (this.scene.kind === "building") this.openBuildingViews(views, capabilities);
    else if (this.scene.kind === "floor") this.openFloorViews(views, capabilities, this.scene.projectId, this.scene.workItemId);
    else this.openRoomViews(views, capabilities, this.scene.projectId, this.scene.department);
  }

  private hasQuery(capabilities: Capabilities, name: string): boolean {
    return capabilities.queries.some((query) => query.name === name);
  }

  private openBuildingViews(views: ViewSync, capabilities: Capabilities): void {
    if (!this.hasQuery(capabilities, QUERIES.projects)) {
      this.setNote(`服务没有登记 ${QUERIES.projects}：楼不画`);
      return;
    }
    void views.open<ProjectList>("building.projects", { query: QUERIES.projects, params: {} }, (data, position) => {
      this.projects = data.projects;
      this.projectPosition = position;
      this.syncProjectLoops(views, capabilities);
      this.rebuildBuilding();
    }, (reason) => this.setNote(`项目列表读不出来：${reason}`));
  }

  /** 楼需要每个项目的 project.loop：项目列表变了就补开、关掉不再有的项目。 */
  private syncProjectLoops(views: ViewSync, capabilities: Capabilities): void {
    if (!this.hasQuery(capabilities, QUERIES.loop)) return;
    const wanted = new Set(this.projects.map((project) => project.project_id));
    for (const projectId of [...this.loops.keys()]) {
      if (!wanted.has(projectId)) {
        views.close(`building.loop.${projectId}`);
        this.loops.delete(projectId);
        this.loopPositions.delete(projectId);
      }
    }
    for (const project of this.projects) {
      if (this.loops.has(project.project_id)) continue;
      void views.open<ProjectLoopResult>(
        `building.loop.${project.project_id}`,
        { query: QUERIES.loop, params: { project_id: project.project_id } },
        (data, position) => {
          this.loops.set(project.project_id, data);
          this.loopPositions.set(project.project_id, position);
          this.rebuildBuilding();
        },
        () => {
          // 这一层读不出来：楼照常画其余各层，层上的事项为空
        },
      );
    }
  }

  private rebuildBuilding(): void {
    const positions = [this.projectPosition, ...this.loopPositions.values()].filter((value) => value > 0);
    const position = positions.length === 0 ? 0 : Math.max(...positions);
    const loops: Record<string, ProjectLoopResult> = {};
    for (const [projectId, loop] of this.loops) loops[projectId] = loop;
    const model = buildingState({ position, projects: this.projects, loops });
    this.setModel(model, []);
  }

  private openFloorViews(views: ViewSync, capabilities: Capabilities, projectId: string, workItemId: string | null): void {
    if (!this.hasQuery(capabilities, QUERIES.loop)) {
      this.setNote(`服务没有登记 ${QUERIES.loop}：楼层不画`);
      return;
    }
    void views.open<ProjectLoopResult>(
      "floor.loop",
      { query: QUERIES.loop, params: { project_id: projectId, work_item: workItemId } },
      (data, position) => {
        this.loop = data;
        this.lastLoop = data;
        this.loopPosition = position;
        this.ensureAsksView(views, capabilities, data, workItemId);
        this.rebuildFloor();
      },
      (reason) => this.setNote(`楼层读不出来：${reason}`),
    );
    if (!this.hasQuery(capabilities, QUERIES.decisions)) return;
    void views.open<DecisionList>(
      "floor.decisions",
      { query: QUERIES.decisions, params: { project_id: projectId, status: ["open"] } },
      (data, position) => {
        this.decisionRows = data.decisions;
        this.decisionPosition = position;
        this.rebuildFloor();
      },
      () => {
        // 决定请求读不出来：大厅板上暂时没有卡片，画面上其余部分照常
      },
    );
  }

  /**
   * 楼层要读这次运行的询问链：聚焦的事项优先，否则进行中的一项，再没有就是第一项（与页面同一口径）。
   * 运行换了就关掉旧的登记、按新的运行重开。
   */
  private ensureAsksView(views: ViewSync, capabilities: Capabilities, loop: ProjectLoopResult, focus: string | null): void {
    if (!this.hasQuery(capabilities, QUERIES.asks)) return;
    const runId = this.focusItem(loop, focus)?.run_id ?? "";
    if (runId === this.asksRunId) return;
    this.asksRunId = runId;
    views.close("floor.asks");
    this.asks = null;
    this.askPosition = 0;
    if (runId === "") return;
    void views.open<RunAsksResult>(
      "floor.asks",
      { query: QUERIES.asks, params: { run_id: runId } },
      (data, position) => {
        this.asks = data;
        this.askPosition = position;
        this.rebuildFloor();
      },
      () => {
        // 询问链读不出来：楼层照常画，传信管里没有信
      },
    );
  }

  private rebuildFloor(): void {
    const loop = this.loop;
    if (loop === null) return;
    const positions = [this.loopPosition, this.askPosition, this.decisionPosition].filter((value) => value > 0);
    const position = positions.length === 0 ? 0 : Math.max(...positions);
    const asks = this.asksRunId === "" || this.asks === null ? null : { [this.asksRunId]: this.asks.asks };
    const model = floorState({
      position,
      loop,
      asks,
      roles: null,
      slots: null,
      ops: null,
      machines: null,
      interrupted: floorInterrupted(loop, this.status.kind === "connected" && this.status.stream === "interrupted"),
      focus: this.scene.kind === "floor" ? this.scene.workItemId : null,
    });
    const cards = floorCards(this.decisionRows, (decision) => ({
      projectName: this.projectName(decision.project_id),
      workItemTitle: this.workItemTitle(decision.work_item_id, loop),
    }), this.now());
    this.setModel(model, cards);
  }

  /** 聚焦的事项：指定的一个、否则进行中的一项、再没有就是第一项。 */
  private focusItem(loop: ProjectLoopResult | null, focus: string | null): { work_item_id: string; run_id: string } | null {
    const rows = loop?.work_items ?? [];
    return (focus === null ? undefined : rows.find((row) => row.work_item_id === focus))
      ?? rows.find((row) => row.status === "in_progress" || row.status === "awaiting_initial_prd")
      ?? rows[0]
      ?? null;
  }

  private openRoomViews(views: ViewSync, capabilities: Capabilities, projectId: string, department: string): void {
    if (!this.hasQuery(capabilities, QUERIES.workspace)) {
      this.setNote(`服务没有登记 ${QUERIES.workspace}：部门房间不画`);
      return;
    }
    // 房间读的是这个部门在一个事项上的工作间：带上事项，画面才画得出这个事项的角色与状态；
    // 没有指定事项时取楼层上正在工作的那一项（从楼进来时楼层还没有打开时为空）
    const scoped = this.scene.kind === "room" ? this.scene.workItemId : null;
    const fallback = this.lastLoop !== null && this.lastLoop.project_id === projectId
      ? this.focusItem(this.lastLoop, null)?.work_item_id ?? null
      : null;
    const workItem = scoped ?? fallback;
    const params: Record<string, unknown> = { project_id: projectId, department };
    if (workItem !== null) params.work_item = workItem;
    void views.open<DepartmentWorkspaceResult>(
      "room.workspace",
      { query: QUERIES.workspace, params },
      (data, position) => {
        this.workspace = data;
        this.workspacePosition = position;
        this.rebuildRoom();
      },
      (reason) => this.setNote(`部门房间读不出来：${reason}`),
    );
  }

  private rebuildRoom(): void {
    if (this.workspace === null) return;
    const model = room.state({ position: this.workspacePosition, workspace: { room: this.workspace.room } });
    this.setModel(model, []);
  }

  private setModel(model: PixelState | null, decisions: DecisionFace[]): void {
    this.model = model;
    this.decisions = decisions;
    this.note = null;
    const binding = this.bindings.get(sceneKey(this.scene));
    if (binding?.surface) {
      if (model !== null) binding.surface.setState(model);
      binding.surface.setDecisions?.(decisions);
    }
    this.notify();
  }

  private setNote(note: string): void {
    this.note = note;
    this.notify();
  }

  private projectName(projectId: string | null): string {
    if (projectId === null) return "";
    return this.projects.find((project) => project.project_id === projectId)?.name ?? projectId;
  }

  private workItemTitle(workItemId: string | null, loop: ProjectLoopResult | null): string {
    if (workItemId === null) return "";
    const row = (loop?.work_items ?? []).find((item) => item.work_item_id === workItemId)
      ?? (this.lastLoop?.work_items ?? []).find((item) => item.work_item_id === workItemId);
    return row?.sign ?? "";
  }

  /** 面包屑：楼 / 项目名 / 部门名；每一项都能回到那一层。 */
  private crumbs(): { label: string; scene: SceneRef }[] {
    const items: { label: string; scene: SceneRef }[] = [{ label: "楼", scene: { kind: "building" } }];
    if (this.scene.kind === "building") return items;
    items.push({
      label: this.projectName(this.scene.projectId),
      scene: { kind: "floor", projectId: this.scene.projectId, workItemId: this.scene.workItemId },
    });
    if (this.scene.kind === "room") {
      items.push({
        label: DEPARTMENT_NAMES[this.scene.department] ?? this.scene.department,
        scene: this.scene,
      });
    }
    return items;
  }

  private notify(): void {
    const state = this.state;
    for (const listener of [...this.stateListeners]) listener(state);
  }
}

/** 能力清单里没有这条命令时的一句话（缺口清单与回调的拒绝共用）。 */
function missingCommandText(name: string, what = ""): string {
  const target = what === "" ? "" : `：${what}`;
  return `能力清单里没有命令 ${name}${target}；对应的物件不可操作`;
}

/** 场景的中文名（缺口清单用）。 */
function sceneName(scene: Scene): string {
  return scene === "building" ? "楼" : scene === "floor" ? "楼层" : "房间";
}

/** 命令的结果 → 画面层要的回答结果（被拒绝时把原因交给卡片）。 */
function toResult(outcome: CommandOutcome): DecisionResult {
  return outcome.ok ? { accepted: true, message: "" } : { accepted: false, message: outcome.message };
}
