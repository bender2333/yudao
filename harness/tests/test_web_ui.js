const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "web", "static");
const APP_JS = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const CONTEXT_JS = fs.readFileSync(path.join(staticDir, "context-view.js"), "utf8");
const TRACE_JS = fs.readFileSync(path.join(staticDir, "trace-view.js"), "utf8");
const INDEX_HTML = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const STYLES_CSS = fs.readFileSync(path.join(staticDir, "styles.css"), "utf8");

function applyLocation(location, url) {
  const parsed = new URL(String(url || "/"), "http://local");
  location.pathname = parsed.pathname;
  location.search = parsed.search;
  location.hash = parsed.hash;
  location.href = parsed.href;
}

function loadApp(fetchImpl = async () => ({ ok: true, status: 200, statusText: "OK", async text() { return "{}"; } }), document = { getElementById() { return null; } }) {
  const location = { pathname: "/", search: "", hash: "", href: "http://local/" };
  const history = {
    pushState(_state, _title, url) { applyLocation(location, url); },
    replaceState(_state, _title, url) { applyLocation(location, url); },
  };
  const sandbox = {
    console,
    document,
    fetch: fetchImpl,
    URLSearchParams,
    URL,
    Promise,
    Map,
    Set,
    JSON,
    Error,
    Number,
    String,
    Array,
    Object,
    Math,
    Date,
    encodeURIComponent,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    location,
    history,
    EventSource: undefined,
    __HARNESS_SKIP_BOOT__: true,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CONTEXT_JS, sandbox);
  vm.runInContext(TRACE_JS, sandbox);
  vm.runInContext(APP_JS, sandbox);
  sandbox.harnessWeb.location = location;
  return sandbox.harnessWeb;
}

function node(id, extra = {}) {
  const listeners = {};
  const result = {
    id,
    value: "",
    hidden: false,
    disabled: false,
    innerHTML: "",
    textContent: "",
    dataset: {},
    elements: {},
    children: [],
    className: "",
    addEventListener(type, callback) { (listeners[type] ||= []).push(callback); },
    async dispatch(type, event = {}) { for (const callback of listeners[type] || []) await callback({ target: result, currentTarget: result, ...event }); },
    querySelector(selector) {
      if (selector === "button[value='default']") return result.submitButton || null;
      return result.queryNode || null;
    },
    querySelectorAll() { return []; },
    replaceChildren(...children) { result.children = children; result.innerHTML = ""; },
    appendChild(child) { result.children.push(child); return child; },
    showModal() { result.open = true; },
    close() { result.open = false; },
    focus() { result.focused = true; },
    setAttribute() {},
    getAttribute() { return null; },
    contains() { return true; },
    classList: { toggle() {}, add() {}, remove() {} },
    ...extra,
  };
  return result;
}

function uiDocument() {
  const ids = [
    "yudao-workbench", "yp-shell", "yp-sidebar", "yp-topbar",
    "department-workspace-prototype", "dw-main",
    "yp-project-dialog", "yp-project-dialog-form", "yp-project-name", "yp-project-goal", "yp-project-submit", "yp-project-error",
    "dw-prompt-dialog", "dw-prompt-dialog-form", "dw-prompt-text", "dw-prompt-error", "dw-prompt-meta", "dw-prompt-default", "dw-prompt-restore",
    "dw-event-dialog", "dw-event-title", "dw-event-version", "dw-event-files", "dw-event-document", "dw-event-json", "dw-event-sources",
    "yp-rename-dialog", "yp-rename-dialog-form", "yp-rename-name", "yp-rename-error",
  ];
  const nodes = new Map(ids.map(id => [id, node(id)]));
  const root = nodes.get("department-workspace-prototype");
  const workbench = nodes.get("yudao-workbench");
  const observationContent = node("dw-observation-content");
  nodes.set("dw-observation-content", observationContent);
  const query = selector => {
    if (selector === ".dw-action-error") return node("dw-action-error");
    if (selector === "#dw-observation-content") return observationContent;
    return null;
  };
  root.querySelector = query;
  workbench.querySelector = query;
  workbench.querySelectorAll = () => [];
  const projectForm = nodes.get("yp-project-dialog-form");
  projectForm.elements = { name: nodes.get("yp-project-name"), goal: nodes.get("yp-project-goal") };
  const promptDialog = nodes.get("dw-prompt-dialog");
  const promptForm = nodes.get("dw-prompt-dialog-form");
  const promptText = nodes.get("dw-prompt-text");
  promptDialog.submitButton = node("prompt-submit");
  promptForm.elements = { text: promptText };
  promptDialog.querySelector = selector => selector === "button[value='default']" ? promptDialog.submitButton : null;
  const document = {
    documentElement: { scrollTop: 0 },
    activeElement: null,
    getElementById(id) { return nodes.get(id) || null; },
    createElement(tag) { return node(tag, { tagName: tag, href: "", download: "" }); },
  };
  return { document, nodes };
}

function pageHtml(nodes) {
  return `${nodes.get("dw-main").innerHTML}${nodes.get("dw-observation-content")?.innerHTML || ""}`;
}

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Bad Request",
    async text() { return JSON.stringify(payload); },
  };
}

function sampleProject(id = "proj_a", extras = {}) {
  return {
    project_id: id,
    name: extras.name || "Echo",
    goal: extras.goal || "长期目标",
    archived: false,
    pinned: false,
    work_items: extras.work_items || [],
    active_work_item_id: extras.active_work_item_id || null,
    current_adoption: extras.current_adoption || null,
    materials: extras.materials || [],
    overview: { pending: [], recent: [] },
    prompt_configs: {},
    ...extras,
  };
}

test("production shell uses third-version chrome and local Lucide bundle", () => {
  assert.match(INDEX_HTML, /id="yudao-workbench"/);
  assert.match(INDEX_HTML, /id="department-workspace-prototype"/);
  assert.match(INDEX_HTML, /class="yp-shell"/);
  assert.match(INDEX_HTML, /id="yp-project-dialog-form"/);
  assert.match(INDEX_HTML, /src="\/static\/app\.js"/);
  assert.match(INDEX_HTML, /src="\/static\/provider-config\.js"/);
  assert.doesNotMatch(INDEX_HTML, /department-workspace-preview|iframe/);
  assert.doesNotMatch(INDEX_HTML, /id="dw-task-dialog"/);
});

