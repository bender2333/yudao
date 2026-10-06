// 一处视图在当前参数下页面能看到什么的单元测试（工单 #295 第 3 项）：
// 视图没有打开（skip，例如项目还没有事项，department.workspace 缺事项标识）时加载状态为假，
// 页面据此显示空态，不显示「正在读取数据」；参数变了以后新快照到达之前仍算读取中，
// 且不给出上一处的数据。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { snapshotView } from "../../src/renderer/src/views/project/use-snapshot.ts";

const KEY = JSON.stringify({ project_id: "p1", work_item: "wi1" });

test("视图没有打开时不显示加载中：项目还没有事项时部门工作间与资料页显示空态", () => {
  const state = { data: { phase: "intent" }, loading: false, key: KEY };
  // 跳过以后即使上一次有数据也不给出，页面显示空态而不是上一次的内容
  assert.deepEqual(snapshotView(state, KEY, true), { data: null, loading: false });
  assert.deepEqual(snapshotView({ data: null, loading: true, key: null }, KEY, true), { data: null, loading: false });
});

test("参数变了以后、新快照到达之前算读取中，且不给出上一处的数据", () => {
  const state = { data: { phase: "intent" }, loading: false, key: JSON.stringify({ project_id: "p2", work_item: "wi2" }) };
  assert.deepEqual(snapshotView(state, KEY, false), { data: null, loading: true });
});

test("参数没变时按快照本身给出：到达以后不再加载", () => {
  assert.deepEqual(
    snapshotView({ data: { phase: "intent" }, loading: false, key: KEY }, KEY, false),
    { data: { phase: "intent" }, loading: false },
  );
  assert.deepEqual(
    snapshotView({ data: null, loading: true, key: KEY }, KEY, false),
    { data: null, loading: true },
  );
});
