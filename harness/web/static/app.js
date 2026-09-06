const TERMINAL = new Set(["DONE", "FAILED", "PAUSED"]);
const HEALTH_POLL_MS = 1000;

const state = {
  runId: null,
  source: null,
  gen: 0,
  refreshSeq: 0,
  refreshInFlight: false,
  pendingRefresh: null,
  submittingStart: false,
  submittingCancel: false,
  busy: false,
  activeRunId: null,
  selectedPhase: null,
};

let workerWatchTimer = null;
let workerWatchInFlight = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function t(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return escapeHtml(value);
}

function stillCurrent(runId, gen, seq) {
  return state.runId === runId && state.gen === gen && state.refreshSeq === seq;
}

function setStatus(kind, text) {
  const el = document.getElementById("status");
  if (!el) return;
  el.dataset.kind = kind;
  el.textContent = text;
}

function setAlert(id, text) {
  const el = document.getElementById(id);
  if (!el) return;
  if (text) {
    el.hidden = false;
    el.textContent = text;
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

function syncButtons() {
  const start = document.getElementById("btn-start");
  const cancel = document.getElementById("btn-cancel");
  if (start) start.disabled = state.submittingStart || state.busy;
  if (!cancel) return;
  const selectedLive = Boolean(state.runId) && state.runId === state.activeRunId;
  const selectedRunning = Boolean(state.runId) && state.selectedPhase && !TERMINAL.has(state.selectedPhase);
  cancel.disabled = state.submittingCancel || !state.runId || !(selectedLive || selectedRunning);
}

function applyProviderAlert(health) {
  if (!health) return;
  if (!health.provider_available && health.provider_message) {
    setAlert("provider-alert", health.provider_message);
  } else {
    setAlert("provider-alert", "");
  }
}

function applyExecAlert(runPayload, health) {
  const selected = state.runId;
  if (!selected) {
    setAlert("exec-alert", "");
    return;
  }
  if (runPayload && runPayload.board && runPayload.board.run_id === selected) {
    setAlert("exec-alert", runPayload.execution_error || "");
    return;
  }
  if (health && health.worker_error && health.worker_error.run_id === selected) {
    setAlert("exec-alert", health.worker_error.message || "");
    return;
  }
  if (health && health.worker_error && health.worker_error.run_id !== selected) {
    setAlert("exec-alert", "");
  }
}

async function fetchJSON(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    const err = new Error(error.message || "网络请求失败");
    err.status = 0;
    throw err;
  }
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text };
    }
  }
  if (!response.ok) {
    const err = new Error(data.error || text || response.statusText);
    err.status = response.status;
    err.payload = data;
    throw err;
  }
  return data;
}

function pill(outcome) {
  const label = outcome || "running";
  return `<span class="pill ${t(label, "")}">${t(label)}</span>`;
}

function kv(entries) {
  return `<dl class="kv">${entries
    .map(([key, value, cls]) => `<div${cls ? ` class="${t(cls, "")}"` : ""}><dt>${t(key)}</dt><dd>${t(value)}</dd></div>`)
    .join("")}</dl>`;
}

function formatCost(cost) {
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost <= 0) return "未上报";
  return String(cost);
}

function latestEventModel(events) {
  if (!Array.isArray(events) || !events.length) return "未上报";
  const ordered = events.slice().sort((a, b) => (Number(a && a.seq) || 0) - (Number(b && b.seq) || 0));
  for (let i = ordered.length - 1; i >= 0; i -= 1) {
    const model = ordered[i] && ordered[i].model;
    if (typeof model === "string" && model.trim()) return model;
  }
  return "未上报";
}

function shortHash(value) {
  if (!value) return "—";
  return String(value).replace(/^sha256:/, "").slice(0, 12);
}

function closeSource() {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
}

function startWorkerWatch() {
  if (workerWatchTimer != null) return;
  workerWatchTimer = setInterval(() => {
    pollWorkerHealth();
  }, HEALTH_POLL_MS);
  if (workerWatchTimer && typeof workerWatchTimer.unref === "function") {
    workerWatchTimer.unref();
  }
}