test("visual contract tokens remain for department internals and third-version chrome", () => {
  for (const token of ["--dw-accent", "--dw-background", "--dw-inspector-width", "--dw-border", "--dw-amber", "--dw-red"]) {
    assert.match(STYLES_CSS, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(STYLES_CSS, /grid-template-columns: 68px minmax\(0, 1fr\)/);
  assert.match(STYLES_CSS, /grid-template-columns: 218px minmax\(0, 1fr\)/);
  assert.match(STYLES_CSS, /@media \(max-width: 760px\)/);
  assert.match(STYLES_CSS, /@media \(max-width: 430px\)/);
  assert.match(STYLES_CSS, /#yudao-workbench/);
});

test("department room uses the v5 stage and keeps real guidance contracts", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    name: "货物装载",
    active_work_item_id: "wi_1",
    work_items: [{ work_item_id: "wi_1", title: "实现导出", run_id: "run_1", status: "in_progress", department: "engineering" }],
  });
  web.state.department = "engineering";
  web.state.workItemId = "wi_1";
  web.state.runId = "run_1";
  web.state.runPayload = { board: { phase: "ENGINEERING", task: "实现导出", active_department: "engineering" } };
  web.state.departmentData.set("run_1/engineering", {
    department: "engineering",
    status: "running",
    messages: [{ source: "工程", text: "正在读取计划", created_at: "2026-09-22T02:00:00Z", event_id: "evt_1" }],
    provider: { provider: "opencode-go", model: "glm-5.1", protocol: "chat_completions" },
    guidance: [],
  });
  web.renderDepartment("engineering");
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /pixel-room-boundary/);
  assert.match(html, /crt-monitor-board/);
  assert.match(html, /glm-5\.1/);
  assert.match(html, /id="dw-dept-form"/);
  assert.match(html, /data-dept-draft="engineering"/);
  assert.match(html, /发送指导/);
  assert.match(html, /data-prompt-edit="engineering"/);
  assert.match(html, /data-work-scope/);
  assert.match(html, /data-inspector-tab="context"/);
  assert.doesNotMatch(html, /派发协作者|SubAgent|动作步进/);
  assert.doesNotMatch(html, /class="dw-inspector /);
});

test("overview leads with handoffs and keeps the idle composer", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    overview: { pending: [], recent: [{ title: "工程 → 产品", summary: "需要产品明确", at: "2026-09-22T02:00:00Z", status: "等待决定" }] },
  });
  web.state.overviewPane = "handoffs";
  web.renderOverview();
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /跨部门流转交接/);
  assert.match(html, /工程 → 产品/);
  assert.match(html, /作为新事项开始/);
  assert.doesNotMatch(html, /class="yp-board"/);
});

test("UI source contains no prototype sample state and keeps D-H plus guidance controls", () => {
  assert.doesNotMatch(APP_JS, /const modelRequests\s*=\s*\[/);
  assert.doesNotMatch(APP_JS, /new Tweak|globalThis\.Tweak/);
  assert.doesNotMatch(APP_JS, /示例 Provider|orion-2\.1-pro|attempt-7F3A/);
  assert.doesNotMatch(APP_JS, /fetchJSON\("\/api\/runs", \{ method: "POST"/);
  assert.match(APP_JS, /data-dept-draft/);
  assert.match(APP_JS, /作为新事项开始/);
  assert.match(APP_JS, /记录原文/);
  assert.match(APP_JS, /发送指导/);
});

test("provider config is a top-bar page and not project Prompt settings", () => {
  const configJs = fs.readFileSync(path.join(staticDir, "provider-config.js"), "utf8");
  assert.match(APP_JS, /data-action="providers"/);
  assert.match(APP_JS, /模型与 Provider/);
  assert.match(configJs, /三部门绑定/);
  assert.match(configJs, /\/api\/providers/);
  assert.match(configJs, /\/api\/department-bindings/);
  assert.match(STYLES_CSS, /yp-provider-row/);
  assert.match(STYLES_CSS, /@media \(max-width: 720px\)/);
  const settings = APP_JS.slice(APP_JS.indexOf("function settingsMarkup"), APP_JS.indexOf("function overviewComposer"));
  assert.doesNotMatch(settings, /模型与 Provider/);
  assert.doesNotMatch(settings, /data-action="providers"/);
});


test("project list selection updates route without calling POST /api/runs", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/projects") return response({ projects: [{ project_id: "proj_a", name: "A" }, { project_id: "proj_b", name: "B" }] });
    if (url === "/api/projects/proj_b") return response(sampleProject("proj_b", { name: "B" }));
    if (url === "/api/health") return response({ ok: true, busy: false });
    return response({});
  }, document);
  web.state.projects = [{ project_id: "proj_a", name: "A" }, { project_id: "proj_b", name: "B" }];
  await web.activateProject("proj_b", { push: true });
  assert.equal(web.state.projectId, "proj_b");
  assert.match(web.location.search, /project=proj_b/);
  assert.equal(calls.some(item => item[0] === "/api/runs" && item[1]?.method === "POST"), false);
  assert.match(nodes.get("dw-main").innerHTML, /B/);
});

test("D-H idle composer offers start work item and record material", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (String(url).endsWith("/work-items") && options.method === "POST") return response({ work_item_id: "wi_1", run_id: "run_1", phase: "PRODUCT_SPEC" }, 201);
    if (String(url).endsWith("/materials") && options.method === "POST") return response({ material_id: "mat_1" }, 201);
    if (url === "/api/projects/proj_a") return response(sampleProject("proj_a"));
    if (url === "/api/projects") return response({ projects: [{ project_id: "proj_a", name: "Echo" }] });
    return response({});
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.renderOverview();
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /作为新事项开始/);
  assert.match(html, /记录原文/);
  assert.doesNotMatch(html, /发送指导/);
  const form = { querySelector: () => ({ value: "  新事项  " }), dataset: {} };
  web.state._dhAction = "start";
  await web.addGlobalInput(form);
  assert.equal(calls[0][0], "/api/projects/proj_a/work-items");
  assert.equal(JSON.parse(calls[0][1].body).text, "新事项");
  web.state.project = sampleProject("proj_a");
  web.state.creating = false;
  web.state._dhAction = "record";
  await web.addGlobalInput({ querySelector: () => ({ value: "备忘" }), dataset: {} });
  assert.equal(calls.some(item => String(item[0]).endsWith("/materials")), true);
});

test("department drafts are isolated by project scope and work item", () => {
  const web = loadApp();
  web.state.projectId = "proj_a";
  web.state.department = "product";
  web.state.workItemId = null;
  const projectKey = web.deptDraftKey("product");
  web.state.workItemId = "wi_1";
  const itemKey = web.deptDraftKey("product");
  assert.equal(projectKey, "proj_a/product/project");
  assert.equal(itemKey, "proj_a/product/wi_1");
  assert.notEqual(projectKey, itemKey);
  web.state.deptDrafts[projectKey] = "项目草稿";
  web.state.deptDrafts[itemKey] = "事项草稿";
  web.state.workItemId = null;
  assert.equal(web.state.deptDrafts[web.deptDraftKey("product")], "项目草稿");
  web.state.workItemId = "wi_1";
  assert.equal(web.state.deptDrafts[web.deptDraftKey("product")], "事项草稿");
});

