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
  const ids = ["department-workspace-prototype", "dw-main", "dw-task-dialog", "dw-task-dialog-form", "dw-task-text", "dw-max-cycles", "dw-context-window", "dw-task-submit", "dw-task-error", "dw-prompt-dialog", "dw-prompt-dialog-form", "dw-prompt-text", "dw-prompt-error", "dw-event-dialog", "dw-event-title", "dw-event-version", "dw-event-files", "dw-event-document", "dw-event-json", "dw-event-sources"];
  const nodes = new Map(ids.map(id => [id, node(id)]));
  const root = nodes.get("department-workspace-prototype");
  const observationContent = node("dw-observation-content");
  nodes.set("dw-observation-content", observationContent);
  root.querySelector = selector => {
    if (selector === ".dw-action-error") return node("dw-action-error");
    if (selector === "#dw-observation-content") return observationContent;
    return null;
  };
  const taskForm = nodes.get("dw-task-dialog-form");
  taskForm.elements = { task: nodes.get("dw-task-text"), max_cycles: nodes.get("dw-max-cycles"), context_window: nodes.get("dw-context-window") };
  taskForm.elements.task.value = "";
  taskForm.elements.max_cycles.value = "8";
  taskForm.elements.context_window.value = "32000";
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

test("production shell uses the frozen workspace root and local Lucide bundle", () => {
  assert.match(INDEX_HTML, /id="department-workspace-prototype"/);
  assert.match(INDEX_HTML, /class="dw-shell"/);
  assert.match(INDEX_HTML, /src="\/static\/lucide\.min\.js"/);
  assert.match(INDEX_HTML, /src="\/static\/app\.js"/);
  assert.doesNotMatch(INDEX_HTML, /department-workspace-preview|iframe/);
});

