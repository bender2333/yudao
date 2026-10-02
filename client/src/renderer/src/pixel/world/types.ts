// 项目楼层的世界与系统的数据形状（原型 v9 设计说明第 3 至 6 节，工单 #82）。
// 这里只放类型：实体、组件、任务目录、待机活动、信号与画面数据。
// 世界与系统不依赖渲染与 PixiJS，可以直接在 node --test 下驱动。

/** 任务里的命名位置（原型 floor-decl.js 的 spot 字段）。 */
export type SpotKind =
  | "desk"
  | "stand"
  | "cabinet"
  | "terminal"
  | "monitor"
  | "inspect"
  | "port_in"
  | "port_out"
  | "door"
  | "peer"
  | "at";

/** 任务声明里的效果：信号、房间闪光、包裹沿管道走。 */
export interface TaskFx {
  when: "start" | "done";
  signal?: string;
  ms?: number;
  flash?: { room: string; color: string; ms?: number };
  send?: { link: string; bmp: string; color?: string; reverse?: boolean; then?: TaskFx[] };
}

/** 任务目录里的一项（原型 floor-decl.js 的 TASKS）。 */
export interface TaskDef {
  label: string;
  spot: SpotKind;
  pose: string;
  /** 'say' 时头顶显示说话气泡；null 时不显示（待机活动）。 */
  bubble: "say" | null;
  ms: number;
  icon?: string | null;
  facing?: number;
  /** 事件没有指定角色时由这种角色做。 */
  by?: string;
  /** 不管事件指定了谁，都由这种角色做（分派任务由经理做）。 */
  actor?: string;
  /** spot 为 'peer' 时走向谁：'role'（事件指定的角色）或者角色种类。 */
  toward?: string;
  /** 做完以后放进走向对象队列的任务键。 */
  then?: string;
  /** spot 为 'dept' 时由哪个部门做（事件没有部门字段时用）。 */
  dept?: string;
  /** 不会被队列上限挤掉，也不会被插队放弃。 */
  must?: boolean;
  /** 流式输出：文字接在正在做的模型请求上。 */
  streaming?: boolean;
  /** 待机活动。 */
  idle?: boolean;
  fx?: TaskFx[];
}

/** 待机活动（原型 floor-decl.js 的 IDLE）。 */
export interface IdleDef {
  key: string;
  weight: number;
  kinds?: string[];
  needs?: "mate";
  at?: "wander" | "door";
}

/** 角色实体：一个部门按角色设置有几个，没有角色设置时一个（id 是部门名）。 */
export interface Character {
  kind: "character";
  id: string;
  department: string | null;
  roleKind: string;
  name: string;
  seatIndex: number;
  spot: { x: number; y: number };
  queue: Task[];
  current: Task | null;
  rest: RestState | null;
  bubble: Bubble | null;
  /** 本次快照对应的主事项（渲染用）。 */
  item: LoopItem | null;
  /** 本次快照对应的角色设置（渲染用）。 */
  roleInfo: RoleInfo | null;
  /** 下一次自己挑待机活动的时刻（毫秒）。 */
  idleAt: number | null;
}

/** 持续状态与任务共有的字段：摆放与动作的形状（任务把 spot、pose、label 声明为必填）。 */
export interface Goal {
  spot?: SpotKind | null;
  pose?: string;
  icon?: string | null;
  iconText?: string | null;
  facing?: number;
  hold?: string | null;
  label?: string;
  /** 为真时角色从画面上消失，回来时从门口走进来。 */
  away?: boolean;
  /** 任务自带的坐标（spot 为 'at' 时）。 */
  at?: { x: number; y: number };
  idle?: boolean;
}

/** 持续状态：形状与任务相同，只在没有任务在做时生效。 */
export type RestState = Goal;

/** 队列里的一项：任务定义加本次的字段。 */
export interface Task extends Omit<TaskDef, "spot" | "pose" | "label" | "facing" | "icon">, Goal {
  taskKey: string;
  label: string;
  spot: SpotKind;
  pose: string;
  withId?: string;
  workItemId?: string | null;
  streaming?: boolean;
  streamed?: boolean;
  /** 到达位置的时刻（毫秒）；走路的时间不算在动作里。 */
  _t0: number | null;
  _started?: boolean;
  start?: (task: Task) => void;
  done?: (task: Task) => void;
  onDone?: (task: Task) => void;
}