function stopWorkerWatch() {
  if (workerWatchTimer == null) return;
  clearInterval(workerWatchTimer);
  workerWatchTimer = null;
}

function syncWorkerWatch() {
  if (state.busy) startWorkerWatch();
  else stopWorkerWatch();
}

async function pollWorkerHealth() {
  if (workerWatchInFlight) return;
  if (!state.busy && !state.activeRunId) {
    stopWorkerWatch();
    return;
  }
  workerWatchInFlight = true;
  const gen = state.gen;
  const runId = state.runId;
  try {
    const health = await fetchJSON("/api/health");
    applyProviderAlert(health);
    if (gen !== state.gen) return;
    const wasBusy = state.busy;
    state.busy = Boolean(health.busy);
    state.activeRunId = health.active_run_id || null;
    applyExecAlert(null, health);
    syncButtons();
    syncWorkerWatch();
    if (wasBusy && !state.busy && runId && runId === state.runId) {
      scheduleRefresh(state.runId, state.gen);
    }
  } catch (error) {
    if (gen === state.gen) setStatus("error", error.message);
  } finally {
    workerWatchInFlight = false;
  }
}

async function loadHealth(gen) {
  try {
    const health = await fetchJSON("/api/health");
    applyProviderAlert(health);
    if (gen === undefined || gen === state.gen) {
      state.busy = Boolean(health.busy);
      state.activeRunId = health.active_run_id || null;
      applyExecAlert(null, health);
      syncButtons();
      syncWorkerWatch();
    }
    return health;
  } catch (error) {
    if (gen !== undefined && gen !== state.gen) return null;
    setStatus("error", error.message);
    return null;
  }
}

async function loadRuns(runId, gen, seq) {
  const data = await fetchJSON("/api/runs");
  if (seq !== undefined && !stillCurrent(runId, gen, seq)) return data;
  const list = document.getElementById("runs");
  const empty = document.getElementById("run-empty");
  if (!list) return data;
  list.replaceChildren();
  if (!data.runs.length) {
    if (empty) empty.style.display = "block";
    return data;
  }
  if (empty) empty.style.display = "none";
  for (const run of data.runs) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = run.run_id;
    const strong = document.createElement("strong");
    strong.textContent = run.phase;
    const task = document.createElement("span");
    task.className = "muted";
    task.textContent = run.task;
    button.append(strong, document.createElement("br"), task);
    if (run.run_id === state.runId) button.classList.add("active");
    button.addEventListener("click", () => selectRun(run.run_id));
    item.appendChild(button);
    list.appendChild(item);
  }
  return data;
}

async function selectRun(runId) {
  const gen = ++state.gen;
  state.runId = runId;
  state.pendingRefresh = null;
  setAlert("exec-alert", "");
  document.querySelectorAll("#runs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === runId);
  });
  closeSource();
  syncButtons();
  try {
    const data = await refreshRun(runId, gen);
    if (gen !== state.gen || !data) return;
    listen(runId, data.events.at(-1)?.seq || 0, gen);
  } catch (error) {
    if (gen !== state.gen) return;
    setStatus("error", error.message);
  }
}

function scheduleRefresh(runId, gen) {
  if (gen !== state.gen || runId !== state.runId) return;
  if (state.refreshInFlight) {
    state.pendingRefresh = { runId, gen };
    return;
  }
  state.refreshInFlight = true;
  (async () => {
    try {
      let current = { runId, gen };
      while (current && current.gen === state.gen && current.runId === state.runId) {
        state.pendingRefresh = null;
        await refreshRun(current.runId, current.gen);
        current = state.pendingRefresh;
      }
    } catch (error) {
      if (state.gen === gen) setStatus("error", error.message);
    } finally {
      state.refreshInFlight = false;
      const pending = state.pendingRefresh;
      if (pending && pending.gen === state.gen && pending.runId === state.runId) {
        scheduleRefresh(pending.runId, pending.gen);
      }
    }
  })();
}

