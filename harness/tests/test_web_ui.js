const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_JS = fs.readFileSync(path.join(__dirname, "..", "web", "static", "app.js"), "utf8");

function makeClassList() {
  const names = new Set();
  return {
    add(name) {
      names.add(name);
    },
    remove(name) {
      names.delete(name);
    },
    toggle(name, force) {
      if (force === true) names.add(name);
      else if (force === false) names.delete(name);
      else if (names.has(name)) names.delete(name);
      else names.add(name);
    },
    contains(name) {
      return names.has(name);
    },
  };
}

function makeEl(id) {
  const listeners = {};
  const el = {
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
    classList: makeClassList(),
    children: [],
    addEventListener(type, fn) {
      (listeners[type] ||= []).push(fn);
    },
    async click() {
      await Promise.all((listeners.click || []).map((fn) => fn()));
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
    showModal() {
      el._shown = true;
    },
    focus() {
      el._focused = true;
      if (el.ownerDocument) el.ownerDocument.activeElement = el;
    },
    blur() {
      el._focused = false;
      if (el.ownerDocument && el.ownerDocument.activeElement === el) {
        el.ownerDocument.activeElement = el.ownerDocument.body;
      }
    },
    scrollIntoView() {
      el._scrolled = true;
    },
  };
  return el;
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
    "board",
    "board-body",
    "timeline-body",
    "evidence-body",
    "context-body",
    "event-json",
    "event-dialog",
    "task-form",
    "task",
    "btn-new",
    "max_cycles",
    "token_budget",
    "context_window",
  ]) {
    nodes.set(id, makeEl(id));
  }
  const body = makeEl("body");
  const doc = {
    nodes,
    body,
    activeElement: null,
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
  for (const node of nodes.values()) node.ownerDocument = doc;
  body.ownerDocument = doc;
  nodes.get("max_cycles").value = "8";
  nodes.get("token_budget").value = "100000";
  nodes.get("context_window").value = "32000";
  return doc;
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
    evidence: { deliveries: [], reviews: [], rejections: [], lesson_candidates: [] },
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
    matchMedia(query) {
      return {
        matches: Boolean(sandbox.__mobile) && String(query).includes("960"),
        media: query,
        addListener() {},
        removeListener() {},
        addEventListener() {},
        removeEventListener() {},
      };
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
  sandbox.__HARNESS_SKIP_BOOT__ = true;
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
    provider: extra.provider || "fake",
    task: extra.task || "build echo",
    human_action: "",
    error: "",
    ask_count: extra.ask_count || 0,
    rework_count: extra.rework_count || 0,
  };
}

const emptyAgg = { latency_ms: 0, tool_count: 0, ask_count: 0, rework_count: 0 };

function sampleLesson(extra = {}) {
  return {
    id: "lesson-old",
    run_id: "run-a",
    created_event_id: "lesson-event-old",
    source_event_id: "qa-event-old",
    source_type: "qa_review",
    observation: {
      verdict: "rework_engineering",
      rationale: "The edge case needs another check.",
      defects: [{ severity: "major", summary: "Missing empty input case." }],
    },
    suggestion: "Check empty input in the next review.",
    product_spec_hash: "product-hash",
    delivery_spec_hash: "delivery-hash",
    checks: [{ name: "smoke", exit_code: 1 }],
    evidence_refs: [],
    status: "unverified",
    ...extra,
  };
}

function lessonButtons(document, candidate) {
  const buttons = [candidate.created_event_id, candidate.source_event_id].map((id) => {
    const button = makeEl(id);
    button.dataset.eventId = id;
    return button;
  });
  document.getElementById("evidence-body").querySelectorAll = (selector) => {
    assert.equal(selector, ".event-link");
    return buttons;
  };
  return buttons;
}

test("lesson candidates distinguish QA records from unverified suggestions and escape content", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  const injected = '<img src=x onerror="alert(1)">';
  web.renderEvidence({
    lesson_candidates: [sampleLesson({
      id: injected,
      created_event_id: injected,
      source_event_id: injected,
      observation: { verdict: injected, rationale: injected, defects: [{ severity: injected, summary: injected }] },
      suggestion: injected,
    })],
  });
  const html = document.getElementById("evidence-body").innerHTML;
  assert.match(html, /经验候选/);
  assert.match(html, /质检记录/);
  assert.match(html, /待验证建议/);
  assert.match(html, /查看候选/);
  assert.match(html, /查看来源/);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /已确认|根因|尚无交付/);
});

test("failure candidates show recorded reason and message", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  web.renderEvidence({ lesson_candidates: [sampleLesson({
    source_type: "run_failed",
    observation: { stop_reason: "provider_error", message: "Provider returned <invalid> data." },
  })] });
  const html = document.getElementById("evidence-body").innerHTML;
  assert.match(html, /失败记录/);
  assert.match(html, /provider_error/);
  assert.match(html, /Provider returned &lt;invalid&gt; data\./);
  assert.match(html, /待验证建议/);
  assert.doesNotMatch(html, /质检记录/);
});

