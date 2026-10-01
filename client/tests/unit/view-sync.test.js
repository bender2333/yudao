// 视图同步的单元测试（应用层与接口层设计说明第 5.7 节）：
// 位置不大于快照位置的事件不作用；按能力清单声明的事件种类重新查询；200 毫秒合并；迟到的结果丢弃。
// 用 node --test 运行，不需要 Electron 与网络：查询由测试的替身给出（不是 mock 接口，是注入的查询函数）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { ViewSync } from "../../src/renderer/src/contract/view-sync.ts";

const CAPABILITIES = {
  queries: [{ name: "projects.list", changed_by: ["project_registered"] }],
};

test("位置不大于快照位置的事件不触发重新查询", async () => {
  let calls = 0;
  const views = new ViewSync(async () => {
    calls += 1;
    return { position: 5, data: { value: calls } };
  }, CAPABILITIES);
  const seen = [];
  await views.open("v", { query: "projects.list" }, (data) => seen.push(data));
  assert.equal(calls, 1);
  // 位置 4 不大于快照位置 5：不作用
  views.applyEvent("project_registered", 4);
  await delay(300);
  assert.equal(calls, 1);
});

test("改变结果的事件种类排入合并队列，200 毫秒内的多条合并为一次", async () => {
  let calls = 0;
  const views = new ViewSync(async () => {
    calls += 1;
    return { position: 10 + calls, data: { value: calls } };
  }, CAPABILITIES);
  await views.open("v", { query: "projects.list" }, () => undefined);
  assert.equal(calls, 1);
  views.applyEvent("project_registered", 11);
  views.applyEvent("project_registered", 12);
  views.applyEvent("project_registered", 13);
  await delay(400);
  assert.equal(calls, 2);
});

test("不在 changed_by 中的事件不触发重新查询", async () => {
  let calls = 0;
  const views = new ViewSync(async () => {
    calls += 1;
    return { position: 1, data: {} };
  }, CAPABILITIES);
  await views.open("v", { query: "projects.list" }, () => undefined);
  views.applyEvent("tool_called", 2);
  await delay(300);
  assert.equal(calls, 1);
});

test("关闭视图以后迟到的查询结果丢弃", async () => {
  let release = () => {};
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const views = new ViewSync(async () => {
    await gate;
    return { position: 9, data: { value: "late" } };
  }, CAPABILITIES);
  const seen = [];
  const opening = views.open("v", { query: "projects.list" }, (data) => seen.push(data));
  views.close("v");
  release();
  await opening;
  assert.deepEqual(seen, []);
});

test("refreshAll 返回已打开视图快照位置中最小的一个", async () => {
  const positions = { "projects.list": 7, "system.status": 3 };
  const views = new ViewSync(async (name) => ({ position: positions[name], data: {} }), {
    queries: [
      { name: "projects.list", changed_by: [] },
      { name: "system.status", changed_by: [] },
    ],
  });
  await views.open("a", { query: "projects.list" }, () => undefined);
  await views.open("b", { query: "system.status" }, () => undefined);
  assert.equal(await views.refreshAll(), 3);
});

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("重复收到同一条事件不会再次查询（没有重复的事件处理）", async () => {
  // 快照位置取 4；事件位置 5 触发一次查询，查询以后快照位置推进到 5，同一条事件（5）不再作用
  let calls = 0;
  const views = new ViewSync(async () => {
    calls += 1;
    return { position: calls === 1 ? 4 : 5, data: {} };
  }, CAPABILITIES);
  await views.open("v", { query: "projects.list" }, () => undefined);
  views.applyEvent("project_registered", 5);
  await delay(400);
  assert.equal(calls, 2);
  // 同一条事件（位置 5）再次到达：不大于快照位置 5，不再查询
  views.applyEvent("project_registered", 5);
  await delay(300);
  assert.equal(calls, 2);
});

test("resync 时重新查询快照（refreshAll），视图补齐", async () => {
  let calls = 0;
  const views = new ViewSync(async () => {
    calls += 1;
    return { position: 20 + calls, data: { value: calls } };
  }, CAPABILITIES);
  const seen = [];
  await views.open("v", { query: "projects.list" }, (data) => seen.push(data));
  assert.equal(calls, 1);
  const position = await views.refreshAll();
  assert.equal(calls, 2);
  assert.equal(position, 22);
  assert.deepEqual(seen.map((item) => item.value), [1, 2]);
});
