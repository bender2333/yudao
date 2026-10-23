// 观测页的部门筛选条件（工单 #801）：范围与筛选条件分开。
// ?w= 是事项范围（作用域），?dept= 是部门筛选条件；部门工作间的「本部门的模型请求」
// 把部门带进观测页，观测页按它只显示这个部门的请求。
// 用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute, paths, withScope } from "../../src/renderer/src/shell/routing.ts";
import { departmentFilterNote, seedFilters } from "../../src/renderer/src/views/project/observe-filter.ts";

test("部门筛选条件写在 ?dept= 里，读得回来", () => {
  assert.equal(parseRoute("#/p/p1/observe?dept=quality").departmentFilter, "quality");
  assert.equal(parseRoute("#/p/p1/observe?dept=engineering").departmentFilter, "engineering");
  assert.equal(parseRoute("#/p/p1/observe").departmentFilter, null);
});

test("范围与部门筛选条件各写各的：两个参数都在时都读得回来", () => {
  const route = parseRoute("#/p/p1/observe?w=w1&dept=quality");
  assert.equal(route.workItemId, "w1");
  assert.equal(route.departmentFilter, "quality");
});

test("未知的部门按没有筛选处理，不把无效的部门发给服务端", () => {
  assert.equal(parseRoute("#/p/p1/observe?dept=abc").departmentFilter, null);
  assert.equal(parseRoute("#/p/p1/observe?dept=").departmentFilter, null);
  assert.equal(parseRoute("#/p/p1/observe?dept=operations").departmentFilter, null);
});

test("观测页与请求详情的地址带着部门筛选条件", () => {
  assert.equal(paths.observe("p1", { department: "quality" }), "#/p/p1/observe?dept=quality");
  assert.equal(paths.observe("p1", { workItem: "w1", department: "quality" }), "#/p/p1/observe?w=w1&dept=quality");
  assert.equal(paths.observe("p1"), "#/p/p1/observe");
  assert.equal(
    paths.observeDetail("p1", "a1", { workItem: "w1", runId: "r1", department: "quality" }),
    "#/p/p1/observe/a1?w=w1&r=r1&dept=quality",
  );
});

test("换事项范围时部门筛选条件不丢", () => {
  assert.equal(withScope(parseRoute("#/p/p1/observe?dept=quality"), "w1"), "#/p/p1/observe?w=w1&dept=quality");
  assert.equal(withScope(parseRoute("#/p/p1/observe?w=w1&dept=quality"), null), "#/p/p1/observe?dept=quality");
  assert.equal(withScope(parseRoute("#/p/p1/observe/a1?dept=quality"), "w1"), "#/p/p1/observe?w=w1&dept=quality");
});

test("进入观测页时部门筛选条件的初值就是地址里带来的那个", () => {
  assert.equal(seedFilters("quality").department, "quality");
  assert.equal(seedFilters(null).department, "");
  assert.equal(seedFilters("quality").status, "");
});

test("页面上说明当前筛选的是哪个部门：中文名，不出现内部标识", () => {
  assert.equal(departmentFilterNote("quality"), "只看质检的请求");
  assert.equal(departmentFilterNote("engineering"), "只看工程的请求");
  assert.equal(departmentFilterNote(""), "");
});
