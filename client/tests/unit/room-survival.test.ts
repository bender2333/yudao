// 真实的 RoomSection 在数据由空到有时同一节点存活（工单 #381 验收）：
// 同一个 React root 挂载 department.tsx 里导出的 RoomSection，先传空数据再传
// tests/fixtures/room/recordings.json 里真实录下的房间数据；舞台容器与房间画面容器
// 在数据到达前后是同一个 DOM 节点，挂载计数仍为 1，没有页面错误。
// 反向验证：把 RoomSection 改回两处条件分支写法时这两个测试必须失败。

import { test } from "node:test";
import assert from "node:assert/strict";
import { roomWorkspaceFixture, runRoomSurvival } from "../helpers/room-screen-page.ts";

test("RoomSection 数据由空到有：舞台与画面容器是同一个 DOM 节点", async () => {
  const engineering = roomWorkspaceFixture("engineering");
  const report = await runRoomSurvival("engineering", [null, engineering]);
  assert.equal(report.pageErrors.length, 0, `页面不应报错：${report.pageErrors.join("\n")}`);
  assert.deepEqual(report.stageCounts, [1, 1]);
  assert.deepEqual(report.mountCounts, [1, 1]);
  assert.equal(report.sameHost, true, "数据到达后舞台与画面容器仍是同一个 DOM 节点");
  assert.equal(report.errorText, null, `不该出现加载失败：${report.errorText ?? ""}`);
});

test("RoomSection 数据到有再变空再到有：仍然是同一个 DOM 节点", async () => {
  const engineering = roomWorkspaceFixture("engineering");
  const report = await runRoomSurvival("engineering", [null, engineering, null, engineering]);
  assert.equal(report.pageErrors.length, 0, `页面不应报错：${report.pageErrors.join("\n")}`);
  assert.deepEqual(report.stageCounts, [1, 1, 1, 1]);
  assert.deepEqual(report.mountCounts, [1, 1, 1, 1]);
  assert.equal(report.sameHost, true, "数据多次变化后舞台与画面容器仍是同一个 DOM 节点");
  assert.equal(report.errorText, null, `不该出现加载失败：${report.errorText ?? ""}`);
});