test("Prompt save uses project PUT with base_version and keeps draft on blank or conflict", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (options.method === "PUT" && String(url).includes("/prompts/product")) {
      const body = JSON.parse(options.body);
      if (!String(body.text || "").trim()) return response({ error: "text is blank" }, 400);
      if (body.base_version === 0 && body.text === "same") return response({ department: "product", text: "same", version: 0, unchanged: true, default_text: "DEFAULT", source: "default" });
      if (body.base_version === 0) return response({ error: "conflict", reason: "prompt_config_conflict", current: { department: "product", text: "server", version: 2, default_text: "DEFAULT", source: "configured" } }, 409);
      return response({ department: "product", text: body.text, version: 1, unchanged: false, default_text: "DEFAULT", source: "configured" });
    }
    return response({});
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.promptConfigs.product = { department: "product", text: "old", version: 0, default_text: "DEFAULT", source: "default" };
  web.openPromptDialog("product");
  const dialog = nodes.get("dw-prompt-dialog");
  assert.equal(dialog.open, true);
  nodes.get("dw-prompt-text").value = "   ";
  await web.savePrompt({ preventDefault() {}, submitter: { value: "default" } });
  assert.equal(nodes.get("dw-prompt-error").hidden, false);
  assert.equal(calls.length, 0);
  nodes.get("dw-prompt-text").value = "new prompt";
  await web.savePrompt({ preventDefault() {}, submitter: { value: "default" } });
  assert.equal(calls[0][1].method, "PUT");
  assert.deepEqual(JSON.parse(calls[0][1].body), { text: "new prompt", base_version: 0 });
  assert.equal(web.state.promptDrafts["proj_a/product"], "new prompt");
  assert.match(nodes.get("dw-prompt-error").textContent, /conflict|department prompt|配置/);
});

test("observation return restores department scope inspector snapshot drafts and scroll", () => {
  const { document } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.view = "department";
  web.state.department = "engineering";
  web.state.workItemId = "wi_1";
  web.state.inspectorTab = "prompt";
  web.state.deptDrafts["proj_a/engineering/wi_1"] = "keep draft";
  web.state.selectedContext["run_1/engineering"] = "ctx-9";
  web.state.runId = "run_1";
  const snap = web.snapshotReturn();
  web.state.view = "observability";
  web.state.department = "product";
  web.state.workItemId = null;
  web.state.inspectorTab = "context";
  web.applyReturn(snap);
  assert.equal(web.state.view, "department");
  assert.equal(web.state.department, "engineering");
  assert.equal(web.state.workItemId, "wi_1");
  assert.equal(web.state.inspectorTab, "prompt");
  assert.equal(web.state.deptDrafts["proj_a/engineering/wi_1"], "keep draft");
  assert.equal(web.state.selectedContext["run_1/engineering"], "ctx-9");
});

test("popstate does not leak project data across projects", async () => {
  const { document } = uiDocument();
  const web = loadApp(async url => {
    if (url === "/api/projects/proj_b") return response(sampleProject("proj_b", { name: "Other", work_items: [{ work_item_id: "wi_b", title: "B item", run_id: "run_b", status: "stopped" }] }));
    return response(sampleProject("proj_a", { name: "Echo" }));
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", { name: "Echo" });
  web.state.departmentData.set("run_a/product", { messages: [{ text: "secret-a" }] });
  web.state.runPayload = { board: { task: "secret-a" } };
  web.location.search = "?project=proj_b&view=overview";
  await web.handlePopState();
  assert.equal(web.state.projectId, "proj_b");
  assert.equal(web.state.project.name, "Other");
  assert.equal(web.state.departmentData.size, 0);
  assert.equal(web.state.runPayload, null);
});

test("terminal work item does not auto-create a new run", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    return response({ board: { run_id: "run_done", task: "done", phase: "DONE" }, timeline: {}, evidence: {}, inputs: [], events: [] });
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    work_items: [{ work_item_id: "wi_done", title: "已结束", run_id: "run_done", status: "stopped", phase: "DONE" }],
  });
  web.state.workItemId = "wi_done";
  web.state.runId = "run_done";
  web.state.runPayload = { board: { run_id: "run_done", task: "done", phase: "DONE", active_department: "product" }, timeline: {}, evidence: {}, inputs: [], events: [] };
  web.renderOverview();
  assert.match(nodes.get("dw-main").innerHTML, /作为新事项开始|还没有|无/);
  assert.equal(calls.some(item => String(item[0]).includes("/work-items") && item[1]?.method === "POST"), false);
});

test("model attempt and usage queries use the project cursor contract and preserve nulls", async () => {
  const calls = [];
  const web = loadApp(async (url) => {
    calls.push(url);
    if (String(url).includes("/model-attempts")) return response({ items: [{ id: "attempt-1", status: "failed", usage: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null, latency_ms: 0 } }], total: 1, next_cursor: null });
    return response({ total_attempts: 1, reported_attempts: 0, totals: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null }, groups: { departments: [], models: [] } });
  });
  web.state.projectId = "proj_a";
  web.state.routeToken = 1;
  await web.loadObservationData();
  assert.match(calls[0], /^\/api\/projects\/proj_a\/model-attempts\?limit=50$/);
  assert.match(calls[1], /^\/api\/projects\/proj_a\/model-usage$/);
  assert.equal(web.state.observationData.items[0].usage.input_tokens, null);
  assert.equal(web.state.usageData.totals.total_tokens, null);
  assert.doesNotMatch(calls.join("\n"), /page=|page_size=|request_id=/);
});

test("observation cursor pagination appends records while usage keeps the complete filter", async () => {
  const calls = [];
  const web = loadApp(async url => {
    calls.push(url);
    if (String(url).includes("cursor=")) return response({ items: [{ id: "a2" }], total: 2, next_cursor: null });
    if (String(url).includes("/model-attempts")) return response({ items: [{ id: "a1" }], total: 2, next_cursor: "c1" });
    return response({ totals: {}, coverage: {} });
  });
  web.state.projectId = "proj_a";
  web.state.routeToken = 1;
  await web.loadObservationData();
  await web.loadObservationData({ append: true });
  assert.equal(web.state.observationData.items.map(item => item.id).join(","), "a1,a2");
  assert.ok(calls.some(url => String(url).includes("cursor=")));
});

test("fetchJSON reports API failures without exposing raw stale UI state", async () => {
  const web = loadApp(async () => response({ error: "provider unavailable" }, 503));
  await assert.rejects(() => web.fetchJSON("/api/projects"), error => {
    assert.equal(error.status, 503);
    assert.equal(error.message, "provider unavailable");
    return true;
  });
});

test("HTTP 200 with non-JSON body fails explicitly", async () => {
  const web = loadApp(async () => ({ ok: true, status: 200, statusText: "OK", async text() { return "not-json"; } }));
  await assert.rejects(() => web.fetchJSON("/api/projects"), /响应不是有效 JSON/);
});

test("department context link is bound to the selected context attempt id", () => {
  const web = loadApp();
  web.state.runId = "run-a";
  web.state.projectId = "proj_a";
  const html = web.contextMarkup("engineering", { contexts: [{ id: "attempt-9", title: "工作输入", purpose: "work" }] });
  assert.match(html, /data-observe-attempt="attempt-9"/);
});