test("all candidates remain visible when their source is older than the recent event list", async () => {
  const calls = [];
  const { web, document } = loadApp(async (url) => {
    calls.push(url);
    return jsonResponse({ event_id: url.split("/").at(-1) });
  });
  web.state.runId = "run-a";
  web.state.gen = 1;
  const old = sampleLesson();
  const buttons = lessonButtons(document, old);
  const candidates = [old, ...Array.from({ length: 13 }, (_,i) => sampleLesson({ id: `lesson-${i}` }))];
  web.renderEvidence({ lesson_candidates: candidates }, 1);
  const events = [
    { event_id: old.source_event_id, seq: 1, type: "qa_review" },
    { event_id: old.created_event_id, seq: 2, type: "lesson_candidate" },
    ...Array.from({ length: 13 }, (_,i) => ({ event_id: `recent-${i}`, seq: i + 3, type: "tool_result" })),
  ];
  web.renderContext({ manifests: [] }, events, 1);
  const html = document.getElementById("evidence-body").innerHTML;
  assert.equal((html.match(/class="item lesson-candidate"/g) || []).length, 14);
  assert.match(html, /data-event-id="lesson-event-old"/);
  assert.match(html, /data-event-id="qa-event-old"/);
  assert.doesNotMatch(document.getElementById("context-body").innerHTML, /qa-event-old|lesson-event-old/);
  await buttons[0].click();
  assert.equal(JSON.parse(document.getElementById("event-json").textContent).event_id, old.created_event_id);
  await buttons[1].click();
  assert.equal(JSON.parse(document.getElementById("event-json").textContent).event_id, old.source_event_id);
  assert.deepEqual(calls, ["/api/runs/run-a/events/lesson-event-old", "/api/runs/run-a/events/qa-event-old"]);
  assert.equal(document.getElementById("event-dialog")._shown, true);
});

test("old candidate buttons do not request events after changing the selected run", async () => {
  const calls = [];
  const { web, document } = loadApp(async (url) => {
    calls.push(url);
    return jsonResponse({});
  });
  web.state.runId = "run-a";
  web.state.gen = 1;
  const old = sampleLesson();
  const buttons = lessonButtons(document, old);
  web.renderEvidence({ lesson_candidates: [old] }, 1);
  web.state.runId = "run-b";
  web.state.gen = 2;
  await buttons[0].click();
  await buttons[1].click();
  assert.deepEqual(calls, []);
  assert.equal(document.getElementById("event-dialog")._shown, undefined);
});

test("in-flight candidate source results do not replace the newly selected run's event detail", async () => {
  for (const status of [200, 500]) {
    let release;
    const hold = new Promise((resolve) => { release = resolve; });
    const { web, document } = loadApp(async () => {
      await hold;
      return jsonResponse(status === 200 ? { event_id: "old-source" } : { error: "old-error" }, status);
    });
    web.state.runId = "run-a";
    web.state.gen = 1;
    const old = sampleLesson();
    const buttons = lessonButtons(document, old);
    web.renderEvidence({ lesson_candidates: [old] }, 1);
    const pending = buttons[1].click();
    web.state.runId = "run-b";
    web.state.gen = 2;
    document.getElementById("event-json").textContent = "selected-event";
    document.getElementById("status").textContent = "selected-status";
    release();
    await pending;
    assert.equal(document.getElementById("event-json").textContent, "selected-event");
    assert.equal(document.getElementById("status").textContent, "selected-status");
    assert.equal(document.getElementById("event-dialog")._shown, undefined);
  }
});

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

test("board shows reported cost and event model, not adapter as vendor", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(
    sampleBoard({ provider: "omp" }),
    { ...emptyAgg, cost: 0.0123 },
    {},
    [
      { seq: 1, model: "" },
      { seq: 2, model: "acctual-model-v1" },
      { seq: 3, model: "   " },
    ],
  );
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /<dt>费用<\/dt><dd>0\.0123<\/dd>/);
  assert.doesNotMatch(html, /\$/);
  assert.match(html, /<dt>模型<\/dt><dd>acctual-model-v1<\/dd>/);
  assert.doesNotMatch(html, /should-not-use/);
  assert.match(html, /<dt>适配器<\/dt><dd>omp<\/dd>/);
  assert.doesNotMatch(html, /<dt>Provider<\/dt>/);
});

test("zero missing and invalid cost display as 未上报", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  for (const cost of [0, null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -2, "0.5"]) {
    web.renderBoard(sampleBoard(), { ...emptyAgg, cost }, {}, []);
    const html = document.getElementById("board-body").innerHTML;
    assert.match(html, /<dt>费用<\/dt><dd>未上报<\/dd>/, String(cost));
  }
});

