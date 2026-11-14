// 页面的路由（工单 #176 验收标准 3、#1418）：地址解析成页面名与参数，路径表里没有图鉴。
// 图鉴随画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）：
// 它是画面自己的整页（view/ 的入口），页面的路径不再解析它。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  attemptBackPath, parseRoute, pathLabel, paths, projectTabs, withScope,
} from "../../src/renderer/src/shell/routing.ts";
import { EMPTY_FILTERS, type Filters } from "../../src/renderer/src/views/project/observe-filter.ts";

test("正式路径照旧解析：home、sys、项目页面；图鉴与已删除的连接页都落到未找到", () => {
  assert.equal(parseRoute("").name, "home");
  assert.equal(parseRoute("#/home").name, "home");
  assert.equal(parseRoute("#/connect").name, "not-found");
  assert.equal(parseRoute("#/gallery").name, "not-found");
  assert.equal(parseRoute("#/sys/machines").name, "sys-machines");
  assert.equal(parseRoute("#/p/demo/conversation").name, "conversation");
  assert.equal(parseRoute("#/nope").name, "not-found");
});

test("路径表里没有图鉴：页签与侧栏取不到它", () => {
  assert.ok(!Object.keys(paths).includes("gallery"), "图鉴不应出现在正式路径表里");
  assert.ok(!Object.values(paths).some((p) => String(p).includes("gallery")), "正式路径不应指向图鉴");
});

