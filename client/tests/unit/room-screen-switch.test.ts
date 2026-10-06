// 部门房间组件的部门切换（工单 #300 验收标准 2）：在页面上真实挂载 RoomScreen 组件，
// 在项目的部门页签之间直接切换，核对画面只应用属于当前部门的模型。
//
// 每个部门的查询结果取录下的真实房间数据（tests/fixtures/room/recordings.json），不是手写的假数据。

import { test } from "node:test";
import assert from "node:assert/strict";
import { roomWorkspaceFixture, runRoomSwitch } from "../helpers/room-screen-page.ts";

test("部门页签之间直接切换：每个页签的画面属于该部门，页面不出现加载失败", async () => {
  const departments = ["product", "engineering", "quality", "product"];
  const fixtures = Object.fromEntries(departments.map((d) => [d, roomWorkspaceFixture(d)]));
  const report = await runRoomSwitch(departments.map((department) => ({ department, data: fixtures[department] })));
  assert.equal(report.states.length, departments.length);
  for (const [index, state] of report.states.entries()) {
    const department = departments[index];
    const fixture = fixtures[department];
    assert.equal(state.errorText, null, `切到 ${department} 时页面不应出现加载失败：${state.errorText ?? ""}`);
    assert.equal(state.viewDepartment, department, `切到 ${department} 时画面应当属于该部门`);
    // 画面里的角色正是该部门录下的角色：画面属于哪个部门因此可核对
    assert.deepEqual(state.roleIds.sort(), fixture.room.roles.map((r) => r.id).sort(), `切到 ${department} 时画面里的角色`);
  }
  assert.deepEqual(report.pageErrors, [], `页面上不应有报错：${report.pageErrors.join("\n")}`);
});

test("换部门时查询结果短暂为空：画面不应用上一个部门的模型", async () => {
  // 顶部页签切换期间，新部门的查询结果还没回来（部门工作间给房间的数据是 null）
  const product = roomWorkspaceFixture("product");
  const engineering = roomWorkspaceFixture("engineering");
  const report = await runRoomSwitch([
    { department: "product", data: product },
    { department: "engineering", data: null },
    { department: "engineering", data: engineering },
  ]);
  for (const state of report.states) {
    assert.equal(state.errorText, null, `切到 ${state.department} 时不应出现加载失败：${state.errorText ?? ""}`);
    assert.equal(state.viewDepartment, state.department, `切到 ${state.department} 时画面应当属于该部门`);
  }
  const [productState, engineeringEmpty, engineeringState] = report.states;
  // 数据为空期间画面是空的工程房间：产品部门的角色一个都不在
  const productRoleIds = product.room.roles.map((r) => r.id);
  assert.equal(engineeringEmpty.roleIds.filter((id) => productRoleIds.includes(id)).length, 0,
    `数据为空时画面里不应有产品部门的角色：${engineeringEmpty.roleIds.join(",")}`);
  assert.deepEqual(productState.roleIds.sort(), productRoleIds.sort());
  // 新部门的查询结果到达后画面显示该部门的角色
  assert.deepEqual(engineeringState.roleIds.sort(), engineering.room.roles.map((r) => r.id).sort());
  assert.deepEqual(report.pageErrors, [], `页面上不应有报错：${report.pageErrors.join("\n")}`);
});

test("同一部门重新查询时数据短暂为空：画面继续沿用本部门的模型不重建", async () => {
  // 换事项这类同一部门内的重新查询：数据短暂为空，画面继续显示上一次查询结果（工单 #177 的行为）
  const engineering = roomWorkspaceFixture("engineering");
  const roleIds = engineering.room.roles.map((r) => r.id);
  const report = await runRoomSwitch([
    { department: "engineering", data: engineering },
    { department: "engineering", data: null },
  ]);
  for (const state of report.states) {
    assert.equal(state.errorText, null, `数据短暂为空时不应出现加载失败：${state.errorText ?? ""}`);
    assert.equal(state.viewDepartment, "engineering");
    // 本部门的角色继续在画面里：清模型只该发生在换部门的时候
    assert.deepEqual(state.roleIds.slice().sort(), roleIds.sort(), `画面里的角色：${state.roleIds.join(",")}`);
  }
  assert.deepEqual(report.pageErrors, [], `页面上不应有报错：${report.pageErrors.join("\n")}`);
});

test("切回原部门：画面重新应用该部门自己的模型", async () => {
  const quality = roomWorkspaceFixture("quality");
  const report = await runRoomSwitch([
    { department: "quality", data: quality },
    { department: "product", data: null },
    { department: "quality", data: quality },
  ]);
  for (const state of report.states) {
    assert.equal(state.errorText, null, `切到 ${state.department} 时不应出现加载失败：${state.errorText ?? ""}`);
    assert.equal(state.viewDepartment, state.department);
  }
  const qualityRoleIds = quality.room.roles.map((r) => r.id);
  const [, productEmpty, qualityAgain] = report.states;
  assert.equal(productEmpty.roleIds.filter((id) => qualityRoleIds.includes(id)).length, 0,
    `切走的质检部门的数据为空时，画面里不应有质检的角色：${productEmpty.roleIds.join(",")}`);
  assert.deepEqual(qualityAgain.roleIds.sort(), qualityRoleIds.sort(), "切回质检以后画面里的角色与离开前一致");
  assert.deepEqual(report.pageErrors, [], `页面上不应有报错：${report.pageErrors.join("\n")}`);
});
