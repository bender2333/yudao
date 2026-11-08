// 三个场景接上同步层与壳（工单 #1573 的验收：同步层用夹具里录下的接口响应与事件流驱动三个场景组件）。
//
// 不启动 Yudao、不连网络：录下的查询应答（tests/fixtures/session/queries.json）与录下的 SSE 帧
// （tests/fixtures/session/events.sse，位置 1..120 的连续窗口）经真正的同步层与壳走到场景上；
// 场景这一侧用假的像素画面接住壳交来的状态与动作（单元测试里没有画布）。
//
// 三个场景各一条：楼、楼层、房间；断言画面读到查询（状态与位置）与事件（动作用的事件位置），
// 并画出录下的那一刻对应的状态。
//
// 守 R1（事实只经接口读，画面不自己累加事实）与 R2（画面合同的位置与取值——状态与动作都带回链）。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { BuildingModel, FloorModel, RoomState } from "../../src/pixel/contract.ts";
import {
  FakeServer, fakeClock, fakeHost, fakeSurface, loadEvents, loadFixtures, recordingOf, settle, shellFor, until,
} from "./session-harness.ts";

/** 壳交给画面的最后一份状态。 */
function lastState(surface: ReturnType<typeof fakeSurface>): unknown {
  const all = [...surface.jumped, ...surface.states];
  return all.length === 0 ? null : all[all.length - 1];
}

test("楼：录下的 projects.list 与 project.loop 画出这一层，录下的事件让这一层闪一下", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  const surface = fakeSurface();
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await shell.open("http://view.test", "");
    await until(() => lastState(surface) !== null, "楼的状态");
    const model = lastState(surface) as BuildingModel;
    // 状态来自录下的查询快照（位置 120 的回放快照），不是画面自己累加的
    assert.equal(model.position, 120);
    assert.equal(model.floors.length, 1);
    assert.equal(model.floors[0].project_id, ids.project_id);
    assert.equal(model.floors[0].name, "Demo 项目");
    assert.equal(model.floors[0].status, "working");
    assert.deepEqual(model.floors[0].lit, { product: false, engineering: true, quality: true, operations: false });
    assert.deepEqual(model.floors[0].flags.map((flag) => [flag.department, flag.work_item_id]),
      [["quality", ids.work_item_id]]);

    // 事件只决定动作：录下的 department_activated（位置 5）让这一层闪一下白光，带来源事件的位置
    server.pushFrames(loadEvents("events.sse"));
    await until(() => shell.sync.position === 120, "事件流读到位置 120");
    await settle();
    const flash = surface.actions.find((action) => action.kind === "floor_flash");
    assert.ok(flash, `楼没有收到闪光动作：${surface.actions.map((action) => action.kind).join(",")}`);
    assert.equal(flash.position, 5);
    assert.equal(flash.color, "white");
    assert.equal(flash.project, ids.project_id);
    assert.ok(surface.actions.every((action) => Number.isFinite(action.position)), "每个动作都带位置");
  } finally {
    detach();
    shell.close();
  }
});

test("楼层：录下的 project.loop 画出事项与大厅，录下的事件演成楼层上的动作", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  const surface = fakeSurface();
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await until(() => lastState(surface) !== null, "楼层的状态");
    const model = lastState(surface) as FloorModel;
    // 楼层状态的位置取楼层与询问链两处快照里新的一个：询问链（run.asks）不可回放，是录制时的那一刻
    assert.equal(model.position, 289);
    assert.equal(model.items.length, 1);
    assert.equal(model.items[0].work_item_id, ids.work_item_id);
    assert.equal(model.items[0].status, "working");
    assert.equal(model.items[0].department, "quality");
    assert.deepEqual(Object.keys(model.items[0].refs ?? {}).sort(), ["elapsed", "round", "sign"]);
    assert.deepEqual(model.shelves, { adopted: [] });
    assert.equal(model.decisions.length, 0, "这一刻没有等待回答的决定请求");
    assert.deepEqual(model.open_requests, [], "录下的询问都已经回答");

    server.pushFrames(loadEvents("events.sse"));
    await until(() => shell.sync.position === 120, "事件流读到位置 120");
    await settle();
    const stamp = surface.actions.find((action) => action.kind === "stamp_valid");
    assert.ok(stamp, `楼层没有收到盖章的动作：${surface.actions.map((action) => action.kind).join(",")}`);
    // spec_accepted 在录下的位置 34：动作的位置就是来源事件的位置（回链）
    assert.equal(stamp.position, 34);
    const handoff = surface.actions.find((action) => action.kind === "handoff");
    assert.ok(handoff, "楼层没有收到包裹送达的动作");
    assert.equal(handoff.artifact, "prd");
  } finally {
    detach();
    shell.close();
  }
});

test("房间：录下的 department.workspace 画出角色与状态，录下的事件演成房间里的动作", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  shell.goRoom("engineering");
  const surface = fakeSurface();
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await until(() => lastState(surface) !== null, "房间的状态");
    const model = lastState(surface) as RoomState;
    assert.equal(model.status, "done");
    assert.equal(model.position, 289);
    assert.deepEqual((model.roles ?? []).map((role) => role.id), ["engineering-agent"]);
    // 房间查询带上了事项：工作间是这个部门在这个事项上的那一份
    const workspaceCall = server.queried.find((entry) => entry.name === "department.workspace");
    assert.ok(workspaceCall);
    assert.equal(workspaceCall.params?.department, "engineering");
    assert.equal(workspaceCall.params?.work_item, ids.work_item_id);

    server.pushFrames(loadEvents("events.sse"));
    await until(() => shell.sync.position === 120, "事件流读到位置 120");
    await settle();
    // 工程的角色在录下的位置 109 写文件、位置 111 查看：动作的位置来自事件
    assert.ok(surface.actions.some((action) => action.kind === "write" && action.position === 109),
      `房间没有收到写文件的动作：${surface.actions.map((action) => `${action.kind}@${action.position}`).join(",")}`);
    assert.ok(surface.actions.some((action) => action.kind === "inspect" && action.position === 111));
    // 别的部门的事件不进这个房间
    assert.deepEqual(surface.actions.filter((action) => action.room === "product"), []);
  } finally {
    detach();
    shell.close();
  }
});