/** 包裹：放进管道时生成，到达终点后销毁。 */
export interface Package {
  kind: "package";
  id: string;
  workItemId: string | null;
  colorIndex: number | null;
  artifact: string | null;
  /** 画出这个包裹所用的位图与颜色（画面在生成时写上）。 */
  bmp?: string;
  color?: string | null;
  small?: boolean;
  atRest: { roomId: string | null; spotKind: string } | null;
  /**
   * 沿管道移动的状态；t0 为本次移动的起始时刻（毫秒）。
   * k 是移动进度：由 GSAP 的补间推进（tweenStart 在第一次推进时建立补间），
   * 没有补间时（纯逻辑测试）按经过时间算。
   */
  transit: {
    linkKey: string | null;
    pts: [number, number][];
    t0: number | null;
    k: number;
    ms: number;
    pos?: [number, number];
    /** 建立这次移动的补间（由场景提供）。 */
    tweenStart?: (scene: SceneLike) => void;
    /** 这次移动有补间（读 k 而不是按时间算）。 */
    tweenKill?: () => number;
    onDone?: ((pk: Package) => void) | null;
  } | null;
}

/** 房间实体（机房里的设备是 roomKind 为 'device' 的节点）。 */
export interface Room {
  kind: "room";
  id: string;
  label: string;
  roomKind: string;
  x: number;
  y: number;
  w: number;
  h?: number;
  door: number;
  inPort: number;
  outPort: number;
  pipeOut: number;
  desk: Seat;
  seats: Seat[] | null;
  cabinet: { x: number; y: number };
  terminal: { x: number; y: number };
  monitor: { x: number; y: number };
  def: RoomDef;
}

export interface Seat {
  x: number;
  w: number;
  seatX: number;
  seatY: number;
}

/** 管道实体：flow 是流动的状态。 */
export interface Pipe {
  kind: "pipe";
  id: string;
  from: string;
  to: string;
  linkKind: string;
  pts: [number, number][];
  flow: { state: "flowing" | "idle" | "stopped"; speed: number; load: number; phase: number; t: number } | null;
  def: LinkDef;
}

/** 房间声明里的 spots 指向的画布位置（文件柜、终端、监控屏等陈设的 x）。 */
export interface SpotTarget {
  x: number;
  y: number;
}

/** 管道的端点：房间，或者走廊尽头通往机房的门（它不是房间，位置固定）。 */
export interface Endpoint {
  pipeOut: number;
  inPort: number;
  outPort: number;
  x: number;
  w: number;
  y: number;
}

/** 一段交接走的管道：折线、键、方向标记与管道实体。 */
export interface LinkHop {
  pts: [number, number][];
  key: string;
  reversed: boolean;
  link: Pipe;
}

/** 房间的陈设画法与条件（需要画布原语，由渲染层按房间 id 提供）。 */
export interface RoomVisual {
  props?: (c: CanvasRenderingContext2D, room: Room, t: number, ctx: DeclContext) => void;
  lit?: (ctx: DeclContext) => boolean;
  tint?: (c: CanvasRenderingContext2D, room: Room, t: number, ctx: DeclContext) => void;
}

/** 房间声明：w、when、agentKind、ports、spots 等（原型 floor-decl.js 的字段）。 */
export interface RoomDef extends RoomVisual {
  id: string;
  label: string;
  roomKind: string;
  w: number | ((flags: Record<string, boolean>) => number);
  when?: string;
  agentKind?: string;
  ports?: string[];
  pipeOutX?: number;
  spots?: Record<string, (room: Room) => number>;
  /** 这个房间自己的持续状态；省略时用通用的事项状态表。 */
  rest?: RestFn;
}

/** 管道声明。 */
export interface LinkDef {
  from: string;
  to: string;
  kind: string;
  via?: string;
  optional?: boolean;
  valve?: boolean;
  pts?: [number, number][];
}

/** 命名信号：带过期时间的值（门缝亮灯、信箱闪、监控屏告警）。 */
export interface Signal {
  until: number;
  value: unknown;
}

