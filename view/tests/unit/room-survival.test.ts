// 部门房间的画面在数据由空到有时存活（接替 #1418 删掉的 client/tests/unit/room-survival.test.ts 的 2 条，工单 #1573）。
//
// 原来测的是页面上的 RoomSection：先传空数据再传真实录下的查询结果，舞台与画面容器是同一个 DOM 节点、
// 挂载计数仍是 1。现在画面有自己的组件与壳：场景组件挂载一次（attachHost），数据变化只走 setState，
// 重新查询失败（数据短暂为空）也不重建。这里用录下的 department.workspace 应答驱动壳，
// 画面用一个记录的替身，核对同一个场景对象只挂载一次、宿主是同一个、画面没有被销毁。
//
// 两条对应原来的两条：
//   1. 数据由空到有：画面挂载一次，宿主是同一个，状态到了就上画面；
//   2. 数据到有再变空再到有：仍然是同一个画面（不重建、不销毁）。
//
// 守 R1（状态只从查询来，画面不自己累加事实）与 R2（画面对象的存活是合同：同一场景不重建）。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { RoomState } from "../../src/pixel/contract.ts";
import {
  FakeServer, fakeClock, fakeHost, fakeSurface, loadFixtures, recordingOf, settle, shellFor, until,
} from "./session-harness.ts";

const fixtures = loadFixtures();
const ids = recordingOf(fixtures, "demo").ids;

function lastModel(surface: ReturnType<typeof fakeSurface>): RoomState | null {
  const all = [...surface.jumped, ...surface.states];
  return all.length === 0 ? null : (all[all.length - 1] as RoomState);
}

/** 建立画面时交给工厂的宿主与那个画面：核对同一个场景对象只挂载一次。 */
interface Mounted {
  hosts: unknown[];
  surface: ReturnType<typeof fakeSurface>;
}

test("房间的数据由空到有：画面挂载一次，宿主是同一个，状态到了就上画面", async () => {
  const server = new FakeServer(fixtures, "demo");
  // 第一次查询先等一等：画面挂上时数据还没有到（数据由空到有）
  server.deferNext("department.workspace");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  shell.goRoom("engineering");
  const mounted: Mounted = { hosts: [], surface: fakeSurface() };
  const detach = shell.attachHost(fakeHost, fakeClock, async (options) => {
    mounted.hosts.push(options.host);
    return mounted.surface;
  });
  try {
    await until(() => server.waiting.length === 1, "房间的查询在等");
    assert.equal(lastModel(mounted.surface), null, "数据还没有到");
    server.release();
    await until(() => lastModel(mounted.surface) !== null, "房间的状态");
    assert.equal(mounted.hosts.length, 1, "画面只挂载一次");
    assert.equal(mounted.hosts[0], fakeHost, "画面挂在同一个宿主上");
    assert.equal(mounted.surface.destroyed, 0, "画面没有被销毁");
    assert.deepEqual((lastModel(mounted.surface)?.roles ?? []).map((role) => role.id), ["engineering-agent"]);
  } finally {
    detach();
    shell.close();
  }
});

test("房间的数据到有再变空再到有：仍然是同一个画面，不重建也不销毁", async () => {
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  shell.goRoom("engineering");
  const mounted: Mounted = { hosts: [], surface: fakeSurface() };
  const detach = shell.attachHost(fakeHost, fakeClock, async (options) => {
    mounted.hosts.push(options.host);
    return mounted.surface;
  });
  try {
    await until(() => lastModel(mounted.surface) !== null, "第一次的房间状态");
    const statesAfterFirst = mounted.surface.states.length;

    // 数据变空：同一部门的重新查询失败，画面继续显示上一次的状态，不重建
    server.failures.add("department.workspace");
    await shell.sync.viewSync?.refresh("room.workspace");
    await settle();
    assert.equal(mounted.surface.destroyed, 0, "数据变空时画面不销毁");
    assert.equal(mounted.hosts.length, 1, "数据变空时画面不重建");
    assert.deepEqual((lastModel(mounted.surface)?.roles ?? []).map((role) => role.id), ["engineering-agent"]);

    // 数据再来：还是同一个画面接住
    server.failures.delete("department.workspace");
    await shell.sync.viewSync?.refresh("room.workspace");
    await settle();
    assert.equal(mounted.surface.destroyed, 0);
    assert.equal(mounted.hosts.length, 1);
    assert.ok(mounted.surface.states.length >= statesAfterFirst, "新数据到了就交给同一个画面");
    assert.deepEqual((lastModel(mounted.surface)?.roles ?? []).map((role) => role.id), ["engineering-agent"]);
  } finally {
    detach();
    shell.close();
  }
});
