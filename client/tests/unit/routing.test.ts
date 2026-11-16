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

test("旧页地址兼容解析：overview/dept 落到对话，materials 落到成果库，observe 与 settings?section=requests 落到事项与用量请求子视图", () => {
  for (const page of ["overview"]) {
    const route = parseRoute(`#/p/demo/${page}?w=w1&at=3&arrow=flow-1`);
    assert.equal(route.name, "conversation");
    assert.equal(route.workItemId, "w1");
    assert.equal(route.at, 3);
    assert.equal(route.arrowFlowId, "flow-1");
    assert.equal(parseRoute(`#/p/demo/${page}`).name, "conversation");
  }
  const materials = parseRoute("#/p/demo/materials?w=w1");
  assert.equal(materials.name, "outcomes");
  assert.equal(materials.workItemId, "w1");
  assert.equal(parseRoute("#/p/demo/materials").name, "outcomes");

  const observeList = parseRoute("#/p/demo/observe?w=w1&dept=engineering&status=failed");
  assert.equal(observeList.name, "items");
  assert.equal(observeList.itemsTab, "requests");
  assert.equal(observeList.workItemId, "w1");
  assert.equal(observeList.requestFilters.department, "engineering");
  assert.equal(observeList.requestFilters.status, "failed");

  const legacySettingsRequests = parseRoute("#/p/demo/settings?w=w1&section=requests&dept=quality&status=failed");
  assert.equal(legacySettingsRequests.name, "items");
  assert.equal(legacySettingsRequests.itemsTab, "requests");
  assert.equal(legacySettingsRequests.settingsSection, null);
  assert.equal(legacySettingsRequests.workItemId, "w1");
  assert.equal(legacySettingsRequests.requestFilters.department, "quality");
  assert.equal(legacySettingsRequests.requestFilters.status, "failed");

  // 职能页（路径上写部门名的那种）落到对话，保留地址里的事项
  const dept = parseRoute("#/p/demo/dept/product?w=w1");
  assert.equal(dept.name, "conversation");
  assert.equal(dept.department, "product");
  assert.equal(dept.workItemId, "w1");
  // 详情页的地址照旧可用（工单 #1713、#1710）
  assert.equal(parseRoute("#/p/demo/dept-detail/engineering?w=w1").name, "dept-detail");
  assert.equal(parseRoute("#/p/demo/observe/a1?w=w1").name, "observe-detail");
  assert.equal(parseRoute("#/p/demo/w/w1/recovery").name, "recovery");
});

// 工单 #1809（保护 R2）：五个一级标签页「对话 · 成果库 · 组织 · 事项与用量 · 设置」，全部保留 ?w=。
test("项目页的一级标签页为五个，按顺序给出并保留事项范围", () => {
  assert.deepEqual(projectTabs("demo", null), [
    { label: "对话", hash: "#/p/demo/conversation", query: "project.loop" },
    { label: "成果库", hash: "#/p/demo/outcomes", query: "project.overview" },
    { label: "组织", hash: "#/p/demo/org", query: "project.organization" },
    { label: "事项与用量", hash: "#/p/demo/items", query: "project.overview" },
    { label: "设置", hash: "#/p/demo/settings", query: "project.settings" },
  ]);
  assert.deepEqual(projectTabs("demo", "w1"), [
    { label: "对话", hash: "#/p/demo/conversation?w=w1", query: "project.loop" },
    { label: "成果库", hash: "#/p/demo/outcomes?w=w1", query: "project.overview" },
    { label: "组织", hash: "#/p/demo/org?w=w1", query: "project.organization" },
    { label: "事项与用量", hash: "#/p/demo/items?w=w1", query: "project.overview" },
    { label: "设置", hash: "#/p/demo/settings?w=w1", query: "project.settings" },
  ]);
  // 空的范围与没有范围一样，不拼一个 ?w=
  assert.equal(projectTabs("demo", "")[0].hash, "#/p/demo/conversation");
  assert.equal(projectTabs("demo", "")[3].hash, "#/p/demo/items");
});

// 「事项与用量」页的「模型请求与用量」子视图（工单 #1710、#1809）：子视图（tab=requests）与筛选条件
// 都写在地址里，刷新、后退、分享与从请求详情返回都读得回；默认事项列表不写 tab，筛选为空时不写键。
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