export interface World {
  rooms: Record<string, Room>;
  roomOrder: string[];
  links: Record<string, Pipe>;
  characters: Record<string, Character>;
  packages: Record<string, Package>;
  signals: Record<string, Signal>;
  catalog: Catalog;
  /** 通往机房的门（走廊尽头，位置固定）。 */
  machineDoor?: { x: number; y: number; w: number; h: number };
  [key: string]: unknown;
}

export interface Catalog {
  tasks: Record<string, TaskDef>;
  idle: IdleDef[];
  keyOf: (event: Pick<PixelFloorEvent, "type" | "department" | "tool" | "payload">) => string;
  /** 部门声明（运维房间的声明也在这里）。 */
  roomDefs: RoomDef[];
  linkDefs: LinkDef[];
  flags: string[];
  deptRest: RestFn;
  roleRest: RoleRestFn;
  geo: Geo;
}

/** 声明读取画面数据的窗口（原型 floor-decl.js 的 ctx）。 */
export interface DeclContext {
  model: FloorModel;
  order: string[];
  waitingDept: (department: string) => WaitingProvider | null;
  time: TimeText;
  sig: (name: string) => boolean;
  reduced: boolean;
}

export type RestFn = (ctx: DeclContext, department: string, item: LoopItem | null) => RestState;
export type RoleRestFn = (
  ctx: DeclContext,
  department: string,
  item: LoopItem | null,
  role: RoleInfo | null,
  isPrimary: boolean,
  roomRest: RestFn,
) => RestState;

export interface Geo {
  TOP: number;
  ROOM_B: number;
  FLOOR_LINE: number;
  DESK_Y: number;
  PORT_STAND: number;
  PIPE_Y: number;
  TUBE_Y: number;
  DUCT_Y: number;
  DUCT_TUBE_Y: number;
  UNDER_Y: number;
  GAP: number;
}

/** 头顶的气泡。 */
export interface Bubble {
  text: string;
  kind: "say" | "think";
  tail?: boolean;
}

// ---------------------------------------------------------------------------
// 画面数据：setModel 传入的项目楼层数据（查询 project.loop 的结果加上部门角色列表与决定请求）

export interface RoleInfo {
  id: string;
  name: string;
  kind: string;
  status: string;
  task?: string | null;
}

export interface LoopItem {
  work_item_id: string;
  kind: string;
  sign: string;
  color_index: number;
  status: string;
  department: string | null;
  phase: string | null;
  round: number;
  started_at: string | null;
  elapsed_sec: number | null;
  time_limit_sec: number;
  pending_question: string | null;
  run_id: string;
  adoption_id: string | null;
  recovery_state: string | null;
  version: number;
  /** 画面的附加字段：排队位置与剩余时间与停止原因的说明（原型示例数据里有）。 */
  queue_pos?: number;
  waiting_provider_sec?: number;
  url?: string;
  [key: string]: unknown;
}

export interface WaitingProvider {
  department: string;
  next_retry_at: string | null;
}

export interface OpenRequest {
  from: string;
  to: string;
  work_item_id: string;
}

export interface DecisionView {
  id: string;
  kind: string;
  version: number;
  title: string;
  work_item_id: string | null;
  [key: string]: unknown;
}

export interface MachineView {
  id: string;
  name: string;
  actions: number;
  unknown?: boolean;
  online?: boolean;
}

/** 项目楼层的画面数据（原型 floor.js 的 model；由查询结果组装）。 */
export interface FloorModel {
  items: LoopItem[];
  open_requests: OpenRequest[];
  shelves: { adopted: string[] };
  slots: { total: number; used: number } | null;
  waiting_provider: WaitingProvider[];
  machines: MachineView[] | null;
  ops: OpsView | null;
  interrupted: boolean;
  roles: Record<string, RoleInfo[]> | null;
  decisions: DecisionView[];
}

export interface OpsView {
  version?: string;
  fault?: boolean;
  auto_repair_stopped?: boolean;
}

/** 项目楼层收到的事件（事件流里本项目的事件）。 */
export interface PixelFloorEvent {
  type: string;
  department?: string | null;
  role?: string | null;
  tool?: string | null;
  label?: string | null;
  work_item_id?: string | null;
  project_id?: string | null;
  position?: number;
  payload?: Record<string, unknown>;
}