async function refreshRun(runId, gen) {
  const seq = ++state.refreshSeq;
  const data = await fetchJSON(`/api/runs/${runId}`);
  if (!stillCurrent(runId, gen, seq)) return null;
  renderBoard(data.board, data.aggregates, data.timeline, data.events);
  renderTimeline(data.timeline);
  renderEvidence(data.evidence, gen);
  renderContext(data.context, data.events, gen);
  await loadRuns(runId, gen, seq);
  if (!stillCurrent(runId, gen, seq)) return null;
  const health = await loadHealth(gen);
  if (!stillCurrent(runId, gen, seq)) return null;
  applyRunStatus(data, health);
  syncButtons();
  return data;
}

function applyRunStatus(data, health) {
  const board = data.board;
  state.selectedPhase = board.phase;
  if (health) {
    state.busy = Boolean(health.busy);
    state.activeRunId = health.active_run_id || null;
  } else if (data.worker_active) {
    state.busy = true;
    state.activeRunId = board.run_id;
  }
  applyExecAlert(data, health);
  syncWorkerWatch();
  if (data.execution_error) {
    setStatus("error", "执行中断");
    return;
  }
  if (board.phase === "DONE") setStatus("idle", `已完成 ${board.run_id}`);
  else if (board.phase === "FAILED") setStatus("error", board.error || board.stop_reason || "失败");
  else if (board.phase === "PAUSED") setStatus("conflict", board.human_action || board.stop_reason || "已暂停");
  else setStatus("running", `${board.phase} · ${board.active_department || ""}`);
}

const CYCLE_NODES = [
  { id: "product", name: "产品" },
  { id: "engineering", name: "工程" },
  { id: "quality", name: "质检" },
];

const PHASE_LABEL = {
  PRODUCT_SPEC: "写规格",
  PRODUCT_REACT: "响应 Ask",
  ASK_PRODUCT: "处理 Ask",
  ENGINEERING: "实现",
  REWORK_ENGINEERING: "返工开发",
  DELIVERY: "提交交付",
  QUALITY: "检查",
  REWORK_PRODUCT: "退回产品",
  DONE: "完成",
  FAILED: "停止",
  PAUSED: "暂停",
};

function stopLabel(reason) {
  return reason === "model_steps_exhausted" ? "模型步骤已达上限" : reason;
}

function cycleNodeClass(nodeId, board) {
  const phase = board.phase || "";
  const active = board.active_department || "";
  if (phase === "DONE") return nodeId === "quality" ? " done" : "";
  if (phase === "FAILED" || phase === "PAUSED") return nodeId === active ? " stop" : "";
  return nodeId === active ? " active" : "";
}

function cycleLinkClass(index, board) {
  const phase = board.phase || "";
  if (index === 0) {
    return ["ENGINEERING", "DELIVERY", "ASK_PRODUCT", "PRODUCT_REACT", "REWORK_ENGINEERING"].includes(phase)
      ? " active"
      : "";
  }
  return ["QUALITY", "DELIVERY", "REWORK_PRODUCT", "REWORK_ENGINEERING", "DONE"].includes(phase) ? " active" : "";
}

function renderCycle(board, timeline) {
  const phase = board.phase || "";
  const nodes = CYCLE_NODES.map((node, index) => {
    const on = (board.active_department || "") === node.id || (phase === "DONE" && node.id === "quality");
    const phaseText = on ? PHASE_LABEL[phase] || phase : "";
    const link =
      index < CYCLE_NODES.length - 1
        ? `<div class="cycle-link${cycleLinkClass(index, board)}" aria-hidden="true">→</div>`
        : "";
    return `<div class="cycle-node${cycleNodeClass(node.id, board)}" title="${t(phase, "")}">
        <div class="cycle-name">${node.name}</div>
        <div class="cycle-phase">${t(phaseText, "")}</div>
      </div>${link}`;
  }).join("");
  const facts = [];
  if (phase === "ASK_PRODUCT" || phase === "PRODUCT_REACT") facts.push("Ask / React");
  else if ((timeline && (timeline.asks || []).length) || board.ask_count) {
    facts.push(`Ask ${board.ask_count || (timeline.asks || []).length}`);
  }
  if (board.rework_count) facts.push(`返工 ${board.rework_count}`);
  if (phase === "DONE") facts.push("已完成");
  else if (phase === "FAILED") facts.push(board.stop_reason || "失败");
  else if (phase === "PAUSED") facts.push(stopLabel(board.stop_reason) || "已暂停");
  const factLine = facts.length ? `<p class="cycle-fact">${facts.map((item) => t(item)).join(" · ")}</p>` : "";
  return `<div class="cycle" role="list">${nodes}</div>${factLine}`;
}

