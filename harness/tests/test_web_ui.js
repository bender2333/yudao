const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "web", "static");
const APP_JS = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const INDEX_HTML = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const STYLES_CSS = fs.readFileSync(path.join(staticDir, "styles.css"), "utf8");

function loadApp(fetchImpl = async () => ({ ok: true, status: 200, statusText: "OK", async text() { return "{}"; } }), document = { getElementById() { return null; } }) {
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
    EventSource: undefined,
    __HARNESS_SKIP_BOOT__: true,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(APP_JS, sandbox);
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
  root.querySelector = selector => selector === ".dw-action-error" ? node("dw-action-error") : null;
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
    if (url.includes("/model-attempts")) return response({ items: [{ id: "attempt-1", status: "failed", usage: { input_tokens: null, output_tokens: null, cache_read_tokens: null, total_tokens: null, cost: null, latency_ms: 0 } }], total: 1, next_cursor: null });
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
  web.state.departmentData.set("run-a/product", { department: "product", prompt: { text: "old" } });
  web.openPromptDialog("run-a/product");
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

test("department context renders its own attempt id and keeps guidance disabled", () => {
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