test("visual contract tokens and required responsive dimensions remain present", () => {
  for (const token of ["--dw-accent", "--dw-background", "--dw-inspector-width", "--dw-border", "--dw-amber", "--dw-red"]) {
    assert.match(STYLES_CSS, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(STYLES_CSS, /grid-template-columns: 68px minmax\(0, 1fr\)/);
  assert.match(STYLES_CSS, /@media \(max-width: 760px\)/);
  assert.match(STYLES_CSS, /@media \(max-width: 430px\)/);
});

test("UI source contains no prototype sample state, tweak controls, or department send simulation", () => {
  assert.doesNotMatch(APP_JS, /const modelRequests\s*=\s*\[/);
  assert.doesNotMatch(APP_JS, /new Tweak|globalThis\.Tweak/);
  assert.doesNotMatch(APP_JS, /示例 Provider|orion-2\.1-pro|attempt-7F3A/);
  assert.match(APP_JS, /data-dept-draft/);
  assert.match(APP_JS, /disabled>.*发送指导/);
});

test("model attempt and usage queries use one exact cursor contract and preserve nulls", async () => {
  const calls = [];
  const web = loadApp(async (url) => {
    calls.push(url);
    if (url.includes("/model-attempts")) return response({ items: [{ id: "attempt-1", status: "failed", usage: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null, latency_ms: 0 } }], total: 1, total_attempts: 1, running_attempts: 0, prepared_attempts: 0, next_cursor: null });
    return response({ total_attempts: 1, reported_attempts: 0, totals: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null }, groups: { departments: [], models: [] } });
  });
  web.state.runId = "run-1";
  web.state.routeToken = 1;
  await web.loadObservationData();
  assert.match(calls[0], /^\/api\/runs\/run-1\/model-attempts\?limit=50$/);
  assert.match(calls[1], /^\/api\/runs\/run-1\/model-usage$/);
  assert.equal(web.state.observationData.items[0].usage.input_tokens, null);
  assert.equal(web.state.usageData.totals.total_tokens, null);
  assert.doesNotMatch(calls.join("\n"), /page=|page_size=|request_id=/);
});

test("observation cursor pagination appends records while usage keeps the complete filter", async () => {
  const calls = [];
  const web = loadApp(async url => {
    calls.push(url);
    if (url.includes("/model-attempts")) {
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      return response(cursor ? { items: [{ id: "attempt-2", status: "success" }], total: 2, total_attempts: 2, running_attempts: 0, prepared_attempts: 0, next_cursor: null } : { items: [{ id: "attempt-1", status: "success" }], total: 2, total_attempts: 2, running_attempts: 0, prepared_attempts: 0, next_cursor: "1" });
    }
    return response({ total_attempts: 2, prepared_attempts: 0, coverage: { attempts: 2, reported_attempts: 0, percent: 0, fields: {} }, totals: {}, groups: { departments: [], models: [] } });
  });
  web.state.runId = "run-1";
  web.state.routeToken = 1;
  await web.loadObservationData();
  await web.loadObservationData({ append: true });
  assert.match(calls[0], /model-attempts\?limit=50$/);
  assert.match(calls[2], /model-attempts\?limit=50&cursor=1$/);
  assert.equal(calls.filter(url => url.includes("model-usage")).length, 1);
  assert.equal(Array.from(web.state.observationData.items, item => item.id).join(","), "attempt-1,attempt-2");
});

test("usage view uses server coverage, prepared count, and explicit currency without filling nulls", () => {
  const web = loadApp();
  web.state.usageData = {
    total_attempts: 2,
    prepared_attempts: 1,
    coverage: { attempts: 2, reported_attempts: 1, percent: 50, fields: { input_tokens: { reported: 1, total: 2 }, total_tokens: { reported: 1, total: 2 } } },
    totals: { input_tokens: 12, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: 0.000001, currency: "CNY" },
    groups: { departments: [{ key: "engineering", label: "工程部", attempts: 2, reported_attempts: 1, running_attempts: 0, input_tokens: 12, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: 0.000001, currency: "CNY", coverage: { reported_attempts: 1, attempts: 2, fields: {} } }], models: [] },
  };
  const html = web.usageMarkup();
  assert.match(html, /1 条准备记录未发出/);
  assert.match(html, /0\.000001 CNY/);
  assert.match(html, /输出<\/span><strong>未上报/);
  assert.doesNotMatch(html, /输出<\/span><strong>等待响应/);
  assert.match(html, /输入 1\/2/);
});

test("late observation responses cannot replace a newer task or query", async () => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const web = loadApp(async (url) => {
    if (url.includes("run-old/model-attempts")) {
      await held;
      return response({ items: [{ id: "old", status: "success" }], total: 1, next_cursor: null });
    }
    if (url.includes("run-old/model-usage")) return response({ total_attempts: 0, reported_attempts: 0, totals: {}, groups: { departments: [], models: [] } });
    return response({ items: [], total: 0, next_cursor: null });
  });
  web.state.runId = "run-old";
  web.state.routeToken = 4;
  const pending = web.loadObservationData();
  web.state.runId = "run-new";
  web.state.routeToken = 5;
  release();
  await pending;
  assert.equal(web.state.observationData, null);
});

test("fetchJSON reports API failures without exposing raw stale UI state", async () => {
  const web = loadApp(async () => response({ error: "provider unavailable" }, 503));
  await assert.rejects(() => web.fetchJSON("/api/runs"), error => {
    assert.equal(error.status, 503);
    assert.equal(error.message, "provider unavailable");
    return true;
  });
});