test("tiny positive cost is not rounded to zero", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(sampleBoard(), { ...emptyAgg, cost: 1e-8 }, {}, []);
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /<dt>费用<\/dt><dd>1e-8<\/dd>/);
  assert.doesNotMatch(html, /<dt>费用<\/dt><dd>0<\/dd>/);
  assert.doesNotMatch(html, /<dt>费用<\/dt><dd>未上报<\/dd>/);
});

test("missing event model is 未上报 and ignores board.model", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(sampleBoard({ model: "fake-script" }), emptyAgg, {}, [
    { seq: 1, model: null },
    { seq: 2, model: "" },
  ]);
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /<dt>模型<\/dt><dd>未上报<\/dd>/);
  assert.doesNotMatch(html, /fake-script/);
});

test("latest event model follows seq and escapes untrusted text", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  const long = `${"vendor/very-long-model-name-".repeat(6)}<img src=x onerror=alert(1)>`;
  web.renderBoard(sampleBoard(), emptyAgg, {}, [
    { seq: 4, model: "later-wrong-order" },
    { seq: 9, model: long },
    { seq: 2, model: "early" },
  ]);
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /kv-model/);
  assert.match(html, /vendor\/very-long-model-name-/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.doesNotMatch(html, /later-wrong-order/);
  assert.doesNotMatch(html, />early</);
});

test("new-task entry focuses existing input and keeps typed text", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  const task = document.getElementById("task");
  const form = document.getElementById("task-form");
  task.value = "keep this draft";
  web.openCompose();
  assert.equal(document.body.classList.contains("compose"), true);
  assert.equal(document.activeElement, task);
  assert.equal(task.value, "keep this draft");
  assert.equal(form._scrolled, true);
});

test("successful start leaves compose and selects the new run", async () => {
  const { web, document, sandbox } = loadApp(async (url, options) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/runs" && options && options.method === "POST") {
      return jsonResponse({ run_id: "run-new", phase: "PRODUCT_SPEC" }, 201);
    }
    if (path === "/api/runs/run-new") return jsonResponse(runPayload("run-new"));
    if (path === "/api/runs") return jsonResponse({ runs: [] });
    if (path === "/api/health") {
      return jsonResponse({
        ok: true,
        busy: true,
        active_run_id: "run-new",
        provider_available: true,
        provider_message: "",
        worker_error: null,
      });
    }
    return jsonResponse({ error: path }, 404);
  });
  sandbox.__mobile = true;
  const task = document.getElementById("task");
  const board = document.getElementById("board");
  task.value = "ship it";
  web.openCompose();
  await web.startRun({ preventDefault() {} });
  assert.equal(document.body.classList.contains("compose"), false);
  assert.equal(web.state.runId, "run-new");
  assert.equal(task.value, "ship it");
  assert.notEqual(document.activeElement, task);
  assert.equal(board._scrolled, true);
});

test("failed start stays on compose with the same input", async () => {
  const { web, document } = loadApp(async (url, options) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/runs" && options && options.method === "POST") {
      return jsonResponse({ error: "已有任务正在运行", reason: "busy" }, 409);
    }
    if (path === "/api/health") {
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
  const task = document.getElementById("task");
  task.value = "retry me";
  web.openCompose();
  await web.startRun({ preventDefault() {} });
  assert.equal(document.body.classList.contains("compose"), true);
  assert.equal(task.value, "retry me");
  assert.equal(document.activeElement, task);
});

test("scrollBoardIntoView only moves the board on mobile", () => {
  const { web, document, sandbox } = loadApp(async () => jsonResponse({ ok: true }));
  const board = document.getElementById("board");
  sandbox.__mobile = false;
  web.scrollBoardIntoView();
  assert.equal(board._scrolled, undefined);
  sandbox.__mobile = true;
  web.scrollBoardIntoView();
  assert.equal(board._scrolled, true);
});

test("desktop successful start does not force-scroll the board", async () => {
  const { web, document, sandbox } = loadApp(async (url, options) => {
    const path = new URL(url, "http://local.test").pathname;
    if (path === "/api/runs" && options && options.method === "POST") {
      return jsonResponse({ run_id: "run-new", phase: "PRODUCT_SPEC" }, 201);
    }
    if (path === "/api/runs/run-new") return jsonResponse(runPayload("run-new"));
    if (path === "/api/runs") return jsonResponse({ runs: [] });
    if (path === "/api/health") {
      return jsonResponse({
        ok: true,
        busy: true,
        active_run_id: "run-new",
        provider_available: true,
        provider_message: "",
        worker_error: null,
      });
    }
    return jsonResponse({ error: path }, 404);
  });
  sandbox.__mobile = false;
  const task = document.getElementById("task");
  task.value = "desktop";
  web.openCompose();
  await web.startRun({ preventDefault() {} });
  assert.equal(document.body.classList.contains("compose"), false);
  assert.equal(web.state.runId, "run-new");
  assert.equal(document.getElementById("board")._scrolled, undefined);
});
