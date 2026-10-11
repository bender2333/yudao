// 部门房间组件在部门工作间页面中的存活（工单 #381 验收）：数据从空到有时同一个组件实例继续存活，
// 不卸载重挂 Pixi 画面与事件流订阅。校验方式：在页面级包装组件按"single"（一处、条件外）或
// "split"（两处、各条件分支里）两种结构渲染 RoomScreen，按真实录下的部门房间数据依次提交；
// 真实录下的数据来自 tests/fixtures/room/recordings.json，由 helper 取部门对应的房间模型，
// 这里不写假数据。

import { test } from "node:test";
import assert from "node:assert/strict";
import { roomWorkspaceFixture, runRoomSurvival } from "../helpers/room-screen-page.ts";

test("split 结构（第 1 轮的错误写法）：房间组件在子节点里的位置变了，数据到达后旧容器被卸载、新容器挂载", async () => {
  const engineering = roomWorkspaceFixture("engineering");
  const report = await runRoomSurvival("split", "engineering", [null, engineering]);
  assert.equal(report.pageErrors.length, 0, `页面不应报错：${report.pageErrors.join("\n")}`);
  // 旧容器卸载、新容器挂载：同一时刻只有一处，但前后不是同一个 DOM 节点；
  // sameHost 为假就是卸载重挂的证据（Pixi 画面与事件流订阅被重置，首段流式文字丢失）
  assert.equal(report.mountCounts.length, 2);
  assert.equal(report.mountCounts[0], 1, "数据为空时 split 结构里只有一处");
  assert.equal(report.mountCounts[1], 1, `数据到达后 split 结构里仍只有一处（实际 ${report.mountCounts[1]}）`);
  assert.equal(report.sameHost, false, "数据到达后房间容器不是同一个 DOM 节点：旧的被卸载了");
  assert.equal(report.errorText, null, `split 也不该出现加载失败：${report.errorText ?? ""}`);
});

test("single 结构：RoomScreen 只渲染一处且在条件分支之外，数据从空到有时同一个 DOM 节点继续存活", async () => {
  const engineering = roomWorkspaceFixture("engineering");
  const report = await runRoomSurvival("single", "engineering", [null, engineering]);
  assert.equal(report.pageErrors.length, 0, `页面不应报错：${report.pageErrors.join("\n")}`);
  assert.equal(report.mountCounts.length, 2);
  assert.equal(report.mountCounts[0], 1, "数据为空时只有一处房间容器");
  assert.equal(report.mountCounts[1], 1, `数据到达后仍然只有一处房间容器（实际 ${report.mountCounts[1]}）`);
  assert.equal(report.sameHost, true, "数据到达后房间容器仍是同一个 DOM 节点");
  assert.equal(report.errorText, null, `single 不该出现加载失败：${report.errorText ?? ""}`);
});