// 一处视图在当前参数下页面能看到什么的单元测试（工单 #295 第 3 项）：
// 视图没有打开（skip，例如项目还没有事项，department.workspace 缺事项标识）时加载状态为假，
// 页面据此显示空态，不显示「正在读取数据」；参数变了以后新快照到达之前仍算读取中，
// 且不给出上一处的数据。
// 读取失败时的原因也要带出来（工单 #728）：界面要能把它与「本来就没有内容」分开。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { Rejected } from "../../src/renderer/src/api/generated/types.gen";
import { rejectionLabel } from "../../src/renderer/src/contract/command-problem.ts";
import { rejectionLinks, snapshotView } from "../../src/renderer/src/views/project/use-snapshot.ts";

const KEY = JSON.stringify({ project_id: "p1", work_item: "wi1" });

test("视图没有打开时不显示加载中：项目还没有事项时部门工作间与资料页显示空态", () => {
  const state = { data: { phase: "intent" }, loading: false, error: null, key: KEY };
  // 跳过以后即使上一次有数据也不给出，页面显示空态而不是上一次的内容
  assert.deepEqual(snapshotView(state, KEY, true), { data: null, loading: false, error: null });
  assert.deepEqual(snapshotView({ data: null, loading: true, error: null, key: null }, KEY, true), { data: null, loading: false, error: null });
});

test("参数变了以后、新快照到达之前算读取中，且不给出上一处的数据", () => {
  const state = { data: { phase: "intent" }, loading: false, error: null, key: JSON.stringify({ project_id: "p2", work_item: "wi2" }) };
  assert.deepEqual(snapshotView(state, KEY, false), { data: null, loading: true, error: null });
});

test("参数没变时按快照本身给出：到达以后不再加载", () => {
  assert.deepEqual(
    snapshotView({ data: { phase: "intent" }, loading: false, error: null, key: KEY }, KEY, false),
    { data: { phase: "intent" }, loading: false, error: null },
  );
  assert.deepEqual(
    snapshotView({ data: null, loading: true, error: null, key: KEY }, KEY, false),
    { data: null, loading: true, error: null },
  );
});

test("读取失败时把原因带出来：界面据此说「读不出来」而不是「本来就没有」", () => {
  // 工单 #728
  const state = { data: null, loading: false, error: "查询 projects.list 没有返回数据：Internal Server Error", key: KEY };
  assert.deepEqual(
    snapshotView(state, KEY, false),
    { data: null, loading: false, error: "查询 projects.list 没有返回数据：Internal Server Error" },
  );
});

test("拒绝的说明只写服务端的中文消息，不带英文的原因标识", () => {
  // 工单 #319 第 5、6 项
  assert.equal(rejectionLabel({
    reason: "provider_unavailable",
    message: "质检部门还没有选择模型，到系统的模型管理页设置部门默认，或在本项目的设置页为这个项目选择",
  } as Rejected), "质检部门还没有选择模型，到系统的模型管理页设置部门默认，或在本项目的设置页为这个项目选择");
  // 基准版本过期仍然给出可操作的一句
  assert.match(rejectionLabel({ reason: "stale_base", message: "基准版本过期", current_version: 7 } as Rejected),
    /^基准版本过期（服务端当前版本 7），请重新读取以后提交$/);
});

test("部门没有选模型时给出两个去处：模型管理页与本项目的设置页", () => {
  const links = rejectionLinks({ kind: "rejected", rejection: { reason: "provider_unavailable", message: "质检部门还没有选择模型" } as Rejected }, "p1");
  assert.deepEqual(links.map((link) => link.label), ["去模型管理页设置部门默认", "在本项目的设置页选择模型"]);
  assert.deepEqual(links.map((link) => link.hash), ["/sys/models", "/p/p1/settings"]);
});

test("其余拒绝原因不给去处", () => {
  assert.deepEqual(rejectionLinks({ kind: "rejected", rejection: { reason: "busy", message: "已有事项正在执行" } as Rejected }, "p1"), []);
  assert.deepEqual(rejectionLinks(null, "p1"), []);
});
