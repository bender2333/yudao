// 画面合同的校验测试（工单 #951 验收标准 2、3）：把原型 v13 js/pixel/contract.js 的取值表与校验改写为对客户端的测试。
//
// 覆盖：楼层、房间、楼三个场景的状态；动作（带位置，kind 必须在传入的声明表里）；交接的包裹；姿势；
// 事实元素的来源；每种取值错了时抛错并写明是哪一项、什么值，正确的取值原样通过。
// 另核对两个新模块（contract.ts、timeline.ts）只互相导入，不导入别的代码。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  ARTIFACTS, BUSY_STATES, FLOOR_SIGNS, ITEM_STATES, LOOP_STATES, POSES, ROOM_STATES, ROLE_STATES, SOURCES,
  action, buildingState, floorState, roomState,
} from "../../src/renderer/src/pixel/contract.ts";
import * as contract from "../../src/renderer/src/pixel/contract.ts";

/** 表里没有的一个取值（与表里的取值都不重样，用来核对抛错信息）。 */
function outside(table: readonly string[]): string {
  let value = "不在表里的取值";
  while (table.includes(value)) value += "_";
  return value;
}

/** 调用 fn 时抛错，错误信息里写明是哪一项（what）与什么值（value）。 */
function throwsWith(fn: () => unknown, what: string, value: string): void {
  assert.throws(fn, (err: unknown) => {
    const message = err instanceof Error ? err.message : String(err);
    assert.ok(message.includes(what), `错误信息里没有「${what}」：${message}`);
    assert.ok(message.includes(value), `错误信息里没有取值 ${value}：${message}`);
    return true;
  });
}

function floor(over: Record<string, unknown> = {}): Record<string, unknown> {
  return { position: 1, items: [{ id: "w1", status: "queued" }], ...over };
}

function room(over: Record<string, unknown> = {}): Record<string, unknown> {
  return { position: 3, status: "working", ...over };
}

function building(over: Record<string, unknown> = {}): Record<string, unknown> {
  return { position: 2, floors: [{ project_id: "p1", status: "working" }], ...over };
}

// ---------------------------------------------------------------------------
// 楼层

test("楼层：事项的每种状态都通过，别的取值抛错并写明是哪个事项的哪一项", () => {
  for (const status of ITEM_STATES) {
    assert.equal(floorState(floor({ items: [{ id: "w1", status }] })).items[0].status, status, `状态 ${status} 应当通过`);
  }
  const bad = outside(ITEM_STATES);
  throwsWith(() => floorState(floor({ items: [{ id: "w1", status: bad }] })), "事项 w1 的状态", JSON.stringify(bad));
});

test("楼层：部门在事项上的每种状态都通过，别的取值抛错并写明是哪个事项的哪个部门", () => {
  for (const state of BUSY_STATES) {
    assert.equal(
      floorState(floor({ items: [{ id: "w1", status: "working", departments: { engineering: state } }] })).items[0].departments?.engineering,
      state,
      `状态 ${state} 应当通过`,
    );
  }
  const bad = outside(BUSY_STATES);
  throwsWith(
    () => floorState(floor({ items: [{ id: "w1", status: "working", departments: { engineering: bad } }] })),
    "事项 w1 里 engineering 的状态",
    JSON.stringify(bad),
  );
});

test("楼层：角色的每种状态都通过，别的取值抛错并写明是哪个角色", () => {
  for (const status of ROLE_STATES) {
    const state = floorState(floor({ roles: { engineering: [{ id: "eng-manager", status }] } }));
    assert.equal(state.roles?.engineering[0].status, status, `状态 ${status} 应当通过`);
  }
  const bad = outside(ROLE_STATES);
  throwsWith(
    () => floorState(floor({ roles: { engineering: [{ id: "eng-manager", status: bad }] } })),
    "角色 eng-manager 的状态",
    JSON.stringify(bad),
  );
});

test("楼层：事实元素的每种来源都通过，别的来源抛错并写明是哪个事项的哪一条", () => {
  for (const source of SOURCES) {
    const ref = { source };
    const state = floorState(floor({ items: [{ id: "w1", status: "working", refs: { f1: ref } }] }));
    assert.equal(state.items[0].refs?.f1?.source, source, `来源 ${source} 应当通过`);
    assert.equal(floorState(floor({ stamp: { ref } })).stamp?.ref?.source, source, `盖章的来源 ${source} 应当通过`);
  }
  const bad = outside(SOURCES);
  throwsWith(
    () => floorState(floor({ items: [{ id: "w1", status: "working", refs: { f1: { source: bad } } }] })),
    "事项 w1.f1的来源",
    JSON.stringify(bad),
  );
  throwsWith(() => floorState(floor({ stamp: { ref: { source: bad } } })), "盖章的来源", JSON.stringify(bad));
});

// ---------------------------------------------------------------------------
// 楼

test("楼：每层的每种状态灯都通过，别的取值抛错并写明是哪一层", () => {
  for (const status of FLOOR_SIGNS) {
    assert.equal(buildingState(building({ floors: [{ project_id: "p1", status }] })).floors[0].status, status, `状态灯 ${status} 应当通过`);
  }
  const bad = outside(FLOOR_SIGNS);
  throwsWith(() => buildingState(building({ floors: [{ project_id: "p1", status: bad }] })), "楼层 p1 的状态灯", JSON.stringify(bad));
});

// ---------------------------------------------------------------------------
// 房间

test("房间：房间的每种状态都通过，别的取值抛错并写明是房间的状态", () => {
  for (const status of ROOM_STATES) {
    assert.equal(roomState(room({ status })).status, status, `状态 ${status} 应当通过`);
  }
  const bad = outside(ROOM_STATES);
  throwsWith(() => roomState(room({ status: bad })), "房间的状态", JSON.stringify(bad));
});

