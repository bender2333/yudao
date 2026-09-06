const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_JS = fs.readFileSync(path.join(__dirname, "..", "web", "static", "app.js"), "utf8");
const STYLES_CSS = fs.readFileSync(path.join(__dirname, "..", "web", "static", "styles.css"), "utf8");

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
    close() {
      el._shown = false;
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
    "event-title",
    "event-document",
    "event-version",
    "event-files",
    "event-sources",
    "event-dialog",
    "task-form",
    "task",
    "btn-new",
    "max_cycles",
    "context_window",
    "input-target", "task-limits", "inputs-body", "prompt-form", "prompt-target",
    "prompt-department", "prompt-text", "prompt-version", "prompt-current-text",
    "prompt-history", "btn-prompt-save",
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
  nodes.get("context_window").value = "32000";
  nodes.get("prompt-department").value = "product";
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
      provider: "fake",
      task: extra.task || "task",
      human_action: "",
      error: extra.error || "",
    },
    aggregates: { latency_ms: 0, tool_count: 0, request_count: 0, rework_count: 0 },
    timeline: { specs: [], requests: [], responses: [], transitions: [] },
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
    provider: extra.provider || "fake",
    adapter: extra.adapter || "fake",
    task: extra.task || "build echo",
    human_action: "",
    error: "",
    request_count: extra.request_count || 0,
    pending_request: extra.pending_request || null,
    rework_count: extra.rework_count || 0,
    retry: extra.retry || null,
  };
}

test("timeline distinguishes the effective contract from an obsolete engineering plan", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  const text = '<img src=x onerror="alert(1)">';
  const oldPlan = {
    content_hash: "plan-old", revision: 1, status: "active", created_event_id: "plan-event",
    effective_contract_hash: "contract-old", objective: text, scope: ["src/"],
    tasks: [{ title: text, outputs: [text], verification: text }],
    assumptions: [{ decision: text, basis: text }], reason: text,
  };
  web.renderTimeline({
    current_product_spec: { goal: "Current product goal" },
    effective_contract: { content_hash: "contract-new", revision: 2, created_event_id: "contract-event" },
    effective_contracts: [
      { content_hash: "contract-old", revision: 1, created_event_id: "old-contract-event" },
      { content_hash: "contract-new", revision: 2, created_event_id: "contract-event" },
    ],
    engineering_plan: oldPlan,
    engineering_plans: [oldPlan],
  });
  const html = document.getElementById("timeline-body").innerHTML;
  assert.match(html, /PRD\.md <span>r2 · 当前有效/);
  assert.match(html, /PLAN\.md <span>r1 · 已失效/);
  assert.match(html, /已被替代/);
  assert.match(html, /专业默认与依据/);
  assert.match(html, /data-event-id="old-contract-event" data-document="prd"/);
  assert.match(html, /data-event-id="plan-event" data-document="plan"/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
});

test("plan original opens exact text and can return to its accepted event", async () => {
  const original = "# PLAN.md\n\n  original <content>\n";
  const { web, document } = loadApp(async () => jsonResponse({
    event_id: "plan-event", plan_markdown: original, payload: { content_hash: "plan-hash" },
  }));
  web.state.runId = "run-a";
  web.state.gen = 4;
  await web.openEvent("plan-event", 4, "plan");
  assert.equal(document.getElementById("event-title").textContent, "PLAN.md");
  assert.equal(document.getElementById("event-document").textContent, original);
  assert.equal(document.getElementById("event-document").hidden, false);
  assert.equal(document.getElementById("event-json").hidden, true);
  const back = document.getElementById("event-sources").children[0];
  assert.equal(back.textContent, "查看接纳记录");
  await back.click();
  assert.equal(document.getElementById("event-document").hidden, true);
  assert.equal(document.getElementById("event-json").hidden, false);
  assert.match(document.getElementById("event-json").textContent, /plan-hash/);
});

