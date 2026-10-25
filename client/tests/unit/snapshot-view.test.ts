// 一处视图在当前参数下页面能看到什么的单元测试（工单 #295 第 3 项）：
// 视图没有打开（skip，例如项目还没有事项，department.workspace 缺事项标识）时加载状态为假，
// 页面据此显示空态，不显示「正在读取数据」；参数变了以后新快照到达之前仍算读取中，
// 且不给出上一处的数据。
// 读取失败时的原因也要带出来（工单 #728）：界面要能把它与「本来就没有内容」分开。
// 交出的位置等于这份数据来自的快照的位置，重新查询以后跟着更新（工单 #952）：
// 画面合同的状态要带位置，页面从 useSnapshot 拿到它再交给翻译层。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { snapshotView } from "../../src/renderer/src/views/project/use-snapshot.ts";

const KEY = JSON.stringify({ project_id: "p1", work_item: "wi1" });

test("视图没有打开时不显示加载中：项目还没有事项时部门工作间与资料页显示空态", () => {
  const state = { data: { phase: "intent" }, loading: false, error: null, key: KEY, position: 7 };
  // 跳过以后即使上一次有数据也不给出，页面显示空态而不是上一次的内容
  assert.deepEqual(snapshotView(state, KEY, true), { data: null, loading: false, error: null, position: 0 });
  assert.deepEqual(snapshotView({ data: null, loading: true, error: null, key: null, position: 0 }, KEY, true),
    { data: null, loading: false, error: null, position: 0 });
});

test("参数变了以后、新快照到达之前算读取中，且不给出上一处的数据", () => {
  const state = {
    data: { phase: "intent" }, loading: false, error: null, position: 7,
    key: JSON.stringify({ project_id: "p2", work_item: "wi2" }),
  };
  assert.deepEqual(snapshotView(state, KEY, false), { data: null, loading: true, error: null, position: 0 });
});

test("参数没变时按快照本身给出：到达以后不再加载", () => {
  assert.deepEqual(
    snapshotView({ data: { phase: "intent" }, loading: false, error: null, key: KEY, position: 7 }, KEY, false),
    { data: { phase: "intent" }, loading: false, error: null, position: 7 },
  );
  assert.deepEqual(
    snapshotView({ data: null, loading: true, error: null, key: KEY, position: 0 }, KEY, false),
    { data: null, loading: true, error: null, position: 0 },
  );
});

test("读取失败时把原因带出来：界面据此说「读不出来」而不是「本来就没有」", () => {
  // 工单 #728
  const state = { data: null, loading: false, error: "查询 projects.list 没有返回数据：Internal Server Error", key: KEY, position: 0 };
  assert.deepEqual(
    snapshotView(state, KEY, false),
    { data: null, loading: false, error: "查询 projects.list 没有返回数据：Internal Server Error", position: 0 },
  );
});

test("交出的位置等于这份数据来自的快照的位置，重新查询以后跟着更新", () => {
  // 工单 #952 验收标准 1：同一处视图的重新查询由视图同步发出，新快照到达时带上新的位置；
  // 这里核对页面拿到的位置随快照走，而不是停在第一次读取的位置
  const first = { data: { count: 1 }, loading: false, error: null, key: KEY, position: 12 };
  assert.equal(snapshotView(first, KEY, false).position, 12);
  const refreshed = { data: { count: 2 }, loading: false, error: null, key: KEY, position: 15 };
  const shown = snapshotView(refreshed, KEY, false);
  assert.deepEqual(shown.data, { count: 2 });
  assert.equal(shown.position, 15);
});