/** 画面与系统共用的时间与数字格式（原型 y9.js 的 Y9.time）。 */
export interface TimeText {
  clock: (iso: string | null) => string;
  duration: (sec: number) => string;
}

// ---------------------------------------------------------------------------
// 场景与 actor：小人与陈设在画面上的当前状态（渲染层只读；走位与姿势由系统推进）

/** 头顶的状态图标（kind 的取值与 shapes.ts 的 drawIcon 一致）。 */
export type HeadIconKind = "think" | "stream" | "bulb" | "hourglass" | "question" | "exclaim" | "check" | "cross" | "heart" | "zzz" | "text";

export interface HeadIcon {
  kind: HeadIconKind;
  text?: string;
  t0: number;
  fromTask?: boolean;
}

/** 画面里的一个演员：小人、包裹或者陈设。 */
export interface Actor {
  id: string;
  sprite: string;
  x: number;
  y: number;
  facing: number;
  anim: string;
  animStart: number;
  clock: number;
  seed: number;
  hold: string | null;
  face: string | null;
  alpha: number;
  dim: number;
  visible: boolean;
  seat: Seat | null;
  script: Script | null;
  step: { st: Step; t0: number; fromX: number; fromY: number; fromAlpha?: number; dur: number; tween?: { kill: () => void }; done?: boolean } | null;
  icon: HeadIcon | null;
  sign: string | null;
  bubble: string | null;
  speed: number;
  shadow: boolean;
  data: Record<string, unknown> & { ecsChar?: boolean; dept?: string; charId?: string; idleWalk?: boolean };
}

/** 走路的一步（原型 engine.js 的脚本步骤）。 */
export interface Step {
  t: string;
  x?: number;
  y?: number;
  name?: string;
  ms?: number;
  /** 关键步骤：减少动画时也保留一段停留时间（原型 engine.js 的 key）。 */
  key?: boolean;
  seat?: Seat | null;
  facing?: number;
  item?: string | null;
  /** 淡入淡出到给定透明度（0 表示离开画面）。 */
  to?: number;
  icon?: { kind: string; text?: string | null } | null;
  gait?: string;
  speed?: number;
  fn?: (actor: Actor) => void;
  [k: string]: unknown;
}

/** 一段走路与动作的脚本。 */
export interface Script {
  steps: Step[];
  i: number;
  /** 可以被打断的部分的起点：关键步骤做完之后允许新动作接管（原型 engine.js 的 tail）。 */
  tail: number;
  finalize?: () => void;
  onDone?: () => void;
}

export type SceneSpec = { steps: Step[] };

/** 状态机在场景里的登记：角色与管道各一个。 */
export interface StateRecord {
  state: string;
  since: number;
}

