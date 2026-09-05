const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_JS = fs.readFileSync(path.join(__dirname, "..", "web", "static", "app.js"), "utf8");

function makeEl(id) {
  const listeners = {};
  return {
    id,
    tagName: "DIV",
    hidden: true,
    disabled: false,
    textContent: "",
    innerHTML: "",
    value: "",
    type: "button",
    className: "",
    dataset: {},
    style: {},
    classList: {
      add() {},
      toggle() {},
      contains() {
        return false;
      },
    },
    children: [],
    addEventListener(type, fn) {
      (listeners[type] ||= []).push(fn);
    },
    replaceChildren() {
      this.children = [];
      this.innerHTML = "";
    },
    append(...nodes) {
      this.children.push(...nodes);
    },
    appendChild(node) {
      this.children.push(node);
      return node;
    },
    querySelectorAll() {
      return [];
    },
    showModal() {},
  };
}

function makeDocument() {
  const nodes = new Map();
  for (const id of [
    "status",
    "provider-alert",
    "exec-alert",
    "btn-start",
    "btn-cancel",
    "runs",
    "run-empty",
    "board-body",
    "timeline-body",
    "evidence-body",
    "context-body",
    "event-json",
    "event-dialog",
  ]) {
    nodes.set(id, makeEl(id));
  }
  return {
    nodes,
    getElementById(id) {
      return nodes.get(id) || null;
    },
    querySelectorAll() {
      return [];
    },
    createElement(tag) {
      return makeEl(tag);
    },
  };
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    async text() {
      return JSON.stringify(payload);
    },
  };
}

function runPayload(runId, extra = {}) {
  return {
    board: {
      run_id: runId,
      phase: extra.phase || "PRODUCT_SPEC",
      outcome: extra.outcome || "",
      active_department: extra.active_department || "product",
      waiting_reason: "",
      stop_reason: extra.stop_reason || "",
      cycle_count: 0,
      max_cycles: 8,
      token_used: 0,
      token_budget: 100000,
      provider: "fake",
      task: extra.task || "task",
      human_action: "",
      error: extra.error || "",
    },
    aggregates: { latency_ms: 0, tool_count: 0, ask_count: 0, rework_count: 0 },
    timeline: { specs: [], asks: [], reactions: [], transitions: [] },
    evidence: { deliveries: [], reviews: [], rejections: [] },
    context: { manifests: [] },
    events: extra.events || [],
    execution_error: extra.execution_error || null,
    worker_active: Boolean(extra.worker_active),
  };
}

function loadApp(fetchImpl) {
  const document = makeDocument();
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    setImmediate,
    clearImmediate,
    fetch: fetchImpl,
    document,
    EventSource: class {
      constructor() {}
      close() {}
      addEventListener() {}
    },
    encodeURIComponent,
    URL,
    Promise,
    Map,
    Set,
    JSON,
    Error,
    Boolean,
    Number,
    String,
    Array,
    Object,
    Math,
    Date,
    parseInt,
    Number: globalThis.Number,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(APP_JS, sandbox);
  return { web: sandbox.harnessWeb, document, sandbox };
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test("scheduleRefresh of B runs after in-flight A when switching gen", async () => {
  let releaseA;
  const holdA = new Promise((resolve) => {
    releaseA = resolve;
  });
  const calls = [];
  const { web } = loadApp(async (url) => {
    const path = new URL(url, "http://local.test").pathname;
    calls.push(path);
    if (path === "/api/runs/A") {
      await holdA;
      return jsonResponse(runPayload("A", { phase: "PRODUCT_SPEC" }));
    }
    if (path === "/api/runs/B") return jsonResponse(runPayload("B", { phase: "ENGINEERING" }));
    if (path === "/api/runs") return jsonResponse({ runs: [] });
    if (path === "/api/health") {
      return jsonResponse({
        ok: true,
        busy: false,
        active_run_id: null,
        provider_available: true,
        provider_message: "",
        worker_error: null,
      });
    }
    return jsonResponse({ error: path }, 404);
  });

  web.state.gen = 1;
  web.state.runId = "A";
  web.scheduleRefresh("A", 1);
  await flush();
  web.state.gen = 2;
  web.state.runId = "B";
  web.scheduleRefresh("B", 2);
  releaseA();
  await flush();
  await flush();
  assert.ok(
    calls.includes("/api/runs/B"),
    `B refresh missing, calls=${JSON.stringify(calls)}`,
  );
  assert.equal(web.state.runId, "B");
});

test("pollWorkerHealth re-enables start after delayed busy=false without SSE", async () => {
  let busy = true;
  const healthCalls = [];
  const { web, document } = loadApp(async (url) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/health") {
      healthCalls.push(busy);
      return jsonResponse({
        ok: true,
        busy,
        active_run_id: busy ? "run-a" : null,
        provider_available: true,
        provider_message: "",
        worker_error: null,
      });
    }
    if (path === "/api/runs/run-a") return jsonResponse(runPayload("run-a", { phase: "FAILED", stop_reason: "cancelled" }));
    if (path === "/api/runs") return jsonResponse({ runs: [] });
    return jsonResponse({ error: path }, 404);
  });

  web.state.gen = 1;
  web.state.runId = "run-a";
  web.state.busy = true;
  web.state.activeRunId = "run-a";
  web.state.selectedPhase = "FAILED";
  web.syncButtons();
  assert.equal(document.getElementById("btn-start").disabled, true);
  web.syncWorkerWatch();

  await web.pollWorkerHealth();
  assert.equal(document.getElementById("btn-start").disabled, true);
  assert.equal(healthCalls.length, 1);

  busy = false;
  await web.pollWorkerHealth();
  await flush();
  await flush();
  web.stopWorkerWatch();
  assert.equal(web.state.busy, false);
  assert.equal(document.getElementById("btn-start").disabled, false);
  assert.ok(healthCalls.length >= 2);
});

