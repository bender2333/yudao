// 部门房间的数据与临时状态（原型 v13 room.js 的 model 与 st，工单 #954）。
//
// 房间的数据是画面合同的状态（pixel/contract.ts 的 RoomState）加上这个部门自己的几项；
// 动作过程中的临时状态（灯、抽屉、工作台上的物件、白板……）只属于表演层，动作演完就回到
// 只由状态决定的样子。这里不依赖渲染与场景，可以直接在 node --test 下驱动。

import type { PixelState, RoomStatus } from "../contract.ts";
import type { RoomRole, RoomSeat } from "./layout.ts";

/** 房间里的一个角色（状态已由翻译层翻成画面的词）。 */
export interface RoomRoleData extends RoomRole {
  status: string;
}

/** 房间的姿势：画面合同的角度只有 anim，role_id 说明是哪个角色摆这个姿势。 */
export interface RoomPoseData {
  role_id?: string | null;
  anim: string;
}

/** 房间的数据：画面合同的状态（带位置）加上部门与档位。 */
export interface RoomData extends PixelState {
  department: string;
  level: string;
  status: RoomStatus;
  crt: { target?: string; model?: string; protocol?: string; status?: string; cycle?: number | null };
  roles: RoomRoleData[];
  pose: RoomPoseData | null;
  door: string | null;
  hold_card: string | null;
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

/** 一份空房间：画面建立时用，状态到达之前的样子（一个部门一个 Agent 由 rolesOf 补上）。 */
export function emptyRoomData(department: string): RoomData {
  return {
    position: 0, department, level: "ui", status: "idle", crt: {}, roles: [], pose: null, door: null,
    hold_card: null, mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0,
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
  noteHide: number;
  replyUntil: number;
  cardHide: number;
  cardFlash: number;
  archiveFlash: number;
  door: number;
  doorEvent: string | null;
  eventStatus: string | null;
  eventCard: string | null;
  bench: BenchState;
  wbSheetUntil: number;
  wbErase: number;
  wbSeed: number;
  wbTags: Record<string, boolean>;
  wbDone: Record<string, boolean>;
  wbExisting: boolean;
  binUntil: number;
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
    exit: null, termRun: false, smokeUntil: 0, trayPaper: false, scrollFlash: 0,
    noteHide: 0, replyUntil: 0, cardHide: 0, cardFlash: 0, archiveFlash: 0, door: 0, doorEvent: null,
    eventStatus: null, eventCard: null,
    bench: { item: null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0, until: 0 },
    wbSheetUntil: 0, wbErase: 0, wbSeed: 1, wbTags: {}, wbDone: {}, wbExisting: false, binUntil: 0,
    cart: { x: 296, box: null, pushed: false }, backupLit: 0, backupFlash: 0,
    mdoorGlow: 0, monitorAlarmUntil: 0, postFlag: 0, toolLit: -1, eventRemote: false, eventMachine: null,
    eventWaiting: false, eventStep: 0, eventLines: null, selfShot: false, desks: [], deskState: {},
    bin: { x: 0, y: 0 }, trialSeat: null, confettiAt: 0,
  };
}