/** 场景：时间、随机数、演员与状态机的容器。渲染层只读它。 */
export interface SceneLike {
  W: number;
  H: number;
  realT: number;
  animT: number;
  reduced: boolean;
  frozen: boolean;
  autonomy: boolean;
  actors: Actor[];
  /** 正在飞行的纸与信件（原型 scene.flyers）。 */
  flyers: FlyerModel[];
  /** 粒子（原型 scene.particles）。 */
  particles: ParticleModel[];
  random: () => number;
  easeInOut: (t: number) => number;
  pointAlong: (pts: [number, number][], d: number) => [number, number];
  /** 角色与管道的状态机（键为角色 id 与 'pipe:' + 管道 id）。 */
  machines: Map<string, { send: (event: unknown) => void; stop: () => void }>;
  characterStates: Map<string, StateRecord>;
  pipeStates: Map<string, StateRecord>;
  /** 到时刻执行一次的回调（原型 scene.after）。 */
  afterCallbacks: { at: number; fn: () => void }[];
  /** 画面要生成的包裹：世界登记的发送请求，画面每帧取走。 */
  packageRequests: PackageVisual[];
  addActor: (o: ActorInit) => Actor;
  removeActor: (a: Actor) => void;
  play: (a: Actor, animName: string, restart?: boolean) => void;
  cancel: (a: Actor) => void;
  run: (a: Actor, steps: Step[], o?: { tail?: number; finalize?: () => void; onDone?: () => void }) => void;
  /** 角色是否已经进入可以被打断的收尾部分（原型 engine.js 的 inTail）。 */
  inTail: (a: Actor) => boolean;
  after: (ms: number, fn: () => void) => void;
  setCharacterState: (ch: Character, state: string, at?: number) => void;
  characterState: (id: string) => StateRecord | null;
  setPipeState: (pipe: Pipe, state: string, at?: number) => void;
  pipeState: (id: string) => StateRecord | null;
  disposeCharacter: (id: string) => void;
  /** 推进一帧：时间、补间位置、走路与到点回调。 */
  stepScene: (deltaMs: number) => void;
  /** 新建一段受共用时钟驱动的补间（GSAP）。 */
  tween: (target: Record<string, unknown>, vars: Record<string, unknown>) => { kill: () => void };
  /** 是否接了真实的补间实现（没有时为纯逻辑测试，按经过时间推进）。 */
  hasTween: boolean;
  /** 让本次推进中新建的补间立刻落到当前时间上（由时钟提供）。 */
  reapply: () => void;
  /** 飞行物：纸飞机、信件、决定单沿弧线飞行（原型 scene.fly）。 */
  fly: (o: { bmp: string; from: [number, number]; to: [number, number]; ms: number; arc?: number; onDone?: () => void }) => void;
  /** 粒子：灰尘、彩带、火花、烟雾（原型 scene.emit）。 */
  emit: (kind: string, x: number, y: number, n: number, o?: { spread?: number; color?: string; floor?: number }) => void;
  /** 当前聚焦的事项（其它事项的小人与包裹调暗）。 */
  focusId: string | null;
  /** 决定卡片上的盖章（画面提供；驱动在收到回答事件时调用）。 */
  cardStamped?: (id: string, text: string) => void;
  makeCharacterMachine: (input: CharacterMachineInput) => unknown;
  makePipeMachine: (input: PipeMachineInput) => unknown;
}

/** 建立一个 actor 的入参。 */
export interface ActorInit {
  id: string;
  sprite: string;
  x: number;
  y: number;
  anim?: string;
  facing?: number;
  hold?: string | null;
  visible?: boolean;
  speed?: number;
  shadow?: boolean;
  data?: Record<string, unknown>;
}

/** 包裹的可视化：世界登记发送请求，画面生成实体与动画。 */
export interface PackageVisual {
  pts: [number, number][];
  linkKey: string;
  bmp: string;
  color?: string | null;
  itemId?: string | null;
  small?: boolean;
  artifact?: string | null;
  ms?: number;
  onDone?: () => void;
}

/** 角色状态机的输入与上下文。 */
export interface CharacterMachineInput {
  id: string;
  department: string | null;
  roleKind: string;
}

/** 飞行物：纸、信件与决定单沿弧线飞行。 */
export interface FlyerModel {
  bmp: string;
  from: [number, number];
  to: [number, number];
  t0: number;
  ms: number;
  arc: number;
  done?: boolean;
  onDone?: () => void;
}

/** 粒子：灰尘、彩带、火花、烟雾、蒸汽。 */
export interface ParticleModel {
  kind: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  g: number;
  life: number;
  age: number;
  size: number;
  color: string;
  drag: number;
  sway?: number;
  floor?: number;
}

/** 建立一个场景的入参。 */
export interface SceneOptions {
  W: number;
  H: number;
  /** 取 0..1 的随机数；测试用确定的随机数。 */
  random: () => number;
  /** 减少动画（系统设置）。 */
  reduced: boolean;
  /**
   * 建立受共用时钟驱动的补间（GSAP）。小人的走动与包裹沿管道的移动都用它：
   * 起点钉在时钟零点上，位置只由「推进到第几毫秒」决定，测试与回放可重复。
   */
  tween?: (target: Record<string, unknown>, vars: Record<string, unknown>) => { kill: () => void };
  /** 让本次推进中新建的补间立刻落到当前时间上（时钟的 reapply）。 */
  reapply?: () => void;
  /** 建立角色与管道的状态机；测试与回放可以注入。 */
  makeCharacterMachine?: (input: CharacterMachineInput) => unknown;
  makePipeMachine?: (input: PipeMachineInput) => unknown;
}

/** 管道状态机的输入与上下文。 */
export interface PipeMachineInput {
  id: string;
  from: string;
  to: string;
  linkKind: string;
}

export interface EventActionsCatalog {
  [eventType: string]: unknown;
}