test("missing original material is an error without showing stale document text", async () => {
  const { web, document } = loadApp(async () => jsonResponse({ event_id: "contract-event" }));
  web.state.runId = "run-a";
  web.state.gen = 4;
  await web.openEvent("contract-event", 4, "prd");
  assert.equal(document.getElementById("status").textContent, "原文工件不可用");
  assert.equal(document.getElementById("event-dialog")._shown, undefined);
});

test("delivery view opens complete manifest and persisted file downloads", async () => {
  const archive = {
    format: "yudao-tree-archive-v1", tree_digest: "tree-hash",
    tree: { directories: ["empty"], files: [{ path: "assets/original bytes.bin", size: 3, content_hash: "blob-hash" }] },
    blobs: [{ path: "assets/original bytes.bin", artifact: { path: "run-a/aa/blob-hash", content_hash: "blob-hash" } }],
  };
  const { web, document } = loadApp(async () => jsonResponse({ event_id: "delivery-event", tree_archive: archive }));
  web.state.runId = "run-a";
  web.state.gen = 4;
  web.renderEvidence({ deliveries: [{ revision: 1, created_event_id: "delivery-event", files: ["src/echo.py"] }] }, 4);
  assert.match(document.getElementById("evidence-body").innerHTML, /data-event-id="delivery-event" data-document="tree"/);
  await web.openEvent("delivery-event", 4, "tree");
  assert.equal(document.getElementById("event-title").textContent, "完整交付清单");
  assert.deepEqual(JSON.parse(document.getElementById("event-document").textContent), archive);
  const links = document.getElementById("event-sources").children;
  assert.equal(links.length, 2);
  assert.equal(links[1].textContent, "assets/original bytes.bin (3 B)");
  assert.equal(links[1].href, "/api/runs/run-a/events/delivery-event/files?path=assets%2Foriginal%20bytes.bin");
  assert.equal(links[1].download, "original bytes.bin");
});

const emptyAgg = { latency_ms: 0, tool_count: 0, request_count: 0, rework_count: 0 };

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
    sampleBoard({ phase: "ENGINEERING", active_department: "engineering", request_count: 1, rework_count: 1 }),
    emptyAgg,
    { requests: [{ id: "request_1", status: "answered" }] },
  );
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /产品/);
  assert.match(html, /工程/);
  assert.match(html, /质检/);
  assert.match(html, /cycle-node active/);
  assert.match(html, /实现/);
  assert.match(html, /协作 1/);
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

test("retry state shows failed attempt, next attempt, and escapes provider error", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(sampleBoard({ retry: {
    status: "waiting", department: "engineering", attempt: 1, max_attempts: 3,
    next_attempt: 2, delay_sec: 2, last_error: '<provider failure>',
  } }), emptyAgg, {});
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /第 1\/3 次尝试失败/);
  assert.match(html, /2 秒后进行第 2\/3 次尝试/);
  assert.match(html, /&lt;provider failure&gt;/);
  assert.doesNotMatch(html, /<provider failure>/);
});

test("terminal phase takes precedence over stale retry status", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  const retry = {
    status: "waiting", department: "engineering", attempt: 1, max_attempts: 3,
    next_attempt: 2, delay_sec: 2,
  };
  const done = sampleBoard({ phase: "DONE", outcome: "done", retry });
  web.renderBoard(done, emptyAgg, {});
  assert.doesNotMatch(document.getElementById("board-body").innerHTML, /尝试失败|请求中|进行第/);
  web.applyRunStatus({
    board: done,
    events: [],
  }, null);
  assert.equal(document.getElementById("status").textContent, "已完成 run-a");

  const paused = sampleBoard({ phase: "PAUSED", outcome: "paused", retry });
  web.renderBoard(paused, emptyAgg, {});
  assert.doesNotMatch(document.getElementById("board-body").innerHTML, /尝试失败|请求中|进行第/);
});

test("retry event card shows escaped failure and backoff", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderContext({ manifests: [], compactions: [] }, [{
    event_id: "retry-event", seq: 4, type: "model_attempt_failed", role: "engineering",
    state_before: "ENGINEERING", state_after: "ENGINEERING", attempt: 1, max_attempts: 3,
    reason: "provider_error", error: '<connection failure>', retryable: true,
  }], 0);
  const html = document.getElementById("context-body").innerHTML;
  assert.match(html, /模型尝试失败 · 第 1\/3 次尝试/);
  assert.match(html, /&lt;connection failure&gt;/);
  assert.doesNotMatch(html, /<connection failure>/);
});

