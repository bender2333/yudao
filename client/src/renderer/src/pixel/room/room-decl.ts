// 部门房间的声明表（画面与播放设计说明第 5.1 节、原型 v13 js/pixel/room-decl.js，工单 #954）：
// 房间画面认的每种动作的级别（tier）与声明的最短时长（ms），时长取自那段演出的主要部分。
//
// 画面层唯一认的动作种类就是这里的键：翻译层（translate/room.ts）只给出这里的 kind，
// 播放时间线按级别与时长排队，驱动（driver.ts）按 kind 找演法。
// 进度一级不排队：思考、整理资料、有想法、等待重试与没有专门动作的工具调用，合并成工位上的一个持续姿势。

import type { ActionClass } from "../timeline.ts";

/** 一个动作的级别与声明时长。 */
export type RoomKind = ActionClass;

const k = (tier: ActionClass["tier"], ms: number): RoomKind => ({ tier, ms });

/** 房间的动作：种类 → 级别与声明时长（原型 v13 room-decl.js 的 kinds）。 */
export const ROOM_KINDS: Readonly<Record<string, RoomKind>> = {
  // 关键：交接、询问与回答、采纳与质检结论、终止与等待、运维的发布回滚与故障
  handoff: k("key", 2400),
  send_letter: k("key", 3000),
  answer_letter: k("key", 2600),
  stamp_valid: k("key", 3200),
  seal: k("key", 3200),
  stamp_release: k("key", 3200),
  stamp_rework: k("key", 2400),
  paused: k("key", 1200),
  failed: k("key", 1400),
  done: k("key", 2200),
  cancelled: k("key", 2200),
  hold_card: k("key", 1200),
  hold_form: k("key", 1600),
  resume: k("key", 1000),
  wait_provider: k("key", 2600),
  deploy: k("key", 2400),
  rollback: k("key", 2200),
  fault: k("key", 3000),
  // 普通：开始一件事、读材料、写文件、运行命令与房间里的其余动作
  activate: k("normal", 1800),
  slump: k("normal", 1900),
  search: k("normal", 2900),
  read: k("normal", 1800),
  write: k("normal", 1800),
  run_command: k("normal", 1000),
  command_done: k("normal", 1200),
  toss: k("normal", 2200),
  submit: k("normal", 1000),
  returned: k("normal", 2500),
  inspect: k("normal", 3400),
  guidance_in: k("normal", 700),
  guidance_read: k("normal", 2600),
  guidance_reply: k("normal", 1700),
  compact: k("normal", 2500),
  compact_fail: k("normal", 2700),
  puzzled: k("normal", 2000),
  remote_run: k("normal", 3600),
  remote_unknown: k("normal", 4500),
  read_existing: k("normal", 3200),
  net_fetch: k("normal", 2100),
  mcp_press: k("normal", 900),
  trial: k("normal", 2200),
  self_test: k("normal", 2200),
  assign: k("normal", 1200),
  hand_back: k("normal", 1200),
  review: k("normal", 2600),
  explore: k("normal", 4000),
  replan: k("normal", 3100),
  semantic: k("normal", 900),
  // 进度
  fetch_folder: k("progress", 0),
  type_think: k("progress", 0),
  idea: k("progress", 0),
  retry_wait: k("progress", 0),
  tool_progress: k("progress", 0),
};

/** 房间声明表里的动作种类（核对与测试用）。 */
export const ROOM_KIND_NAMES: readonly string[] = Object.keys(ROOM_KINDS);

/** 一个动作在这个场景的级别与声明时长；表里没有的种类抛错（房间只演声明表里的动作）。 */
export function roomKind(kind: string): RoomKind {
  const hit = ROOM_KINDS[kind];
  if (!hit) throw new Error("房间的声明表里没有这种动作：" + kind);
  return hit;
}
