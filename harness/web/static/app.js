(() => {
  "use strict";

  const root = document.getElementById("department-workspace-prototype");
  const main = document.getElementById("dw-main");
  const TERMINAL = new Set(["DONE", "FAILED", "PAUSED"]);
  const DEPARTMENTS = {
    product: { name: "产品部", role: "需求与方案", icon: "clipboard-list" },
    engineering: { name: "工程部", role: "实现与交付", icon: "braces" },
    quality: { name: "质检部", role: "验证与反馈", icon: "check-check" },
  };
  const DEPARTMENT_ORDER = ["product", "engineering", "quality"];
  const CONTEXT_SOURCE_LABELS = {
    intend: "用户原文",
    current_work: "当前工作",
    department_rules: "部门规则",
    professional_completion: "完成标准",
    collaboration_rules: "协作规则",
    input_handling: "输入处理",
    proposal_contract: "提案约束",
    binding_refs: "绑定依据",
    allowed_tools: "可用工具",
    department_history: "部门历史",
    tool_schemas: "工具定义",
    input_progress: "输入进度",
    loop_limits: "循环限制",
    current_contract: "当前合同",
    current_engineering_plan: "当前工程计划",
    latest_response: "最近回应",
    current_product_spec: "当前产品规格",
    prior_delivery: "前次交付",
    qa_defects: "质检缺陷",
    causal_chain: "因果链",
    department_memory: "部门记忆",
    tools: "工具定义",
    product_spec: "产品规格",
    effective_contract: "有效合同",
    engineering_plan: "工程计划",
    delivery_spec: "交付规格",
    validation_feedback: "质检反馈",
    pending_request: "待处理协作",
    provider_binding: "Provider 绑定",
  };
  const STATUS_LABELS = { success: "成功", failed: "失败", running: "进行中", cancelled: "已取消" };
  const PHASE_LABELS = {
    PRODUCT_SPEC: "产品处理中",
    ENGINEERING_PLAN: "工程计划中",
    ENGINEERING: "工程处理中",
    QUALITY: "质检处理中",
    DONE: "已完成",
    FAILED: "执行失败",
    PAUSED: "已暂停",
  };

  const state = {
    view: "overview",
    department: "product",
    runId: null,
    runs: [],
    runPayload: null,
    health: null,
    departmentData: new Map(),
    contextDetails: new Map(),
    selectedContextPart: {},
    departmentLoading: false,
    observationTab: "requests",
    observationScreen: "list",
    observationDetailTab: "overview",
    observationData: null,
    observationLoading: false,
    observationFilters: { department: "all", status: "all", q: "" },
    observationCursor: null,
    observationMoreLoading: false,
    observationDetail: null,
    selectedAttemptId: null,
    selectedContext: {},
    inspectorTab: "context",
    inspectorCollapsed: false,
    selectedHandoff: null,
    globalDrafts: {},
    deptDrafts: {},
    promptDrafts: {},
    routeToken: 0,
    observationSeq: 0,
    detailSeq: 0,
    eventSeq: 0,
    busy: false,
    creating: false,
    cancelling: false,
    inputSubmitting: null,
    guidanceSubmitting: {},
    promptSubmitting: false,
    newTaskDraft: { task: "", max_cycles: "8", context_window: "32000" },
    error: "",
    scrollPositions: {},
  };

  let stream = null;
  let refreshTimer = null;
  let filterTimer = null;
  let runRequestSeq = 0;
  const departmentRequestSeq = new Map();
  const contextRequestSeq = new Map();

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    }[character]));
  }

  function text(value, fallback = "未知") {
    return value === null || value === undefined || value === "" ? fallback : escapeHtml(value);
  }

  function displayValue(value, fallback = "未知") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "object") {
      try { return escapeHtml(JSON.stringify(value)); } catch { return "无法显示"; }
    }
    return escapeHtml(value);
  }

  function number(value, fallback = "未上报") {
    return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : fallback;
  }

  function count(value) {
    return number(value, "未上报");
  }

  function safeClass(value) {
    return String(value || "unknown").replace(/[^a-z0-9_-]/gi, "-");
  }

  function json(value) {
    if (value === null || value === undefined) return "未知";
    try { return escapeHtml(JSON.stringify(value, null, 2)); } catch { return "无法显示原始数据"; }
  }

  function departmentName(key) {
    return DEPARTMENTS[key]?.name || key || "未知部门";
  }

  function phaseLabel(phase) {
    return PHASE_LABELS[phase] || phase || "未知状态";
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status || "未知";
  }

  function attemptStatusLabel(item) {
    if (item?.stage === "prepared") return "准备中";
    if (item?.stage === "requesting") return "请求中";
    return statusLabel(item?.status);
  }

  function departmentStatusLabel(status, fallback) {
    return ({ success: "已完成", failed: "失败", running: "处理中", waiting: "等待" }[status] || status || fallback || "未知");
  }

  function promptStatusLabel(status) {
    return ({ adopted: "生效中", pending: "待下次激活" }[status] || status || "未知状态");
  }

  function guidanceStatusLabel(status) {
    return ({
      received: "已接收",
      in_input: "已进入模型输入",
      completed: "已处理",
      declined: "已说明边界",
      needs_work: "需要后续处理",
    }[status] || status || "未知状态");
  }

  function formatTime(value, includeDate = false) {
    if (!value) return "未知时间";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    const date = parsed.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
    const time = parsed.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return includeDate ? `${date} ${time}` : time;
  }

  function duration(value, status) {
    if (status === "running") return "进行中";
    if (typeof value !== "number" || !Number.isFinite(value)) return "未上报";
    return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(1)}s`;
  }

  function usageOf(item) {
    return item && item.usage && typeof item.usage === "object" ? item.usage : null;
  }

  function usageValue(item, key, runningFallback = null) {
    const usage = usageOf(item);
    const value = usage ? usage[key] : null;
    if (typeof value === "number" && Number.isFinite(value)) return number(value);
    if (runningFallback && item?.status === "running" && item?.stage !== "prepared") return runningFallback;
    return "未上报";
  }

  function usageRawValue(item, key) {
    const usage = usageOf(item);
    const value = usage ? usage[key] : null;
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function reportedUsage(item) {
    const usage = usageOf(item);
    if (!usage) return false;
    if (usage.reported === true) return true;
    return ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens", "cost"]
      .some(key => typeof usage[key] === "number" && Number.isFinite(usage[key]));
  }

  function currentDraft(map, key) {
    return map[key] || "";
  }

  function attemptIdFromContext(context) {
    return context?.id || null;
  }

  function currentDepartmentData(department = state.department) {
    if (!state.runId) return null;
    return state.departmentData.get(`${state.runId}/${department}`) || null;
  }

  function scrollKey() {
    return `${state.runId || "none"}/${state.view}/${state.department}/${state.selectedAttemptId || "list"}`;
  }

  function captureScroll() {
    const current = typeof globalThis.scrollY === "number" ? globalThis.scrollY : (document.documentElement?.scrollTop || 0);
    state.scrollPositions[scrollKey()] = current;
    return current;
  }

  function restoreScroll(value) {
    if (typeof globalThis.scrollTo !== "function") return;
    const restore = () => globalThis.scrollTo(0, value);
    if (typeof globalThis.requestAnimationFrame === "function") globalThis.requestAnimationFrame(restore);
    else restore();
  }

  function jsonScrollNode() {
    return main?.querySelector?.(".dw-detail-panel .dw-json, .dw-event-raw .dw-json");
  }

  function captureJsonScroll() {
    return jsonScrollNode()?.scrollTop || 0;
  }

  function restoreJsonScroll(value) {
    const node = jsonScrollNode();
    if (node) node.scrollTop = value;
  }

  function setStatus(message, kind = "") {
    state.error = message || "";
    const node = root?.querySelector?.(".dw-action-error");
    if (node) {
      node.textContent = message || "";
      node.hidden = !message;
      node.className = `dw-action-error ${kind}`.trim();
    }
  }

  async function fetchJSON(url, options = {}) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      const failure = new Error(error?.message || "网络请求失败");
      failure.status = 0;
      throw failure;
    }
    const raw = await response.text();
    let payload = {};
    if (raw) {
      try { payload = JSON.parse(raw); } catch {
        const failure = new Error("响应不是有效 JSON");
        failure.status = response.status;
        failure.payload = { raw };
        throw failure;
      }
    }
    if (!response.ok) {
      const failure = new Error(payload.error || response.statusText || "请求失败");
      failure.status = response.status;
      failure.payload = payload;
      throw failure;
    }
    return payload;
  }

  function apiPath(runId, suffix = "") {
    return `/api/runs/${encodeURIComponent(runId)}${suffix}`;
  }

  function queryPath(path, params) {
    const search = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "" && value !== "all") search.set(key, value);
    });
    const query = search.toString();
    return query ? `${path}?${query}` : path;
  }

  function routeFromLocation() {
    const search = typeof location !== "undefined" ? new URLSearchParams(location.search) : new URLSearchParams();
    const view = search.get("view");
    state.view = view === "observability" || view === "department" ? view : "overview";
    state.department = DEPARTMENTS[search.get("department")] ? search.get("department") : "product";
    state.runId = search.get("run") || null;
    state.observationTab = search.get("obTab") === "usage" ? "usage" : "requests";
    state.observationScreen = search.get("attempt") ? "detail" : "list";
    state.selectedAttemptId = search.get("attempt") || null;
    state.observationDetailTab = ["overview", "request", "response", "events"].includes(search.get("detailTab"))
      ? search.get("detailTab") : "overview";
    state.inspectorTab = ["context", "provider", "prompt"].includes(search.get("inspectorTab"))
      ? search.get("inspectorTab") : "context";
    state.inspectorCollapsed = search.get("inspector") === "collapsed";
    const contextId = search.get("context");
    if (contextId && state.runId) state.selectedContext[`${state.runId}/${state.department}`] = contextId;
    const contextPart = search.get("contextPart");
    if (contextId && contextPart && state.runId) state.selectedContextPart[`${state.runId}/${contextId}`] = contextPart;
    state.observationFilters = {
      department: ["product", "engineering", "quality"].includes(search.get("departmentFilter")) ? search.get("departmentFilter") : "all",
      status: ["success", "failed", "running", "cancelled"].includes(search.get("status")) ? search.get("status") : "all",
      q: search.get("q") || "",
    };
  }

  function updateRoute({ push = true } = {}) {
    if (typeof history === "undefined" || typeof location === "undefined") return;
    const params = new URLSearchParams();
    if (state.runId) params.set("run", state.runId);
    if (state.view !== "overview") params.set("view", state.view);
    if (state.view === "department") params.set("department", state.department);
    if (state.view === "observability") {
      if (state.observationTab !== "requests") params.set("obTab", state.observationTab);
      if (state.observationScreen === "detail" && state.selectedAttemptId) params.set("attempt", state.selectedAttemptId);
      if (state.observationScreen === "detail" && state.observationDetailTab !== "overview") params.set("detailTab", state.observationDetailTab);
      if (state.observationFilters.department !== "all") params.set("departmentFilter", state.observationFilters.department);
      if (state.observationFilters.status !== "all") params.set("status", state.observationFilters.status);
      if (state.observationFilters.q) params.set("q", state.observationFilters.q);
    }
    if (state.view === "department") {
      if (state.inspectorTab !== "context") params.set("inspectorTab", state.inspectorTab);
      if (state.inspectorCollapsed) params.set("inspector", "collapsed");
      const contextId = state.selectedContext[`${state.runId}/${state.department}`];
      if (contextId) params.set("context", contextId);
      const contextPart = contextId && state.selectedContextPart[`${state.runId}/${contextId}`];
      if (contextPart) params.set("contextPart", contextPart);
    }
    const next = `${location.pathname}${params.toString() ? `?${params}` : ""}${location.hash || ""}`;
    const method = push ? "pushState" : "replaceState";
    history[method]({}, "", next);
  }

  function icons() {
    if (!root) return;
    root.querySelectorAll(".dw-icon-button[aria-label], .dw-tool-button[title], .dw-inline-action[title]").forEach(button => {
      if (button.getAttribute("title")) button.setAttribute("data-tooltip", button.getAttribute("title"));
      if (button.getAttribute("aria-label")) button.setAttribute("data-tooltip", button.getAttribute("aria-label"));
    });
    if (globalThis.lucide && typeof globalThis.lucide.createIcons === "function") {
      globalThis.lucide.createIcons({ attrs: { width: 16, height: 16 } });
    }
  }

  function renderLoading(label = "正在读取真实记录") {
    if (main) main.innerHTML = `<div class="dw-page"><div class="dw-load-state">${escapeHtml(label)}…</div></div>`;
    updateNav();
    icons();
  }

  function renderError(error) {
    const message = error?.message || String(error || "读取失败");
    state.error = message;
    if (main) main.innerHTML = `<div class="dw-page"><div class="dw-load-state error">${escapeHtml(message)}</div><div class="dw-task-tools"><button class="dw-tool-button" type="button" data-action="refresh" title="重新读取"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>重新读取</span></button></div></div>`;
    updateNav();
    icons();
  }

  function taskToolsMarkup() {
    const phase = state.runPayload?.board?.phase;
    const canCancel = Boolean(state.runId && phase && !TERMINAL.has(phase) && !state.cancelling);
    const options = state.runs.map(run => `<option value="${escapeHtml(run.run_id)}" ${run.run_id === state.runId ? "selected" : ""}>${escapeHtml(run.task || run.run_id)}</option>`).join("");
    return `<div class="dw-task-tools"><label class="dw-run-picker"><span class="dw-small">任务</span><select data-run-picker aria-label="选择任务">${options || "<option>暂无任务</option>"}</select></label><button class="dw-tool-button" type="button" data-action="new-task" title="新建任务"><i data-lucide="plus" aria-hidden="true"></i><span>新建</span></button><button class="dw-tool-button" type="button" data-action="history" title="任务历史"><i data-lucide="history" aria-hidden="true"></i><span>历史</span></button><button class="dw-tool-button" type="button" data-action="export" title="导出任务观测"><i data-lucide="download" aria-hidden="true"></i><span>导出</span></button><button class="dw-tool-button${canCancel ? " danger" : ""}" type="button" data-action="cancel" title="取消当前任务" ${canCancel ? "" : "disabled"}><i data-lucide="square" aria-hidden="true"></i><span>取消</span></button></div>`;
  }

  function statusTone(status) {
    if (status === "success" || status === "done" || status === "completed") return "done";
    if (status === "failed" || status === "error") return "issue";
    if (status === "running" || status === "active" || status === "waiting") return "waiting";
    return "";
  }

  function nodeState(key, data) {
    const board = data?.board;
    if (!board) return { status: "等待", tone: "waiting" };
    const phase = board.phase || "";
    if (phase === "DONE") return { status: "已完成", tone: "done" };
    if (phase === "FAILED") return { status: "失败", tone: key === board.active_department ? "issue" : "waiting" };
    if (phase === "PAUSED") return { status: "已暂停", tone: "waiting" };
    const pending = data.timeline?.pending_request || board.pending_request;
    if (pending?.recipient === key) {
      if (pending.request_type === "consultation") return { status: "咨询待回应", tone: "waiting" };
      if (String(pending.action || "").startsWith("revise")) return { status: "返工待处理", tone: "waiting" };
      return { status: "待处理", tone: "waiting" };
    }
    if (board.active_department === key) return { status: phaseLabel(phase), tone: "active" };
    const latest = (data.events || []).filter(event => event.role === key).at(-1);
    if (latest?.type === "collaboration_requested") return { status: "已发起协作", tone: "active" };
    if (latest?.type === "collaboration_responded") return { status: "已回应", tone: "done" };
    if (latest?.type === "proposal_rejected") return { status: "需要处理", tone: "issue" };
    const index = { product: 0, engineering: 1, quality: 2 }[key];
    const activeIndex = { product: 0, engineering: 1, quality: 2 }[board.active_department];
    if (Number.isInteger(index) && Number.isInteger(activeIndex) && index < activeIndex) return { status: "已处理", tone: "done" };
    return { status: "等待", tone: "waiting" };
  }

  function statusMarkup(status) {
    return `<span class="dw-node-status ${safeClass(status.tone)}"><span class="dw-status-dot ${status.tone === "waiting" ? "waiting" : status.tone === "issue" ? "issue" : ""}"></span>${text(status.status)}</span>`;
  }

  function artifactFor(key, timeline, evidence) {
    if (key === "product") {
      const item = timeline?.effective_contract || timeline?.current_product_spec;
      return item?.revision ? `PRD.md r${item.revision}` : item?.goal || "暂无产品材料";
    }
    if (key === "engineering") {
      const item = timeline?.engineering_plan;
      return item?.revision ? `PLAN.md r${item.revision}` : item?.objective || "暂无工程计划";
    }
    const review = evidence?.reviews?.[evidence.reviews.length - 1];
    const delivery = timeline?.current_delivery_spec;
    return review?.verdict || delivery?.summary || (delivery?.revision ? `交付 r${delivery.revision}` : "暂无质检记录");
  }

  function taskFor(key, timeline, board, evidence) {
    if (key === "product") return timeline?.effective_contract?.goal || timeline?.current_product_spec?.goal || "等待产品需求";
    if (key === "engineering") return timeline?.engineering_plan?.objective || "等待工程计划";
    return evidence?.reviews?.[evidence.reviews.length - 1]?.rationale || timeline?.current_delivery_spec?.summary || "等待工程交付";
  }

  function departmentTitle(key, data, board) {
    const history = data?.history || data?.overview?.timeline || {};
    const materials = data?.materials || data?.overview?.evidence || {};
    if (key === "product") return history.effective_contract?.goal || history.current_product_spec?.goal || data?.task || board?.task || "产品工作区";
    if (key === "engineering") return history.engineering_plan?.objective || data?.task || board?.task || "工程工作区";
    return materials.reviews?.at(-1)?.rationale || history.current_delivery_spec?.summary || data?.task || board?.task || "质检工作区";
  }

  function shortDepartmentTarget(department) {
    const data = currentDepartmentData(department);
    const history = data?.history || data?.overview?.timeline || state.runPayload?.timeline || {};
    const materials = data?.materials || data?.overview?.evidence || state.runPayload?.evidence || {};
    if (department === "product") return history.effective_contract?.goal || history.current_product_spec?.goal || null;
    if (department === "engineering") return history.engineering_plan?.objective || null;
    return materials.reviews?.at(-1)?.rationale || history.current_delivery_spec?.summary || null;
  }

  function observationTaskText(department) {
    if (department && DEPARTMENTS[department]) {
      return shortDepartmentTarget(department) || { product: "等待产品需求", engineering: "等待工程计划", quality: "等待工程交付" }[department];
    }
    for (const key of DEPARTMENT_ORDER) {
      const value = shortDepartmentTarget(key);
      if (value) return value;
    }
    return "当前任务";
  }

  function attemptRequestedText(item) {
    return `${item?.requested_provider || "未知"} / ${item?.requested_model || "未知"}`;
  }

  function attemptActualText(item) {
    const provider = item?.actual_provider;
    const model = item?.actual_model;
    if ((provider == null || provider === "") && (model == null || model === "")) return "未知";
    return `${provider || "未知"} / ${model || "未知"}`;
  }

  function nodeMarkup(key, data) {
    const status = nodeState(key, data);
    const index = String(DEPARTMENT_ORDER.indexOf(key) + 1).padStart(2, "0");
    return `<button class="dw-dept-node" type="button" data-department="${key}"><span class="dw-node-meta"><span class="dw-node-index">${index}</span>${statusMarkup(status)}</span><h3>${departmentName(key)}</h3><span class="dw-node-role">${text(DEPARTMENTS[key].role)}</span><span class="dw-node-task">${text(taskFor(key, data.timeline, data.board, data.evidence))}</span><span class="dw-node-artifact">${text(artifactFor(key, data.timeline, data.evidence))}</span><span class="dw-node-foot"><span>当前记录</span><span>进入工作区 <i data-lucide="arrow-up-right" aria-hidden="true"></i></span></span></button>`;
  }

  function eventById() {
    return new Map((state.runPayload?.events || []).map(item => [item.event_id, item]));
  }

  function handovers() {
    const timeline = state.runPayload?.timeline || {};
    const evidence = state.runPayload?.evidence || {};
    const events = eventById();
    const requests = timeline.requests || [];
    const responses = timeline.responses || [];
    const closures = timeline.request_closures || [];
    const rows = [];
    const seen = new Set();
    const deliveries = evidence.deliveries || [];
    const reviews = evidence.reviews || [];
    const eventSeq = eventId => events.get(eventId)?.seq || 0;
    const releaseByDelivery = new Map(reviews.filter(review => review.verdict === "release" && review.delivery_spec_hash).map(review => [review.delivery_spec_hash, review]));
    const addRow = row => {
      if (!row.id || seen.has(row.id)) return;
      seen.add(row.id);
      rows.push(row);
    };
    requests.forEach(request => {
      const response = responses.find(item => item.request_id === request.id);
      const closure = closures.find(item => item.request_id === request.id);
      const source = events.get(request.created_event_id);
      addRow({
        id: request.id || request.created_event_id,
        title: `${departmentName(request.requester)} → ${departmentName(request.recipient)}`,
        kind: request.request_type === "consultation" ? "咨询" : ({ inspect: "查看", check: "检查", revise_requirements: "需求修订", revise_delivery: "交付修订" }[request.action] || request.action || "协作请求"),
        status: closure?.status || response?.status || request.status,
        time: source?.created_at,
        body: request.question || request.background || "",
        detail: request.expected_result || request.background || "",
        sourceEventId: request.created_event_id,
      });
    });
    const contract = timeline.effective_contract || timeline.current_product_spec;
    if (contract?.created_event_id) {
      const source = events.get(contract.created_event_id);
      addRow({ id: contract.created_event_id, title: "产品部 → 工程部", kind: "需求交接", status: contract.status || "已处理", time: source?.created_at, body: contract.goal || "产品材料已形成", detail: contract.content_hash || "", sourceEventId: contract.created_event_id });
    }
    deliveries.forEach(delivery => {
      const source = events.get(delivery.created_event_id);
      const release = releaseByDelivery.get(delivery.content_hash);
      const status = release ? "accepted" : delivery.status === "superseded" ? "superseded" : delivery.status || "waiting";
      addRow({ id: delivery.created_event_id, title: "工程部 → 质检部", kind: "版本交付", status, time: source?.created_at, body: delivery.summary || "工程交付已形成", detail: (delivery.files || []).join("、"), sourceEventId: delivery.created_event_id });
    });
    reviews.forEach(review => {
      if (!String(review.verdict || "").startsWith("rework")) return;
      const source = events.get(review.created_event_id);
      const followup = deliveries.find(delivery => delivery.parent_hash === review.delivery_spec_hash && eventSeq(delivery.created_event_id) > eventSeq(review.created_event_id));
      addRow({ id: review.created_event_id, title: "质检部 → 工程部", kind: "问题反馈", status: followup ? "superseded" : "needs_work", time: source?.created_at, body: review.rationale || "质检记录要求重新处理", detail: (review.defects || []).map(item => item.summary).join("；"), sourceEventId: review.created_event_id });
    });
    return rows.sort((a, b) => String(b.time || "").localeCompare(String(a.time || "")));
  }

  function handoffStatus(status) {
    return ({ open: "待回应", answered: "已回答", completed: "已完成", accepted: "已验收", active: "处理中", waiting: "等待处理", declined: "未接受", needs_work: "仍需处理", superseded: "已被后续交付接续", cancelled: "已取消", stopped: "已停止" })[status] || status || "未知";
  }

  function handoffDetailMarkup(item) {
    if (!item) return `<div class="dw-empty-results">暂无部门交接记录</div>`;
    return `<div class="dw-detail" id="dw-handoff-detail" aria-live="polite"><div><h3>${text(item.kind)}</h3><p>${text(item.body)}</p>${item.detail && item.detail !== item.body ? `<p class="dw-small">期望结果：${text(item.detail)}</p>` : ""}<p>${legacyLink(item.sourceEventId, "", "查看原始交接")}</p></div><span class="dw-detail-route">${text(item.title)} · ${text(formatTime(item.time))}</span></div>`;
  }

  function globalLogMarkup() {
    const inputs = state.runPayload?.inputs || [];
    const events = eventById();
    const entries = inputs.map(item => `<div class="dw-global-entry"><strong>${item.kind === "command" ? "系统命令" : "用户"} · v${text(item.version)}</strong><span>${text(item.text, "原文不可用")}</span><time>${text(formatTime(item.created_at || events.get(item.created_event_id)?.created_at))}</time></div>`).join("");
    if (!entries) return `<p class="dw-small">暂无任务输入。</p>`;
    return entries;
  }

  function legacyLink(eventId, documentKind, label) {
    if (!eventId) return "";
    return `<button class="dw-inline-action" type="button" data-event-id="${escapeHtml(eventId)}" data-document="${escapeHtml(documentKind || "")}" title="${escapeHtml(label)}"><i data-lucide="external-link" aria-hidden="true"></i>${escapeHtml(label)}</button>`;
  }

  function gitVersionMarkup(item) {
    const version = item?.git_version;
    if (!version) return "";
    return `<span class="dw-small dw-git-version">Git ${text(String(version.commit || "").slice(0, 12))} · ${version.parent_commit ? `父提交 ${text(String(version.parent_commit).slice(0, 12))}` : "初始版本"} ${legacyLink(item.created_event_id, "git", "查看 Git 差异")}</span>`;
  }

  function legacyOverviewMarkup(data) {
    const timeline = data.timeline || {};
    const evidence = data.evidence || {};
    const inputs = data.inputs || [];
    const contractHistory = Array.isArray(timeline.effective_contracts) && timeline.effective_contracts.length ? timeline.effective_contracts : (timeline.specs || []);
    const contracts = contractHistory.map(item => `<article class="item"><header><span>PRD.md r${text(item.revision)}</span><span>${text(item.status, "已记录")}</span></header><p>${text(item.goal)}</p><p>${legacyLink(item.created_event_id, "prd", "查看 PRD.md 原文")}${gitVersionMarkup(item)}</p></article>`).join("");
    const plans = (timeline.engineering_plans || []).map(item => `<article class="item"><header><span>PLAN.md r${text(item.revision)}</span><span>${text(item.status, "已记录")}</span></header><p>${text(item.objective)}</p><p>${legacyLink(item.created_event_id, "plan", "查看 PLAN.md 原文")}${gitVersionMarkup(item)}</p></article>`).join("");
    const deliveries = (evidence.deliveries || []).map(item => `<article class="item"><header><span>交付 r${text(item.revision)}</span><span>${text((item.files || []).join("、"), "文件清单未知")}</span></header><p>${text(item.summary)}</p><p>${legacyLink(item.created_event_id, "tree", "查看封存清单")}${gitVersionMarkup(item)}</p></article>`).join("");
    const reviews = (evidence.reviews || []).map(item => `<article class="item"><header><span>QA ${text(item.verdict)}</span><span>${text(item.created_at ? formatTime(item.created_at) : "")}</span></header><p>${text(item.rationale)}</p></article>`).join("");
    const inputHistory = inputs.map(item => `<article class="item"><header><span>输入 v${text(item.version)}</span><span>${text(item.kind === "command" ? "系统命令" : "用户原文")}</span></header><pre class="dw-json">${text(item.text, "原文不可用")}</pre><p class="dw-small">UTF-8 字节 [${text(item.byte_start)}, ${text(item.byte_end)}) ${legacyLink(item.created_event_id, "", "查看接收记录")}</p>${gitVersionMarkup(item)}</article>`).join("");
    if (!(contracts || plans || deliveries || reviews || inputHistory)) return "";
    return `<section class="dw-materials-section" aria-labelledby="dw-history-heading"><div class="dw-section-head"><h2 id="dw-history-heading">材料与证据</h2><p>原文、Git 差异与封存下载</p></div><div class="dw-material-groups"><details class="dw-material-group"><summary>用户输入 <span>${count(inputs.length)} 条</span></summary><div class="list">${inputHistory || '<p class="dw-small">暂无用户输入记录</p>'}</div></details><details class="dw-material-group"><summary>需求与计划 <span>${count(contractHistory.length + (timeline.engineering_plans || []).length)} 条</span></summary><div class="list">${contracts || '<p class="dw-small">暂无 PRD 记录</p>'}${plans || '<p class="dw-small">暂无 PLAN 记录</p>'}</div></details><details class="dw-material-group"><summary>交付与质检 <span>${count((evidence.deliveries || []).length + (evidence.reviews || []).length)} 条</span></summary><div class="list">${deliveries || '<p class="dw-small">暂无交付记录</p>'}${reviews || '<p class="dw-small">暂无质检记录</p>'}</div></details></div></section>`;
  }

  function renderOverview() {
    const scrollY = captureScroll();
    const data = state.runPayload;
    if (!data || !data.board) {
      main.innerHTML = `<div class="dw-page dw-overview-page"><header class="dw-topline"><div><div class="dw-eyebrow"><span class="dw-status-dot"></span><strong>协作台</strong><span>·</span><span>请选择任务</span></div><h1>没有选中的任务</h1><p class="dw-subtitle">从任务历史中打开一个任务，或创建新的任务。</p></div>${taskToolsMarkup()}</header><div class="dw-no-run"><h2>任务工作区</h2><p>当前页面只显示真实任务记录。创建任务后，产品、工程、质检和观测入口会使用同一任务范围。</p></div></div>`;
      updateNav(); icons();
      restoreScroll(scrollY);
      return;
    }
    const board = data.board;
    const rows = handovers();
    if (!state.selectedHandoff || !rows.some(item => item.id === state.selectedHandoff)) state.selectedHandoff = rows[0]?.id || null;
    const selected = rows.find(item => item.id === state.selectedHandoff);
    const lastEvent = (data.events || [])[data.events?.length - 1];
    const active = board.active_department ? departmentName(board.active_department) : "暂无";
    const records = rows.slice(0, 8).map(item => `<button class="dw-record-row" type="button" data-handoff="${escapeHtml(item.id)}"><span class="dw-record-time">${escapeHtml(formatTime(item.time))}</span><span class="dw-record-text"><strong>${text(item.title)}</strong><span>${text(item.body)}</span></span><span class="dw-record-state ${["open", "needs_work", "active", "waiting"].includes(item.status) ? "waiting" : ""}">${text(handoffStatus(item.status))}</span></button>`).join("");
    main.innerHTML = `<div class="dw-page dw-overview-page"><header class="dw-topline"><div><div class="dw-eyebrow"><span class="dw-status-dot ${statusTone(board.phase) === "waiting" ? "waiting" : ""}"></span><strong>任务</strong><span>·</span><span>三部门协作</span></div><h1>${text(board.task)}</h1><p class="dw-subtitle">最近更新 ${text(formatTime(lastEvent?.created_at))} · 当前协作节点为 ${text(active)}</p></div><div><span class="dw-current-state"><span class="dw-status-dot ${statusTone(board.phase) === "waiting" ? "waiting" : ""}"></span>${text(phaseLabel(board.phase))}</span>${taskToolsMarkup()}</div></header><section class="dw-section" aria-labelledby="flow-title"><div class="dw-section-head"><h2 id="flow-title">协作流转</h2><p>需求交接 → 版本交付 → 验收反馈</p></div><div class="dw-flow-map">${nodeMarkup("product", data)}<div class="dw-flow-connector" aria-hidden="true"><span>需求</span><i data-lucide="arrow-right"></i></div>${nodeMarkup("engineering", data)}<div class="dw-flow-connector" aria-hidden="true"><span>交付</span><i data-lucide="arrow-right"></i></div>${nodeMarkup("quality", data)}</div>${rows.length ? `<div class="dw-feedback-lane"><div class="dw-feedback-route">${rows.slice(0, 1).map(item => `<button class="dw-handoff ${item.id === state.selectedHandoff ? "is-selected" : ""}" type="button" data-handoff="${escapeHtml(item.id)}"><i data-lucide="corner-up-left" aria-hidden="true"></i><span class="dw-handoff-copy"><strong>${text(item.title)}</strong><span>${text(item.kind)} · ${text(formatTime(item.time))} · ${text(handoffStatus(item.status))}</span></span><span class="dw-handoff-arrow"><i data-lucide="arrow-left" aria-hidden="true"></i></span></button>`).join("")}</div></div>` : ""}${handoffDetailMarkup(selected)}</section><section class="dw-section" aria-labelledby="recent-title"><div class="dw-section-head"><h2 id="recent-title">最近流转</h2><p>按真实事件时间倒序</p></div><div class="dw-record-list">${records || '<div class="dw-empty-results">暂无部门交接记录</div>'}</div></section><section class="dw-global" aria-labelledby="global-title"><div class="dw-section-head"><h2 id="global-title">任务输入</h2><p>从用户端追加需求</p></div><div class="dw-global-log" id="dw-global-log">${globalLogMarkup()}</div><form class="dw-compose" id="dw-global-form"><div class="dw-compose-meta"><span>当前接收方</span><strong>产品部 · 任务入口</strong></div><textarea class="dw-textarea" rows="2" data-global-draft aria-label="追加任务需求" placeholder="补充目标、优先级或需要确认的事项" ${TERMINAL.has(board.phase) ? "disabled" : ""}>${escapeHtml(currentDraft(state.globalDrafts, state.runId))}</textarea><div class="dw-compose-actions"><span>${TERMINAL.has(board.phase) ? "任务已结束，请新建任务" : "提交后等待产品处理"}</span><button class="dw-primary" type="submit" ${TERMINAL.has(board.phase) || state.inputSubmitting === state.runId ? "disabled" : ""}><i data-lucide="send" aria-hidden="true"></i>发送</button></div></form></section>${legacyOverviewMarkup(data)}<p class="dw-action-error" role="alert" hidden></p></div>`;
    updateNav(); icons();
    restoreScroll(scrollY);
  }

  function messageKind(message) {
    if (message.kind === "user") return "user";
    if (message.kind === "self" || message.source === "本部门") return "self";
    return "other";
  }

  function messageMarkup(message) {
    const parsed = parseMessageText(message.text);
    const eventLink = parsed.clipped && message.event_id ? `<p class="dw-message-actions">${legacyLink(message.event_id, "", "查看事件原文")}</p>` : "";
    return `<article class="dw-message is-${safeClass(messageKind(message))}"><div class="dw-message-head"><span class="dw-message-origin">${text(message.source)} <span>${text(message.detail, "")}</span></span><time>${text(formatTime(message.created_at || message.time))}</time></div><p>${text(parsed.text, "原文不可用")}</p>${eventLink}</article>`;
  }

  function guidanceMarkup(data) {
    const items = Array.isArray(data?.guidance) ? data.guidance : [];
    if (!items.length) return '<section class="dw-guidance-section"><div class="dw-section-head"><h3>部门指导记录</h3><p>发送后由本部门在下一次安全激活中处理</p></div><p class="dw-small">暂无部门指导。</p></section>';
    const rows = items.map(item => `<article class="dw-guidance-item"><div class="dw-guidance-head"><strong>指导 v${text(item.version)}</strong><span class="dw-record-state ${["received", "in_input", "needs_work"].includes(item.status) ? "waiting" : ""}">${text(guidanceStatusLabel(item.status))}</span></div><p>${text(item.text, "原文不可用")}</p><div class="dw-guidance-meta"><span>${text(item.id)}</span>${item.applied_context_event_id ? `<span>Context ${text(item.applied_context_event_id)}</span>` : ""}${item.response_event_id ? legacyLink(item.response_event_id, "", "查看回应") : ""}</div>${item.response_text ? `<p class="dw-guidance-response">部门回应：${text(item.response_text)}</p>` : ""}</article>`).join("");
    return `<section class="dw-guidance-section"><div class="dw-section-head"><h3>部门指导记录</h3><p>${count(items.length)} 条 · 原文、进入输入与回应分开记录</p></div><div class="dw-guidance-list">${rows}</div></section>`;
  }

  function contextDefaultId(contexts) {
    const work = contexts.filter(item => item.purpose === "work");
    return (work.at(-1) || contexts.at(-1) || null)?.id || null;
  }

  function contextSourceLabel(source) {
    return CONTEXT_SOURCE_LABELS[source] || `其他来源 · ${source || "未知"}`;
  }

  function contextDetailFor(attemptId) {
    return attemptId ? state.contextDetails.get(`${state.runId}/${attemptId}`) || null : null;
  }

  function parseMessageText(value) {
    const raw = String(value ?? "");
    if (!raw.trim()) return { text: "原文不可用", clipped: false };
    if (raw.startsWith("工具调用：")) {
      const separator = raw.indexOf(" · 参数");
      return { text: separator > 0 ? raw.slice(0, separator) : raw, clipped: separator > 0 };
    }
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return { text: "结构化工作输入已保存", clipped: true };
    } catch {}
    if (raw.length > 1400) return { text: `${raw.slice(0, 1400)}…`, clipped: true };
    return { text: raw, clipped: false };
  }

  function contextMarkup(department, data) {
    const contexts = Array.isArray(data?.contexts) ? data.contexts : [];
    const contextKey = `${state.runId}/${department}`;
    const requestedId = state.selectedContext[contextKey];
    const selected = contexts.find(item => item.id === requestedId) || contexts.filter(item => item.purpose === "work").at(-1) || contexts.at(-1) || null;
    const selectedId = selected?.id || null;
    state.selectedContext[contextKey] = selectedId;
    const items = contexts.map(item => `<button class="dw-context-item ${item.id === selectedId ? "is-selected" : ""}" type="button" data-context-id="${escapeHtml(item.id)}" aria-pressed="${item.id === selectedId}"><strong>${text(item.title)}</strong><span>${text(item.meta || formatTime(item.snapshot_at))}</span></button>`).join("");
    const selectedAttempt = attemptIdFromContext(selected);
    const detail = contextDetailFor(selectedAttempt);
    const parts = detail?.context && Object.prototype.hasOwnProperty.call(detail.context, "parts") ? detail.context.parts : null;
    const partKey = `${state.runId}/${selectedAttempt || "none"}`;
    const selectedSource = state.selectedContextPart[partKey];
    const selectedPart = Array.isArray(parts) ? (parts.find(item => item.source === selectedSource) || parts[0] || null) : null;
    if (selectedPart) state.selectedContextPart[partKey] = selectedPart.source;
    const partItems = Array.isArray(parts) ? parts.map(item => `<button class="dw-context-part ${item.source === selectedPart?.source ? "is-selected" : ""}" type="button" data-context-part-source="${escapeHtml(item.source)}"><strong>${text(contextSourceLabel(item.source))}</strong><span>${item.version == null ? "版本未知" : `v${escapeHtml(item.version)}`} · ${text(String(item.digest || "").slice(0, 12), "摘要未知")}</span></button>`).join("") : "";
    const sourceBody = !selectedAttempt ? "当前没有可查看的 Context 原文" : !detail ? "正在读取本次快照来源…" : detail.error ? `本次 Context 来源读取失败：${detail.error}` : !Array.isArray(parts) ? "本次 Context 来源未记录" : !selectedPart ? "本次 Context 没有可显示来源" : selectedPart.text;
    const observe = selectedAttempt ? `<button class="dw-observation-link" type="button" data-observe-attempt="${escapeHtml(selectedAttempt)}"><i data-lucide="activity" aria-hidden="true"></i>查看模型请求</button>` : `<span class="dw-observation-link is-disabled"><i data-lucide="circle-help" aria-hidden="true"></i>本次 Context 尚未发起模型请求</span>`;
    return `<div class="dw-inspect-panel" id="dw-panel-context" role="tabpanel" aria-labelledby="dw-tab-context"><h3>Context 快照</h3><div class="dw-context-snapshot-meta"><strong>本次工作输入</strong><time>快照时间 · ${text(formatTime(selected?.snapshot_at || data?.snapshot_at))}</time></div><div class="dw-context-list">${items || '<p class="dw-small">暂无 Context 快照</p>'}</div><div class="dw-context-part-list" aria-label="本次快照来源">${partItems || (detail && Array.isArray(parts) ? '<p class="dw-small">本次 Context 没有来源条目</p>' : '<p class="dw-small">本次 Context 来源未记录</p>')}</div><div class="dw-context-body"><p>${text(sourceBody, "当前没有可查看的 Context 原文")}</p></div>${observe}</div>`;
  }

  function providerMarkup(provider) {
    const value = provider || {};
    const rows = [["提供方", value.provider], ["模型", value.model], ["协议", value.protocol], ["温度", value.temperature], ["上下文窗", value.context_window], ["最大输出", value.max_output_tokens]];
    return `<div class="dw-inspect-panel" id="dw-panel-provider" role="tabpanel" aria-labelledby="dw-tab-provider"><h3>Provider 配置</h3><dl class="dw-data-list">${rows.map(([key, item]) => `<div class="dw-data-row"><dt>${key}</dt><dd>${text(item)}</dd></div>`).join("")}</dl><p class="dw-small">以上为本次任务采用的只读快照。</p></div>`;
  }

  function promptMarkup(department, data) {
    const saved = data?.prompt_latest || state.runPayload?.prompts?.current?.[department] || {};
    const selectedAttempt = state.selectedContext[`${state.runId}/${department}`];
    const selectedDetail = contextDetailFor(selectedAttempt);
    const snapshotPrompt = selectedDetail?.context?.parts?.find(item => item.source === "department_rules") || null;
    const adopted = data?.prompt || {};
    const prompt = snapshotPrompt ? { ...adopted, version: snapshotPrompt.version, text: snapshotPrompt.text, prompt_ref: { content_hash: snapshotPrompt.digest } } : adopted;
    const key = `${state.runId}/${department}`;
    const editable = Boolean(saved.text || adopted.text) && !TERMINAL.has(state.runPayload?.board?.phase);
    const actualMeta = prompt.version ? `实际使用 v${prompt.version}` : "实际使用版本未知";
    const savedMeta = saved.version && saved.version !== prompt.version ? ` · 待下次激活 v${saved.version}` : "";
    return `<div class="dw-inspect-panel" id="dw-panel-prompt" role="tabpanel" aria-labelledby="dw-tab-prompt"><div class="dw-prompt-version"><span>本次工作 Prompt</span><span>${text(actualMeta)}${text(savedMeta, "")}</span></div><pre class="dw-prompt-block">${text(prompt.text, "当前 Prompt 原文不可用")}</pre>${saved.version && saved.version !== prompt.version ? `<p class="dw-small">最新保存版本 v${text(saved.version)} 可编辑，当前快照仍使用 v${text(prompt.version)}。</p>` : ""}${editable ? `<button class="dw-observation-link" type="button" data-prompt-edit="${escapeHtml(key)}" title="编辑 Prompt"><i data-lucide="pencil" aria-hidden="true"></i>编辑 Prompt</button>` : ""}</div>`;
  }

  function inspectorMarkup(department, data) {
    return `<aside class="dw-inspector ${state.inspectorCollapsed ? "is-collapsed" : ""}" aria-label="${departmentName(department)}检查区"><div class="dw-inspector-head"><div><span class="dw-inspector-kicker">检查区</span><strong>${departmentName(department)}</strong></div><button class="dw-icon-button" type="button" data-inspector-toggle aria-label="${state.inspectorCollapsed ? "展开检查区" : "收起检查区"}" title="${state.inspectorCollapsed ? "展开检查区" : "收起检查区"}"><i data-lucide="${state.inspectorCollapsed ? "panel-right-open" : "panel-right-close"}" aria-hidden="true"></i></button></div><div class="dw-inspector-content"><div class="dw-inspector-tabs" role="tablist" aria-label="检查项"><button id="dw-tab-context" class="dw-inspector-tab ${state.inspectorTab === "context" ? "is-active" : ""}" type="button" data-inspector-tab="context" role="tab" aria-controls="dw-panel-context" aria-selected="${state.inspectorTab === "context"}">Context</button><button id="dw-tab-provider" class="dw-inspector-tab ${state.inspectorTab === "provider" ? "is-active" : ""}" type="button" data-inspector-tab="provider" role="tab" aria-controls="dw-panel-provider" aria-selected="${state.inspectorTab === "provider"}">Provider</button><button id="dw-tab-prompt" class="dw-inspector-tab ${state.inspectorTab === "prompt" ? "is-active" : ""}" type="button" data-inspector-tab="prompt" role="tab" aria-controls="dw-panel-prompt" aria-selected="${state.inspectorTab === "prompt"}">Prompt</button></div>${state.inspectorTab === "provider" ? providerMarkup(data.provider) : state.inspectorTab === "prompt" ? promptMarkup(department, data) : contextMarkup(department, data)}</div></aside>`;
  }

  function renderDepartment(department) {
    const scrollY = captureScroll();
    state.view = "department";
    state.department = department;
    const data = currentDepartmentData(department);
    const board = state.runPayload?.board;
    if (!board) {
      main.innerHTML = `<div class="dw-page dw-department-page"><header class="dw-dept-header"><div class="dw-dept-header-top"><button class="dw-back" type="button" data-view="overview"><i data-lucide="arrow-left" aria-hidden="true"></i>回到总览</button></div><div><div class="dw-eyebrow"><span class="dw-status-dot"></span><strong>${departmentName(department)}</strong></div><h1>没有选中的任务</h1><p class="dw-subtitle">请选择任务后查看部门工作区。</p></div></header></div>`;
      updateNav(); icons();
      restoreScroll(scrollY);
      return;
    }
    if (!data) {
      main.innerHTML = `<div class="dw-page dw-department-page"><header class="dw-dept-header"><div class="dw-dept-header-top"><button class="dw-back" type="button" data-view="overview"><i data-lucide="arrow-left" aria-hidden="true"></i>回到总览</button><span class="dw-current-state"><span class="dw-status-dot waiting"></span>正在读取</span></div><div><div class="dw-eyebrow"><span class="dw-status-dot waiting"></span><strong>${departmentName(department)}</strong><span>·</span><span>${text(DEPARTMENTS[department].role)}</span></div><h1>${text(board.task)}</h1><p class="dw-subtitle">${text(board.run_id)} · 部门工作区</p></div></header><div class="dw-load-state">正在读取部门消息与检查区…</div></div>`;
      updateNav(); icons();
      restoreScroll(scrollY);
      return;
    }
    const messages = (data.messages || []).map(messageMarkup).join("");
    const status = departmentStatusLabel(data.status, phaseLabel(board.phase));
    const deptDraftKey = `${state.runId}/${department}`;
    const departmentTask = departmentTitle(department, data, board);
    main.innerHTML = `<div class="dw-page dw-department-page"><header class="dw-dept-header"><div class="dw-dept-header-top"><button class="dw-back" type="button" data-view="overview"><i data-lucide="arrow-left" aria-hidden="true"></i>回到总览</button><span class="dw-current-state"><span class="dw-status-dot ${statusTone(status)}"></span>${text(departmentName(department))} · ${text(status)}</span></div><div><div class="dw-eyebrow"><span class="dw-status-dot ${statusTone(status) === "waiting" ? "waiting" : ""}"></span><strong>${text(departmentName(department))}</strong><span>·</span><span>${text(data.role || DEPARTMENTS[department].role)}</span></div><h1>${text(departmentTask)}</h1><p class="dw-subtitle">${text(board.run_id)} · 部门工作区</p></div></header><div class="dw-task-strip"><i data-lucide="route" aria-hidden="true"></i><span>当前任务</span><strong>${text(departmentTask)}</strong></div><div class="dw-work-grid ${state.inspectorCollapsed ? "has-collapsed-inspector" : ""}"><section class="dw-conversation" aria-labelledby="conversation-title"><div class="dw-conversation-head"><h2 id="conversation-title">工作消息</h2><p>${number((data.messages || []).length, "0")} 条记录 · ${text(status)}</p></div><div class="dw-timeline" aria-live="polite">${messages || '<p class="dw-small">暂无部门消息</p>'}</div><form class="dw-compose" id="dw-dept-form" data-department-form="${escapeHtml(department)}"><div class="dw-compose-meta"><span>当前接收方</span><strong>发给${text(departmentName(department))}</strong></div><textarea class="dw-textarea" rows="3" data-dept-draft="${escapeHtml(department)}" aria-label="发给${escapeHtml(departmentName(department))}" placeholder="追加对话或指导" disabled>${escapeHtml(currentDraft(state.deptDrafts, deptDraftKey))}</textarea><div class="dw-compose-actions"><span>部门指导将在 W6 接入真实内核</span><button class="dw-primary" type="submit" disabled><i data-lucide="send" aria-hidden="true"></i>发送指导</button></div></form></section>${inspectorMarkup(department, data)}</div><p class="dw-action-error" role="alert" hidden></p></div>`;
    const guidanceHistory = main.querySelector?.(".dw-timeline");
    guidanceHistory?.insertAdjacentHTML?.("afterend", guidanceMarkup(data));
    const guidanceKey = `${state.runId}/${department}`;
    const guidanceBusy = Boolean(state.guidanceSubmitting[guidanceKey]);
    const guidanceDisabled = TERMINAL.has(board.phase) || guidanceBusy;
    const guidanceForm = main.querySelector?.("#dw-dept-form");
    const guidanceTextarea = guidanceForm?.querySelector?.("[data-dept-draft]");
    const guidanceSubmit = guidanceForm?.querySelector?.("button[type='submit']");
    const guidanceStatus = guidanceForm?.querySelector?.(".dw-compose-actions span");
    if (guidanceTextarea) guidanceTextarea.disabled = guidanceDisabled;
    if (guidanceSubmit) guidanceSubmit.disabled = guidanceDisabled;
    if (guidanceStatus) guidanceStatus.textContent = TERMINAL.has(board.phase)
      ? "任务已结束，请新建任务"
      : guidanceBusy ? "正在保存指导" : "保存后由目标部门在下一次安全激活中处理";
    updateNav(); icons();
    restoreScroll(scrollY);
  }

  function requestStateMarkup(item) {
    const status = item.status;
    return `<span class="dw-request-state ${safeClass(status)}"><span class="dw-status-dot ${status === "running" ? "waiting" : status === "failed" ? "issue" : ""}"></span>${text(attemptStatusLabel(item))}</span>`;
  }

  function attemptRowMarkup(item) {
    const logical = item.logical_call_id || "未知调用";
    const attemptText = `${number(item.attempt, "?")}/${number(item.attempt_count, "?")}`;
    return `<button class="dw-request-row" type="button" data-obs-request="${escapeHtml(item.id)}" aria-label="查看 ${escapeHtml(logical)} 第 ${escapeHtml(item.attempt ?? "?")} 次尝试"><span class="dw-request-time">${text(formatTime(item.created_at))}${requestStateMarkup(item)}<span>尝试 ${escapeHtml(attemptText)}</span></span><span class="dw-request-main"><strong>${text(departmentName(item.department))}</strong><span>请求：${text(attemptRequestedText(item))}</span><span>返回：${text(attemptActualText(item))} · ${text(item.provider_response_id)} · ${text(item.work_round)} · ${text(item.step)}</span></span><span class="dw-request-metrics"><span>Input <strong>${usageValue(item, "input_tokens")}</strong> · Output <strong>${usageValue(item, "output_tokens", "等待响应")}</strong></span><span>耗时 <strong>${duration(usageRawValue(item, "latency_ms"), item.status)}</strong></span></span></button>`;
  }

  function observationShellMarkup() {
    const filters = state.observationFilters;
    const items = state.observationData?.items || [];
    const current = state.observationData ? count(state.observationData.running_attempts) : "未知";
    const task = observationTaskText(state.observationFilters.department);
    const scope = state.observationData?.scope || {};
    return `<div class="dw-observation-page" role="region" aria-label="任务模型请求观测"><header class="dw-observation-head"><div><div class="dw-eyebrow"><span class="dw-status-dot"></span><strong>观测</strong><span>·</span><span>任务</span></div><h1>${state.observationScreen === "detail" ? "模型请求详情" : "模型请求"}</h1><p class="dw-subtitle">请求 · 响应 · usage</p></div><div><span class="dw-current-state"><span class="dw-status-dot waiting"></span>${text(current)} 个请求进行中</span>${taskToolsMarkup()}</div></header><div class="dw-observation-scope"><i data-lucide="activity" aria-hidden="true"></i><span>任务范围</span><strong>${text(task)}</strong><span>·</span><span>${text(scope.time_range || "真实查询结果")}</span><span>·</span><span>${count(state.observationData?.total)} 条记录 · ${count(state.observationData?.total_attempts)} 次已发出 · ${count(state.observationData?.prepared_attempts)} 条准备未发出</span></div><div class="dw-observation-tabs" role="tablist" aria-label="观测页签"><button id="dw-ob-tab-requests" class="dw-observation-tab ${state.observationTab === "requests" ? "is-active" : ""}" type="button" data-ob-tab="requests" role="tab" aria-controls="dw-observation-content" aria-selected="${state.observationTab === "requests"}">请求记录</button><button id="dw-ob-tab-usage" class="dw-observation-tab ${state.observationTab === "usage" ? "is-active" : ""}" type="button" data-ob-tab="usage" role="tab" aria-controls="dw-observation-content" aria-selected="${state.observationTab === "usage"}">用量统计</button></div><div class="dw-observation-filters"><label class="dw-filter-field"><span>部门</span><select class="dw-filter-select" data-obs-department aria-label="按部门筛选"><option value="all" ${filters.department === "all" ? "selected" : ""}>全部部门</option><option value="product" ${filters.department === "product" ? "selected" : ""}>产品部</option><option value="engineering" ${filters.department === "engineering" ? "selected" : ""}>工程部</option><option value="quality" ${filters.department === "quality" ? "selected" : ""}>质检部</option></select></label><label class="dw-filter-field"><span>状态</span><select class="dw-filter-select" data-obs-status aria-label="按状态筛选"><option value="all" ${filters.status === "all" ? "selected" : ""}>全部状态</option><option value="success" ${filters.status === "success" ? "selected" : ""}>成功</option><option value="failed" ${filters.status === "failed" ? "selected" : ""}>失败</option><option value="running" ${filters.status === "running" ? "selected" : ""}>进行中</option><option value="cancelled" ${filters.status === "cancelled" ? "selected" : ""}>取消</option></select></label><label class="dw-filter-field"><span>搜索</span><input class="dw-search-input" type="search" data-obs-search aria-label="搜索调用 ID、Provider 或模型" placeholder="调用 ID、Provider 或模型" value="${escapeHtml(filters.q)}"></label></div><div id="dw-observation-content" role="tabpanel" aria-live="polite"></div><p class="dw-action-error" role="alert" hidden></p></div>`;
  }

  function requestListMarkup() {
    const data = state.observationData;
    if (!data) return `<div class="dw-load-state">正在读取模型请求…</div>`;
    const items = data.items || [];
    const rows = items.length ? items.map(attemptRowMarkup).join("") : `<div class="dw-empty-results">当前筛选没有模型请求</div>`;
    const more = data.next_cursor ? `<div class="dw-task-tools"><button class="dw-tool-button" type="button" data-obs-more ${state.observationMoreLoading ? "disabled" : ""} title="加载更多请求"><i data-lucide="chevrons-down" aria-hidden="true"></i><span>${state.observationMoreLoading ? "正在加载" : "加载更多"}</span></button></div>` : "";
    return `<div class="dw-observation-results-head"><h2>模型请求</h2><p>显示 ${number(items.length, "0")} / ${count(data.total)} 条记录 · ${count(data.total_attempts)} 次已发出</p></div><div class="dw-request-list">${rows}</div>${more}`;
  }

  function coverageLabel(group) {
    if (group?.coverage && typeof group.coverage === "object") {
      return `${count(group.coverage.reported_attempts)}/${count(group.coverage.attempts)} 次尝试已上报`;
    }
    return `${count(group?.reported_attempts)}/${count(group?.attempts)} 次尝试已上报`;
  }

  function usageStatValue(value, running = false) {
    if (typeof value === "number" && Number.isFinite(value)) return number(value);
    return running ? "等待响应" : "未上报";
  }

  function usageCostValue(value, currency, costStatus) {
    if (costStatus === "mixed_currency") return "不可合计";
    if (costStatus === "missing") return "未上报";
    if (typeof value !== "number" || !Number.isFinite(value) || typeof currency !== "string" || !currency) return "未上报";
    return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 12 })} ${escapeHtml(currency)}`;
  }

  function fieldCoverageMarkup(fields) {
    if (!fields || typeof fields !== "object") return "";
    const labels = { input_tokens: "输入", output_tokens: "输出", cache_read_tokens: "缓存读取", total_tokens: "总 Token", cost: "成本" };
    const parts = Object.entries(labels).map(([key, label]) => {
      const value = fields[key];
      if (!value || typeof value !== "object") return null;
      return `${label} ${count(value.reported)}/${count(value.total)}`;
    }).filter(Boolean);
    return parts.length ? `<span class="dw-usage-field-coverage">${parts.map(escapeHtml).join(" · ")}</span>` : "";
  }

  function usageValueMarkup(label, value) {
    return `<span class="dw-usage-value"><span>${escapeHtml(label)}</span><strong>${value}</strong></span>`;
  }

  function usageGroupMarkup(group, maxTotal) {
    const total = group?.total_tokens;
    const width = typeof total === "number" && maxTotal > 0 ? Math.min(100, Math.round((total / maxTotal) * 100)) : 0;
    const runningCount = typeof group?.running_attempts === "number" ? group.running_attempts : null;
    const running = runningCount !== null && runningCount > 0;
    const label = group?.department ? departmentName(group.department) : group?.label || group?.key;
    return `<div class="dw-usage-row"><div class="dw-usage-label"><strong>${text(label)}</strong><span>${text(coverageLabel(group))}${running ? ` · ${number(runningCount)} 进行中` : ""}</span><span class="dw-usage-track" aria-hidden="true"><i style="width:${width}%"></i></span>${fieldCoverageMarkup(group?.coverage?.fields)}</div><div class="dw-usage-values">${usageValueMarkup("输入（含缓存）", usageStatValue(group?.input_tokens))}${usageValueMarkup("输出", usageStatValue(group?.output_tokens, running))}${usageValueMarkup("缓存读取（输入子集）", usageStatValue(group?.cache_read_tokens))}${usageValueMarkup("总 Token", usageStatValue(group?.total_tokens))}${usageValueMarkup("成本", usageCostValue(group?.cost, group?.currency, group?.cost_status))}</div></div>`;
  }

  function usageSection(title, groups) {
    const list = Array.isArray(groups) ? groups : [];
    const totals = list.map(group => group.total_tokens).filter(value => typeof value === "number" && Number.isFinite(value));
    const max = totals.length ? Math.max(...totals) : 0;
    return `<section class="dw-usage-section"><h3>${escapeHtml(title)}</h3><div class="dw-usage-rows">${list.length ? list.map(group => usageGroupMarkup(group, max)).join("") : '<div class="dw-empty-results">当前筛选没有可汇总的模型请求</div>'}</div></section>`;
  }

  function usageMarkup() {
    const data = state.usageData;
    if (!data) return `<div class="dw-load-state">正在读取用量统计…</div>`;
    const totals = data.totals || {};
    const coverage = data.coverage || {};
    const reported = coverage.reported_attempts ?? data.reported_attempts;
    const attempts = coverage.attempts ?? data.total_attempts;
    const prepared = data.prepared_attempts;
    return `<div class="dw-observation-results-head"><h2>用量统计</h2><p>覆盖率 ${text(coverage.percent == null ? null : `${coverage.percent}%`)}</p></div><div class="dw-usage-coverage"><strong>${count(reported)} / ${count(attempts)}</strong><span>次尝试已上报 usage</span>${prepared == null ? "" : `<span>${count(prepared)} 条准备记录未发出</span>`}<span>输入（含缓存）与缓存读取（输入子集）不重复相加</span>${fieldCoverageMarkup(coverage.fields)}</div><div class="dw-usage-total-strip"><div class="dw-usage-total-label"><strong>筛选总计</strong><span>${count(reported)}/${count(attempts)} 次尝试已上报</span></div>${usageValueMarkup("输入（含缓存）", usageStatValue(totals.input_tokens))}${usageValueMarkup("输出", usageStatValue(totals.output_tokens))}${usageValueMarkup("缓存读取（输入子集）", usageStatValue(totals.cache_read_tokens))}${usageValueMarkup("总 Token", usageStatValue(totals.total_tokens))}${usageValueMarkup("成本", usageCostValue(totals.cost, data.currency, data.cost_status))}</div>${usageSection("按部门", data.groups?.departments)}${usageSection("按模型", data.groups?.models)}`;
  }

  function updateObservationContent() {
    const content = root?.querySelector?.("#dw-observation-content");
    if (!content) return;
    content.innerHTML = state.observationTab === "requests" ? requestListMarkup() : usageMarkup();
    root.querySelectorAll(".dw-observation-tab").forEach(tab => {
      const active = tab.dataset.obTab === state.observationTab;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    icons();
  }

  function renderObservability() {
    const scrollY = captureScroll();
    state.view = "observability";
    state.observationScreen = state.selectedAttemptId ? "detail" : "list";
    main.innerHTML = observationShellMarkup();
    updateNav();
    icons();
    updateObservationContent();
    restoreScroll(scrollY);
  }

  function detailOverviewMarkup(detail) {
    const item = detail.attempt || {};
    const usage = usageOf(item);
    const fields = [["请求", attemptRequestedText(item)], ["返回", attemptActualText(item)], ["耗时", duration(usageRawValue(item, "latency_ms"), item.status)], ["成本", usageCostValue(usage?.cost, usage?.currency)], ["本轮工作", item.work_round], ["步骤", item.step], ["Context 快照", item.context_event_id], ["Prompt 版本", item.prompt_version], ["协作请求", item.collaboration_request_id], ["采集范围", item.observed_scope]];
    const tools = detail.tools?.length ? `<details class="dw-detail-extra"><summary>工具调用 <span>${count(detail.tools.length)} 条</span></summary><pre class="dw-json">${json(detail.tools)}</pre></details>` : "";
    return `<div class="dw-detail-panel"><div class="dw-detail-usage">${usageValueMarkup("输入（含缓存）", usageValue(item, "input_tokens"))}${usageValueMarkup("输出", usageValue(item, "output_tokens", "等待响应"))}${usageValueMarkup("缓存读取（输入子集）", usageValue(item, "cache_read_tokens"))}${usageValueMarkup("总 Token", usageValue(item, "total_tokens"))}</div><dl class="dw-detail-grid">${fields.map(([key, value]) => `<div class="dw-detail-field"><dt>${escapeHtml(key)}</dt><dd>${displayValue(value)}</dd></div>`).join("")}</dl>${tools}</div>`;
  }

  function detailRequestMarkup(detail) {
    if (!detail.request) return `<div class="dw-detail-panel"><div class="dw-response-empty">请求原文不可用</div></div>`;
    return `<div class="dw-detail-panel"><div class="dw-json-heading"><h3>Request JSON</h3><span>${text(attemptStatusLabel(detail.attempt))}</span></div><pre class="dw-json">${json(detail.request)}</pre></div>`;
  }

  function detailResponseMarkup(detail) {
    if (detail.attempt?.stage === "prepared") return `<div class="dw-detail-panel"><div class="dw-response-empty">模型请求尚未发出</div></div>`;
    if (!detail.response) return `<div class="dw-detail-panel"><div class="dw-response-empty">等待模型响应</div></div>`;
    return `<div class="dw-detail-panel"><div class="dw-json-heading"><h3>Response JSON</h3><span>${text(attemptStatusLabel(detail.attempt))}</span></div><pre class="dw-json">${json(detail.response)}</pre></div>`;
  }

  function detailEventsMarkup(detail) {
    const rows = (detail.events || []).map(event => `<details class="dw-event-item"><summary class="dw-event-row"><time>${text(formatTime(event.time || event.created_at))}</time><span class="dw-event-kind ${event.tone === "error" ? "error" : event.tone === "waiting" ? "waiting" : ""}">${text(event.type)}</span><p>${text(event.summary)}</p><span class="dw-event-expand">查看原文</span></summary><div class="dw-event-raw"><pre class="dw-json">${json(event.raw ?? event)}</pre></div></details>`).join("");
    return `<div class="dw-detail-panel"><div class="dw-event-list">${rows || '<div class="dw-empty-results">暂无事件记录</div>'}</div></div>`;
  }

  function detailTabContent() {
    const detail = state.observationDetail;
    if (!detail) return "";
    return ({ overview: detailOverviewMarkup(detail), request: detailRequestMarkup(detail), response: detailResponseMarkup(detail), events: detailEventsMarkup(detail) })[state.observationDetailTab] || detailOverviewMarkup(detail);
  }

  function renderObservationDetail() {
    const scrollY = captureScroll();
    const detail = state.observationDetail;
    if (!detail) {
      renderObservability();
      return;
    }
    const item = detail.attempt || {};
    const siblings = Array.isArray(detail.siblings) ? detail.siblings : [];
    const attempts = [...siblings.filter(sibling => sibling.id !== item.id), item].sort((a, b) => Number(a.attempt || 0) - Number(b.attempt || 0));
    state.view = "observability";
    state.observationScreen = "detail";
    state.selectedAttemptId = item.id;
    main.innerHTML = `<div class="dw-observation-page" role="region" aria-label="模型请求详情"><div class="dw-observation-detail-top"><button class="dw-back" type="button" data-obs-back><i data-lucide="arrow-left" aria-hidden="true"></i>返回请求记录</button><button class="dw-back" type="button" data-department="${escapeHtml(item.department)}"><i data-lucide="corner-up-left" aria-hidden="true"></i>返回${text(departmentName(item.department))}</button></div><header class="dw-observation-detail-title" style="margin-top:18px"><h1>模型请求详情</h1><p>${text(item.logical_call_id)} · <span class="dw-request-state ${safeClass(item.status)}">${text(attemptStatusLabel(item))}</span></p></header><div class="dw-observation-crumbs" aria-label="请求关联"><span>任务</span><strong>${text(observationTaskText(item.department))}</strong><span aria-hidden="true">›</span><span>部门</span><strong>${text(departmentName(item.department))}</strong><span aria-hidden="true">›</span><span>本轮工作</span><strong>${text(item.work_round)}</strong><span aria-hidden="true">›</span><span>调用</span><strong>${text(item.logical_call_id)}</strong><span aria-hidden="true">›</span><span>尝试</span><strong>第 ${text(item.attempt)}/${text(item.attempt_count)}</strong></div><div class="dw-attempt-bar"><span class="dw-attempt-label">同次调用 · ${text(item.logical_call_id)}</span>${attempts.map(attempt => `<button class="dw-attempt-option ${attempt.status === "failed" ? "failed" : ""} ${attempt.id === item.id ? "is-active" : ""}" type="button" data-obs-attempt="${escapeHtml(attempt.id)}">第 ${text(attempt.attempt)} 次 · ${text(attemptStatusLabel(attempt))}</button>`).join("")}</div><div class="dw-observation-detail-tabs" role="tablist" aria-label="请求详情页签"><button class="dw-detail-tab ${state.observationDetailTab === "overview" ? "is-active" : ""}" type="button" data-ob-detail-tab="overview" role="tab" aria-selected="${state.observationDetailTab === "overview"}">概览</button><button class="dw-detail-tab ${state.observationDetailTab === "request" ? "is-active" : ""}" type="button" data-ob-detail-tab="request" role="tab" aria-selected="${state.observationDetailTab === "request"}">Request</button><button class="dw-detail-tab ${state.observationDetailTab === "response" ? "is-active" : ""}" type="button" data-ob-detail-tab="response" role="tab" aria-selected="${state.observationDetailTab === "response"}">Response</button><button class="dw-detail-tab ${state.observationDetailTab === "events" ? "is-active" : ""}" type="button" data-ob-detail-tab="events" role="tab" aria-selected="${state.observationDetailTab === "events"}">事件</button></div><div id="dw-observation-detail-content" role="tabpanel" aria-live="polite">${detailTabContent()}</div><p class="dw-action-error" role="alert" hidden></p></div>`;
    updateNav(); icons();
    restoreScroll(scrollY);
  }

  function updateNav() {
    if (!root) return;
    root.querySelectorAll(".dw-nav-item").forEach(item => {
      const active = state.view === "overview" ? item.dataset.view === "overview" : state.view === "observability" ? item.dataset.view === "observability" : item.dataset.department === state.department;
      item.classList.toggle("is-active", active);
      if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    });
  }

  function renderCurrent() {
    if (!main) return;
    if (state.view === "observability" && state.observationScreen === "detail" && state.observationDetail) renderObservationDetail();
    else if (state.view === "observability") renderObservability();
    else if (state.view === "department") renderDepartment(state.department);
    else renderOverview();
  }

  function closeStream() {
    if (stream) {
      stream.close();
      stream = null;
    }
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  function handleLoopEvent(runId = state.runId, token = state.routeToken) {
    if (!runId || token !== state.routeToken || runId !== state.runId) return;
    return loadRunPayload(runId, token, true);
  }

  function openStream(runId, token) {
    closeStream();
    if (typeof EventSource !== "function" || !runId) return;
    try {
      stream = new EventSource(apiPath(runId, "/stream"));
      stream.addEventListener("loop", () => {
        if (token !== state.routeToken || runId !== state.runId) return;
        handleLoopEvent(runId, token);
      });
      stream.onerror = () => {};
    } catch { stream = null; }
    refreshTimer = setInterval(() => {
      if (token === state.routeToken && runId === state.runId) handleLoopEvent(runId, token);
    }, 5000);
  }

  async function loadRunPayload(runId, token, silent = false) {
    const seq = ++runRequestSeq;
    try {
      const data = await fetchJSON(apiPath(runId));
      if (token !== state.routeToken || runId !== state.runId || seq !== runRequestSeq) return null;
      state.runPayload = data;
      state.busy = Boolean(data.worker_active);
      state.error = data.execution_error || "";
      if (!silent) renderCurrent();
      else if (state.view === "overview") renderOverview();
      else if (state.view === "department") await loadDepartment(state.department, token);
      else if (state.view === "observability" && state.observationScreen === "list") await loadObservationData();
      else if (state.view === "observability" && state.observationScreen === "detail" && state.selectedAttemptId) {
        await loadAttemptDetail(state.selectedAttemptId, { push: false });
      }
      else if (!main?.innerHTML) renderCurrent();
      return data;
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== runRequestSeq) return null;
      if (!silent) renderError(error);
      return null;
    }
  }

  async function loadDepartment(department, token) {
    if (!state.runId) return;
    const runId = state.runId;
    const dataKey = `${runId}/${department}`;
    const seq = (departmentRequestSeq.get(dataKey) || 0) + 1;
    departmentRequestSeq.set(dataKey, seq);
    state.departmentLoading = true;
    try {
      const data = await fetchJSON(apiPath(runId, `/departments/${encodeURIComponent(department)}`));
      if (token !== state.routeToken || runId !== state.runId || seq !== departmentRequestSeq.get(dataKey)) return;
      state.departmentData.set(dataKey, data);
      state.departmentLoading = false;
      const contexts = Array.isArray(data.contexts) ? data.contexts : [];
      const selected = contexts.find(item => item.id === state.selectedContext[dataKey]) || contexts.filter(item => item.purpose === "work").at(-1) || contexts.at(-1) || null;
      state.selectedContext[dataKey] = selected?.id || null;
      if (state.view === "department" && state.department === department) renderDepartment(department);
      if (selected?.id) await loadContextDetail(selected.id, token);
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== departmentRequestSeq.get(dataKey)) return;
      state.departmentLoading = false;
      renderError(error);
    }
  }

  async function loadContextDetail(attemptId, token = state.routeToken) {
    if (!state.runId || !attemptId) return;
    const runId = state.runId;
    const contextKey = `${runId}/${attemptId}`;
    const seq = (contextRequestSeq.get(contextKey) || 0) + 1;
    contextRequestSeq.set(contextKey, seq);
    try {
      const detail = await fetchJSON(apiPath(runId, `/model-attempts/${encodeURIComponent(attemptId)}`));
      if (token !== state.routeToken || runId !== state.runId || seq !== contextRequestSeq.get(contextKey)) return;
      state.contextDetails.set(contextKey, detail);
      const currentContext = `${state.runId}/${state.department}`;
      if (state.view === "department" && state.selectedContext[currentContext] === attemptId) renderDepartment(state.department);
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== contextRequestSeq.get(contextKey)) return;
      state.contextDetails.set(contextKey, { context: null, error: error.message });
      if (state.view === "department" && state.selectedContext[`${state.runId}/${state.department}`] === attemptId) renderDepartment(state.department);
    }
  }

  async function loadObservationData({ append = false } = {}) {
    if (!state.runId) return;
    const runId = state.runId;
    const token = state.routeToken;
    const seq = ++state.observationSeq;
    const params = { department: state.observationFilters.department, status: state.observationFilters.status, q: state.observationFilters.q, limit: 50 };
    if (append) params.cursor = state.observationData?.next_cursor;
    state.observationMoreLoading = append;
    if (!append) state.observationLoading = true;
    try {
      const requests = await fetchJSON(queryPath(apiPath(runId, "/model-attempts"), params));
      let usage = state.usageData;
      if (!append || !usage || state.observationTab === "usage") {
        usage = await fetchJSON(queryPath(apiPath(runId, "/model-usage"), { department: state.observationFilters.department, status: state.observationFilters.status, q: state.observationFilters.q }));
      }
      if (token !== state.routeToken || runId !== state.runId || seq !== state.observationSeq) return;
      const prior = append && state.observationData ? state.observationData.items || [] : [];
      state.observationData = { ...requests, items: [...prior, ...(requests.items || [])] };
      state.usageData = usage;
      state.observationLoading = false;
      state.observationMoreLoading = false;
      if (state.view === "observability" && state.observationScreen === "list") {
        renderObservability();
        if (state.observationTab === "usage") updateObservationContent();
      }
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== state.observationSeq) return;
      state.observationLoading = false;
      state.observationMoreLoading = false;
      renderError(error);
    }
  }

  async function loadAttemptDetail(attemptId, { push = true } = {}) {
    if (!state.runId || !attemptId) return;
    const runId = state.runId;
    const alreadyShowing = state.observationScreen === "detail" && state.observationDetail?.attempt?.id === attemptId;
    state.selectedAttemptId = attemptId;
    state.observationScreen = "detail";
    state.view = "observability";
    const token = state.routeToken;
    const seq = ++state.detailSeq;
    if (push) updateRoute({ push: true });
    if (!alreadyShowing) {
      state.observationDetail = null;
      renderLoading("正在读取模型请求详情");
    }
    const jsonScroll = alreadyShowing ? captureJsonScroll() : 0;
    try {
      const detail = await fetchJSON(apiPath(runId, `/model-attempts/${encodeURIComponent(attemptId)}`));
      if (token !== state.routeToken || runId !== state.runId || attemptId !== state.selectedAttemptId || seq !== state.detailSeq) return;
      state.observationDetail = detail;
      renderObservationDetail();
      if (alreadyShowing) restoreJsonScroll(jsonScroll);
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== state.detailSeq) return;
      if (!alreadyShowing) renderError(error);
    }
  }

  async function handlePopState() {
    const previousRunId = state.runId;
    routeFromLocation();
    if (state.runId !== previousRunId) {
      if (state.runId && state.runs.some(item => item.run_id === state.runId)) {
        await activateRun(state.runId, { push: false, preserveRoute: true });
        return;
      }
      closeStream();
      state.runPayload = null;
      state.observationData = null;
      state.usageData = null;
      state.observationDetail = null;
      const token = ++state.routeToken;
      if (!state.runId) {
        renderCurrent();
        return;
      }
      renderLoading("正在读取任务");
      await loadRunPayload(state.runId, token);
      if (token === state.routeToken && state.runId) openStream(state.runId, token);
      if (token === state.routeToken && state.view === "department") await loadDepartment(state.department, token);
      if (token === state.routeToken && state.view === "observability") {
        if (state.observationScreen === "detail" && state.selectedAttemptId) await loadAttemptDetail(state.selectedAttemptId, { push: false });
        else await loadObservationData();
      }
      return;
    }
    const token = ++state.routeToken;
    if (state.observationScreen !== "detail") state.observationDetail = null;
    renderCurrent();
    if (state.view === "department" && state.runId) loadDepartment(state.department, token);
    if (state.view === "observability" && state.runId && state.observationScreen === "list") loadObservationData();
    if (state.view === "observability" && state.selectedAttemptId && state.runId) loadAttemptDetail(state.selectedAttemptId, { push: false });
    if (state.runId) openStream(state.runId, token);
  }

  async function activateRun(runId, { push = true, preserveRoute = false } = {}) {
    if (!runId || !state.runs.some(item => item.run_id === runId)) return;
    const requestedAttempt = preserveRoute ? state.selectedAttemptId : null;
    const requestedScreen = preserveRoute ? state.observationScreen : "list";
    closeStream();
    state.runId = runId;
    state.runPayload = null;
    state.observationData = null;
    state.usageData = null;
    state.observationDetail = null;
    state.selectedAttemptId = requestedAttempt;
    state.observationScreen = requestedAttempt && requestedScreen === "detail" ? "detail" : "list";
    const token = ++state.routeToken;
    if (push) updateRoute({ push: true });
    renderLoading("正在读取任务");
    await loadRunPayload(runId, token);
    if (token === state.routeToken && state.runId === runId) openStream(runId, token);
    if (token === state.routeToken && state.view === "department") await loadDepartment(state.department, token);
    if (token === state.routeToken && state.view === "observability") {
      if (state.observationScreen === "detail" && state.selectedAttemptId) await loadAttemptDetail(state.selectedAttemptId, { push: false });
      else await loadObservationData();
    }
  }

  async function loadRuns(preferredRunId = null, push = false) {
    try {
      const payload = await fetchJSON("/api/runs");
      if (!Array.isArray(payload.runs)) throw new Error("任务列表格式无效");
      state.runs = payload.runs;
      const selected = preferredRunId && state.runs.some(item => item.run_id === preferredRunId)
        ? preferredRunId
        : state.runId && state.runs.some(item => item.run_id === state.runId) ? state.runId : state.runs[0]?.run_id || null;
      if (selected) await activateRun(selected, { push, preserveRoute: !push && Boolean(state.selectedAttemptId) });
      else renderCurrent();
    } catch (error) {
      renderError(error);
    }
  }

  async function refreshCurrent() {
    if (!state.runId) return loadRuns();
    const token = state.routeToken;
    await loadRunPayload(state.runId, token);
    if (token === state.routeToken && state.view === "department") await loadDepartment(state.department, token);
    if (token === state.routeToken && state.view === "observability" && state.observationScreen === "list") await loadObservationData();
  }

  async function createRun(event) {
    event.preventDefault();
    if (state.creating) return;
    if (event.submitter && event.submitter.value === "cancel") return document.getElementById("dw-task-dialog")?.close();
    const form = event.currentTarget;
    const task = form.elements.task.value;
    if (!task.trim()) return;
    state.newTaskDraft = {
      task,
      max_cycles: form.elements.max_cycles.value,
      context_window: form.elements.context_window.value,
    };
    state.creating = true;
    const submit = document.getElementById("dw-task-submit");
    if (submit) submit.disabled = true;
    const errorNode = document.getElementById("dw-task-error");
    if (errorNode) errorNode.hidden = true;
    try {
      const body = { task };
      if (form.elements.max_cycles.value) body.max_cycles = Number(form.elements.max_cycles.value);
      if (form.elements.context_window.value) body.context_window = Number(form.elements.context_window.value);
      const result = await fetchJSON("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      document.getElementById("dw-task-dialog")?.close();
      state.newTaskDraft = { task: "", max_cycles: "8", context_window: "32000" };
      if (result.run_id) {
        state.view = "overview";
        state.observationScreen = "list";
        state.observationDetail = null;
        state.selectedAttemptId = null;
        await loadRuns(result.run_id, true);
      }
    } catch (error) {
      if (errorNode) { errorNode.hidden = false; errorNode.textContent = error.message; }
    } finally {
      state.creating = false;
      if (submit) submit.disabled = false;
    }
  }

  async function cancelRun() {
    if (!state.runId || state.cancelling || TERMINAL.has(state.runPayload?.board?.phase)) return;
    state.cancelling = true;
    try {
      await fetchJSON(apiPath(state.runId, "/cancel"), { method: "POST" });
      await refreshCurrent();
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      state.cancelling = false;
    }
  }

  async function addGlobalInput(form) {
    if (!state.runId || state.inputSubmitting === state.runId || TERMINAL.has(state.runPayload?.board?.phase)) return;
    const textarea = form.querySelector("[data-global-draft]");
    const value = textarea?.value || "";
    if (!value.trim()) return;
    const runId = state.runId;
    const token = state.routeToken;
    state.globalDrafts[runId] = value;
    state.inputSubmitting = runId;
    try {
      await fetchJSON(apiPath(runId, "/inputs"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: value }) });
      if (token !== state.routeToken || runId !== state.runId) return;
      if (state.globalDrafts[runId] === value) state.globalDrafts[runId] = "";
      await refreshCurrent();
    } catch (error) {
      if (token === state.routeToken && runId === state.runId) setStatus(error.message, "error");
    } finally {
      if (state.inputSubmitting === runId) state.inputSubmitting = null;
    }
  }

  async function exportRun() {
    if (!state.runId) return;
    const runId = state.runId;
    try {
      const payload = await fetchJSON(apiPath(runId, "/export"));
      const link = document.createElement("a");
      link.href = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(payload, null, 2))}`;
      link.download = `${runId}-observations.json`;
      link.click?.();
      setStatus("任务观测已导出", "success");
    } catch (error) {
      setStatus(error.message, "error");
    }
  }

  async function addDepartmentGuidance(form) {
    const department = form?.dataset?.departmentForm;
    if (!state.runId || !department) return;
    const textarea = form.querySelector?.("[data-dept-draft]");
    const value = textarea?.value || "";
    if (!value.trim()) return;
    const runId = state.runId;
    const token = state.routeToken;
    const key = `${runId}/${department}`;
    state.deptDrafts[key] = value;
    state.guidanceSubmitting[key] = true;
    renderDepartment(department);
    try {
      await fetchJSON(apiPath(runId, `/departments/${encodeURIComponent(department)}/guidance`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      });
      if (token !== state.routeToken || runId !== state.runId) return;
      if (state.deptDrafts[key] === value) delete state.deptDrafts[key];
      await loadDepartment(department, token);
      await loadRunPayload(runId, token, true);
      setStatus("部门指导已接收", "success");
    } catch (error) {
      if (token === state.routeToken && runId === state.runId) setStatus(error.message, "error");
    } finally {
      delete state.guidanceSubmitting[key];
      if (token === state.routeToken && runId === state.runId && state.view === "department") renderDepartment(department);
    }
  }

  function openTaskDialog() {
    const dialog = document.getElementById("dw-task-dialog");
    if (!dialog) return;
    const form = document.getElementById("dw-task-dialog-form");
    if (form) {
      form.elements.task.value = state.newTaskDraft.task;
      form.elements.max_cycles.value = state.newTaskDraft.max_cycles;
      form.elements.context_window.value = state.newTaskDraft.context_window;
    }
    dialog.showModal();
    icons();
    document.getElementById("dw-task-text")?.focus();
  }

  function openHistoryDialog() {
    const dialog = document.getElementById("dw-history-dialog");
    const list = document.getElementById("dw-history-list");
    if (!dialog || !list) return;
    list.innerHTML = state.runs.length ? state.runs.map(run => `<div class="dw-history-row"><button type="button" data-history-run="${escapeHtml(run.run_id)}"><strong>${text(run.task || run.run_id)}</strong><span>${text(run.run_id)} · ${text(phaseLabel(run.phase))}</span></button><span class="dw-record-state ${TERMINAL.has(run.phase) ? "" : "waiting"}">${text(run.outcome || phaseLabel(run.phase))}</span></div>`).join("") : `<p class="dw-small">暂无历史任务</p>`;
    list.querySelectorAll("[data-history-run]").forEach(button => button.addEventListener("click", () => {
      dialog.close();
      activateRun(button.dataset.historyRun, { push: true });
    }));
    dialog.showModal();
    icons();
  }

  function openPromptDialog(key) {
    const [runId, department] = String(key).split("/");
    if (runId !== state.runId) return;
    const data = currentDepartmentData(department);
    const prompt = data?.prompt_latest || state.runPayload?.prompts?.current?.[department] || data?.prompt;
    if (!prompt?.text) return;
    state.promptDrafts[key] = state.promptDrafts[key] ?? prompt.text;
    const dialog = document.getElementById("dw-prompt-dialog");
    const textarea = document.getElementById("dw-prompt-text");
    if (!dialog || !textarea) return;
    textarea.value = state.promptDrafts[key];
    dialog.dataset.promptKey = key;
    dialog.dataset.promptRouteToken = String(state.routeToken);
    dialog.showModal();
    icons();
    textarea.focus();
  }

  async function savePrompt(event) {
    event.preventDefault();
    if (event.submitter?.value === "cancel") return document.getElementById("dw-prompt-dialog")?.close();
    if (state.promptSubmitting) return;
    const dialog = document.getElementById("dw-prompt-dialog");
    const key = dialog?.dataset.promptKey;
    const textValue = document.getElementById("dw-prompt-text")?.value || "";
    if (!key || !textValue.trim() || !state.runId) return;
    const separator = key.lastIndexOf("/");
    const runId = separator < 0 ? "" : key.slice(0, separator);
    const department = separator < 0 ? "" : key.slice(separator + 1);
    const token = Number(dialog.dataset.promptRouteToken);
    if (!runId || runId !== state.runId || token !== state.routeToken) return;
    state.promptDrafts[key] = textValue;
    state.promptSubmitting = true;
    const submit = dialog.querySelector("button[value='default']");
    if (submit) submit.disabled = true;
    const errorNode = document.getElementById("dw-prompt-error");
    if (errorNode) errorNode.hidden = true;
    try {
      await fetchJSON(apiPath(runId, `/prompts/${encodeURIComponent(department)}`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: textValue }) });
      if (token !== state.routeToken || runId !== state.runId) return;
      delete state.promptDrafts[key];
      dialog.close();
      await loadDepartment(department, token);
      await loadRunPayload(runId, token);
    } catch (error) {
      if (token === state.routeToken && runId === state.runId && errorNode) { errorNode.hidden = false; errorNode.textContent = error.message; }
    } finally {
      state.promptSubmitting = false;
      if (submit) submit.disabled = false;
    }
  }

  async function openEvent(eventId, documentKind = "") {
    if (!state.runId || !eventId) return;
    const runId = state.runId;
    const token = state.routeToken;
    const seq = ++state.eventSeq;
    const dialog = document.getElementById("dw-event-dialog");
    const documentNode = document.getElementById("dw-event-document");
    const jsonNode = document.getElementById("dw-event-json");
    const titleNode = document.getElementById("dw-event-title");
    const versionNode = document.getElementById("dw-event-version");
    const filesNode = document.getElementById("dw-event-files");
    const sourcesNode = document.getElementById("dw-event-sources");
    if (documentNode) { documentNode.textContent = ""; documentNode.hidden = true; }
    if (jsonNode) { jsonNode.textContent = "正在读取…"; jsonNode.hidden = false; }
    if (versionNode) { versionNode.textContent = ""; versionNode.hidden = true; }
    if (filesNode) { filesNode.replaceChildren(); filesNode.hidden = true; }
    if (sourcesNode) sourcesNode.replaceChildren();
    try {
      const data = await fetchJSON(apiPath(runId, `/events/${encodeURIComponent(eventId)}`));
      if (token !== state.routeToken || runId !== state.runId || seq !== state.eventSeq) return;
      let documentText = null;
      if (documentKind === "tree" && data.tree_archive) documentText = JSON.stringify(data.tree_archive, null, 2);
      else if (documentKind === "git") documentText = data.git_version_detail?.diff;
      else if (documentKind === "prd" || documentKind === "plan") documentText = data[`${documentKind}_markdown`];
      if (documentKind && typeof documentText !== "string") throw new Error(documentKind === "git" ? "Git 版本不可用" : "原文工件不可用");
      if (titleNode) titleNode.textContent = documentKind === "git" ? "Git 变更" : documentKind === "tree" ? "完整交付清单" : documentKind ? `${documentKind.toUpperCase()}.md` : "事件详情";
      if (jsonNode) { jsonNode.textContent = JSON.stringify(data, null, 2); jsonNode.hidden = Boolean(documentKind); }
      if (documentNode) { documentNode.textContent = documentText || ""; documentNode.hidden = !documentKind; }
      const version = data.git_version_detail;
      if (versionNode && version) { versionNode.hidden = false; versionNode.textContent = `提交 ${version.commit || "未知"}\n父提交 ${version.parent_commit || "初始版本"}\n树 ${version.tree || "未知"}`; }
      if (filesNode && version) {
        filesNode.hidden = false;
        const files = version.files || [];
        files.forEach(file => { const item = document.createElement("li"); item.textContent = `${({ A: "新增", M: "修改", D: "删除", R: "移动", C: "复制", T: "类型变化" }[file.status] || file.status || "变化")} ${file.old_path ? `${file.old_path} -> ` : ""}${file.path || "未知文件"}${file.binary ? "（二进制）" : ""}`; filesNode.appendChild(item); });
        if (!files.length) { const item = document.createElement("li"); item.textContent = "无文件变化"; filesNode.appendChild(item); }
      }
      if (sourcesNode && data.tree_archive?.tree?.files) {
        data.tree_archive.tree.files.forEach(file => {
          const link = document.createElement("a");
          link.textContent = `${file.path} (${number(file.size, "未知大小")}${typeof file.size === "number" ? " B" : ""})`;
          link.href = `${apiPath(runId, `/events/${encodeURIComponent(eventId)}/files`)}?path=${encodeURIComponent(file.path)}`;
          link.download = String(file.path).split("/").pop();
          sourcesNode.appendChild(link);
        });
      }
      if (dialog) dialog.showModal();
    } catch (error) {
      if (token !== state.routeToken || runId !== state.runId || seq !== state.eventSeq) return;
      setStatus(error.message, "error");
      dialog?.close();
    }
  }

  function clickHandler(event) {
    const target = event.target.closest?.("button");
    if (!target || !root?.contains?.(target)) return;
    if (target.dataset.action === "new-task") return openTaskDialog();
    if (target.dataset.action === "history") return openHistoryDialog();
    if (target.dataset.action === "cancel") return cancelRun();
    if (target.dataset.action === "export") return exportRun();
    if (target.dataset.action === "refresh") return refreshCurrent();
    if (target.dataset.historyRun) {
      document.getElementById("dw-history-dialog")?.close();
      return activateRun(target.dataset.historyRun, { push: true });
    }
    if (target.dataset.runPicker) return activateRun(target.value, { push: true });
    if (target.dataset.department) {
      state.view = "department";
      state.department = target.dataset.department;
      state.observationDetail = null;
      state.selectedAttemptId = null;
      const token = ++state.routeToken;
      updateRoute({ push: true });
      renderCurrent();
      if (state.runId) loadDepartment(state.department, token);
      return;
    }
    if (target.dataset.view) {
      state.view = target.dataset.view === "observability" ? "observability" : "overview";
      state.observationScreen = "list";
      state.observationDetail = null;
      state.selectedAttemptId = null;
      const token = ++state.routeToken;
      updateRoute({ push: true });
      renderCurrent();
      if (state.runId) openStream(state.runId, token);
      if (state.view === "observability" && state.runId) loadObservationData();
      if (state.view === "overview" && state.runId) loadRunPayload(state.runId, token);
      return;
    }
    if (target.dataset.handoff) {
      state.selectedHandoff = target.dataset.handoff;
      updateRoute({ push: false });
      renderOverview();
      return;
    }
    if (target.dataset.eventId) return openEvent(target.dataset.eventId, target.dataset.document);
    if (target.dataset.obsBack !== undefined) {
      state.observationScreen = "list";
      state.observationDetail = null;
      state.selectedAttemptId = null;
      updateRoute({ push: true });
      renderObservability();
      openStream(state.runId, state.routeToken);
      loadObservationData();
      return;
    }
    if (target.dataset.obsRequest) return loadAttemptDetail(target.dataset.obsRequest);
    if (target.dataset.obsAttempt) return loadAttemptDetail(target.dataset.obsAttempt);
    if (target.dataset.obTab) {
      state.observationTab = target.dataset.obTab;
      updateRoute({ push: true });
      updateObservationContent();
      loadObservationData();
      return;
    }
    if (target.dataset.obDetailTab) {
      state.observationDetailTab = target.dataset.obDetailTab;
      updateRoute({ push: false });
      if (state.observationDetail) renderObservationDetail();
      return;
    }
    if (target.dataset.obsMore !== undefined) return loadObservationData({ append: true });
    if (target.dataset.observeAttempt) {
      state.observationFilters.department = currentDepartmentData()?.department || state.observationFilters.department;
      return loadAttemptDetail(target.dataset.observeAttempt);
    }
    if (target.dataset.inspectorTab) {
      state.inspectorTab = target.dataset.inspectorTab;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.contextId) {
      state.selectedContext[`${state.runId}/${state.department}`] = target.dataset.contextId;
      updateRoute({ push: false });
      renderDepartment(state.department);
      loadContextDetail(target.dataset.contextId, state.routeToken);
      return;
    }
    if (target.dataset.contextPartSource) {
      const selectedAttempt = state.selectedContext[`${state.runId}/${state.department}`];
      state.selectedContextPart[`${state.runId}/${selectedAttempt}`] = target.dataset.contextPartSource;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.inspectorToggle !== undefined) {
      state.inspectorCollapsed = !state.inspectorCollapsed;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.promptEdit) return openPromptDialog(target.dataset.promptEdit);
  }

  function inputHandler(event) {
    const target = event.target;
    if (target.matches?.("[data-global-draft]") && state.runId) state.globalDrafts[state.runId] = target.value;
    if (target.matches?.("[data-dept-draft]") && state.runId) state.deptDrafts[`${state.runId}/${target.dataset.deptDraft}`] = target.value;
    if (target.matches?.("[data-obs-search]")) {
      state.observationFilters.q = target.value;
      updateRoute({ push: false });
      clearTimeout(filterTimer);
      filterTimer = setTimeout(() => loadObservationData(), 180);
    }
  }

  function changeHandler(event) {
    const target = event.target;
    if (target.matches?.("[data-obs-department]")) state.observationFilters.department = target.value;
    if (target.matches?.("[data-obs-status]")) state.observationFilters.status = target.value;
    if (target.matches?.("[data-run-picker]")) return activateRun(target.value, { push: true });
    if (target.matches?.("[data-obs-department], [data-obs-status]")) {
      state.observationData = null;
      state.usageData = null;
      updateRoute({ push: false });
      loadObservationData();
    }
  }

  function submitHandler(event) {
    const form = event.target;
    if (form.id === "dw-global-form") { event.preventDefault(); addGlobalInput(form); }
    if (form.id === "dw-dept-form") { event.preventDefault(); addDepartmentGuidance(form); }
  }

  function bootDialogs() {
    const taskForm = document.getElementById("dw-task-dialog-form");
    taskForm?.addEventListener("input", () => {
      state.newTaskDraft = { task: taskForm.elements.task.value, max_cycles: taskForm.elements.max_cycles.value, context_window: taskForm.elements.context_window.value };
    });
    taskForm?.addEventListener("submit", createRun);
    document.getElementById("dw-prompt-dialog-form")?.addEventListener("submit", savePrompt);
  }

  function boot() {
    routeFromLocation();
    root.addEventListener("click", clickHandler);
    root.addEventListener("input", inputHandler);
    root.addEventListener("change", changeHandler);
    root.addEventListener("submit", submitHandler);
    globalThis.addEventListener?.("popstate", () => { handlePopState(); });
    bootDialogs();
    loadRuns();
  }

  const api = {
    state,
    escapeHtml,
    fetchJSON,
    renderOverview,
    renderDepartment,
    renderObservability,
    renderObservationDetail,
    updateObservationContent,
    loadRuns,
    activateRun,
    loadRunPayload,
    loadDepartment,
    loadContextDetail,
    loadObservationData,
    loadAttemptDetail,
    openEvent,
    usageMarkup,
    contextMarkup,
    promptMarkup,
    createRun,
    cancelRun,
    exportRun,
    addGlobalInput,
    addDepartmentGuidance,
    openTaskDialog,
    openPromptDialog,
    savePrompt,
    refreshCurrent,
    updateRoute,
    handlePopState,
    handleLoopEvent,
    openStream,
    changeHandler,
  };
  globalThis.harnessWeb = api;
  if (!root || !main || globalThis.__HARNESS_SKIP_BOOT__) return;
  boot();
})();