test("raw request and response rendering uses text-safe JSON serialization", () => {
  const web = loadApp();
  assert.match(web.escapeHtml("<x>"), /&lt;x&gt;/);
});

test("department guidance labels distinguish explanation from verified action", () => {
  const web = loadApp();
  const html = web.usageMarkup && APP_JS;
  assert.match(APP_JS, /已解释/);
  assert.match(APP_JS, /动作已核实/);
});

test("department context renders its own attempt id and exposes guidance controls", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    active_work_item_id: "wi_1",
    work_items: [{ work_item_id: "wi_1", title: "进行中", run_id: "run-a", status: "in_progress", department: "engineering", phase: "ENGINEERING" }],
  });
  web.state.runId = "run-a";
  web.state.workItemId = "wi_1";
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING" }, timeline: {}, evidence: {}, inputs: [], events: [] };
  web.state.departmentData.set("run-a/engineering", { run_id: "run-a", department: "engineering", guidance: [], contexts: [{ id: "ctx-1", title: "工作输入", purpose: "work" }], messages: [], history: {}, materials: {}, provider: {}, prompt: null, status: "running" });
  web.renderDepartment("engineering");
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /data-dept-draft="engineering"/);
  assert.match(html, /发送指导/);
  assert.match(html, /data-context-id="ctx-1"/);
});

test("department guidance posts to the captured run and keeps the draft scoped", async () => {
  const calls = [];
  const { document } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url.endsWith("/departments/engineering")) return response({ run_id: "run-a", department: "engineering", guidance: [], contexts: [], messages: [], history: {}, materials: {}, provider: {}, prompt: null });
    if (url === "/api/runs/run-a") return response({ board: { run_id: "run-a", task: "task", phase: "ENGINEERING" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    active_work_item_id: "wi_1",
    work_items: [{ work_item_id: "wi_1", title: "进行中", run_id: "run-a", status: "in_progress", department: "engineering" }],
  });
  web.state.runId = "run-a";
  web.state.workItemId = "wi_1";
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING" } };
  const form = { dataset: { departmentForm: "engineering" }, querySelector: () => ({ value: "  inspect the boundary  " }) };
  await web.addDepartmentGuidance(form);
  assert.equal(calls[0][0], "/api/runs/run-a/departments/engineering/guidance");
  assert.deepEqual(JSON.parse(calls[0][1].body), { text: "  inspect the boundary  " });
});

test("request response and event raw json stay in a viewport scroller", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.observationDetail = {
    attempt: { id: "attempt-1", status: "success", department: "engineering", logical_call_id: "call-1", attempt: 1, attempt_count: 1 },
    events: [{ type: "x", summary: "s", raw: { a: 1 } }],
    siblings: [],
  };
  web.state.observationDetailTab = "events";
  web.renderObservationDetail();
  assert.match(nodes.get("dw-main").innerHTML, /class="dw-event-raw"/);
  assert.match(nodes.get("dw-main").innerHTML, /class="dw-json"/);
});

test("64KB request and response JSON land whole inside the dw-json scroller with no size branch", () => {
  const padTo = (size, fill) => ({ blob: fill.repeat(size - JSON.stringify({ blob: "" }, null, 2).length) });
  const request = padTo(65536, "R");
  const responsePayload = padTo(65536, "S");
  const expectedRequest = JSON.stringify(request, null, 2);
  const expectedResponse = JSON.stringify(responsePayload, null, 2);
  assert.equal(Buffer.byteLength(expectedRequest, "utf8"), 65536);
  assert.equal(Buffer.byteLength(expectedResponse, "utf8"), 65536);
  const escaped = value => value.replace(/"/g, "&quot;");
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.observationDetail = {
    attempt: { id: "attempt-1", status: "success", department: "engineering", logical_call_id: "call-1", attempt: 1, attempt_count: 1 },
    request,
    response: responsePayload,
    events: [],
    siblings: [],
  };
  for (const [tab, expected, heading] of [["request", expectedRequest, "Request JSON"], ["response", expectedResponse, "Response JSON"]]) {
    web.state.observationDetailTab = tab;
    web.renderObservationDetail();
    const html = nodes.get("dw-main").innerHTML;
    const panelStart = html.indexOf('<div class="dw-detail-panel">');
    const panel = html.slice(panelStart, html.indexOf("</div>", html.indexOf("</pre>", panelStart)) + 6);
    assert.ok(panelStart >= 0, `${tab} tab renders a detail panel`);
    assert.match(panel, new RegExp(`^<div class="dw-detail-panel"><div class="dw-json-heading"><h3>${heading}</h3>`));
    assert.ok(panel.endsWith(`<pre class="dw-json">${escaped(expected)}</pre></div>`), `${tab} JSON is rendered whole inside pre.dw-json`);
    assert.equal(panel.split('class="dw-json"').length - 1, 1, `${tab} tab has exactly one dw-json container`);
    assert.doesNotMatch(html, /…|截断|下载原文|展开全部|dw-json-truncated|dw-json-download/, `${tab} tab has no truncation or download branch`);
  }
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-json \{[^}]*white-space: pre-wrap; overflow-wrap: anywhere; \}/);
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-detail-panel \{[^}]*min-width: 0; \}/);
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-detail-panel \.dw-json,\s*#department-workspace-prototype \.dw-event-raw \.dw-json \{ max-height: min\(50vh, 24rem\); overflow: auto; \}/);
});

test("observation list and detail show requested and actual identity separately", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.observationData = {
    items: [
      {
        id: "in-flight",
        status: "failed",
        department: "product",
        requested_provider: "penguin",
        requested_model: "gpt-5.6-luna",
        actual_provider: null,
        actual_model: null,
      },
      {
        id: "done",
        status: "success",
        department: "product",
        requested_provider: "penguin",
        requested_model: "gpt-5.6-luna",
        actual_provider: "penguin",
        actual_model: "gpt-5.6-actual",
      },
    ],
    total: 2,
    total_attempts: 2,
    running_attempts: 0,
    prepared_attempts: 0,
  };
  web.renderObservability();
  const list = pageHtml(nodes);
  assert.match(list, /请求：penguin \/ gpt-5\.6-luna/);
  assert.match(list, /返回：未知/);
  assert.match(list, /返回：penguin \/ gpt-5\.6-actual/);

  web.state.observationDetail = { attempt: web.state.observationData.items[0], siblings: [] };
  web.renderObservationDetail();
  const pending = nodes.get("dw-main").innerHTML;
  assert.match(pending, /<dt>请求<\/dt><dd>penguin \/ gpt-5\.6-luna<\/dd>/);
  assert.match(pending, /<dt>返回<\/dt><dd>未知<\/dd>/);

  web.state.observationDetail = { attempt: web.state.observationData.items[1], siblings: [] };
  web.renderObservationDetail();
  const completed = nodes.get("dw-main").innerHTML;
  assert.match(completed, /<dt>请求<\/dt><dd>penguin \/ gpt-5\.6-luna<\/dd>/);
  assert.match(completed, /<dt>返回<\/dt><dd>penguin \/ gpt-5\.6-actual<\/dd>/);
});