test("事项与用量页的子视图与筛选写在地址里，地址读回来是同一组", () => {
  assert.equal(paths.outcomes("demo", { workItem: "w1" }), "#/p/demo/outcomes?w=w1");
  assert.equal(paths.org("demo", { workItem: "w1" }), "#/p/demo/org?w=w1");
  assert.equal(paths.items("demo", { workItem: "w1", tab: "items" }), "#/p/demo/items?w=w1");

  const hash = paths.items("demo", { workItem: "w1", tab: "requests", requests: requestFilters() });
  assert.equal(
    hash,
    "#/p/demo/items?w=w1&tab=requests&dept=engineering&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc",
  );
  const route = parseRoute(hash);
  assert.equal(route.name, "items");
  assert.equal(route.workItemId, "w1");
  assert.equal(route.itemsTab, "requests");
  assert.equal(route.departmentFilter, "engineering");
  assert.deepEqual(route.requestFilters, requestFilters());
  // 默认事项列表不写 tab，没有筛选时不写空的键
  assert.equal(paths.items("demo", { workItem: "w1", requests: EMPTY_FILTERS }), "#/p/demo/items?w=w1");
  assert.equal(parseRoute("#/p/demo/items").itemsTab, "items");
  assert.equal(pathLabel(parseRoute("#/p/demo/outcomes"), [{ project_id: "demo", name: "演示项目" }]), "演示项目 / 成果库");
  assert.equal(pathLabel(parseRoute("#/p/demo/org"), [{ project_id: "demo", name: "演示项目" }]), "演示项目 / 组织");
  assert.equal(pathLabel(route, [{ project_id: "demo", name: "演示项目" }]), "演示项目 / 事项与用量");
});

test("地址里带项目职能清单里有、默认三个里没有的职能时筛选生效", () => {
  const route = parseRoute("#/p/demo/items?tab=requests&dept=analysis");
  assert.equal(route.name, "items");
  assert.equal(route.itemsTab, "requests");
  assert.equal(route.departmentFilter, "analysis");
  assert.equal(route.requestFilters.department, "analysis");
});

test("在成果库、组织与事项与用量页切事项范围保留当前页与子视图参数", () => {
  assert.equal(withScope(parseRoute("#/p/demo/outcomes?w=w1"), "w2"), "#/p/demo/outcomes?w=w2");
  assert.equal(withScope(parseRoute("#/p/demo/org?w=w1"), "w2"), "#/p/demo/org?w=w2");
  assert.equal(withScope(parseRoute("#/p/demo/items?w=w1"), "w2"), "#/p/demo/items?w=w2");
  const route = parseRoute("#/p/demo/items?tab=requests&dept=engineering&status=failed");
  assert.equal(withScope(route, "w2"), "#/p/demo/items?w=w2&tab=requests&dept=engineering&status=failed");
});

test("从事项与用量的请求列表进请求详情：返回到这一子视图，保持筛选", () => {
  const hash = paths.observeDetail("demo", "a1", {
    workItem: "w1", runId: "r1", department: "engineering", from: "items", requests: requestFilters(),
  });
  assert.equal(
    hash,
    "#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&from=items&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc",
  );
  const route = parseRoute(hash);
  assert.equal(route.name, "observe-detail");
  assert.equal(route.attemptOrigin, "items");
  assert.deepEqual(route.requestFilters, requestFilters());
  const back = attemptBackPath(route);
  assert.equal(back.label, "返回模型请求与用量");
  assert.equal(back.hash, "#/p/demo/items?w=w1&tab=requests&dept=engineering&status=failed&provider=proxy-a&model=gpt-5&model_returned=gpt-5-mini&q=abc");

  // 旧链接 ?from=settings 兼容折算为 "items"
  const legacy = parseRoute("#/p/demo/observe/a1?w=w1&from=settings");
  assert.equal(legacy.attemptOrigin, "items");
  assert.equal(attemptBackPath(legacy).hash, "#/p/demo/items?w=w1&tab=requests");
});

test("从工作过程进请求详情：返回到同一事项的对话页", () => {
  const hash = paths.observeDetail("demo", "a1", { workItem: "w1", runId: "r1", department: "engineering", from: "conversation" });
  assert.equal(hash, "#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&from=conversation");
  const back = attemptBackPath(parseRoute(hash));
  assert.equal(back.label, "返回对话");
  assert.equal(back.hash, "#/p/demo/conversation?w=w1");
});

// 工单 #1715、#1809：直接输入请求详情地址时，回到「事项与用量」的「模型请求与用量」子视图。
test("直接输入请求详情地址：返回事项与用量页的「模型请求与用量」子视图", () => {
  const route = parseRoute("#/p/demo/observe/a1?w=w1&r=r1&dept=engineering");
  assert.equal(route.attemptOrigin, null);
  const back = attemptBackPath(route);
  assert.equal(back.label, "返回模型请求与用量");
  assert.equal(back.hash, "#/p/demo/items?w=w1&tab=requests&dept=engineering");
  // 认不出的来处按没有来处处理，不当成事项列表或对话页
  assert.equal(parseRoute("#/p/demo/observe/a1?from=elsewhere").attemptOrigin, null);
});