function renderBoard(board, aggregates, timeline, events) {
  const node = document.getElementById("board-body");
  if (!node) return;
  const agg = aggregates || {};
  node.innerHTML = `
    ${renderCycle(board, timeline || {})}
    ${pill(board.outcome)}
    ${kv([
      ["阶段", board.phase],
      ["活动部门", board.active_department],
      ["等待原因", board.waiting_reason],
      ["停止原因", stopLabel(board.stop_reason)],
      ["循环", `${board.cycle_count} / ${board.max_cycles}`],
      ["Token", board.token_used || "未上报"],
      ["耗时 ms", agg.latency_ms],
      ["工具次数", agg.tool_count],
      ["Ask", agg.ask_count],
      ["返工", agg.rework_count],
      ["费用", formatCost(agg.cost)],
      ["模型", latestEventModel(events), "kv-model"],
      ["适配器", board.adapter],
      ["供应商", board.provider === board.adapter ? "未上报" : board.provider],
    ])}
    <p class="task-text">${t(board.task)}</p>
    ${board.human_action ? `<p class="note">${t(board.human_action)}</p>` : ""}
    ${board.error ? `<p class="note">${t(board.error)}</p>` : ""}
  `;
}

function renderTimeline(timeline, gen = state.gen) {
  const node = document.getElementById("timeline-body");
  if (!node) return;
  const contract = timeline.effective_contract;
  const product = timeline.current_product_spec;
  const plan = timeline.engineering_plan;
  const currentPlan = plan && contract && plan.status === "active" && plan.effective_contract_hash === contract.content_hash;
  const current = `
    <div class="work-document">
      <h3>当前需求</h3>
      ${contract ? `
      <p class="document-heading">PRD.md <span>r${t(contract.revision)} · 当前有效</span></p>
      <p>${t(product && product.goal, "")}</p>
      <p class="hash">合同 ${t(shortHash(contract.content_hash))}</p>
      <button type="button" class="event-link" data-event-id="${t(contract.created_event_id)}" data-document="prd">查看 PRD.md 原文</button>
      ` : '<p class="muted">产品尚未接纳有效需求。</p>'}
    </div>
    <div class="work-document">
      <h3>工程计划</h3>
      ${plan ? `
      <p class="document-heading">PLAN.md <span>r${t(plan.revision)} · ${currentPlan ? "当前有效" : "已失效"}</span></p>
      <p>${t(plan.objective)}</p>
      <p class="path">范围：${t((plan.scope || []).join(", "))}</p>
      <ol class="plan-tasks">${(plan.tasks || []).map((task) => `<li>
        <strong>${t(task.title)}</strong>
        <p>产出：${t((task.outputs || []).join("；"))}</p>
        <p class="muted">验证：${t(task.verification)}</p>
      </li>`).join("")}</ol>
      ${plan.reason ? `<p>调整原因：${t(plan.reason)}</p>` : ""}
      ${(plan.assumptions || []).length ? `<details><summary>专业默认与依据</summary><ul>${plan.assumptions.map((item) => `<li>${t(item.decision)}<p class="muted">${t(item.basis)}</p></li>`).join("")}</ul></details>` : ""}
      <p class="hash">依据合同 ${t(shortHash(plan.effective_contract_hash))}</p>
      <button type="button" class="event-link" data-event-id="${t(plan.created_event_id)}" data-document="plan">查看 PLAN.md 原文</button>
      ` : '<p class="muted">工程尚未接纳实施计划。</p>'}
    </div>`;
  const contracts = (timeline.effective_contracts || []).map((item) => `
    <article class="item">
      <header><span>PRD r${t(item.revision)}</span><span>${contract && item.content_hash === contract.content_hash ? "当前有效" : "已被替代"}</span></header>
      <p class="hash">${t(shortHash(item.content_hash))}</p>
      <button type="button" class="event-link" data-event-id="${t(item.created_event_id)}" data-document="prd">查看 PRD.md 原文</button>
    </article>`).join("");
  const plans = (timeline.engineering_plans || []).map((item) => `
    <article class="item">
      <header><span>计划 r${t(item.revision)}</span><span>${currentPlan && item.content_hash === plan.content_hash ? "当前有效" : "已失效"}</span></header>
      <p>${t(item.objective)}</p>
      ${item.reason ? `<p>调整原因：${t(item.reason)}</p>` : ""}
      <p class="hash">依据合同 ${t(shortHash(item.effective_contract_hash))}</p>
      <button type="button" class="event-link" data-event-id="${t(item.created_event_id)}" data-document="plan">查看 PLAN.md 原文</button>
    </article>`).join("");
  const specs = (timeline.specs || [])
    .map(
      (spec) => `
    <article class="item">
      <header><span>ProductSpec r${t(spec.revision)}</span><span>${t(spec.status)}</span></header>
      <p>${t(spec.goal, "")}</p>
      <p class="hash">${t(shortHash(spec.content_hash))} ← ${t(shortHash(spec.parent_hash))}</p>
    </article>`,
    )
    .join("");
  const asks = (timeline.asks || [])
    .map(
      (ask) => `
    <article class="item">
      <header><span>Ask ${t(ask.id)}</span><span>${t(ask.status)}</span></header>
      <p>${t(ask.question)}</p>
      <p class="hash">spec ${t(shortHash(ask.product_spec_hash))}</p>
    </article>`,
    )
    .join("");
  const reactions = (timeline.reactions || [])
    .map(
      (item) => `
    <article class="item">
      <header><span>React ${t(item.decision)}</span><span>${item.produces_new_spec ? "new spec" : "same spec"}</span></header>
      <p class="hash">ask ${t(item.ask_id)} → spec ${t(shortHash(item.new_spec_hash))}</p>
    </article>`,
    )
    .join("");
  node.innerHTML = `
    ${current}
    <details class="work-history"><summary>需求与计划历史</summary><div class="list">${contracts}${plans}</div></details>
    <p class="muted">transitions: ${t((timeline.transitions || []).join(" · "), "—")}</p>
    <div class="list">${specs}${asks}${reactions || '<p class="muted">尚无 ask/react。</p>'}</div>
  `;
  node.querySelectorAll(".event-link").forEach((button) => {
    button.addEventListener("click", () => openEvent(button.dataset.eventId, gen, button.dataset.document));
  });
}

