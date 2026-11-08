// 部门房间的部门切换（接替 #1418 删掉的 client/tests/unit/room-screen-switch.test.ts 的 4 条，工单 #1573）。
//
// 原来测的是页面上的 RoomScreen：在部门页签之间切换，画面只应用属于当前部门的模型；
// 现在画面有自己的组件与壳：房间的查询走进同步层，画面经壳拿到状态。这里用录下的
// department.workspace 应答（tests/fixtures/session/queries.json）驱动壳，像素画面用一个记录的替身。
//
// 四条对应原来的四条：
//   1. 部门之间直接切换：每个部门的画面属于该部门；
//   2. 换部门时查询结果还没到：画面不应用上一个部门的模型；
//   3. 同一部门重新查询（数据短暂为空）：画面沿用本部门的模型，不重建；
//   4. 切回原部门：画面重新应用该部门自己的模型。
//
// 守 R1（状态只从查询来）与 R2（换部门时画面的归属是合同：不把上一个部门的事实画给新部门）。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { RoomState } from "../../src/pixel/contract.ts";
import {
  FakeServer, fakeClock, fakeHost, fakeSurface, loadFixtures, recordingOf, settle, shellFor, until,
} from "./session-harness.ts";

const fixtures = loadFixtures();
const ids = recordingOf(fixtures, "demo").ids;
const departments = ["product", "engineering", "quality"] as const;

function roomModel(surface: ReturnType<typeof fakeSurface>): RoomState | null {
  const all = [...surface.jumped, ...surface.states];
  return all.length === 0 ? null : (all[all.length - 1] as RoomState);
}

function roleIds(surface: ReturnType<typeof fakeSurface>): string[] {
  return (roomModel(surface)?.roles ?? []).map((role) => role.id).sort();
}

test("部门之间直接切换：每个部门的画面只应用它自己的查询结果", async () => {
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  try {
    for (const department of departments) {
      shell.goRoom(department);
      const surface = fakeSurface();
      const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
      try {
        await until(() => roomModel(surface) !== null, `${department} 房间的状态`);
        assert.deepEqual(roleIds(surface), [`${department}-agent`], `${department} 的房间属于这个部门`);
        assert.equal(shell.state.note, null, `切到 ${department} 时不该出现读不出来的说明`);
      } finally {
        detach();
      }
    }
    // 每次切换都按当前部门查询（不是拿上一个部门的应答顶替）
    const requested = server.queried
      .filter((entry) => entry.name === "department.workspace")
      .map((entry) => entry.params?.department);
    assert.deepEqual(requested, [...departments]);
  } finally {
    shell.close();
  }
});

test("换部门时查询结果还没到：画面不应用上一个部门的模型", async () => {
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  try {
    server.deferNext("department.workspace");
    shell.goRoom("product");
    const productSurface = fakeSurface();
    const detachProduct = shell.attachHost(fakeHost, fakeClock, async () => productSurface);
    await until(() => server.waiting.length === 1, "产品部门的查询在等");
    // 产品部门的查询还没回来就切到工程：旧的结果不能画到新部门的画面上
    detachProduct();
    shell.goRoom("engineering");
    const engineeringSurface = fakeSurface();
    const detachEngineering = shell.attachHost(fakeHost, fakeClock, async () => engineeringSurface);
    try {
      assert.equal(roomModel(engineeringSurface), null, "工程部门的画面还没有数据");
      server.release();
      await until(() => roomModel(engineeringSurface) !== null, "工程房间的状态");
      assert.deepEqual(roleIds(engineeringSurface), ["engineering-agent"]);
      // 新部门的画面从未收到产品部门的模型
      const seen = [...engineeringSurface.jumped, ...engineeringSurface.states] as RoomState[];
      assert.ok(seen.every((model) => (model.roles ?? []).every((role) => role.id !== "product-agent")),
        "工程部门的画面里出现了产品部门的角色");
    } finally {
      detachEngineering();
    }
  } finally {
    shell.close();
  }
});

test("同一部门重新查询（数据短暂为空）：画面沿用本部门的模型，不重建", async () => {
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  shell.goRoom("engineering");
  const surface = fakeSurface();
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await until(() => roomModel(surface) !== null, "工程房间的状态");
    const before = shell.inspectBinding({ kind: "room", projectId: ids.project_id, department: "engineering", workItemId: ids.work_item_id });
    assert.equal(before.mounts, 1);
    const states = surface.states.length;

    // 同一部门的一次重新查询没有拿到数据（查询失败）：画面不重建，继续显示上一次的模型
    server.failures.add("department.workspace");
    await shell.sync.viewSync?.refresh("room.workspace");
    await settle();
    assert.deepEqual(roleIds(surface), ["engineering-agent"], "画面继续显示工程部门的角色");
    assert.equal(shell.inspectBinding({ kind: "room", projectId: ids.project_id, department: "engineering", workItemId: ids.work_item_id }).mounts, 1);
    assert.equal(surface.destroyed, 0, "数据短暂为空时画面不重建");

    // 数据再回来：同一个画面上换成新的状态（不是重建）
    server.failures.delete("department.workspace");
    await shell.sync.viewSync?.refresh("room.workspace");
    await settle();
    assert.ok(surface.states.length >= states, "新数据到了就交给同一个画面");
    assert.equal(surface.destroyed, 0);
  } finally {
    detach();
    shell.close();
  }
});

test("切回原部门：画面重新应用该部门自己的模型", async () => {
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  shell.goFloor(ids.project_id, ids.work_item_id);
  try {
    shell.goRoom("product");
    const first = fakeSurface();
    const detachFirst = shell.attachHost(fakeHost, fakeClock, async () => first);
    await until(() => roomModel(first) !== null, "产品房间的状态");
    detachFirst();

    shell.goRoom("engineering");
    const engineering = fakeSurface();
    const detachEngineering = shell.attachHost(fakeHost, fakeClock, async () => engineering);
    await until(() => roomModel(engineering) !== null, "工程房间的状态");
    detachEngineering();

    shell.goRoom("product");
    const again = fakeSurface();
    const detachAgain = shell.attachHost(fakeHost, fakeClock, async () => again);
    try {
      await until(() => roomModel(again) !== null, "回到产品房间的状态");
      assert.deepEqual(roleIds(again), ["product-agent"], "切回产品部门以后画面重新应用产品部门的模型");
    } finally {
      detachAgain();
    }
  } finally {
    shell.close();
  }
});