test("房间：角色的每种状态、每种姿势都通过，别的取值抛错并写明是哪一项", () => {
  for (const status of ROLE_STATES) {
    assert.equal(roomState(room({ roles: [{ id: "eng-architect", status }] })).roles?.[0].status, status, `角色状态 ${status} 应当通过`);
  }
  for (const anim of POSES) {
    assert.equal(roomState(room({ pose: { anim } })).pose?.anim, anim, `姿势 ${anim} 应当通过`);
  }
  const badRole = outside(ROLE_STATES);
  throwsWith(() => roomState(room({ roles: [{ id: "eng-architect", status: badRole }] })), "角色 eng-architect 的状态", JSON.stringify(badRole));
  const badPose = outside(POSES);
  throwsWith(() => roomState(room({ pose: { anim: badPose } })), "房间的姿势", JSON.stringify(badPose));
});

// ---------------------------------------------------------------------------
// 动作

const KINDS = { handoff: { tier: "key", ms: 1800 }, read: { tier: "normal", ms: 1100 } } as const;

test("动作：kind 在这个场景的声明表里就通过，不在表里就抛错并写明是哪种动作", () => {
  const a = { kind: "read", position: 7 };
  assert.equal(action("楼层", a, KINDS), a);
  throwsWith(() => action("楼层", { kind: "不存在的动作", position: 7 }, KINDS), "楼层的声明表里没有这种动作", JSON.stringify("不存在的动作"));
});

test("动作：交接的每种包裹都通过，别的包裹抛错并写明是交接的包裹", () => {
  for (const artifact of ARTIFACTS) {
    assert.equal(action("楼层", { kind: "handoff", position: 7, artifact }, KINDS).artifact, artifact, `包裹 ${artifact} 应当通过`);
  }
  const bad = outside(ARTIFACTS);
  throwsWith(() => action("楼层", { kind: "handoff", position: 7, artifact: bad as never }, KINDS), "交接的包裹", JSON.stringify(bad));
});

// ---------------------------------------------------------------------------
// 位置与缺项

test("状态与动作都要带位置：没有位置时抛错并写明是哪一项", () => {
  assert.equal(floorState(floor()).position, 1);
  assert.equal(buildingState(building()).position, 2);
  assert.equal(roomState(room()).position, 3);
  throwsWith(() => floorState({ items: [] }), "楼层的状态没有位置", JSON.stringify(undefined));
  throwsWith(() => buildingState({ floors: [] }), "楼的状态没有位置", JSON.stringify(undefined));
  throwsWith(() => roomState({ status: "idle" }), "房间的状态没有位置", JSON.stringify(undefined));
  throwsWith(() => action("房间", { kind: "read" } as never, KINDS), "房间的动作没有位置", JSON.stringify(undefined));
});

test("楼层与楼的状态里，事项与楼层必须是数组；缺了就抛错并写明缺哪一项", () => {
  throwsWith(() => floorState({ position: 1 }), "楼层的状态缺少 items", JSON.stringify(undefined));
  throwsWith(() => buildingState({ position: 1 }), "楼的状态缺少 floors", JSON.stringify(undefined));
});

// ---------------------------------------------------------------------------
// 取值表与边界

test("取值表：九张表都在合同的接口上，收敛状态只有取值表（覆盖层由翻译层写好，不进时间线）", () => {
  const tables = {
    ITEM_STATES, BUSY_STATES, FLOOR_SIGNS, ROOM_STATES, ROLE_STATES, SOURCES, LOOP_STATES, ARTIFACTS, POSES,
  };
  for (const [name, table] of Object.entries(tables)) {
    assert.ok(Array.isArray(table) && table.length > 0, `${name} 应当是非空的取值表`);
    for (const value of table) assert.equal(typeof value, "string", `${name} 里的每个取值都应当是字符串：${String(value)}`);
    assert.equal(new Set(table).size, table.length, `${name} 里的取值不应当重复`);
  }
  // 工单 #951：机房的状态不移植
  assert.equal("machineRoomState" in contract, false, "机房的状态不在这张工单的范围里");
});

// ---------------------------------------------------------------------------
// 导入方向

/** 一个文件里的导入语句（from 的那一截与 import "x" 两种写法）。 */
function importPaths(code: string): string[] {
  const paths: string[] = [];
  for (const m of code.matchAll(/(?:^|\n)\s*(?:import|export)[^;\n]*?from\s+["']([^"']+)["']/g)) paths.push(m[1]);
  for (const m of code.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)) paths.push(m[1]);
  return paths;
}

test("导入：两个新模块只互相导入，不导入别的代码", () => {
  const pixel = new URL("../../src/renderer/src/pixel/", import.meta.url);
  const contractModule = readFileSync(new URL("contract.ts", pixel), "utf8");
  const timelineModule = readFileSync(new URL("timeline.ts", pixel), "utf8");

  const contractImports = importPaths(contractModule);
  assert.deepEqual(contractImports, [], `contract.ts 不应当导入任何别的代码：${contractImports.join(",")}`);

  const timelineImports = importPaths(timelineModule);
  assert.ok(timelineImports.length > 0, "timeline.ts 应当按类型引用 contract.ts");
  for (const path of timelineImports) {
    assert.equal(path, "./contract.ts", `timeline.ts 只应当导入 contract.ts，实际还有 ${path}`);
    assert.ok(!path.startsWith("node:") && !path.includes("contract.ts/"), path);
  }
});