function renderEvidence(evidence, gen = state.gen) {
  const node = document.getElementById("evidence-body");
  if (!node) return;
  const deliveries = (evidence.deliveries || [])
    .map(
      (item) => `
    <article class="item">
      <header><span>Delivery r${t(item.revision)}</span><span class="path">${t((item.files || []).join(", "))}</span></header>
      <p>${t(item.summary)}</p>
      <p class="hash">${t(shortHash(item.code_tree_digest))}</p>
      <p class="muted">${t((item.checks || []).map((check) => `${check.name}:${check.exit_code}`).join(" "))}</p>
      <button type="button" class="event-link" data-event-id="${t(item.created_event_id)}" data-document="tree">查看完整交付</button>
    </article>`,
    )
    .join("");
  const reviews = (evidence.reviews || [])
    .map(
      (item) => `
    <article class="item">
      <header><span>QA ${t(item.verdict)}</span><span>${t((item.defects || []).length)} defects</span></header>
      <p>${t(item.rationale)}</p>
      <p class="hash">spec ${t(shortHash(item.product_spec_hash))} snapshot ${t(shortHash(item.code_snapshot_hash))}</p>
    </article>`,
    )
    .join("");
  const rejections = (evidence.rejections || [])
    .map(
      (item) => `
    <article class="item">
      <header><span>Rejected ${t(item.department)}</span><span>${t(item.phase)}</span></header>
      <pre>${t(JSON.stringify(item.errors, null, 2))}</pre>
    </article>`,
    )
    .join("");
  const candidates = (evidence.lesson_candidates || [])
    .map((item) => {
      const observation = item.observation;
      const isReview = Boolean(observation.verdict);
      const defects = (observation.defects || [])
        .map((defect) => `<li>${t(defect.severity)} · ${t(defect.summary)}</li>`)
        .join("");
      return `
    <article class="item lesson-candidate">
      <header><span>候选 ${t(item.id)}</span><span>待验证</span></header>
      <p><strong>${isReview ? "质检记录" : "失败记录"}</strong> · ${t(isReview ? observation.verdict : observation.stop_reason)}</p>
      <p>${t(isReview ? observation.rationale : observation.message)}</p>
      ${defects ? `<ul>${defects}</ul>` : ""}
      <p><strong>待验证建议</strong>：${t(item.suggestion)}</p>
      <div class="actions">
        <button type="button" class="event-link" data-event-id="${t(item.created_event_id)}">查看候选</button>
        <button type="button" class="event-link" data-event-id="${t(item.source_event_id)}">查看来源</button>
      </div>
    </article>`;
    })
    .join("");
  node.innerHTML =
    deliveries || reviews || rejections || candidates
      ? `<div class="list">${deliveries}${reviews}${rejections}</div>${candidates ? `<h3 class="lesson-heading">经验候选</h3><div class="list">${candidates}</div>` : ""}`
      : `<p class="muted">尚无交付或质检证据。</p>`;
  node.querySelectorAll(".event-link").forEach((button) => {
    button.addEventListener("click", () => openEvent(button.dataset.eventId, gen, button.dataset.document));
  });
}

