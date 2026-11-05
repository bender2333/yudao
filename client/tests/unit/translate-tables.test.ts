// 状态对应表的单元测试（工单 #952 验收标准 2）：服务端的每个状态值都翻成画面合同（pixel/contract.ts）
// 取值表里的值；表里没有的值抛错，错误写明是哪张表、哪个值。
// 另核对原 #900 的对应搬进对应表以后口径不变：进行中按恢复观察状态分开、状态灯按优先顺序取。
// 守第 13 节的 R2（画面合同）：对应表的两头都是合同的取值表。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FLOOR_SIGNS,
  ITEM_STATES,
  POSES,
  ROLE_STATES,
  ROOM_STATES,
} from "../../src/renderer/src/pixel/contract.ts";
import {
  floorSign,
  floorSignOf,
  itemStateOf,
  itemStatus,
  roleStatus,
  roomPose,
  roomStatus,
} from "../../src/renderer/src/translate/tables.ts";
import { WORK_ITEM_STATUS } from "../../src/renderer/src/views/project/labels.ts";

test("事项状态的对应：接口给出的每个事项状态都翻成画面合同的事项状态", () => {
  // 接口给出的状态值（页面文字表里逐个列出的那几个，与 harness/projects.py 写入的一致）
  for (const server of Object.keys(WORK_ITEM_STATUS)) {
    assert.ok(ITEM_STATES.includes(itemStatus(server)), `${server} 翻出的值不在画面合同的事项状态里`);
  }
  // 进行中的事项：中断、待恢复、暂停按恢复观察状态画，其余算在工作（#900 的对应）
  assert.equal(itemStateOf({ status: "in_progress" }), "working");
  assert.equal(itemStateOf({ status: "in_progress", recovery_state: "running" }), "working");
  assert.equal(itemStateOf({ status: "in_progress", recovery_state: "interrupted" }), "interrupted");
  assert.equal(itemStateOf({ status: "in_progress", recovery_state: "waiting_resume" }), "waiting_resume");
  assert.equal(itemStateOf({ status: "in_progress", recovery_state: "paused" }), "paused");
  // 不在进行中的事项不看恢复观察状态
  assert.equal(itemStateOf({ status: "stopped", recovery_state: "interrupted" }), "cancelled");
  assert.equal(itemStateOf({ status: "not_started" }), "queued");
  assert.equal(itemStateOf({ status: "adopted" }), "adopted");
  assert.equal(itemStateOf({ status: "released_unsettled" }), "done");
  assert.equal(itemStateOf({ status: "awaiting_initial_prd" }), "asking");
  assert.equal(itemStateOf({ status: "held" }), "paused");
});

test("事项状态：因升级停止与用户停止分开（工单 #1186）", () => {
  // 停止原因不同，画面上的状态不同：因升级停止单独一种，门口牌子据此出现；用户停止仍按已取消画
  assert.equal(itemStateOf({ status: "stopped", stop_reason: "run_event_version_changed" }), "upgrade_stopped");
  assert.ok(ITEM_STATES.includes(itemStateOf({ status: "stopped", stop_reason: "run_event_version_changed" })));
  assert.equal(itemStateOf({ status: "stopped", stop_reason: "user_cancelled" }), "cancelled");
  assert.equal(itemStateOf({ status: "stopped", stop_reason: "cancelled" }), "cancelled");
  assert.equal(itemStateOf({ status: "stopped" }), "cancelled");
  // 其他状态不因停止原因改变
  assert.equal(itemStateOf({ status: "adopted", stop_reason: "run_event_version_changed" }), "adopted");
  // 状态灯：因升级停止的事项不决定灯
  assert.equal(floorSign("upgrade_stopped"), null);
  assert.equal(floorSignOf([{ status: "stopped", stop_reason: "run_event_version_changed" }]), "idle");
});

test("楼的状态灯的对应：每个事项状态翻出的灯都在画面合同的状态灯里，或明确不决定灯", () => {
  for (const state of ITEM_STATES) {
    const sign = floorSign(state);
    assert.ok(sign === null || FLOOR_SIGNS.includes(sign), `${state} 翻出的灯不在画面合同的状态灯里`);
  }
  // 优先顺序（#734 的口径）：待恢复、中断、等待你的决定、等待模型服务、等待槽位、工作、排队
  assert.equal(floorSignOf([]), "idle");
  assert.equal(floorSignOf([{ status: "in_progress" }]), "working");
  assert.equal(floorSignOf([{ status: "in_progress" }, { status: "in_progress", recovery_state: "interrupted" }]), "interrupted");
  assert.equal(floorSignOf([{ status: "in_progress", recovery_state: "interrupted" }, { status: "in_progress", recovery_state: "waiting_resume" }]), "waiting_resume");
  assert.equal(floorSignOf([{ status: "not_started" }]), "queued");
  // 只由已结束的事项组成的一层是空闲（与 #734 的用例一致）
  assert.equal(floorSignOf([{ status: "stopped" }, { status: "adopted" }, { status: "released_unsettled" }]), "idle");
});

test("房间状态、房间姿势与角色状态的对应：翻出的值都在画面合同的取值表里", () => {
  for (const value of ["idle", "working", "asking", "paused", "failed", "done", "cancelled", "interrupted", "waiting_resume"]) {
    assert.ok(ROOM_STATES.includes(roomStatus(value)), `${value} 翻出的值不在画面合同的房间状态里`);
  }
  for (const value of ["typing", "reading", "writing", "thinking", "searching", "waiting", "tea", "idle", "inspecting"]) {
    assert.ok(POSES.includes(roomPose(value)), `${value} 翻出的值不在画面合同的姿势里`);
  }
  for (const value of ["idle", "assigned", "working", "returned", "failed", "away"]) {
    assert.ok(ROLE_STATES.includes(roleStatus(value)), `${value} 翻出的值不在画面合同的角色状态里`);
  }
});

test("表里没有的值抛错，错误写明是哪张表、哪个值（不原样透传）", () => {
  assert.throws(() => itemStatus("flying"), /翻译层没有对应的事项状态：flying/);
  assert.throws(() => itemStateOf({ status: "flying" }), /事项状态：flying/);
  assert.throws(() => floorSign("flying"), /翻译层没有对应的楼层状态灯：flying/);
  assert.throws(() => roomStatus("flying"), /翻译层没有对应的房间状态：flying/);
  assert.throws(() => roomPose("flying"), /翻译层没有对应的房间姿势：flying/);
  assert.throws(() => roleStatus("flying"), /翻译层没有对应的角色状态：flying/);
});