test("createProject posts name and goal then selects the new project", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/projects" && options.method === "POST") return response({ project_id: "proj_new" }, 201);
    if (url === "/api/projects") return response({ projects: [{ project_id: "proj_new", name: "N" }] });
    if (url === "/api/projects/proj_new") return response(sampleProject("proj_new", { name: "N" }));
    if (url === "/api/health") return response({ ok: true });
    return response({});
  }, document);
  nodes.get("yp-project-name").value = "N";
  nodes.get("yp-project-goal").value = "G";
  const form = nodes.get("yp-project-dialog-form");
  form.elements.name.value = "N";
  form.elements.goal.value = "G";
  await web.createProject({ preventDefault() {}, currentTarget: form, submitter: { value: "default" } });
  assert.equal(calls[0][0], "/api/projects");
  assert.equal(calls[0][1].method, "POST");
  assert.deepEqual(JSON.parse(calls[0][1].body), { name: "N", goal: "G" });
  assert.equal(web.state.projectId, "proj_new");
});

test("context-view and trace-view scripts load before app.js", () => {
  assert.match(INDEX_HTML, /src="\/static\/context-view\.js"/);
  assert.match(INDEX_HTML, /src="\/static\/trace-view\.js"/);
  const contextAt = INDEX_HTML.indexOf("/static/context-view.js");
  const traceAt = INDEX_HTML.indexOf("/static/trace-view.js");
  const appAt = INDEX_HTML.indexOf("/static/app.js");
  assert.ok(contextAt >= 0 && traceAt >= 0 && contextAt < appAt && traceAt < appAt);
  assert.match(STYLES_CSS, /@media \(min-width: 1440px\)/);
  assert.match(STYLES_CSS, /@media \(max-width: 390px\)/);
});

test("observation filters expose provider and model and keep page size 50", async () => {
  const calls = [];
  const { document, nodes } = uiDocument();
  const web = loadApp(async (url) => {
    calls.push(String(url));
    if (String(url).includes("/model-attempts")) return response({ items: [], total: 0, next_cursor: null });
    return response({ totals: {}, coverage: {} });
  }, document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.routeToken = 1;
  web.state.observationData = { items: [{ id: "a1", requested_provider: "penguin", requested_model: "luna", actual_provider: "penguin", actual_model: "luna-actual", status: "success", department: "product" }], total: 1, total_attempts: 1 };
  web.renderObservability();
  const html = pageHtml(nodes);
  assert.match(html, /data-obs-provider/);
  assert.match(html, /data-obs-requested-model/);
  assert.match(html, /data-obs-actual-model/);
  assert.match(html, /data-obs-department/);
  assert.match(html, /data-obs-status/);
  assert.match(html, /data-obs-search/);
  web.state.observationFilters.provider = "penguin";
  web.state.observationFilters.requested_model = "luna";
  web.state.observationFilters.actual_model = "luna-actual";
  await web.loadObservationData();
  assert.match(calls[0], /\/model-attempts\?/);
  assert.match(calls[0], /provider=penguin/);
  assert.match(calls[0], /requested_model=luna/);
  assert.match(calls[0], /actual_model=luna-actual/);
  assert.match(calls[0], /limit=50/);
  assert.match(calls[1], /\/model-usage\?/);
  assert.match(calls[1], /provider=penguin/);
});

test("attempt detail header shows error class diagnostics retry and partial output", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a");
  web.state.observationDetail = {
    attempt: {
      id: "attempt-1",
      status: "failed",
      department: "engineering",
      logical_call_id: "call-1",
      attempt: 2,
      attempt_count: 3,
      started_at: "2026-09-15T01:00:00Z",
      duration_ms: 1200,
      partial_output: true,
      output_item_count: 1,
      requested_provider: "penguin",
      requested_model: "luna",
      actual_provider: "penguin",
      actual_model: "luna-actual",
      error_class: "provider_error",
      reason: "provider_error",
      diagnostics: { error_type: "timeout", error_code: "server_is_overloaded" },
      error: "Model request timed out",
    },
    siblings: [],
  };
  web.renderObservationDetail();
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /dw-attempt-diagnostics/);
  assert.match(html, /错误分类 provider_error/);
  assert.match(html, /timeout/);
  assert.match(html, /server_is_overloaded/);
  assert.match(html, /部分输出/);
  assert.match(html, /第 2\/3 次/);
  assert.match(html, /请求 penguin \/ luna/);
  assert.match(html, /返回 penguin \/ luna-actual/);
});

test("context summary shows coverage range and original event control", () => {
  const web = loadApp();
  web.state.runId = "run-a";
  web.state.projectId = "proj_a";
  web.state.contextDetails.set("run-a/attempt-9", {
    context: {
      parts: [
        { source: "department_rules", text: "developer instruction", version: 1, digest: "abc" },
        { source: "department_history", text: JSON.stringify([{ role: "user", content: "[department_memory]\n" + JSON.stringify({ summary: "kept the contract", covered_through_event_id: "evt-9" }) }]), version: 1, digest: "def" },
        { source: "tool_schemas", text: "[]", version: 1, digest: "ghi" },
        { source: "current_contract", text: "{\"goal\":\"ship\"}", version: 1, digest: "jkl" },
      ],
      coverage: {
        compaction_event_id: "cmp-1",
        covered_through_event_id: "evt-9",
        covered_through_seq: 12,
        source_seq_from: 4,
        source_seq_through: 12,
      },
      summaries: [{ source: "department_memory", summary: "kept the contract", covered_through_event_id: "evt-9" }],
    },
  });
  const html = web.contextMarkup("engineering", { contexts: [{ id: "attempt-9", title: "工作输入", purpose: "work" }] });
  assert.match(html, /Developer 指令/);
  assert.match(html, /部门历史/);
  assert.match(html, /工具 schema/);
  assert.match(html, /合同摘要/);
  assert.match(html, /覆盖范围 seq 4–12/);
  assert.match(html, /covered_through evt-9/);
  assert.match(html, /data-event-id="cmp-1"/);
  assert.match(html, /data-observe-attempt="attempt-9"/);
});

test("breadcrumb names task department and request without dropping provider page", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.projectId = "proj_a";
  web.state.project = sampleProject("proj_a", {
    work_items: [{ work_item_id: "wi_1", title: "导出 CSV", run_id: "run-a", status: "in_progress", department: "engineering" }],
  });
  web.state.workItemId = "wi_1";
  web.state.view = "observability";
  web.state.observationScreen = "detail";
  web.state.observationDetail = { attempt: { id: "a1", attempt: 2, department: "engineering" }, siblings: [] };
  web.renderObservationDetail();
  const bar = nodes.get("yp-topbar").innerHTML;
  assert.match(bar, /导出 CSV/);
  assert.match(bar, /工程部/);
  assert.match(bar, /请求 2/);
  assert.match(APP_JS, /模型与 Provider/);
  assert.match(APP_JS, /data-action="providers"/);
});