function renderContext(context, events, gen) {
  const node = document.getElementById("context-body");
  if (!node) return;
  const manifests = (context.manifests || [])
    .map((item) => {
      return `
    <article class="item">
      <header><span>${t(item.department)} · 第 ${t(item.step_id)} 步${item.purpose === "compaction" ? " · 压缩" : ""}</span><span>${t(item.token_estimate)} tok / 窗口 ${t(item.budget)}</span></header>
      <p>注入：${t((item.injected || []).map((part) => part.source).join(", "))}</p>
      <p class="muted">排除：${t((item.excluded || []).map((part) => part.source).join(", "))}</p>
      <p class="hash">${t(shortHash(item.digest))}</p>
      ${item.source_event_id && item.request_ref ? `<button type="button" class="event-link" data-event-id="${t(item.source_event_id)}">查看模型输入</button>` : ""}
      ${item.compaction_event_id ? `<button type="button" class="event-link" data-event-id="${t(item.compaction_event_id)}">查看使用的摘要</button>` : ""}
    </article>`;
    })
    .join("");
  const compactions = (context.compactions || [])
    .map((item) => `
    <article class="item">
      <header><span>${t(item.department)} · 上下文摘要</span><span>第 ${t(item.step_id)} 步</span></header>
      <button type="button" class="event-link" data-event-id="${t(item.source_event_id)}">查看摘要与原始记录</button>
    </article>`)
    .join("");
  const cards = (events || [])
    .slice(-12)
    .reverse()
    .map(
      (event) => `
    <article class="item event" data-id="${t(event.event_id)}">
      <header><span>${t(event.seq)}. ${t(event.type)}</span><span>${t(event.role, "")}</span></header>
      <p class="muted">${t(event.state_before)} → ${t(event.state_after)}</p>
    </article>`,
    )
    .join("");
  node.innerHTML = `
    <div class="list">${manifests}</div>
    ${compactions ? `<h3>压缩记录</h3><div class="list">${compactions}</div>` : ""}
    <h3>最近事件</h3>
    <div class="list">${cards}</div>
  `;
  document.querySelectorAll(".event").forEach((nodeEl) => {
    nodeEl.addEventListener("click", () => {
      openEvent(nodeEl.dataset.id, gen).catch((error) => {
        if (gen !== state.gen) return;
        setStatus("error", error.message);
      });
    });
  });
  node.querySelectorAll(".event-link").forEach((button) => {
    button.addEventListener("click", () => openEvent(button.dataset.eventId, gen));
  });
}