test("long rejection details stay within the mobile content width", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderEvidence({
    deliveries: [], reviews: [],
    rejections: [{ department: "engineering", phase: "ENGINEERING", errors: [{
      field: "reason", message: "an adjusted plan must explain the changed requirements and include a sufficiently long validation detail to exercise mobile wrapping",
    }] }],
    lesson_candidates: [],
  });
  assert.match(document.getElementById("evidence-body").innerHTML, /<pre>/);
  assert.match(STYLES_CSS, /pre \{[^}]*white-space: pre-wrap;[^}]*overflow-wrap: anywhere;/);
});

test("consultation shows actual recipient and the work to return to without a special phase", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(
    sampleBoard({ phase: "QUALITY", active_department: "product", pending_request: {
      requester: "quality", recipient: "product", request_type: "consultation", return_phase: "QUALITY",
    } }),
    emptyAgg,
    {},
  );
  const html = document.getElementById("board-body").innerHTML;
  assert.match(html, /cycle-node active/);
  assert.match(html, /咨询/);
  assert.match(html, /等待回应/);
  assert.match(html, /质检 → 产品/);
  assert.match(html, /返回 检查/);
  assert.doesNotMatch(html, /cycle-link active/);
});

test("collaboration history separates answers from formal decisions and links action results", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  web.renderTimeline({
    requests: [{ id: "request-1", created_event_id: "request-event", requester: "engineering", recipient: "product",
      request_type: "action", action: "revise_requirements", status: "completed", question: "Required behavior?",
      background: "Current task", expected_result: "Publish the requirement" }],
    responses: [{ request_id: "request-1", created_event_id: "response-event", status: "completed", text: "Published <decision>",
      result_event_ids: ["decision-event"], return_phase: "ENGINEERING", return_work_valid: false }],
    effective_decisions: [{ content_hash: "decision-hash" }],
    product_decisions: [{ created_event_id: "decision-event", content_hash: "decision-hash", statement: "Reject invalid flags",
      rationale: "The public behavior requires this" }],
  });
  const html = document.getElementById("timeline-body").innerHTML;
  assert.match(html, /工程 → 产品 · 修订需求/);
  assert.match(html, /产品正式决定/);
  assert.match(html, /Published &lt;decision&gt;/);
  assert.match(html, /原工作已失效，转到 实现/);
  assert.match(html, /data-event-id="request-event"/);
  assert.match(html, /data-event-id="response-event"/);
  assert.match(html, /data-event-id="decision-event">结果 1/);
});

test("terminated collaboration shows its reason and original closure record", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  web.renderTimeline({
    requests: [{ id: "request-1", created_event_id: "request-event", requester: "product", recipient: "quality",
      request_type: "consultation", status: "cancelled", question: "Review the acceptance approach?" }],
    request_closures: [{ request_id: "request-1", created_event_id: "closed-event", status: "cancelled",
      reason: "The run was cancelled.", return_phase: "PRODUCT_SPEC", return_work_valid: false }],
  });
  const html = document.getElementById("timeline-body").innerHTML;
  assert.match(html, /已取消/);
  assert.match(html, /The run was cancelled\./);
  assert.match(html, /原工作未继续 写规格/);
  assert.match(html, /data-event-id="closed-event">查看关闭记录/);
  assert.doesNotMatch(html, /查看回应/);
});