// 工单 #1638：项目页先是对话（上面带循环图），打开项目时落在这一页；
// 工单 #1715：概览、资料、观测与职能页的地址不再有页面，打开时落到对话并保留地址里的事项。
test("打开项目落在对话页，事项范围写在 ?w= 里", () => {
  assert.equal(parseRoute("#/p/demo").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation?w=w1").workItemId, "w1");
  assert.equal(parseRoute("#/p/demo/conversation?w=").workItemId, null);
  assert.equal(paths.conversation("demo"), "#/p/demo/conversation");
  assert.equal(paths.conversation("demo", { workItem: "w1" }), "#/p/demo/conversation?w=w1");
});

test("收进对话的旧页地址落到对话页，保留地址里的事项", () => {
  for (const page of ["overview", "materials", "observe"]) {
    assert.equal(parseRoute(`#/p/demo/${page}?w=w1`).name, "conversation", `${page} 页应收进对话`);
    assert.equal(parseRoute(`#/p/demo/${page}?w=w1`).workItemId, "w1", `${page} 页的地址保留事项`);
    assert.equal(parseRoute(`#/p/demo/${page}`).name, "conversation", `${page} 页没有事项时也落到对话`);
  }
  // 职能页（路径上写部门名的那种）同样落到对话，部门那一段不再有页面
  const dept = parseRoute("#/p/demo/dept/product?w=w1");
  assert.equal(dept.name, "conversation");
  assert.equal(dept.department, "product");
  assert.equal(dept.workItemId, "w1");
  // 详情页的地址照旧可用（工单 #1713、#1710）
  assert.equal(parseRoute("#/p/demo/dept-detail/engineering?w=w1").name, "dept-detail");
  assert.equal(parseRoute("#/p/demo/observe/a1?w=w1").name, "observe-detail");
  assert.equal(parseRoute("#/p/demo/w/w1/recovery").name, "recovery");
});

// 工单 #1715：项目页的页签只有对话与设置两项，任何组织下都一样（部门不再各占一个页签）。
test("项目页的页签只有对话与设置两项", () => {
  assert.deepEqual(projectTabs("demo", null), [
    { label: "对话", hash: "#/p/demo/conversation", query: "project.loop" },
    { label: "设置", hash: "#/p/demo/settings", query: "project.settings" },
  ]);
  assert.deepEqual(projectTabs("demo", "w1"), [
    { label: "对话", hash: "#/p/demo/conversation?w=w1", query: "project.loop" },
    { label: "设置", hash: "#/p/demo/settings?w=w1", query: "project.settings" },
  ]);
  // 空的范围与没有范围一样，不拼一个 ?w=
  assert.equal(projectTabs("demo", "")[0].hash, "#/p/demo/conversation");
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

// 工单 #1715：请求原来的列表页（观测）收进设置页的「模型请求与用量」；
// 直接输入请求详情的地址时回到这一节，与从这一节进来一样。
test("直接输入请求详情地址：返回设置页的「模型请求与用量」那一节", () => {
  const route = parseRoute("#/p/demo/observe/a1?w=w1&r=r1&dept=engineering");
  assert.equal(route.attemptOrigin, null);
  const back = attemptBackPath(route);
  assert.equal(back.label, "返回模型请求与用量");
  assert.equal(back.hash, "#/p/demo/settings?w=w1&section=requests&dept=engineering");
  // 认不出的来处按没有来处处理，不当成设置页或对话页
  assert.equal(parseRoute("#/p/demo/observe/a1?from=elsewhere").attemptOrigin, null);
});

// 换事项范围时请求详情不再留在详情上（它的内容属于某一个请求），回到请求所在的列表：
// 设置页的「模型请求与用量」那一节，筛选跟着留着。
test("在请求详情上切事项范围：回到设置页这一节，筛选跟着留着", () => {
  const route = parseRoute("#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&status=failed");
  assert.equal(route.name, "observe-detail");
  assert.equal(withScope(route, "w2"), "#/p/demo/settings?w=w2&section=requests&dept=engineering&status=failed");
});

// 工单 #1715：恢复详情清掉范围（原来那个页面收进对话以后没有概览页可回）时回到对话页；
// 换一个范围时按新的事项打开同一页。
test("在恢复详情上清掉范围：回到对话页；换范围时按新事项打开", () => {
  const route = parseRoute("#/p/demo/w/w1/recovery");
  assert.equal(route.name, "recovery");
  assert.equal(withScope(route, "w2"), "#/p/demo/w/w2/recovery");
  assert.equal(withScope(route, null), "#/p/demo/conversation");
});

// 职能详情（工单 #1713）：从节点面板的「职能详情」进，路径上写职能名，事项范围写在 ?w= 里；
// 关闭回到同一事项的对话页，切事项范围时仍留在这个职能上。
test("职能详情的地址往返：路径上写职能名，事项范围写在 ?w= 里", () => {
  assert.equal(paths.departmentDetail("demo", "engineering"), "#/p/demo/dept-detail/engineering");
  const hash = paths.departmentDetail("demo", "engineering", { workItem: "w1" });
  assert.equal(hash, "#/p/demo/dept-detail/engineering?w=w1");
  const route = parseRoute(hash);
  assert.equal(route.name, "dept-detail");
  assert.equal(route.projectId, "demo");
  assert.equal(route.department, "engineering");
  assert.equal(route.workItemId, "w1");
  // 自己加的职能同样进得去：路径上就是组织里的那个标识
  assert.equal(parseRoute(paths.departmentDetail("demo", "analysis")).department, "analysis");
  // 职能名照旧译成中文，路径上仍写标识
  assert.equal(pathLabel(route, [{ project_id: "demo", name: "演示项目" }]), "演示项目 / 工程");
  // 关闭回到同一事项的对话页；切事项范围仍留在这个职能上
  assert.equal(paths.conversation("demo", { workItem: "w1" }), "#/p/demo/conversation?w=w1");
  assert.equal(withScope(route, "w2"), "#/p/demo/dept-detail/engineering?w=w2");
});

// 工单 #1745（保护 R2）：对话页路径支持可选的回放位置参数 at，未传入或非法值时省略；
// 对话页地址与画面的概览回链地址均解析到对话页，同时保留事项标识与事件位置。
test("对话页路径支持可选位置参数，概览与对话回链均解析到对话页并保留事项与位置", () => {
  assert.equal(paths.conversation("demo"), "#/p/demo/conversation");
  assert.equal(paths.conversation("demo", { workItem: "w1", at: null }), "#/p/demo/conversation?w=w1");
  assert.equal(paths.conversation("demo", { workItem: "w1", at: undefined }), "#/p/demo/conversation?w=w1");
  assert.equal(paths.conversation("demo", { workItem: "w1", at: -1 }), "#/p/demo/conversation?w=w1");
  assert.equal(paths.conversation("demo", { workItem: "w1", at: 1.5 }), "#/p/demo/conversation?w=w1");
  assert.equal(paths.conversation("demo", { at: 0 }), "#/p/demo/conversation?at=0");
  assert.equal(paths.conversation("demo", { workItem: "w1", at: 2 }), "#/p/demo/conversation?w=w1&at=2");

  const fromConversation = parseRoute("#/p/demo/conversation?at=2&w=w1");
  assert.equal(fromConversation.name, "conversation");
  assert.equal(fromConversation.projectId, "demo");
  assert.equal(fromConversation.workItemId, "w1");
  assert.equal(fromConversation.at, 2);

  const fromOverview = parseRoute("#/p/demo/overview?at=2&w=w1");
  assert.equal(fromOverview.name, "conversation");
  assert.equal(fromOverview.projectId, "demo");
  assert.equal(fromOverview.workItemId, "w1");
  assert.equal(fromOverview.at, 2);

  const projectOnly = parseRoute("#/p/demo/overview?at=2");
  assert.equal(projectOnly.name, "conversation");
  assert.equal(projectOnly.projectId, "demo");
  assert.equal(projectOnly.workItemId, null);
  assert.equal(projectOnly.at, 2);
});