async function openEvent(eventId, gen, documentKind) {
  const runId = state.runId;
  const token = gen === undefined ? state.gen : gen;
  if (token !== state.gen || !runId) return;
  try {
    const data = await fetchJSON(`/api/runs/${encodeURIComponent(runId)}/events/${encodeURIComponent(eventId)}`);
    if (token !== state.gen || state.runId !== runId) return;
    const documentText = documentKind === "tree" && data.tree_archive
      ? JSON.stringify({ format: data.tree_archive.format, tree_digest: data.tree_archive.tree_digest,
        tree: data.tree_archive.tree, blobs: data.tree_archive.blobs }, null, 2)
      : documentKind === "prd" || documentKind === "plan" ? data[`${documentKind}_markdown`] : null;
    if (documentKind && typeof documentText !== "string") throw new Error("原文工件不可用");
    const jsonNode = document.getElementById("event-json");
    const documentNode = document.getElementById("event-document");
    const titleNode = document.getElementById("event-title");
    jsonNode.textContent = JSON.stringify(data, null, 2);
    jsonNode.hidden = Boolean(documentKind);
    if (documentNode) {
      documentNode.textContent = documentText || "";
      documentNode.hidden = !documentKind;
    }
    if (titleNode) titleNode.textContent = documentKind === "tree" ? "完整交付清单" : documentKind ? `${documentKind.toUpperCase()}.md` : "事件详情";
    const sources = document.getElementById("event-sources");
    if (sources) {
      sources.replaceChildren();
      if (documentKind) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "event-link";
        button.textContent = "查看接纳记录";
        button.addEventListener("click", () => openEvent(eventId, token));
        sources.appendChild(button);
      }
      for (const file of data.tree_archive?.tree.files || []) {
        const link = document.createElement("a");
        link.className = "event-link";
        link.textContent = `${file.path} (${file.size} B)`;
        link.href = `/api/runs/${encodeURIComponent(runId)}/events/${encodeURIComponent(eventId)}/files?path=${encodeURIComponent(file.path)}`;
        link.download = file.path.split("/").pop();
        sources.appendChild(link);
      }
      for (const source of data.source_events || []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "event-link";
        button.textContent = `${source.seq}. ${source.type}`;
        button.addEventListener("click", () => openEvent(source.event_id, token));
        sources.appendChild(button);
      }
    }
    document.getElementById("event-dialog").showModal();
  } catch (error) {
    if (token !== state.gen || state.runId !== runId) return;
    setStatus("error", error.message);
  }
}

function listen(runId, afterSeq, gen) {
  closeSource();
  const source = new EventSource(`/api/runs/${runId}/stream?after_seq=${encodeURIComponent(afterSeq)}`);
  state.source = source;
  source.addEventListener("loop", () => {
    if (gen !== state.gen || state.source !== source || state.runId !== runId) return;
    scheduleRefresh(runId, gen);
  });
  source.onerror = () => {
    if (gen !== state.gen || state.source !== source) return;
    setStatus("error", "事件流连接中断");
  };
  source.onopen = () => {
    if (gen !== state.gen || state.source !== source) return;
    if (document.getElementById("status") && document.getElementById("status").textContent === "事件流连接中断") {
      setStatus("running", "事件流已恢复");
    }
  };
}

function isMobileLayout() {
  try {
    return Boolean(globalThis.matchMedia && globalThis.matchMedia("(max-width: 960px)").matches);
  } catch {
    return false;
  }
}

function blurTask() {
  const task = document.getElementById("task");
  if (task && typeof task.blur === "function") task.blur();
}