// —— provider-config 设置页：解析 markup() 输出的轻量 DOM 与 fetch 桩 ——

const PROVIDER_CONFIG_JS = fs.readFileSync(path.join(staticDir, "provider-config.js"), "utf8");

function decodeEntities(text) {
  return String(text)
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

const PROVIDER_VOID_TAGS = new Set(["input", "br", "hr", "img", "link", "meta"]);

function parseProviderAttrs(raw) {
  const attrs = {};
  const attrRe = /([a-zA-Z_][-\w]*)(?:="([^"]*)")?/g;
  let match;
  while ((match = attrRe.exec(raw))) {
    attrs[match[1]] = match[2] === undefined ? "" : decodeEntities(match[2]);
  }
  return attrs;
}

function makeProviderDomNode(tag, attrs) {
  const dataset = {};
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("data-")) {
      dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
    }
  }
  const listeners = {};
  const node = {
    tag,
    attrs,
    dataset,
    value: tag === "select" ? undefined : (attrs.value ?? ""),
    checked: attrs.type === "checkbox" ? "checked" in attrs : undefined,
    disabled: "disabled" in attrs,
    hidden: "hidden" in attrs,
    focused: false,
    _fields: [],
    addEventListener(type, callback) { (listeners[type] ||= []).push(callback); },
    async dispatch(type, event = {}) {
      for (const callback of listeners[type] || []) {
        await callback({ target: node, currentTarget: node, stopPropagation() {}, preventDefault() {}, ...event });
      }
    },
    focus() { node.focused = true; },
    click() { return node.dispatch("click"); },
  };
  return node;
}

function parseProviderHtml(html) {
  const nodes = [];
  const stack = [];
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>/g;
  let match;
  while ((match = tagRe.exec(html))) {
    const tag = match[2].toLowerCase();
    if (match[1]) {
      for (let i = stack.length - 1; i >= 0; i--) {
        if (stack[i].tag === tag) {
          if (tag === "select" && stack[i].value === undefined) {
            stack[i].value = stack[i]._firstOptionValue ?? "";
          }
          stack.length = i;
          break;
        }
      }
      continue;
    }
    const attrs = parseProviderAttrs(match[3] || "");
    const node = makeProviderDomNode(tag, attrs);
    nodes.push(node);
    if (tag === "option") {
      const select = [...stack].reverse().find(item => item.tag === "select");
      if (select) {
        if (select._firstOptionValue === undefined) select._firstOptionValue = attrs.value ?? "";
        if ("selected" in attrs) select.value = attrs.value ?? "";
      }
      continue;
    }
    if (tag === "input" || tag === "select" || tag === "textarea") {
      const form = [...stack].reverse().find(item => item.tag === "form");
      if (form && attrs.name) {
        form._fields.push({ name: attrs.name, kind: attrs.type === "checkbox" ? "checkbox" : tag, node });
      }
    }
    if (!PROVIDER_VOID_TAGS.has(tag)) stack.push(node);
  }
  return nodes;
}

function providerMatches(node, selector) {
  const idMatch = /^#([\w-]+)$/.exec(selector);
  if (idMatch) return node.attrs.id === idMatch[1];
  const attrMatch = /^\[([a-zA-Z-]+)(?:='([^']*)'|="([^"]*)")?\]$/.exec(selector);
  if (attrMatch) {
    if (!Object.prototype.hasOwnProperty.call(node.attrs, attrMatch[1])) return false;
    if (attrMatch[2] !== undefined) return node.attrs[attrMatch[1]] === attrMatch[2];
    if (attrMatch[3] !== undefined) return node.attrs[attrMatch[1]] === attrMatch[3];
    return true;
  }
  return false;
}

function providerRoot() {
  return {
    _html: "",
    _nodes: [],
    set innerHTML(html) { this._html = String(html); this._nodes = parseProviderHtml(this._html); },
    get innerHTML() { return this._html; },
    querySelectorAll(selector) { return this._nodes.filter(node => providerMatches(node, selector)); },
    querySelector(selector) { return this._nodes.find(node => providerMatches(node, selector)) || null; },
  };
}

class ProviderFormData {
  constructor(form) {
    this._entries = [];
    for (const field of (form && form._fields) || []) {
      if (field.kind === "checkbox") {
        if (field.node.checked) this._entries.push([field.name, field.node.attrs.value || "on"]);
      } else {
        this._entries.push([field.name, field.node.value ?? ""]);
      }
    }
  }
  entries() { return this._entries[Symbol.iterator](); }
}

function loadProviderConfig(fetchImpl) {
  const sandbox = {
    console, Promise, Map, Set, JSON, Error, Number, String, Array, Object, Math, Date,
    encodeURIComponent, setTimeout, clearTimeout,
    fetch: fetchImpl,
    FormData: ProviderFormData,
    Blob: class { constructor(parts, options) { this.parts = parts; this.type = options && options.type; } },
    URL: class { static createObjectURL() { return "blob:test"; } static revokeObjectURL() {} },
    document: { createElement(tag) { return { tagName: tag, href: "", download: "", click() {} }; } },
    confirm: () => true,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(PROVIDER_CONFIG_JS, sandbox);
  return sandbox.harnessProviderConfig;
}

function providerFetch(routes) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push([String(url), options]);
    const route = routes[String(url)];
    if (route === undefined) return response({ error: `未打桩的请求：${url}` }, 404);
    return response(typeof route === "function" ? route(options) : route);
  };
  return { calls, fetchImpl };
}

function samplePreset() {
  return {
    id: "opencode-go", name: "OpenCode Go", auth: "api_key",
    base_urls: {
      responses: "https://go.example.com/v1",
      chat_completions: "https://go.example.com/v1",
      messages: "https://go.example.com/anthropic",
    },
    models_url: "https://go.example.com/models",
    docs_url: "https://go.example.com/docs",
    source: "official", notes: "OpenCode Go 订阅接入",
    known_models: [{ model_id: "gpt-5.6-luna", protocol: "responses", capability_source: "preset-v1" }],
  };
}

function catalogModel(id, model, overrides = {}) {
  return {
    id, provider_id: "p1", model, protocol: "responses",
    context_window: 128000, max_output_tokens: 4096, capability_source: "preset-v1",
    admitted_at: null, admitted_model: null, admitted_revision: null,
    ...overrides,
  };
}

function catalogView({ revision = 5, credential = { ref: "K", configured: true, source: "env", has_override: false }, models = [], bindings = {} } = {}) {
  const provider = {
    id: "p1", name: "Go 连接", base_url: "https://go.example.com/v1",
    credential_ref: "K", timeout_sec: 600, preset_id: "", models_url: "",
    credential, credential_configured: credential.configured !== false,
    models,
  };
  return { revision, providers: [provider], models, bindings };
}