test("department context link is bound to the selected context attempt id", () => {
  assert.match(APP_JS, /data-observe-attempt=\"\$\{escapeHtml\(selectedAttempt\)\}\"/);
  assert.match(APP_JS, /function attemptIdFromContext\(context\)/);
  assert.doesNotMatch(APP_JS, /sort\(\(a, b\) => b\.time\.localeCompare/);
});

test("raw request and response rendering uses text-safe JSON serialization", () => {
  assert.match(APP_JS, /function json\(value\)/);
  assert.match(APP_JS, /JSON\.stringify\(value, null, 2\)/);
  assert.match(APP_JS, /dw-response-empty.*等待模型响应/);
  assert.match(STYLES_CSS, /white-space: pre-wrap/);
  assert.match(STYLES_CSS, /overflow-wrap: anywhere/);
});

test("createRun sends the dialog values and selects the newly returned run", async () => {
  const { document, nodes } = uiDocument();
  const calls = [];
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/runs") {
      if (options.method === "POST") return response({ run_id: "run-new", phase: "PRODUCT_SPEC" }, 201);
      return response({ runs: [{ run_id: "run-new", task: "new task", phase: "PRODUCT_SPEC" }] });
    }
    if (url === "/api/runs/run-new") return response({ board: { run_id: "run-new", task: "new task", phase: "PRODUCT_SPEC", active_department: "product" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  nodes.get("dw-task-text").value = "  new task\n";
  nodes.get("dw-max-cycles").value = "5";
  nodes.get("dw-context-window").value = "12000";
  await web.createRun({ preventDefault() {}, currentTarget: nodes.get("dw-task-dialog-form"), submitter: { value: "default" } });
  assert.deepEqual(JSON.parse(calls[0][1].body), { task: "  new task\n", max_cycles: 5, context_window: 12000 });
  assert.equal(web.state.runId, "run-new");
  assert.equal(web.state.newTaskDraft.task, "");
});

test("failed create keeps the exact new-task draft for reopen", async () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({ error: "provider unavailable" }, 503), document);
  nodes.get("dw-task-text").value = "long task text";
  nodes.get("dw-max-cycles").value = "7";
  nodes.get("dw-context-window").value = "64000";
  await web.createRun({ preventDefault() {}, currentTarget: nodes.get("dw-task-dialog-form"), submitter: { value: "default" } });
  assert.equal(web.state.newTaskDraft.task, "long task text");
  assert.equal(web.state.newTaskDraft.max_cycles, "7");
  assert.equal(web.state.newTaskDraft.context_window, "64000");
  web.openTaskDialog();
  assert.equal(nodes.get("dw-task-text").value, "long task text");
  assert.equal(nodes.get("dw-context-window").value, "64000");
});

test("global input is sent to the captured run and a late response cannot clear the new task draft", async () => {
  const { document, nodes } = uiDocument();
  const calls = [];
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/runs/run-a/inputs") { await hold; return response({ ok: true }, 201); }
    if (url === "/api/runs/run-a") return response({ board: { run_id: "run-a", task: "a", phase: "ENGINEERING" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 4;
  web.state.runPayload = { board: { phase: "ENGINEERING" } };
  const textarea = node("global-draft", { value: "keep exact" });
  const form = node("global-form", { querySelector() { return textarea; } });
  const pending = web.addGlobalInput(form);
  await new Promise(resolve => setImmediate(resolve));
  web.state.runId = "run-b";
  web.state.routeToken = 5;
  web.state.globalDrafts["run-b"] = "new task draft";
  release();
  await pending;
  assert.equal(calls[0][0], "/api/runs/run-a/inputs");
  assert.deepEqual(JSON.parse(calls[0][1].body), { text: "keep exact" });
  assert.equal(web.state.globalDrafts["run-a"], "keep exact");
  assert.equal(web.state.globalDrafts["run-b"], "new task draft");
});

test("terminal task rejects global input without issuing a command", async () => {
  const { document } = uiDocument();
  let called = false;
  const web = loadApp(async () => { called = true; return response({}); }, document);
  web.state.runId = "done";
  web.state.runPayload = { board: { phase: "DONE" } };
  await web.addGlobalInput({ querySelector() { return node("draft", { value: "ignored" }); } });
  assert.equal(called, false);
});

test("SSE terminal refresh keeps the original run draft and exposes new-task as the only create path", async () => {
  const { document, nodes } = uiDocument();
  const calls = [];
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    return response({ board: { run_id: "run-a", task: "finished task", phase: "DONE", active_department: null }, timeline: {}, evidence: {}, inputs: [], events: [] });
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 4;
  web.state.globalDrafts["run-a"] = "draft kept for run-a";
  await web.loadRunPayload("run-a", 4);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/runs/run-a");
  assert.equal(calls[0][1].method, undefined);
  assert.match(nodes.get("dw-main").innerHTML, /draft kept for run-a/);
  assert.match(nodes.get("dw-main").innerHTML, /data-action="new-task"/);
  assert.match(nodes.get("dw-main").innerHTML, /data-global-draft[^>]*disabled/);
  assert.equal(calls.some(item => item[0] === "/api/runs" && item[1].method === "POST"), false);
});

test("cancel uses the selected run and refreshes its projection", async () => {
  const { document } = uiDocument();
  const calls = [];
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/runs/run-active/cancel") return response({ ok: true });
    if (url === "/api/runs/run-active") return response({ board: { run_id: "run-active", task: "task", phase: "PAUSED" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  web.state.runId = "run-active";
  web.state.routeToken = 3;
  web.state.runPayload = { board: { phase: "ENGINEERING" } };
  await web.cancelRun();
  assert.equal(calls[0][0], "/api/runs/run-active/cancel");
  assert.equal(calls[0][1].method, "POST");
  assert.equal(calls[1][0], "/api/runs/run-active");
  assert.equal(web.state.runPayload.board.phase, "PAUSED");
});

test("Prompt save is tied to its dialog run, locks duplicate submits, and keeps draft on failure", async () => {
  const { document, nodes } = uiDocument();
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  const calls = [];
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url === "/api/runs/run-a/prompts/product") { await hold; return response({ ok: true }, 201); }
    if (url === "/api/runs/run-a/departments/product") return response({ run_id: "run-a", department: "product", contexts: [], messages: [], prompt: { version: 2, status: "生效中", text: "saved" } });
    if (url === "/api/runs/run-a") return response({ board: { run_id: "run-a", task: "task", phase: "PRODUCT_SPEC" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 8;
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "PRODUCT_SPEC" }, prompts: { current: { product: { version: 2, text: "latest saved" } } } };
  web.state.departmentData.set("run-a/product", { department: "product", prompt: { version: 1, status: "adopted", text: "old" }, prompt_latest: { version: 2, status: "pending", text: "latest saved" } });
  assert.match(web.promptMarkup("product", web.state.departmentData.get("run-a/product")), /实际使用 v1/);
  assert.match(web.promptMarkup("product", web.state.departmentData.get("run-a/product")), /待下次激活 v2/);
  web.openPromptDialog("run-a/product");
  assert.equal(nodes.get("dw-prompt-text").value, "latest saved");
  nodes.get("dw-prompt-text").value = "new prompt";
  const first = web.savePrompt({ preventDefault() {}, submitter: { value: "default" } });
  const second = web.savePrompt({ preventDefault() {}, submitter: { value: "default" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.filter(item => item[0].includes("/prompts/")).length, 1);
  web.state.runId = "run-b";
  web.state.routeToken = 9;
  release();
  await Promise.all([first, second]);
  assert.equal(calls.filter(item => item[0].includes("/prompts/")).length, 1);
  assert.equal(calls[0][0], "/api/runs/run-a/prompts/product");
  assert.deepEqual(JSON.parse(calls[0][1].body), { text: "new prompt" });
  assert.equal(web.state.promptDrafts["run-a/product"], "new prompt");
});

test("HTTP 200 with non-JSON body fails explicitly", async () => {
  const web = loadApp(async () => ({ ok: true, status: 200, statusText: "OK", async text() { return "not-json"; } }));
  await assert.rejects(() => web.fetchJSON("/api/runs"), /响应不是有效 JSON/);
});

test("late run projection cannot overwrite a newer selected task", async () => {
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  const web = loadApp(async url => {
    if (url === "/api/runs/run-old") { await hold; return response({ board: { run_id: "run-old", task: "old", phase: "DONE" } }); }
    return response({ board: { run_id: "run-new", task: "new", phase: "ENGINEERING" } });
  });
  web.state.runId = "run-old";
  web.state.routeToken = 10;
  const pending = web.loadRunPayload("run-old", 10);
  web.state.runId = "run-new";
  web.state.routeToken = 11;
  release();
  await pending;
  assert.equal(web.state.runPayload, null);
});

test("department guidance labels distinguish explanation from verified action", () => {
  assert.match(APP_JS, /explained: "已解释"/);
  assert.match(APP_JS, /completed: "动作已核实"/);
  assert.match(APP_JS, /received: "已接收"/);
  assert.match(APP_JS, /in_input: "已进入模型输入"/);
  assert.doesNotMatch(APP_JS, /completed: "已处理"/);
});

test("department context renders its own attempt id and exposes guidance controls", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.runId = "run-a";
  web.state.view = "department";
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING", active_department: "engineering" } };
  web.state.departmentData.set("run-a/engineering", { run_id: "run-a", department: "engineering", task: "long task", role: "实现与交付", status: "running", history: { engineering_plan: { objective: "short engineering objective" } }, messages: [], contexts: [{ id: "attempt-exact", title: "Context", body: "body", snapshot_at: "2026-09-06T00:00:00Z" }], provider: {}, prompt: null });
  web.renderDepartment("engineering");
  assert.match(nodes.get("dw-main").innerHTML, /short engineering objective/);
  assert.match(nodes.get("dw-main").innerHTML, /data-observe-attempt="attempt-exact"/);
  assert.match(nodes.get("dw-main").innerHTML, /data-dept-draft/);
  assert.match(nodes.get("dw-main").innerHTML, /发送指导/);
  assert.match(APP_JS, /function addDepartmentGuidance\(form\)/);
  assert.match(APP_JS, /departments\/\$\{encodeURIComponent\(department\)\}\/guidance/);
});

test("department guidance posts to the captured run and keeps the draft scoped", async () => {
  const { document, nodes } = uiDocument();
  const calls = [];
  const web = loadApp(async (url, options = {}) => {
    calls.push([url, options]);
    if (url.includes("/guidance")) return response({ ok: true, guidance_id: "guidance-1", status: "received" }, 201);
    if (url.endsWith("/departments/engineering")) return response({ run_id: "run-a", department: "engineering", guidance: [], contexts: [], messages: [], history: {}, materials: {}, provider: {}, prompt: null });
    if (url === "/api/runs/run-a") return response({ board: { run_id: "run-a", task: "task", phase: "ENGINEERING" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    return response({});
  }, document);
  web.state.runId = "run-a";
  web.state.view = "department";
  web.state.department = "engineering";
  web.state.routeToken = 4;
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING" } };
  const textarea = { value: "  inspect the boundary  " };
  const form = {
    dataset: { departmentForm: "engineering" },
    querySelector(selector) { return selector === "[data-dept-draft]" ? textarea : null; },
  };
  await web.addDepartmentGuidance(form);
  assert.equal(calls[0][0], "/api/runs/run-a/departments/engineering/guidance");
  assert.deepEqual(JSON.parse(calls[0][1].body), { text: "  inspect the boundary  " });
  assert.equal(web.state.deptDrafts["run-a/engineering"], undefined);
});

test("Context defaults to the latest work snapshot and renders its own source parts", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.runId = "run-a";
  web.state.view = "department";
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING", active_department: "engineering" } };
  web.state.departmentData.set("run-a/engineering", { run_id: "run-a", department: "engineering", task: "task", role: "实现与交付", status: "running", contexts: [{ id: "attempt-old", purpose: "work", title: "旧快照", meta: "旧" }, { id: "attempt-compact", purpose: "compaction", title: "压缩快照", meta: "中间" }, { id: "attempt-new", purpose: "work", title: "最新快照", meta: "新" }], history: {}, materials: {}, provider: {}, prompt: null });
  web.state.contextDetails.set("run-a/attempt-new", { context: { parts: [{ source: "intend", version: "2", text: "用户原文正文", digest: "sha256:intend" }, { source: "department_rules", version: "1", text: "部门规则正文", digest: "sha256:rules" }] } });
  web.renderDepartment("engineering");
  const html = nodes.get("dw-main").innerHTML;
  assert.match(html, /data-context-id="attempt-new"[^>]*aria-pressed="true"/);
  assert.match(html, /用户原文/);
  assert.match(html, /部门规则/);
  assert.match(html, /用户原文正文/);
  assert.match(html, /data-observe-attempt="attempt-new"/);
  assert.match(html, /data-context-id="attempt-old" aria-pressed="false"/);
});

test("selected Context source is fetched by its exact attempt id", async () => {
  const calls = [];
  const web = loadApp(async url => {
    calls.push(url);
    return response({ run_id: "run-a", attempt: { id: "attempt-exact" }, context: { parts: [{ source: "intend", version: "1", text: "body", digest: "sha256:body" }] } });
  });
  web.state.runId = "run-a";
  web.state.routeToken = 2;
  await web.loadContextDetail("attempt-exact", 2);
  assert.deepEqual(calls, ["/api/runs/run-a/model-attempts/attempt-exact"]);
  assert.equal(web.state.contextDetails.get("run-a/attempt-exact").context.parts[0].source, "intend");
});

test("terminal overview marks each delivery from its own QA evidence", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.runId = "run-done";
  web.state.runPayload = {
    board: { run_id: "run-done", task: "task", phase: "DONE", active_department: null },
    timeline: {},
    evidence: {
      deliveries: [
        { content_hash: "old", parent_hash: null, created_event_id: "delivery-old", revision: 1, status: "superseded", summary: "old" },
        { content_hash: "new", parent_hash: "old", created_event_id: "delivery-new", revision: 2, status: "active", summary: "new" },
      ],
      reviews: [
        { delivery_spec_hash: "old", created_event_id: "review-old", verdict: "rework_engineering", rationale: "rework" },
        { delivery_spec_hash: "new", created_event_id: "review-new", verdict: "release", rationale: "released" },
      ],
    },
    events: [
      { event_id: "delivery-old", seq: 1, created_at: "2026-09-06T00:00:01Z" },
      { event_id: "review-old", seq: 2, created_at: "2026-09-06T00:00:02Z" },
      { event_id: "delivery-new", seq: 3, created_at: "2026-09-06T00:00:03Z" },
      { event_id: "review-new", seq: 4, created_at: "2026-09-06T00:00:04Z" },
    ],
  };
  web.renderOverview();
  assert.match(nodes.get("dw-main").innerHTML, /已验收/);
  assert.match(nodes.get("dw-main").innerHTML, /已被后续交付接续/);
  assert.match(nodes.get("dw-main").innerHTML, /任务.*已完成/);
});

test("Git event detail preserves exact diff and archived file download links", async () => {
  const { document, nodes } = uiDocument();
  const diff = "diff --git a/PRD.md b/PRD.md\n+保留原文\n";
  const web = loadApp(async url => {
    assert.equal(url, "/api/runs/run-a/events/event-1");
    return response({ event_id: "event-1", git_version_detail: { commit: "c", parent_commit: "p", tree: "t", diff, files: [{ path: "PRD.md", status: "M", binary: false }] }, tree_archive: { tree: { files: [{ path: "dist/report.csv", size: 4 }] } } });
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 1;
  await web.openEvent("event-1", "git");
  assert.equal(nodes.get("dw-event-title").textContent, "Git 变更");
  assert.equal(nodes.get("dw-event-document").textContent, diff);
  assert.equal(nodes.get("dw-event-files").children[0].textContent, "修改 PRD.md");
  assert.equal(nodes.get("dw-event-sources").children[0].href, "/api/runs/run-a/events/event-1/files?path=dist%2Freport.csv");
});

test("older event detail cannot replace a newer event selection", async () => {
  const { document, nodes } = uiDocument();
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  const web = loadApp(async url => {
    if (url.endsWith("/old")) { await hold; return response({ event_id: "old", git_version_detail: { diff: "stale", files: [] } }); }
    return response({ event_id: "new", git_version_detail: { diff: "newest", files: [] } });
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 1;
  const old = web.openEvent("old", "git");
  await web.openEvent("new", "git");
  release();
  await old;
  assert.equal(nodes.get("dw-event-document").textContent, "newest");
});

test("cancelled attempts are labeled and remain filterable in the observation route", async () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async url => {
    if (url.includes("/model-attempts")) {
      return response({ items: [{ id: "c1", status: "cancelled", department: "product" }], total: 1, total_attempts: 1, running_attempts: 0, prepared_attempts: 0, next_cursor: null });
    }
    return response({ total_attempts: 1, totals: {}, groups: { departments: [], models: [] } });
  }, document);
  web.state.runId = "run-1";
  web.state.view = "observability";
  web.state.observationData = {
    items: [{ id: "c1", status: "cancelled", department: "product" }],
    total: 1,
    total_attempts: 1,
    running_attempts: 0,
    prepared_attempts: 0,
    next_cursor: null,
  };
  web.renderObservability();
  const html = pageHtml(nodes);
  assert.match(html, /已取消/);
  assert.doesNotMatch(html, />cancelled</);
  assert.match(html, /<option value="cancelled"[^>]*>取消<\/option>/);
  await web.changeHandler({
    target: {
      value: "cancelled",
      matches(selector) { return selector.includes("data-obs-status"); },
    },
  });
  assert.equal(web.state.observationFilters.status, "cancelled");
  assert.match(web.location.search, /status=cancelled/);
});

test("usage totals show sourced cost and do not zero mixed or missing currency", () => {
  const web = loadApp();
  web.state.usageData = {
    cost_status: "reported",
    currency: "CNY",
    coverage: { attempts: 1, reported_attempts: 1, percent: 100, fields: {} },
    totals: { input_tokens: 12, output_tokens: 3, cache_read_tokens: null, total_tokens: 15, cost: 1 },
    groups: { departments: [], models: [] },
  };
  assert.match(web.usageMarkup(), /成本<\/span><strong>1 CNY/);

  web.state.usageData = {
    cost_status: "mixed_currency",
    currency: null,
    coverage: { attempts: 2, reported_attempts: 2, percent: 100, fields: {} },
    totals: { input_tokens: 12, output_tokens: 3, cache_read_tokens: null, total_tokens: 15, cost: null },
    groups: {
      departments: [{
        key: "engineering",
        label: "工程部",
        cost: null,
        currency: null,
        cost_status: "mixed_currency",
        coverage: { reported_attempts: 2, attempts: 2, fields: {} },
      }],
      models: [],
    },
  };
  const mixed = web.usageMarkup();
  assert.equal((mixed.match(/成本<\/span><strong>不可合计/g) || []).length, 2);
  assert.doesNotMatch(mixed, /成本<\/span><strong>0/);
  assert.doesNotMatch(mixed, /成本<\/span><strong>未上报/);

  web.state.usageData = {
    cost_status: "missing",
    currency: null,
    coverage: { attempts: 1, reported_attempts: 0, percent: 0, fields: {} },
    totals: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null },
    groups: { departments: [], models: [] },
  };
  const missing = web.usageMarkup();
  assert.match(missing, /成本<\/span><strong>未上报/);
  assert.doesNotMatch(missing, /成本<\/span><strong>0/);
  assert.doesNotMatch(missing, /不可合计/);
});

test("popstate reloads the URL run and keeps drafts keyed by run", async () => {
  const { document, nodes } = uiDocument();
  const calls = [];
  const web = loadApp(async url => {
    calls.push(url);
    if (url === "/api/runs/run-a") {
      return response({ board: { run_id: "run-a", task: "alpha task", phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    }
    if (url === "/api/runs/run-b") {
      return response({ board: { run_id: "run-b", task: "beta task", phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    }
    return response({});
  }, document);
  web.state.runs = [
    { run_id: "run-a", task: "alpha task" },
    { run_id: "run-b", task: "beta task" },
  ];
  web.state.runId = "run-b";
  web.state.routeToken = 6;
  web.state.runPayload = { board: { run_id: "run-b", task: "beta task", phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] };
  web.state.globalDrafts = { "run-a": "draft-a-only", "run-b": "draft-b-only" };
  web.renderOverview();
  assert.match(nodes.get("dw-main").innerHTML, /beta task/);
  assert.match(nodes.get("dw-main").innerHTML, /draft-b-only/);
  web.location.search = "?run=run-a";
  await web.handlePopState();
  const html = nodes.get("dw-main").innerHTML;
  assert.equal(web.state.runId, "run-a");
  assert.equal(calls.includes("/api/runs/run-a"), true);
  assert.match(html, /<h1>alpha task<\/h1>/);
  assert.doesNotMatch(html, /<h1>beta task<\/h1>/);
  assert.match(html, /draft-a-only/);
  assert.doesNotMatch(html, /draft-b-only/);
});

test("silent run refresh refetches the visible department and open attempt", async () => {
  const { document } = uiDocument();
  const calls = [];
  const web = loadApp(async url => {
    calls.push(url);
    if (url === "/api/runs/run-a") {
      return response({ board: { run_id: "run-a", task: "task", phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] });
    }
    if (url.includes("/departments/engineering")) {
      return response({ run_id: "run-a", department: "engineering", history: { engineering_plan: { objective: "short objective" } }, contexts: [], messages: [], provider: {}, prompt: null });
    }
    if (url.includes("/model-attempts/attempt-1")) {
      return response({ attempt: { id: "attempt-1", status: "running", department: "engineering" }, request: { n: 1 }, response: { n: 2 } });
    }
    return response({});
  }, document);
  web.state.runId = "run-a";
  web.state.routeToken = 4;
  web.state.view = "department";
  web.state.department = "engineering";
  web.state.runPayload = { board: { run_id: "run-a", task: "task", phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] };
  web.state.departmentData.set("run-a/engineering", { department: "engineering", history: { engineering_plan: { objective: "cached" } }, contexts: [], messages: [] });
  await web.loadRunPayload("run-a", 4, true);
  assert.equal(calls.some(url => url.includes("/departments/engineering")), true);

  calls.length = 0;
  web.state.view = "observability";
  web.state.observationScreen = "detail";
  web.state.selectedAttemptId = "attempt-1";
  web.state.observationDetail = { attempt: { id: "attempt-1", status: "running", department: "engineering" }, request: {}, response: null };
  await web.handleLoopEvent("run-a", 4);
  assert.equal(calls.some(url => url.includes("/model-attempts/attempt-1")), true);
});

test("observation chrome uses the short department target instead of the intend blob", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  const blob = `intend-blob-${"x".repeat(188)}`;
  web.state.runId = "run-a";
  web.state.view = "observability";
  web.state.runPayload = { board: { run_id: "run-a", task: blob, phase: "ENGINEERING", active_department: "engineering" }, timeline: {}, evidence: {}, inputs: [], events: [] };
  web.state.departmentData.set("run-a/engineering", { department: "engineering", history: { engineering_plan: { objective: "short objective" } } });
  web.state.observationData = { items: [], total: 0, total_attempts: 0, running_attempts: 0, prepared_attempts: 0 };
  web.renderObservability();
  let html = nodes.get("dw-main").innerHTML;
  assert.match(html, /<strong>short objective<\/strong>/);
  assert.doesNotMatch(html, new RegExp(blob));

  web.state.observationDetail = {
    attempt: { id: "attempt-1", department: "engineering", logical_call_id: "call-1", attempt: 1, attempt_count: 1, status: "success" },
    siblings: [],
  };
  web.renderObservationDetail();
  html = nodes.get("dw-main").innerHTML;
  assert.match(html, /<strong>short objective<\/strong>/);
  assert.doesNotMatch(html, new RegExp(blob));
});

test("request response and event raw json stay in a viewport scroller", () => {
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-detail-panel \.dw-json,\s*#department-workspace-prototype \.dw-event-raw \.dw-json \{ max-height: min\(50vh, 24rem\); overflow: auto; \}/);
  assert.match(STYLES_CSS, /@media \(max-width: 320px\) \{[^}]*#department-workspace-prototype \.dw-detail-panel \.dw-json,\s*#department-workspace-prototype \.dw-event-raw \.dw-json \{ max-height: min\(50vh, 24rem\); overflow: auto; \}/);
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.runId = "run-a";
  web.state.observationDetail = {
    attempt: { id: "attempt-1", status: "success", department: "engineering", logical_call_id: "call-1", attempt: 1, attempt_count: 1 },
    request: { blob: "r".repeat(64 * 1024) },
    response: { blob: "s".repeat(1024) },
    events: [{ type: "model_message", summary: "raw", raw: { blob: "e".repeat(1024) } }],
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
  web.state.runId = "run-a";
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
    assert.equal(html.split('class="dw-json"').length - 1, 1, `${tab} page has no second JSON container`);
    assert.doesNotMatch(html, /…|截断|下载原文|展开全部|dw-json-truncated|dw-json-download/, `${tab} tab has no truncation or download branch`);
  }
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-json \{[^}]*white-space: pre-wrap; overflow-wrap: anywhere; \}/);
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-detail-panel \{[^}]*min-width: 0; \}/);
  assert.match(STYLES_CSS, /#department-workspace-prototype \.dw-detail-panel \.dw-json,\s*#department-workspace-prototype \.dw-event-raw \.dw-json \{ max-height: min\(50vh, 24rem\); overflow: auto; \}/);
});

test("observation list and detail show requested and actual identity separately", () => {
  const { document, nodes } = uiDocument();
  const web = loadApp(async () => response({}), document);
  web.state.runId = "run-a";
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
