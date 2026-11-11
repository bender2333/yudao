// 页面的路由（工单 #176 验收标准 3、#1418）：地址解析成页面名与参数，路径表里没有图鉴。
// 图鉴随画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）：
// 它是画面自己的整页（view/ 的入口），页面的路径不再解析它。

import { test } from "node:test";
import assert from "node:assert/strict";

import { attemptBackPath, parseRoute, paths, withScope } from "../../src/renderer/src/shell/routing.ts";
import { EMPTY_FILTERS, type Filters } from "../../src/renderer/src/views/project/observe-filter.ts";

test("正式路径照旧解析：home、sys、项目页面；图鉴与已删除的连接页都落到未找到", () => {
  assert.equal(parseRoute("").name, "home");
  assert.equal(parseRoute("#/home").name, "home");
  assert.equal(parseRoute("#/connect").name, "not-found");
  assert.equal(parseRoute("#/gallery").name, "not-found");
  assert.equal(parseRoute("#/sys/machines").name, "sys-machines");
  assert.equal(parseRoute("#/p/demo/overview").name, "overview");
  assert.equal(parseRoute("#/p/demo/dept/product").name, "dept");
  assert.equal(parseRoute("#/nope").name, "not-found");
});

test("路径表里没有图鉴：页签与侧栏取不到它", () => {
  assert.ok(!Object.keys(paths).includes("gallery"), "图鉴不应出现在正式路径表里");
  assert.ok(!Object.values(paths).some((p) => String(p).includes("gallery")), "正式路径不应指向图鉴");
});

// 工单 #1638：项目页先是对话（上面带循环图），打开项目时落在这一页；概览等页先留着
test("打开项目落在对话页，事项范围写在 ?w= 里", () => {
  assert.equal(parseRoute("#/p/demo").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation?w=w1").workItemId, "w1");
  assert.equal(parseRoute("#/p/demo/conversation?w=").workItemId, null);
  assert.equal(paths.conversation("demo"), "#/p/demo/conversation");
  assert.equal(paths.conversation("demo", { workItem: "w1" }), "#/p/demo/conversation?w=w1");
  // 已有的页面照旧
  assert.equal(parseRoute("#/p/demo/overview").name, "overview");
  assert.equal(paths.overview("demo"), "#/p/demo/overview");
});

// 设置页底部「模型请求与用量」这一节（工单 #1710）：展开状态（section=requests）与筛选条件
// 都写在地址里，刷新、后退、分享与从请求详情返回都读得回；收着时不写 section，筛选为空时不写键。
function requestFilters(): Filters {
  return {
    department: "engineering",
    status: "failed",
    provider: "proxy-a",
    requestedModel: "gpt-5",
    actualModel: "gpt-5-mini",
    q: "abc",
  };
}

test("设置页这一节：展开与筛选写在地址里，地址读回来是同一组", () => {
  const hash = paths.settings("demo", { workItem: "w1", section: "requests", requests: requestFilters() });
  assert.equal(
    hash,
    "#/p/demo/settings?w=w1&section=requests&dept=engineering&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc",
  );
  const route = parseRoute(hash);
  assert.equal(route.name, "settings");
  assert.equal(route.workItemId, "w1");
  assert.equal(route.settingsSection, "requests");
  assert.equal(route.departmentFilter, "engineering");
  assert.deepEqual(route.requestFilters, requestFilters());
  // 收着的时候不写节名，没有筛选时不写空的键
  assert.equal(paths.settings("demo", { workItem: "w1", requests: EMPTY_FILTERS }), "#/p/demo/settings?w=w1");
});

test("地址里带项目职能清单里有、默认三个里没有的职能时筛选生效", () => {
  const route = parseRoute("#/p/demo/settings?dept=analysis");
  assert.equal(route.departmentFilter, "analysis");
  assert.equal(route.requestFilters.department, "analysis");
});

test("切事项范围不丢这一节的展开与筛选", () => {
  const route = parseRoute("#/p/demo/settings?section=requests&dept=engineering&status=failed");
  assert.equal(withScope(route, "w2"), "#/p/demo/settings?w=w2&section=requests&dept=engineering&status=failed");
});

test("从设置页这一节进请求详情：返回到这一节，保持展开与筛选", () => {
  const hash = paths.observeDetail("demo", "a1", {
    workItem: "w1", runId: "r1", department: "engineering", from: "settings", requests: requestFilters(),
  });
  assert.equal(
    hash,
    "#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&from=settings&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc",
  );
  const route = parseRoute(hash);
  assert.equal(route.name, "observe-detail");
  assert.equal(route.attemptOrigin, "settings");
  assert.deepEqual(route.requestFilters, requestFilters());
  const back = attemptBackPath(route);
  assert.equal(back.label, "返回模型请求与用量");
  assert.equal(back.hash, "#/p/demo/settings?w=w1&section=requests&dept=engineering&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc");
});

test("从工作过程进请求详情：返回到同一事项的对话页", () => {
  const hash = paths.observeDetail("demo", "a1", { workItem: "w1", runId: "r1", department: "engineering", from: "conversation" });
  assert.equal(hash, "#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&from=conversation");
  const back = attemptBackPath(parseRoute(hash));
  assert.equal(back.label, "返回对话");
  assert.equal(back.hash, "#/p/demo/conversation?w=w1");
});

test("直接输入请求详情地址：返回观测页的请求记录，与没有这一节时一样", () => {
  const route = parseRoute("#/p/demo/observe/a1?w=w1&r=r1&dept=engineering");
  assert.equal(route.attemptOrigin, null);
  const back = attemptBackPath(route);
  assert.equal(back.label, "返回请求记录");
  assert.equal(back.hash, "#/p/demo/observe?w=w1&dept=engineering");
  // 认不出的来处按没有来处处理，不当成设置页或对话页
  assert.equal(parseRoute("#/p/demo/observe/a1?from=elsewhere").attemptOrigin, null);
});