test("late worker_error for selected run appears from health without new events", async () => {
  const { web, document } = loadApp(async (url) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/health") {
      return jsonResponse({
        ok: true,
        busy: false,
        active_run_id: null,
        provider_available: true,
        provider_message: "",
        worker_error: { run_id: "run-a", message: "late-boom" },
      });
    }
    return jsonResponse({ error: path }, 404);
  });
  web.state.gen = 1;
  web.state.runId = "run-a";
  web.state.busy = true;
  web.state.activeRunId = "run-a";
  web.syncButtons();
  await web.pollWorkerHealth();
  web.stopWorkerWatch();
  const alert = document.getElementById("exec-alert");
  assert.equal(alert.hidden, false);
  assert.equal(alert.textContent, "late-boom");
  assert.equal(web.state.busy, false);
  assert.equal(document.getElementById("btn-start").disabled, false);
});

test("worker_error of another run does not fill exec-alert", async () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.state.runId = "run-b";
  web.applyExecAlert(null, { worker_error: { run_id: "run-a", message: "old-boom" } });
  const alert = document.getElementById("exec-alert");
  assert.equal(alert.textContent, "");
  assert.equal(alert.hidden, true);

  web.applyExecAlert({ board: { run_id: "run-b" }, execution_error: null }, { worker_error: { run_id: "run-a", message: "old-boom" } });
  assert.equal(alert.textContent, "");

  web.state.runId = "run-a";
  web.applyExecAlert({ board: { run_id: "run-a" }, execution_error: "old-boom" }, { worker_error: { run_id: "run-a", message: "old-boom" } });
  assert.equal(alert.textContent, "old-boom");
  assert.equal(alert.hidden, false);
});

test("overlap pollWorkerHealth does not issue a second health request", async () => {
  let release;
  const hold = new Promise((resolve) => {
    release = resolve;
  });
  let healthCount = 0;
  const { web } = loadApp(async (url) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/health") {
      healthCount += 1;
      await hold;
      return jsonResponse({
        ok: true,
        busy: true,
        active_run_id: "run-a",
        provider_available: true,
        provider_message: "",
        worker_error: null,
      });
    }
    return jsonResponse({ error: path }, 404);
  });
  web.state.busy = true;
  web.state.activeRunId = "run-a";
  web.state.runId = "hist";
  const first = web.pollWorkerHealth();
  const second = web.pollWorkerHealth();
  await flush();
  assert.equal(healthCount, 1);
  release();
  await first;
  await second;
  assert.equal(healthCount, 1);
});

function sampleBoard(extra = {}) {
  return {
    run_id: extra.run_id || "run-a",
    phase: extra.phase || "ENGINEERING",
    outcome: extra.outcome || "",
    active_department: extra.active_department || "engineering",
    waiting_reason: extra.waiting_reason || "",
    stop_reason: extra.stop_reason || "",
    cycle_count: 1,
    max_cycles: 8,
    token_used: 10,
    token_budget: 100000,
    provider: "fake",
    task: extra.task || "build echo",
    human_action: "",
    error: "",
    ask_count: extra.ask_count || 0,
    rework_count: extra.rework_count || 0,
  };
}

const emptyAgg = { latency_ms: 0, tool_count: 0, ask_count: 0, rework_count: 0 };

test("cycle band shows 产品 工程 质检 and highlights current department", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(
    sampleBoard({ phase: "ENGINEERING", active_department: "engineering", ask_count: 1, rework_count: 1 }),
    emptyAgg,
    { asks: [{ id: "ask_1", status: "open" }] },
  );
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /产品/);
  assert.match(html, /工程/);
  assert.match(html, /质检/);
  assert.match(html, /cycle-node active/);
  assert.match(html, /实现/);
  assert.match(html, /Ask/);
  assert.match(html, /返工 1/);
});

test("done cycle marks quality and records completion", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(sampleBoard({ phase: "DONE", active_department: "quality", outcome: "done" }), emptyAgg, {});
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /cycle-node done/);
  assert.match(html, /已完成/);
  assert.match(html, /产品/);
});

test("ask phase is visible on the product node and fact line", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(
    sampleBoard({ phase: "ASK_PRODUCT", active_department: "product" }),
    emptyAgg,
    { asks: [{ id: "ask_1" }] },
  );
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /cycle-node active/);
  assert.match(html, /处理 Ask/);
  assert.match(html, /Ask \/ React/);
});