test("board distinguishes actual provider from adapter and shows reported cost", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderBoard(
    sampleBoard({ adapter: "responses", provider: "blackrouter" }),
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
  assert.match(html, /<dt>适配器<\/dt><dd>responses<\/dd>/);
  assert.match(html, /<dt>供应商<\/dt><dd>blackrouter<\/dd>/);
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

test("context links each model step by its stable source event despite identical hashes", () => {
  const { web, document } = loadApp(async () => jsonResponse({ ok: true }));
  web.renderContext({ manifests: [
    { department: "engineering", step_id: 2, session_id: "session-b", digest: "sha256:second", source_event_id: "model-step-b",
      token_estimate: 900, budget: 32000, request_ref: { content_hash: "sha256:request" },
      injected: [{ source: "department_history" }], excluded: [{ source: "other_department_transcript" }] },
  ] }, [
    { type: "context_assembled", context_digest: "sha256:second", session_id: "session-b", event_id: "wrong-step" },
    { type: "context_assembled", context_digest: "sha256:second", session_id: "session-b", event_id: "model-step-b" },
  ], 0);
  const html = document.getElementById("context-body").innerHTML;
  assert.match(html, /engineering · 第 2 步/);
  assert.match(html, /data-event-id="model-step-b">查看模型输入/);
  assert.doesNotMatch(html, /data-event-id="wrong-step"/);
  assert.match(html, /department_history/);
});

test("context input links remain available outside the recent events window", async () => {
  const { web, document } = loadApp(async (url) => {
    assert.equal(url, "/api/runs/run-a/events/early-model-step");
    return jsonResponse({ model_input: { input: [{ role: "developer", content: "early input" }], tools: [] } });
  });
  web.state.runId = "run-a";
  web.state.gen = 4;
  const button = makeEl("early-input-button");
  button.dataset.eventId = "early-model-step";
  document.getElementById("context-body").querySelectorAll = () => [button];
  web.renderContext({ manifests: [
    { department: "product", step_id: 1, digest: "sha256:early", source_event_id: "early-model-step",
      request_ref: { content_hash: "sha256:input" } },
  ] }, Array.from({ length: 20 }, (_, index) => ({
    seq: index + 100, event_id: `later-${index}`, type: "model_message", role: "quality",
  })), 4);
  assert.match(document.getElementById("context-body").innerHTML, /data-event-id="early-model-step"/);
  await button.click();
  assert.equal(document.getElementById("event-dialog")._shown, true);
  assert.match(document.getElementById("event-json").textContent, /early input/);
});

test("compaction stays visible with source links outside recent events", async () => {
  const { web, document } = loadApp(async (url) => {
    if (url.endsWith("/summary-event")) return jsonResponse({
      compaction_summary: "Department summary <checked>",
      source_events: [{ seq: 3, event_id: "original-message", type: "model_message" }],
    });
    assert.equal(url, "/api/runs/run-a/events/original-message");
    return jsonResponse({ message: { role: "assistant", content: "original uncompressed content" } });
  });
  web.state.runId = "run-a";
  web.state.gen = 2;
  web.renderContext({
    manifests: [{ department: "engineering", step_id: 8, purpose: "compaction", source_event_id: "request-event",
      request_ref: {}, compaction_event_id: "summary-event" }],
    compactions: [{ department: "engineering", step_id: 8, source_event_id: "summary-event" }],
  }, [{ event_id: "latest-event", seq: 99, type: "tool_called" }], 2);
  const html = document.getElementById("context-body").innerHTML;
  assert.match(html, /第 8 步 · 压缩/);
  assert.match(html, /查看摘要与原始记录/);
  assert.match(html, /data-event-id="summary-event"/);
  await web.openEvent("summary-event", 2);
  assert.match(document.getElementById("event-json").textContent, /Department summary <checked>/);
  const sources = document.getElementById("event-sources");
  assert.equal(sources.children.length, 1);
  assert.equal(sources.children[0].textContent, "3. model_message");
  await sources.children[0].click();
  assert.match(document.getElementById("event-json").textContent, /original uncompressed content/);
  assert.equal(sources.children.length, 0);
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
  assert.equal(task.value, "");
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

test("live task accepts exact text and the mobile compose entry keeps its target", async () => {
  const posts = [];
  const { web, document, sandbox } = loadApp(async (url, options) => {
    if (options?.method === "POST") {
      posts.push([url, JSON.parse(options.body)]);
      return jsonResponse({ run_id: "running", phase: "ENGINEERING", input_version: 2 }, 201);
    }
    if (url === "/api/runs/running") return jsonResponse(runPayload("running", { phase: "ENGINEERING", worker_active: true }));
    if (url === "/api/runs") return jsonResponse({ runs: [] });
    return jsonResponse({ busy: true, active_run_id: "running", provider_available: true });
  });
  Object.assign(web.state, { runId: "running", selectedPhase: "ENGINEERING", activeRunId: "running", busy: true });
  sandbox.__mobile = true;
  web.newTask();
  assert.equal(web.inputRunId(), "running");
  assert.equal(document.getElementById("btn-new").title, "补充输入");
  assert.equal(document.getElementById("btn-start").disabled, false);
  assert.match(document.getElementById("input-target").textContent, /当前任务 running/);
  assert.equal(document.getElementById("task-limits").hidden, true);
  const original = "  补充\r\n\n";
  document.getElementById("task").value = original;
  await web.startRun({ preventDefault() {} });
  assert.deepEqual(posts, [["/api/runs/running/inputs", { text: original }]]);
  assert.equal(document.getElementById("task").value, "");
  web.newTask();
  assert.equal(web.inputRunId(), "running");
  assert.equal(document.activeElement, document.getElementById("task"));
  web.stopWorkerWatch();
});

test("submission blocks duplicates only until HTTP returns and preserves text typed meanwhile", async () => {
  let finish;
  let calls = 0;
  const { web, document } = loadApp(async (url, options) => {
    if (options?.method === "POST") {
      calls += 1;
      return new Promise(resolve => { finish = resolve; });
    }
    if (url === "/api/runs/running") return jsonResponse(runPayload("running"));
    if (url === "/api/runs") return jsonResponse({ runs: [] });
    return jsonResponse({ busy: true, active_run_id: "running", provider_available: true });
  });
  Object.assign(web.state, { runId: "running", selectedPhase: "ENGINEERING", busy: true });
  const task = document.getElementById("task");
  task.value = "sent";
  const pending = web.startRun({ preventDefault() {} });
  assert.equal(document.getElementById("btn-start").disabled, true);
  assert.equal(task.disabled, false);
  task.value = "next draft";
  await web.startRun({ preventDefault() {} });
  assert.equal(calls, 1);
  finish(jsonResponse({ run_id: "running" }, 201));
  await pending;
  assert.equal(task.value, "next draft");
  assert.equal(document.getElementById("btn-start").disabled, false);
  web.stopWorkerWatch();
});

test("terminal race keeps raw input and targets a new task without automatic retry", async () => {
  const posts = [];
  const { web, document } = loadApp(async (url, options) => {
    if (options?.method === "POST") {
      posts.push(url);
      return jsonResponse({ error: "ended", reason: "run_terminal" }, 409);
    }
    return jsonResponse({ busy: false, provider_available: true });
  });
  Object.assign(web.state, { runId: "ended", selectedPhase: "QUALITY" });
  const raw = " \r\nKeep me  ";
  document.getElementById("task").value = raw;
  await web.startRun({ preventDefault() {} });
  assert.deepEqual(posts, ["/api/runs/ended/inputs"]);
  assert.equal(document.getElementById("task").value, raw);
  assert.equal(document.getElementById("input-target").textContent, "新任务");
  assert.equal(web.inputRunId(), null);
  web.newTask();
  assert.equal(web.inputRunId(), null);
  assert.equal(document.getElementById("btn-new").title, "新任务");
});

for (const recorded of [true, false]) {
  test(`cancelled input save failure keeps the draft and stopped status (recorded=${recorded})`, async () => {
    const posts = [];
    const message = "执行已取消，但命令原文未形成正式 Git 版本。" + (recorded ? "" : "取消事实也未能保存。");
    const { web, document } = loadApp(async (url, options) => {
      if (options?.method === "POST") {
        posts.push([url, JSON.parse(options.body)]);
        return jsonResponse({ error: message, code: "cancelled_input_not_saved", run_id: "running",
          cancelled: true, cancellation_recorded: recorded }, 503);
      }
      if (url === "/api/runs/running") return jsonResponse(runPayload("running", {
        phase: recorded ? "FAILED" : "PRODUCT_SPEC", stop_reason: recorded ? "cancelled" : "",
        outcome: recorded ? "failed" : "running",
        events: recorded ? [{ type: "run_failed", stop_reason: "cancelled", input_save_failure: { text: " /stop\r\n" } }] : [],
        worker_active: true,
      }));
      if (url === "/api/runs") return jsonResponse({ runs: [] });
      return jsonResponse({ busy: true, active_run_id: "running", provider_available: true });
    });
    Object.assign(web.state, { runId: "running", selectedPhase: "PRODUCT_SPEC", busy: true, activeRunId: "running" });
    const raw = " /stop\r\n";
    document.getElementById("task").value = raw;
    await web.startRun({ preventDefault() {} });
    assert.deepEqual(posts, [["/api/runs/running/inputs", { text: raw }]]);
    assert.equal(document.getElementById("task").value, raw);
    assert.equal(document.body.classList.contains("compose"), true);
    assert.equal(document.getElementById("input-target").textContent, "新任务");
    assert.equal(document.getElementById("btn-cancel").disabled, true);
    assert.equal(web.inputRunId(), null);
    assert.doesNotMatch(document.getElementById("board-body").innerHTML, /class="pill running"/);
    assert.match(document.getElementById("board-body").innerHTML, /class="pill failed"/);
    await web.pollWorkerHealth();
    await web.refreshRun("running", web.state.gen);
    assert.match(document.getElementById("status").textContent, /执行已取消.*未形成正式 Git 版本/);
    assert.match(document.getElementById("exec-alert").textContent, /执行已取消.*未形成正式 Git 版本/);
    if (!recorded) assert.match(document.getElementById("exec-alert").textContent, /取消事实也未能保存/);
    assert.equal(document.getElementById("task").value, raw);
    assert.equal(document.getElementById("btn-cancel").disabled, true);
    assert.equal(posts.length, 1);
    web.stopWorkerWatch();
  });
}

test("cancelled input save failure remains explicit when the status refresh also fails", async () => {
  const { web, document } = loadApp(async (url, options) => {
    if (options?.method === "POST") return jsonResponse({ error: "执行已取消，但命令原文未形成正式 Git 版本。",
      code: "cancelled_input_not_saved", run_id: "running", cancelled: true, cancellation_recorded: false }, 503);
    throw new Error("status storage unavailable");
  });
  Object.assign(web.state, { runId: "running", selectedPhase: "QUALITY", busy: true, activeRunId: "running" });
  document.getElementById("task").value = " /cancel\r\n";
  await web.startRun({ preventDefault() {} });
  assert.equal(document.getElementById("task").value, " /cancel\r\n");
  assert.match(document.getElementById("status").textContent, /执行已取消.*状态刷新失败/);
  assert.match(document.getElementById("exec-alert").textContent, /执行已取消.*未形成正式 Git 版本/);
  assert.equal(document.getElementById("btn-cancel").disabled, true);
  assert.equal(web.inputRunId(), null);
  web.stopWorkerWatch();
});

test("reloading a cancelled task restores its input save failure from the event", async () => {
  const { web, document } = loadApp(async url => {
    if (url === "/api/runs/stopped") return jsonResponse(runPayload("stopped", { phase: "FAILED", stop_reason: "cancelled",
      events: [{ type: "run_failed", stop_reason: "cancelled", input_save_failure: { text: " /cancel\r\n" } }],
    }));
    if (url === "/api/runs") return jsonResponse({ runs: [] });
    return jsonResponse({ busy: false, provider_available: true });
  });
  await web.selectRun("stopped");
  assert.match(document.getElementById("status").textContent, /执行已取消.*未形成正式 Git 版本/);
  assert.match(document.getElementById("exec-alert").textContent, /执行已取消.*未形成正式 Git 版本/);
  assert.equal(document.getElementById("btn-cancel").disabled, true);
  assert.equal(web.inputRunId(), null);
});

test("selected terminal task sends ordinary input as a distinct new task", async () => {
  const posts = [];
  const { web, document } = loadApp(async (url, options) => {
    if (options?.method === "POST") {
      posts.push([url, JSON.parse(options.body)]);
      return jsonResponse({ run_id: "new-run", phase: "PRODUCT_SPEC" }, 201);
    }
    if (url === "/api/runs/new-run") return jsonResponse(runPayload("new-run"));
    if (url === "/api/runs") return jsonResponse({ runs: [] });
    return jsonResponse({ busy: false, provider_available: true });
  });
  Object.assign(web.state, { runId: "done-run", selectedPhase: "DONE" });
  web.syncButtons();
  assert.equal(document.getElementById("input-target").textContent, "新任务");
  document.getElementById("task").value = "  next task\r\n";
  await web.startRun({ preventDefault() {} });
  assert.equal(posts[0][0], "/api/runs");
  assert.equal(posts[0][1].task, "  next task\r\n");
  assert.equal(web.state.runId, "new-run");
});

test("input history exposes original ranges and each product processing state", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  web.renderInputs([
    { version: 1, text: "  initial\n", kind: "text", byte_start: 0, byte_end: 10 },
    { version: 2, text: "<pending>", kind: "text", byte_start: 10, byte_end: 19 },
    { version: 3, text: "  waiting", kind: "text", byte_start: 19, byte_end: 28 },
    { version: 4, text: " /stop\r\n", kind: "command", byte_start: 28, byte_end: 36 },
  ], { processed_input_version: 1, product_work_input_version: 2 }, 1);
  const shown = document.getElementById("inputs-body").innerHTML;
  assert.match(shown, /已进入需求/);
  assert.match(shown, /产品处理中/);
  assert.match(shown, /等待产品处理/);
  assert.match(shown, /取消命令已执行/);
  assert.match(shown, /  initial\n/);
  assert.match(shown, /\[10, 19\)/);
  assert.match(shown, /&lt;pending&gt;/);
  assert.doesNotMatch(shown, /<pending>/);
});

test("prompt editor shows adopted versions and preserves unsaved drafts through refresh and failure", async () => {
  let submitted;
  const { web, document } = loadApp(async (url, options) => {
    submitted = [url, JSON.parse(options.body)];
    return jsonResponse({ error: "network error" }, 500);
  });
  Object.assign(web.state, { runId: "running", selectedPhase: "ENGINEERING" });
  const prompt = { department: "product", version: 2, text: "  saved <prompt>\r\n", prompt_ref: { content_hash: "sha256:abc" }, created_event_id: "saved" };
  const prompts = { current: { product: prompt }, versions: [prompt], activations: [{ department: "product", prompt_version: 2, input_version: 3, activation_id: "active", event_id: "adopted" }] };
  const board = { run_id: "running", phase: "ENGINEERING" };
  web.renderPrompts(prompts, board, 0);
  assert.equal(document.getElementById("prompt-text").value, prompt.text);
  assert.equal(document.getElementById("prompt-current-text").textContent, prompt.text);
  assert.match(document.getElementById("prompt-history").innerHTML, /已采用 1 次/);
  assert.match(document.getElementById("prompt-history").innerHTML, /data-event-id="adopted"/);
  assert.match(document.getElementById("prompt-history").innerHTML, /&lt;prompt&gt;/);
  const raw = "  new prompt\r\n ";
  web.state.promptDrafts["running/product"] = raw;
  web.renderPrompts(prompts, board, 0);
  assert.equal(document.getElementById("prompt-text").value, raw);
  await web.savePrompt({ preventDefault() {} });
  assert.deepEqual(submitted, ["/api/runs/running/prompts/product", { text: raw }]);
  assert.equal(document.getElementById("prompt-text").value, raw);
  assert.equal(web.state.promptDrafts["running/product"], raw);
});

test("formal input requirement plan and delivery versions link their own accepted Git changes", () => {
  const { web, document } = loadApp(async () => jsonResponse({}));
  const first = { commit: "a".repeat(40), parent_commit: null, tree: "b".repeat(40) };
  const later = { commit: "c".repeat(40), parent_commit: first.commit, tree: "d".repeat(40) };
  web.renderInputs([{ version: 1, kind: "text", text: "original", created_event_id: "input", git_version: first }], { processed_input_version: 1 }, 0);
  const input = document.getElementById("inputs-body").innerHTML;
  assert.match(input, /data-event-id="input" data-document="git"/);
  assert.match(input, /初始版本/);
  const contract = { revision: 2, content_hash: "contract", created_event_id: "prd", git_version: later };
  const plan = { revision: 2, status: "active", effective_contract_hash: "contract", created_event_id: "plan", git_version: later };
  web.renderTimeline({ current_product_spec: { goal: "echo", git_version: later, created_event_id: "spec" },
    effective_contract: contract, effective_contracts: [contract], engineering_plan: plan, engineering_plans: [plan] });
  const timeline = document.getElementById("timeline-body").innerHTML;
  assert.match(timeline, /data-event-id="prd" data-document="git"/);
  assert.match(timeline, /data-event-id="plan" data-document="git"/);
  assert.match(timeline, /父提交 aaaaaaaaaaaa/);
  web.renderEvidence({ deliveries: [{ created_event_id: "delivery", git_version: later }] });
  assert.match(document.getElementById("evidence-body").innerHTML, /data-event-id="delivery" data-document="git"/);
});

test("Git details display the exact diff as text with binary files and archived downloads", async () => {
  const diff = "diff --git a/specs/PRD.md b/specs/PRD.md\n-old\n+<script>alert(1)</script>\n";
  const version = { commit: "c".repeat(40), parent_commit: "a".repeat(40), tree: "d".repeat(40), diff,
    files: [{ path: "specs/PRD.md", status: "M", binary: false }, { path: "code/assets/image.bin", status: "A", binary: true }] };
  const { web, document } = loadApp(async () => jsonResponse({ event_id: "accepted", git_version_detail: version,
    tree_archive: { tree: { files: [{ path: "assets/image.bin", size: 3 }] } } }));
  web.state.runId = "run";
  await web.openEvent("accepted", 0, "git");
  assert.equal(document.getElementById("event-title").textContent, "Git 变更");
  assert.equal(document.getElementById("event-document").textContent, diff);
  assert.equal(document.getElementById("event-document").innerHTML, "");
  assert.match(document.getElementById("event-version").textContent, /父提交 aaaaaaaaaa/);
  const files = document.getElementById("event-files").children;
  assert.deepEqual(files.map(item => item.textContent), ["修改 specs/PRD.md", "新增 code/assets/image.bin（二进制）"]);
  const archive = document.getElementById("event-sources").children.at(-1);
  assert.equal(archive.href, "/api/runs/run/events/accepted/files?path=assets%2Fimage.bin");
});

test("missing Git versions report an error and close previously displayed diff", async () => {
  const { web, document } = loadApp(async () => jsonResponse({ error: "Git version cannot be verified" }, 400));
  web.state.runId = "run";
  document.getElementById("event-document").textContent = "stale diff";
  document.getElementById("event-dialog").showModal();
  await web.openEvent("missing", 0, "git");
  assert.equal(document.getElementById("status").textContent, "Git version cannot be verified");
  assert.equal(document.getElementById("event-document").textContent, "");
  assert.equal(document.getElementById("event-dialog")._shown, false);
});

test("an older Git lookup cannot replace a newer selected event", async () => {
  let first;
  const version = { commit: "c", parent_commit: null, tree: "t", files: [], diff: "newest" };
  const { web, document } = loadApp(async (url) => url.endsWith("old")
    ? new Promise(resolve => { first = resolve; }) : jsonResponse({ git_version_detail: version }));
  web.state.runId = "run";
  const old = web.openEvent("old", 0, "git");
  await web.openEvent("new", 0, "git");
  first(jsonResponse({ git_version_detail: { ...version, diff: "stale" } }));
  await old;
  assert.equal(document.getElementById("event-document").textContent, "newest");
  assert.equal(document.getElementById("event-files").children[0].textContent, "无文件变化");
});