function openCompose() {
  if (document.body && document.body.classList) document.body.classList.add("compose");
  const form = document.getElementById("task-form");
  const task = document.getElementById("task");
  if (form && typeof form.scrollIntoView === "function") form.scrollIntoView({ block: "start" });
  if (task && typeof task.focus === "function") task.focus();
}

function closeCompose() {
  if (document.body && document.body.classList) document.body.classList.remove("compose");
}

function scrollBoardIntoView() {
  if (!isMobileLayout()) return;
  blurTask();
  if (typeof globalThis.scrollTo === "function") globalThis.scrollTo(0, 0);
  const board = document.getElementById("board");
  if (board && typeof board.scrollIntoView === "function") board.scrollIntoView({ block: "start" });
}

function readLimits() {
  const options = {};
  for (const key of ["max_cycles", "context_window"]) {
    const raw = document.getElementById(key).value;
    if (raw === "") continue;
    if (!/^[0-9]+$/.test(raw)) throw new Error(`${key} 必须是正整数`);
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 1) throw new Error(`${key} 必须是正整数`);
    options[key] = value;
  }
  return options;
}

async function startRun(event) {
  event.preventDefault();
  if (state.submittingStart || state.busy) return;
  const task = document.getElementById("task").value;
  let options;
  try {
    options = readLimits();
  } catch (error) {
    setStatus("error", error.message);
    openCompose();
    return;
  }
  state.submittingStart = true;
  syncButtons();
  try {
    const created = await fetchJSON("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, ...options }),
    });
    state.busy = true;
    state.activeRunId = created.run_id;
    syncButtons();
    syncWorkerWatch();
    blurTask();
    closeCompose();
    await selectRun(created.run_id);
    scrollBoardIntoView();
  } catch (error) {
    if (error.status === 409) setStatus("conflict", error.message);
    else setStatus("error", error.message);
    openCompose();
    await loadHealth(state.gen);
  } finally {
    state.submittingStart = false;
    syncButtons();
  }
}

async function cancelRun() {
  if (!state.runId || state.submittingCancel) return;
  const runId = state.runId;
  const gen = state.gen;
  state.submittingCancel = true;
  syncButtons();
  try {
    const result = await fetchJSON(`/api/runs/${runId}/cancel`, { method: "POST" });
    if (gen !== state.gen) return;
    setStatus("error", result.stop_reason === "cancelled" ? "已取消" : result.phase);
    await refreshRun(runId, gen);
    syncWorkerWatch();
  } catch (error) {
    if (gen !== state.gen) return;
    setStatus("error", error.message);
  } finally {
    state.submittingCancel = false;
    if (gen === state.gen) syncButtons();
  }
}

function boot() {
  document.getElementById("task-form").addEventListener("submit", startRun);
  document.getElementById("btn-cancel").addEventListener("click", cancelRun);
  const newer = document.getElementById("btn-new");
  if (newer) newer.addEventListener("click", openCompose);
  syncButtons();
  loadHealth()
    .then(() => loadRuns())
    .then((data) => {
      if (data && data.runs.length && !state.runId) return selectRun(data.runs[0].run_id);
      return null;
    })
    .catch((error) => setStatus("error", error.message));
}

globalThis.harnessWeb = {
  state,
  scheduleRefresh,
  refreshRun,
  selectRun,
  pollWorkerHealth,
  startWorkerWatch,
  stopWorkerWatch,
  syncWorkerWatch,
  syncButtons,
  applyExecAlert,
  applyProviderAlert,
  renderBoard,
  renderCycle,
  renderTimeline,
  renderEvidence,
  renderContext,
  openEvent,
  formatCost,
  latestEventModel,
  openCompose,
  closeCompose,
  startRun,
  isMobileLayout,
  scrollBoardIntoView,
  blurTask,
  HEALTH_POLL_MS,
};

if (!globalThis.__HARNESS_SKIP_BOOT__ && typeof document !== "undefined" && document.getElementById && document.getElementById("task-form")) {
  boot();
}