test("provider empty state lists presets and prefills the form without auto-saving", async () => {
  const { calls, fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "preset-v1", presets: [samplePreset()] },
    "/api/providers": { revision: 3, providers: [], models: [], bindings: {} },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  let html = root.innerHTML;
  assert.match(html, /添加模型服务/);
  assert.match(html, /选择服务方案/);
  assert.match(html, /自定义连接/);
  assert.match(html, /OpenCode Go/);
  assert.match(html, /预置表版本 preset-v1/);
  assert.match(html, /不会自动保存任何任务绑定/);
  const chooseButton = root.querySelectorAll("[data-pc-action='choose-preset']")[0];
  await chooseButton.dispatch("click");
  html = root.innerHTML;
  assert.match(html, /data-preset-panel/);
  assert.match(html, /OPENCODE_GO_KEY/);
  assert.match(html, /https:\/\/go\.example\.com\/v1/);
  assert.match(html, /https:\/\/go\.example\.com\/models/);
  assert.match(html, /请求基址（按协议）/);
  // 连接地址预填为请求基址，请求路径由协议适配器拼接
  const providerFormAfter = root.querySelector("[data-pc-form='provider']");
  assert.equal(providerFormAfter._fields.find(field => field.name === "base_url").node.value, "https://go.example.com/v1");
  assert.match(html, /官方文档与 Key 获取/);
  // 选择方案后展示 Key 输入与内存作用域说明
  assert.match(html, /name="secret"/);
  assert.match(html, /本进程有效，重启后需重新提供/);
  assert.match(html, /持久化到 \.yudao\/\.env/);
  // 预填不触发任何保存或绑定请求
  assert.equal(calls.some(([, options]) => options && options.method === "POST"), false);
  assert.equal(calls.some(([url]) => String(url).includes("/api/department-bindings")), false);
});

