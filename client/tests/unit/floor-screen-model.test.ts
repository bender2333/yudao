// 概览页楼层的事项状态（工单 #900）：project.loop 给的是项目流里事项的状态（in_progress 等），
// 楼层只认画面的状态名（floor.ts 的 IN_ROOM 与 ACTIVE）。这里核对 floorModelOf 换出来的名字，
// 并把换出来的数据交给真实的楼层驱动，看事项在不在它部门的房间里、房间算不算在工作。
//
// floorModelOf 在 floor-screen.tsx 里，Node 直接导入不了 .tsx，所以经 Vite 的模块服务器取它的实现；
// 楼层驱动、场景与目录是纯 TS 模块，直接导入。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ViteDevServer } from "vite";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildCatalog } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { createScene } from "../../src/renderer/src/pixel/world/scene.ts";
import { ACTIVE, IN_ROOM, createFloorDriver, createFloorState } from "../../src/renderer/src/pixel/world/floor.ts";
import type * as FloorScreenModule from "../../src/renderer/src/views/project/floor-screen.tsx";
import type { FloorModel } from "../../src/renderer/src/pixel/world/types.ts";
import type { WorkItemLoop } from "../../src/renderer/src/api/generated/types.gen.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

let server: ViteDevServer | null = null;
let floorModelOf: typeof FloorScreenModule.floorModelOf;

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间并行运行：缓存目录与房间、楼层回放等同样起模块服务器的测试分开
    cacheDir: join(clientRoot, "node_modules", ".vite-floor-screen-model"),
    plugins: [],
    server: { middlewareMode: true },
    logLevel: "error",
    appType: "custom",
  });
  const mod = await server.ssrLoadModule("/src/views/project/floor-screen.tsx") as typeof FloorScreenModule;
  floorModelOf = mod.floorModelOf;
});

after(async () => {
  await server?.close();
  server = null;
});

/** project.loop 里的一行事项：只写与楼层有关的字段，其余按查询合同补空。 */
function row(over: Partial<WorkItemLoop>): WorkItemLoop {
  return {
    work_item_id: "w1", kind: "request", sign: "示例事项", color_index: 1, status: "in_progress",
    department: "engineering", progress: null, round: 1, started_at: null, elapsed_sec: 100,
    time_limit_sec: 7200, pending_question: null, run_id: "r1", adoption_id: null,
    recovery_state: "running", version: 1, ...over,
  };
}

/** 把一行的 project.loop 查询结果交给 floorModelOf，取出楼层画面数据。 */
function modelOf(rows: WorkItemLoop[]): FloorModel {
  return floorModelOf({
    loop: { project_id: "p1", work_items: rows, adoptions: [] },
    workspaces: {}, decisions: null, slots: null, ops: null, machines: null, interrupted: false,
  });
}

const CATALOG = buildCatalog({});
const TIME = { clock: (iso: string | null) => iso ?? "", duration: (sec: number) => String(sec) };

/** 把楼层画面数据交给真实的楼层驱动，返回驱动与某个部门房间里的小人。 */
function floorOf(m: FloorModel): { driver: ReturnType<typeof createFloorDriver>; characterIn: (department: string) => ReturnType<typeof createFloorDriver>["world"]["characters"][string] | null } {
  const scene = createScene({ W: 640, H: 320, random: () => 0.5, reduced: false });
  scene.autonomy = false;
  const driver = createFloorDriver({ model: m, scene, state: createFloorState(), catalog: CATALOG, W: 640, H: 320, time: TIME });
  const characterIn = (department: string) => Object.values(driver.world.characters).find((c) => c.department === department) ?? null;
  return { driver, characterIn };
}

test("进行中的事项进入它部门的房间，房间算作在工作", () => {
  const m = modelOf([row({ status: "in_progress", department: "engineering", recovery_state: "running" })]);
  assert.equal(m.items[0].status, "running", "楼层拿到的是画面的状态名");
  assert.equal(ACTIVE.includes(m.items[0].status), true, "运行中算作在工作（房间亮灯）");
  // 文字列表写事项本身的状态（进行中），不是画面的状态名
  assert.equal(m.items[0].work_item_status, "in_progress");
  const { driver, characterIn } = floorOf(m);
  assert.ok(driver.world.rooms.engineering, "工程部门的房间立着");
  const ch = characterIn("engineering");
  assert.ok(ch, "工程部门有小人");
  assert.equal(ch.item?.work_item_id, "w1", "事项在工程部门的房间里");
  assert.equal(ch.rest?.pose, "type", "房间按工作画：人在工位上打字");
});

test("中断、待恢复、已暂停的事项留在房间里，状态是各自的画面状态", () => {
  const cases: { recovery: string; pose: string; iconText?: string }[] = [
    { recovery: "interrupted", pose: "sit" },
    { recovery: "waiting_resume", pose: "sit_wait", iconText: "待恢复" },
    { recovery: "paused", pose: "sit_relax" },
  ];
  for (const c of cases) {
    const m = modelOf([row({ status: "in_progress", department: "product", recovery_state: c.recovery })]);
    assert.equal(m.items[0].status, c.recovery, `进行中的事项按恢复观察状态画：${c.recovery}`);
    assert.equal(IN_ROOM.includes(c.recovery), true, `${c.recovery} 待在房间里`);
    const { characterIn } = floorOf(m);
    const ch = characterIn("product");
    assert.equal(ch?.item?.work_item_id, "w1", `${c.recovery} 的事项还在房间里`);
    assert.equal(ch?.rest?.pose, c.pose, `${c.recovery} 在房间里的画法`);
    if (c.iconText !== undefined) assert.equal(ch?.rest?.iconText, c.iconText);
  }
});

test("其余状态按页面的状态词换，表里没有的原样保留", () => {
  assert.equal(modelOf([row({ status: "awaiting_initial_prd" })]).items[0].status, "asking");
  assert.equal(modelOf([row({ status: "not_started" })]).items[0].status, "idle");
  assert.equal(modelOf([row({ status: "adopted" })]).items[0].status, "adopted");
  assert.equal(modelOf([row({ status: "released_unsettled" })]).items[0].status, "released");
  // 表里没有的（已停止、成果已挂起）原样保留，不猜
  assert.equal(modelOf([row({ status: "stopped" })]).items[0].status, "stopped");
  assert.equal(modelOf([row({ status: "held" })]).items[0].status, "held");
});

test("等待确认初始 PRD 的事项进房间等；已采纳与已停止的不进房间", () => {
  const asking = modelOf([row({ status: "awaiting_initial_prd", department: "product", recovery_state: null })]);
  assert.equal(ACTIVE.includes(asking.items[0].status), true);
  const { characterIn } = floorOf(asking);
  assert.equal(characterIn("product")?.item?.work_item_id, "w1", "等待确认的事项在房间里等");
  for (const status of ["adopted", "stopped", "not_started"]) {
    const m = modelOf([row({ status, department: "quality", recovery_state: null })]);
    assert.equal(floorOf(m).characterIn("quality")?.item, null, `${status} 的事项不进房间`);
  }
});