// 换事项范围时请求详情不再留在详情上（它的内容属于某一个请求），回到「事项与用量」页的「模型请求与用量」子视图，筛选跟着留着。
test("在请求详情上切事项范围：回到模型请求与用量子视图，筛选跟着留着", () => {
  const route = parseRoute("#/p/demo/observe/a1?w=w1&r=r1&dept=engineering&status=failed");
  assert.equal(route.name, "observe-detail");
  assert.equal(withScope(route, "w2"), "#/p/demo/items?w=w2&tab=requests&dept=engineering&status=failed");
});

// 工单 #1715：恢复详情清掉范围时回到对话页；换一个范围时按新的事项打开同一页。
test("在恢复详情上清掉范围：回到对话页；换范围时按新事项打开", () => {
  const route = parseRoute("#/p/demo/w/w1/recovery");
  assert.equal(route.name, "recovery");
  assert.equal(withScope(route, "w2"), "#/p/demo/w/w2/recovery");
  assert.equal(withScope(route, null), "#/p/demo/conversation");
});

// 职能详情（工单 #1713、#1809）：路径上写职能名，事项范围写在 ?w= 里，来处写在 ?from= 里；
// 切事项范围时仍留在这个职能并保留来处；对话页的 ?arrow= 参数也可往返解析。
test("职能详情的地址往返：路径上写职能名，事项范围写在 ?w= 里，来处写在 ?from= 里", () => {
  assert.equal(paths.departmentDetail("demo", "engineering"), "#/p/demo/dept-detail/engineering");
  const hash = paths.departmentDetail("demo", "engineering", { workItem: "w1", from: "org" });
  assert.equal(hash, "#/p/demo/dept-detail/engineering?w=w1&from=org");
  const route = parseRoute(hash);
  assert.equal(route.name, "dept-detail");
  assert.equal(route.projectId, "demo");
  assert.equal(route.department, "engineering");
  assert.equal(route.workItemId, "w1");
  assert.equal(route.departmentOrigin, "org");
  assert.equal(route.attemptOrigin, null);
  // 自己加的职能同样进得去：路径上就是组织里的那个标识
  assert.equal(parseRoute(paths.departmentDetail("demo", "analysis")).department, "analysis");
  // 职能名照旧译成中文，路径上仍写标识
  assert.equal(pathLabel(route, [{ project_id: "demo", name: "演示项目" }]), "演示项目 / 工程");
  // 切事项范围仍留在这个职能并保留 ?from=org
  assert.equal(withScope(route, "w2"), "#/p/demo/dept-detail/engineering?w=w2&from=org");
  assert.equal(parseRoute(paths.departmentDetail("demo", "engineering", { from: "conversation" })).departmentOrigin, "conversation");
  assert.equal(parseRoute("#/p/demo/dept-detail/engineering?from=other").departmentOrigin, null);

  // 对话页 ?arrow= 参数往返
  const withArrow = paths.conversation("demo", { workItem: "w1", arrow: "flow-9" });
  assert.equal(withArrow, "#/p/demo/conversation?w=w1&arrow=flow-9");
  assert.equal(parseRoute(withArrow).arrowFlowId, "flow-9");
  assert.equal(parseRoute("#/p/demo/conversation?arrow=").arrowFlowId, null);
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

// 工单 #1806（保护 R2）：独立新建与接入已有项目页使用规范路径 #/projects/new 与 #/projects/onboard，
// 同时兼容解析 #/new 与 #/onboard；顶栏路径直接写页名，不拼项目前缀。
test("独立新建与接入已有项目页的路径生成、兼容解析与顶栏路径名", () => {
  assert.equal(paths.newProject(), "#/projects/new");
  assert.equal(paths.onboardProject(), "#/projects/onboard");

  for (const hash of ["#/projects/new", "#/projects/new/", "#/new", "#/new?from=home"]) {
    const route = parseRoute(hash);
    assert.equal(route.name, "new-project");
    assert.equal(route.projectId, null);
    assert.equal(pathLabel(route, [{ project_id: "demo", name: "演示项目" }]), "从想法新建项目");
  }

  for (const hash of ["#/projects/onboard", "#/projects/onboard/", "#/onboard"]) {
    const route = parseRoute(hash);
    assert.equal(route.name, "onboard-project");
    assert.equal(route.projectId, null);
    assert.equal(pathLabel(route, [{ project_id: "demo", name: "演示项目" }]), "接入已有项目");
  }

  assert.equal(parseRoute("#/projects/other").name, "not-found");
  assert.equal(parseRoute("#/projects/new/extra").name, "not-found");
});