test("candidate refresh renders suggested protocols and drops the older list on unknown", async () => {
  let candidatesStatus = "ok";
  const { calls, fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": () => catalogView({ models: [catalogModel("m1", "luna")] }),
    "/api/providers/p1/candidates": options => {
      const body = JSON.parse(options.body || "{}");
      if (candidatesStatus === "ok") {
        assert.deepEqual(body, {});
        return {
          provider_id: "p1", source_url: "https://go.example.com/models",
          fetched_at: "2026-09-19T10:00:00Z", status: "ok",
          candidates: [
            { id: "gpt-5.6-luna", protocol: "responses", capability_source: "preset-v1" },
            { id: "mystery-7", protocol: null, capability_source: null },
          ],
          error: null,
        };
      }
      assert.deepEqual(body, { models_url: "https://custom.example.com/models" });
      return {
        provider_id: "p1", source_url: "https://custom.example.com/models",
        fetched_at: "2026-09-19T10:05:00Z", status: "unknown",
        candidates: [], error: "上游 503",
      };
    },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  await root.querySelector("[data-pc-action='refresh-candidates']").dispatch("click");
  let html = root.innerHTML;
  assert.match(html, /data-candidates="ok"/);
  assert.match(html, /gpt-5\.6-luna/);
  assert.match(html, /需选择协议/);
  assert.match(html, /建立访问定义/);
  assert.match(html, /候选不落盘、不自动绑定/);
  // 建立访问定义只预填表单：无建议协议时必须手动选择，容量字段不造默认值
  const admitButton = root.querySelectorAll("[data-pc-action='admit-candidate']")
    .find(button => button.dataset.candidateId === "mystery-7");
  await admitButton.dispatch("click");
  const modelForm = root.querySelector("[data-pc-form='model']");
  assert.equal(modelForm._fields.find(field => field.name === "protocol").node.value, "");
  assert.equal(modelForm._fields.find(field => field.name === "context_window").node.value, "");
  assert.equal(modelForm._fields.find(field => field.name === "max_output_tokens").node.value, "");
  assert.match(root.innerHTML, /需选择协议/);
  // 覆写模型列表地址后刷新：上游不可达时显示候选未知，且不沿用上一次列表
  const providerForm = root.querySelector("[data-pc-form='provider']");
  providerForm._fields.find(field => field.name === "models_url").node.value = "https://custom.example.com/models";
  candidatesStatus = "unknown";
  await root.querySelector("[data-pc-action='refresh-candidates']").dispatch("click");
  html = root.innerHTML;
  assert.match(html, /data-candidates="unknown"/);
  assert.match(html, /候选未知/);
  assert.match(html, /上游 503/);
  assert.doesNotMatch(html, /gpt-5\.6-luna/);
  assert.doesNotMatch(html, /建立访问定义/);
  assert.equal(calls.filter(([url]) => String(url).endsWith("/candidates")).length, 2);
});

test("model rows show admission badges for admitted, unadmitted and stale revisions", async () => {
  const models = [
    catalogModel("m-admitted", "luna", { admitted_at: "2026-09-19T09:00:00Z", admitted_model: "luna-actual", admitted_revision: 7 }),
    catalogModel("m-fresh", "nova", { protocol: "chat_completions", capability_source: "" }),
    catalogModel("m-stale", "orion", { protocol: "messages", admitted_at: "2026-09-18T09:00:00Z", admitted_model: "orion", admitted_revision: 6 }),
  ];
  const { fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": catalogView({ revision: 7, models, bindings: { product: { provider_id: "p1", model_id: "m-admitted" } } }),
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  const html = root.innerHTML;
  assert.match(html, /class="admission admitted"/);
  assert.match(html, /class="admission unadmitted"/);
  assert.match(html, /class="admission stale"/);
  assert.match(html, /测试结果不对应当前修订/);
  // 配置、凭据、准入、额度分开呈现，不合并成一个绿点
  assert.match(html, /data-status-strip/);
  assert.match(html, /配置：就绪 · 1\/3 模型已准入/);
  assert.match(html, /凭据：已配置 · 来源 宿主进程环境/);
  assert.match(html, /准入：1\/3 已准入/);
  assert.match(html, /额度：未知/);
});

test("saved key is never echoed back and credential status shows source and override", async () => {
  let view = catalogView({ credential: { ref: "K", configured: false, source: "missing", has_override: false }, models: [catalogModel("m1", "luna")] });
  const { calls, fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": () => view,
    "/api/provider-credentials": options => {
      const body = JSON.parse(options.body);
      if (body.action === "set") {
        view = catalogView({
          credential: { ref: "K", configured: true, source: "override", has_override: true },
          models: [catalogModel("m1", "luna")],
        });
        return { ok: true, ref: "K", credential: { ref: "K", configured: true, source: "override", has_override: true }, revision: 2 };
      }
      return { ok: true };
    },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  assert.match(root.innerHTML, /凭据：缺失/);
  const credentialForm = root.querySelector("[data-pc-form='credential']");
  credentialForm._fields.find(field => field.name === "secret").node.value = "sk-secret-value-123";
  await credentialForm.dispatch("submit");
  const saveCall = calls.find(([url, options]) => url === "/api/provider-credentials" && options.method === "POST");
  assert.deepEqual(JSON.parse(saveCall[1].body), { ref: "K", action: "set", secret: "sk-secret-value-123", persist: false });
  const html = root.innerHTML;
  // 已保存的 Key 永不回填，页面只显示 configured/source/has_override
  assert.doesNotMatch(html, /sk-secret-value-123/);
  assert.match(html, /临时 Key/);
  assert.match(html, /本进程有效，重启后需重新提供/);
  assert.match(html, /内存覆盖当前生效/);
  assert.match(html, /data-credential-status/);
  assert.match(html, /清除内存覆盖/);
  assert.match(html, /删除持久凭据/);
});

test("model test shows inline progress then result and keeps filled fields", async () => {
  let resolveTest;
  const testResponse = new Promise(resolve => { resolveTest = resolve; });
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push([String(url), options]);
    if (url === "/api/provider-presets") return response({ table_version: "v1", presets: [] });
    if (url === "/api/providers") return response(catalogView({ models: [catalogModel("m1", "luna")] }));
    if (String(url).endsWith("/test")) return testResponse.then(payload => response(payload));
    return response({ error: "not found" }, 404);
  };
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  // 预填一个未保存的容量值：测试过程中不能丢失已填的非敏感字段
  const modelForm = root.querySelector("[data-pc-form='model']");
  modelForm._fields.find(field => field.name === "context_window").node.value = "256000";
  const pending = root.querySelector("[data-pc-action='test-model']").dispatch("click");
  // dispatch 同步执行监听器前缀，此时进度渲染已完成
  let html = root.innerHTML;
  assert.match(html, /data-test-progress/);
  assert.match(html, /测试中…/);
  assert.equal(root.querySelector("[data-pc-action='test-model']").disabled, true);
  resolveTest({ ok: true, error: null, actual_model: "luna-actual", elapsed_ms: 812, revision: 8, admitted: true, protocol: "responses" });
  await pending;
  html = root.innerHTML;
  assert.match(html, /data-test-result="ok"/);
  assert.match(html, /实际返回 luna-actual/);
  assert.match(html, /协议 responses/);
  assert.match(html, /修订 8/);
  assert.match(html, /耗时 812 ms/);
  assert.match(html, /class="admission admitted"/);
  const modelFormAfter = root.querySelector("[data-pc-form='model']");
  assert.equal(modelFormAfter._fields.find(field => field.name === "context_window").node.value, "256000");
  const testCall = calls.find(([url]) => String(url).endsWith("/test"));
  assert.deepEqual(JSON.parse(testCall[1].body), { model_id: "m1", kind: "model" });
});

test("model test failure keeps the verifiable reason and filled fields", async () => {
  const { fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": catalogView({ models: [catalogModel("m1", "luna")] }),
    "/api/providers/p1/test": { ok: false, error: "缺少凭据环境变量 K，请补充后重试", actual_model: null, elapsed_ms: 3, revision: 5, admitted: false, protocol: null },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  const modelForm = root.querySelector("[data-pc-form='model']");
  modelForm._fields.find(field => field.name === "max_output_tokens").node.value = "2048";
  await root.querySelector("[data-pc-action='test-model']").dispatch("click");
  const html = root.innerHTML;
  assert.match(html, /data-test-result="bad"/);
  assert.match(html, /模型测试失败 · m1/);
  assert.match(html, /缺少凭据环境变量 K，请补充后重试/);
  const modelFormAfter = root.querySelector("[data-pc-form='model']");
  assert.equal(modelFormAfter._fields.find(field => field.name === "max_output_tokens").node.value, "2048");
});

test("binding options mark unadmitted models unavailable with the reason visible", async () => {
  const models = [
    catalogModel("m1", "luna", { admitted_at: "2026-09-19T09:00:00Z", admitted_model: "luna", admitted_revision: 5 }),
    catalogModel("m2", "nova"),
  ];
  const { calls, fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": () => catalogView({ revision: 5, models, bindings: { product: { provider_id: "p1", model_id: "m1" } } }),
    "/api/department-bindings": { bindings: { product: { provider_id: "p1", model_id: "m1" } } },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  const html = root.innerHTML;
  assert.match(html, /未准入的模型不能绑定到部门/);
  const m1Option = html.match(/<option value="p1\/m1"[^>]*>([^<]*)<\/option>/);
  const m2Option = html.match(/<option value="p1\/m2"[^>]*disabled[^>]*>([^<]*)<\/option>/);
  assert.ok(m1Option, "已准入模型应出现在绑定下拉中");
  assert.ok(!/disabled/.test(m1Option[0]), "已准入模型可以被选择");
  assert.ok(m2Option, "未准入模型应被禁用");
  assert.match(m2Option[1], /未准入，需先通过模型测试/);
  // 保存绑定后提示只影响新任务
  await root.querySelector("[data-pc-form='bindings']").dispatch("submit");
  const putCall = calls.find(([url, options]) => url === "/api/department-bindings" && options.method === "PUT");
  assert.deepEqual(JSON.parse(putCall[1].body), { product: { provider_id: "p1", model_id: "m1" } });
  assert.match(root.innerHTML, /新任务将使用此配置，已有任务保持原配置/);
});

test("readiness gap chip jumps to the missing credential field", async () => {
  const { fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": catalogView({ credential: { ref: "K", configured: false, source: "missing", has_override: false }, models: [] }),
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  const html = root.innerHTML;
  assert.match(html, /已保存但未就绪 · 缺凭据/);
  assert.match(html, /点击跳到对应字段/);
  const chip = root.querySelector("[data-pc-jump]");
  assert.equal(chip.dataset.pcJump, "credential-secret");
  await chip.dispatch("click");
  assert.equal(root.querySelector("[data-pc-field='credential-secret']").focused, true);
});

test("reload error keeps a visible notice that the current revision stays in use", async () => {
  const { fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": catalogView({ models: [catalogModel("m1", "luna")] }),
    "/api/providers/reload": { ok: false, revision: 4, reload_error: "Provider 配置无法解析：Expecting value", changed: false },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  await root.querySelector("[data-pc-action='reload']").dispatch("click");
  const html = root.innerHTML;
  assert.match(html, /data-reload-notice/);
  assert.match(html, /文件更新未生效/);
  assert.match(html, /Provider 配置无法解析：Expecting value/);
  assert.match(html, /当前仍用修订 4/);
});

test("provider level connection test posts kind=connection and reports the revision", async () => {
  const { calls, fetchImpl } = providerFetch({
    "/api/provider-presets": { table_version: "v1", presets: [] },
    "/api/providers": catalogView({ models: [catalogModel("m1", "luna")] }),
    "/api/providers/p1/test": { ok: true, error: null, actual_model: "luna", elapsed_ms: 120, revision: 5, admitted: false, protocol: "responses" },
  });
  const config = loadProviderConfig(fetchImpl);
  const root = providerRoot();
  await config.mount(root);
  await root.querySelector("[data-pc-action='test']").dispatch("click");
  const testCall = calls.find(([url]) => String(url).endsWith("/test"));
  assert.deepEqual(JSON.parse(testCall[1].body), { kind: "connection" });
  assert.match(root.innerHTML, /连接成功 · luna · 120 ms · 修订 5/);
});

