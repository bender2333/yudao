const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "web", "static");
const APP_JS = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
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
  assert.match(INDEX_HTML, /src="\/static\/lucide\.min\.js"/);
  assert.match(INDEX_HTML, /src="\/static\/app\.js"/);
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
