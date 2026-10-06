// 部门房间的数据与规则（原型 v9 room.js 的状态与事件处理部分，工单 #177）：
// 房间数据（roomModel）、动作过程中的临时状态、询问信的两端与说话内容。
//
// 这里不依赖渲染与 PixiJS，可以直接在 node --test 下驱动。小人的位置与动作由房间驱动用场景的
// 脚本推进（world/scene.ts 的 createScene）；说话气泡的内容来自 world/say.ts 的目录。

import { say, sayMs } from "../world/say.ts";
import type { PixelFloorEvent } from "../world/types.ts";
import type { RoomRole, RoomSeat } from "./layout.ts";

/** 部门房间的画面数据（department.workspace 的 room 字段，原型 roomModel）。 */
export interface RoomModel {
  department: string;
  level?: string;
  status: string;
  crt: { target?: string; model?: string; protocol?: string; status?: string; cycle?: number | null };
  roles: RoomRole[];
  pose: { role_id?: string | null; action: string } | null;
  door: string | null;
  hold_card: string | null;
  pending_tool: string | null;
  mailbox: number;
  summaries: number;
  scrolls: number;
  pinned_notes: number;
  semantic_cards: number;
  machine: string | null;
  remote_unknown: boolean;
  waiting_provider: boolean;
  pipes: { out?: string; letters_waiting?: number } | null;
  existing_read: boolean;
  trial: Record<string, unknown> | null;
  tool_panel: { buttons?: string[]; lit?: number } | null;
  self_test: Record<string, unknown> | null;
}

export function emptyRoomModel(department: string): RoomModel {
  return {
    department, level: "ui", status: "idle", crt: {}, roles: [], pose: null, door: null, hold_card: null,
    pending_tool: null, mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0,
    machine: null, remote_unknown: false, waiting_provider: false, pipes: null, existing_read: false,
    trial: null, tool_panel: null, self_test: null,
  };
}

export interface BenchState {
  item: string | null;
  mark: { text: string; color: string } | null;
  slip: string | null;
  slipMark: { text: string; color: string } | null;
  ticks: number;
  tape: number;
  until: number;
  sig?: string;
}

export interface DeskState {
  papers: number;
  hidePapers: boolean;
  folder: number;
  doc: number;
  box: number;
  card: number;
  cardResult: number;
  scroll: number;
  letter: number;
  redLamp: boolean;
}

/** 动作过程中的临时状态；动作结束以后画面回到只由数据决定的样子（除了保留一段时间的桌上物件）。 */
export interface RoomState {
  clock: number;
  dark: number;
  darkTarget: number;
  yellow: boolean;
  crtBoot: number;
  drawer: number;
  lever: number;
  exit: "green" | "red" | null;
  termRun: boolean;
  smokeUntil: number;
  trayPaper: boolean;
  scrollFlash: number;
  scrollHide: number;
  noteHide: number;
  replyUntil: number;
  cardHide: number;
  cardFlash: number;
  archiveFlash: number;
  door: number;
  doorEvent: string | null;
  eventStatus: string | null;
  eventCard: string | null;
  eventTool: string | null;
  lastPendingTool: string | null;
  bench: BenchState;
  wbSheetUntil: number;
  wbErase: number;
  wbSeed: number;
  wbTags: Record<string, boolean>;
  wbDone: Record<string, boolean>;
  wbExisting: boolean;
  binUntil: number;
  alarmUntil: number;
  cart: { x: number; box: string | null; pushed: boolean };
  backupLit: number;
  backupFlash: number;
  mdoorGlow: number;
  monitorAlarmUntil: number;
  postFlag: number;
  toolLit: number;
  eventRemote: boolean;
  eventMachine: string | null;
  eventWaiting: boolean;
  eventStep: number;
  eventLines: string[] | null;
  selfShot: boolean;
  desks: RoomSeat[];
  deskState: Record<string, DeskState>;
  bin: { x: number; y: number };
  trialSeat: RoomSeat | null;
  confettiAt: number;
}

export function createRoomState(): RoomState {
  return {
    clock: 15.5 * 3600000, dark: 0.36, darkTarget: 0.36, yellow: false, crtBoot: 1, drawer: 0, lever: 0,
    exit: null, termRun: false, smokeUntil: 0, trayPaper: false, scrollFlash: 0, scrollHide: 0,
    noteHide: 0, replyUntil: 0, cardHide: 0, cardFlash: 0, archiveFlash: 0, door: 0, doorEvent: null,
    eventStatus: null, eventCard: null, eventTool: null, lastPendingTool: null,
    bench: { item: null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0, until: 0 },
    wbSheetUntil: 0, wbErase: 0, wbSeed: 1, wbTags: {}, wbDone: {}, wbExisting: false, binUntil: 0,
    alarmUntil: 0, cart: { x: 296, box: null, pushed: false }, backupLit: 0, backupFlash: 0,
    mdoorGlow: 0, monitorAlarmUntil: 0, postFlag: 0, toolLit: -1, eventRemote: false, eventMachine: null,
    eventWaiting: false, eventStep: 0, eventLines: null, selfShot: false, desks: [], deskState: {},
    bin: { x: 0, y: 0 }, trialSeat: null, confettiAt: 0,
  };
}

/** 事件说明中用「」括起的部分。 */
export function quoted(label: string | null | undefined): string | null {
  const m = /「([^」]+)」/.exec(String(label || ""));
  return m ? m[1] : (label || null);
}

/** 询问信的两端：发问的部门与回答的部门（原型 letterSides）。 */
export function letterSides(ev: PixelFloorEvent): { asker: string | null; answerer: string | null } {
  const pl = (ev.payload ?? {}) as Record<string, unknown>;
  if (ev.type === "collaboration_requested") {
    return { asker: (pl.from as string) || ev.department || null, answerer: (pl.to as string) || null };
  }
  const answerer = ev.department || (pl.to as string) || null;
  const asker = pl.from === answerer ? ((pl.to as string) || null) : ((pl.from as string) || null);
  return { asker, answerer };
}

export { say, sayMs };
