(() => {
  "use strict";

  const workbench = document.getElementById("yudao-workbench");
  const root = document.getElementById("department-workspace-prototype") || workbench;
  const main = document.getElementById("dw-main");
  const sidebar = document.getElementById("yp-sidebar");
  const topbar = document.getElementById("yp-topbar");
  const shell = document.getElementById("yp-shell");
  const TERMINAL = new Set(["DONE", "FAILED", "PAUSED"]);
  const DEPARTMENTS = {
    product: { name: "产品部", role: "需求与方案", icon: "clipboard-list" },
    engineering: { name: "工程部", role: "实现与交付", icon: "braces" },
    quality: { name: "质检部", role: "验证与反馈", icon: "check-check" },
  };
  const DEPARTMENT_ORDER = ["product", "engineering", "quality"];
  const WORK_STATUS = {
    not_started: "未开始", in_progress: "进行中", adopted: "已采纳",
    held: "基线已变", released_unsettled: "已放行", stopped: "已停止",
  };
  const CONTEXT_SOURCE_LABELS = {
    intend: "用户原文", current_work: "当前工作", department_rules: "部门规则",
    professional_completion: "完成标准", collaboration_rules: "协作规则", input_handling: "输入处理",
    proposal_contract: "提案约束", binding_refs: "绑定依据", allowed_tools: "可用工具",
    department_history: "部门历史", tool_schemas: "工具定义", input_progress: "输入进度",
    loop_limits: "循环限制", current_contract: "当前合同", current_engineering_plan: "当前工程计划",
    latest_response: "最近回应", current_product_spec: "当前产品规格", prior_delivery: "前次交付",
    qa_defects: "质检缺陷", causal_chain: "因果链", department_memory: "部门记忆", tools: "工具定义",
    product_spec: "产品规格", effective_contract: "有效合同", engineering_plan: "工程计划",
    delivery_spec: "交付规格", validation_feedback: "质检反馈", pending_request: "待处理协作",
    provider_binding: "Provider 绑定", project: "项目上下文",
  };
  const STATUS_LABELS = { success: "成功", failed: "失败", running: "进行中", cancelled: "已取消" };
  const PHASE_LABELS = {
    PRODUCT_SPEC: "产品处理中", ENGINEERING_PLAN: "工程计划中", ENGINEERING: "工程处理中",
    QUALITY: "质检处理中", DONE: "已完成", FAILED: "执行失败", PAUSED: "已暂停",
  };

  const state = {
    view: "overview",
    department: "product",
    projectId: null,
    projects: [],
    project: null,
    workItemId: null,
    runId: null,
    runPayload: null,
    health: null,
    departmentData: new Map(),
    contextDetails: new Map(),
    selectedContext: {},
    departmentLoading: false,
    observationTab: "requests",
    observationScreen: "list",
    observationDetailTab: "overview",
    observationData: null,
    usageData: null,
    observationLoading: false,
    observationFilters: { department: "all", status: "all", q: "", work_item: "all", provider: "all", requested_model: "all", actual_model: "all" },
    observationCursor: null,
    observationMoreLoading: false,
    observationDetail: null,
    selectedAttemptId: null,
    selectedContextPart: {},
    inspectorTab: "context",
    inspectorCollapsed: false,
    deptMenu: false,
    roomInspect: false,
    selectedHandoff: null,
    globalDrafts: {},
    deptDrafts: {},
    promptDrafts: {},
    promptConfigs: {},
    overviewPane: "handoffs",
    boardMode: "flow",
    sidebarCollapsed: false,
    mobileNav: false,
    projectSearch: "",
    projectMenu: false,
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
    newProjectDraft: { name: "", goal: "" },
    workDraft: { text: "", max_cycles: "8", context_window: "32000" },
    error: "",
    scrollPositions: {},
    observationReturn: null,
  };

  let stream = null;
  let refreshTimer = null;
  let filterTimer = null;
  let runRequestSeq = 0;
  let projectRequestSeq = 0;
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
      explained: "已解释",
      completed: "动作已核实",
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



  function projectPath(id, suffix = "") {
    return `/api/projects/${encodeURIComponent(id)}${suffix}`;
  }

  function workItems() {
    return Array.isArray(state.project?.work_items) ? state.project.work_items : [];
  }

  function workItemById(id) {
    return workItems().find(item => item.work_item_id === id) || null;
  }

  function activeWorkItem() {
    return workItemById(state.project?.active_work_item_id);
  }

  function focusedWorkItem() {
    if (state.workItemId) return workItemById(state.workItemId);
    return null;
  }

  function focusedRunId() {
    const item = focusedWorkItem() || activeWorkItem();
    return item?.run_id || state.runId || null;
  }

  function hasInProgress() {
    return Boolean(state.project?.active_work_item_id);
  }

  function isWritable() {
    return Boolean(state.project) && !state.project.archived;
  }

  function deptDraftKey(department = state.department) {
    const scope = state.workItemId || "project";
    return `${state.projectId || "none"}/${department}/${scope}`;
  }

  function globalDraftKey() {
    const scope = state.workItemId || "project";
    return `${state.projectId || "none"}/${scope}`;
  }

  function currentDepartmentData(department = state.department) {
    const runId = focusedRunId();
    if (!runId) return null;
    return state.departmentData.get(`${runId}/${department}`) || null;
  }

  function scrollKey() {
    return `${state.projectId || "none"}/${state.view}/${state.department}/${state.workItemId || "project"}/${state.selectedAttemptId || "list"}`;
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

  function snapshotReturn() {
    return {
      projectId: state.projectId,
      view: state.view,
      department: state.department,
      workItemId: state.workItemId,
      inspectorTab: state.inspectorTab,
      roomInspect: state.roomInspect,
      selectedContext: { ...state.selectedContext },
      selectedContextPart: { ...state.selectedContextPart },
      globalDrafts: { ...state.globalDrafts },
      deptDrafts: { ...state.deptDrafts },
      scroll: captureScroll(),
    };
  }

  function applyReturn(snapshot) {
    if (!snapshot) return;
    state.view = snapshot.view || "department";
    state.department = snapshot.department || state.department;
    state.workItemId = snapshot.workItemId || null;
    state.inspectorTab = snapshot.inspectorTab || "context";
    state.roomInspect = Boolean(snapshot.roomInspect);
    Object.assign(state.selectedContext, snapshot.selectedContext || {});
    Object.assign(state.selectedContextPart, snapshot.selectedContextPart || {});
    Object.assign(state.globalDrafts, snapshot.globalDrafts || {});
    Object.assign(state.deptDrafts, snapshot.deptDrafts || {});
    state.observationScreen = "list";
    state.observationDetail = null;
    state.selectedAttemptId = null;
  }

  function routeFromLocation() {
    const search = typeof location !== "undefined" ? new URLSearchParams(location.search) : new URLSearchParams();
    const view = search.get("view");
    state.view = ["observability", "department", "overview", "providers"].includes(view) ? view : "overview";
    state.department = DEPARTMENTS[search.get("department")] ? search.get("department") : "product";
    state.projectId = search.get("project") || null;
    state.workItemId = search.get("work_item") || null;
    state.overviewPane = ["materials", "settings", "board"].includes(search.get("pane")) ? search.get("pane") : "handoffs";
    state.boardMode = search.get("board") === "board" ? "board" : "flow";
    state.observationTab = search.get("obTab") === "usage" ? "usage" : "requests";
    state.observationScreen = search.get("attempt") ? "detail" : "list";
    state.selectedAttemptId = search.get("attempt") || null;
    state.observationDetailTab = ["overview", "request", "response", "events"].includes(search.get("detailTab"))
      ? search.get("detailTab") : "overview";
    state.inspectorTab = ["context", "provider", "prompt"].includes(search.get("inspectorTab"))
      ? search.get("inspectorTab") : "context";
    state.inspectorCollapsed = search.get("inspector") === "collapsed";
    const contextId = search.get("context");
    const runId = focusedRunId();
    if (contextId && runId) state.selectedContext[`${runId}/${state.department}`] = contextId;
    const contextPart = search.get("contextPart");
    if (contextId && contextPart && runId) state.selectedContextPart[`${runId}/${contextId}`] = contextPart;
    state.observationFilters = {
      department: ["product", "engineering", "quality"].includes(search.get("departmentFilter")) ? search.get("departmentFilter") : "all",
      status: ["success", "failed", "running", "cancelled"].includes(search.get("status")) ? search.get("status") : "all",
      q: search.get("q") || "",
      work_item: search.get("obsWorkItem") || "all",
      provider: search.get("provider") || "all",
      requested_model: search.get("requestedModel") || "all",
      actual_model: search.get("actualModel") || "all",
    };
  }

  function updateRoute({ push = true } = {}) {
    if (typeof history === "undefined" || typeof location === "undefined") return;
    const params = new URLSearchParams();
    if (state.projectId) params.set("project", state.projectId);
    if (state.view !== "overview") params.set("view", state.view);
    if (state.view === "providers") params.set("view", "providers");
    if (state.view === "department") params.set("department", state.department);
    if (state.workItemId) params.set("work_item", state.workItemId);
    if (state.view === "overview" && state.overviewPane !== "handoffs") params.set("pane", state.overviewPane);
    if (state.view === "overview" && state.boardMode === "board") params.set("board", "board");
    if (state.view === "observability") {
      if (state.observationTab !== "requests") params.set("obTab", state.observationTab);
      if (state.observationScreen === "detail" && state.selectedAttemptId) params.set("attempt", state.selectedAttemptId);
      if (state.observationScreen === "detail" && state.observationDetailTab !== "overview") params.set("detailTab", state.observationDetailTab);
      if (state.observationFilters.department !== "all") params.set("departmentFilter", state.observationFilters.department);
      if (state.observationFilters.status !== "all") params.set("status", state.observationFilters.status);
      if (state.observationFilters.q) params.set("q", state.observationFilters.q);
      if (state.observationFilters.work_item && state.observationFilters.work_item !== "all") params.set("obsWorkItem", state.observationFilters.work_item);
      if (state.observationFilters.provider && state.observationFilters.provider !== "all") params.set("provider", state.observationFilters.provider);
      if (state.observationFilters.requested_model && state.observationFilters.requested_model !== "all") params.set("requestedModel", state.observationFilters.requested_model);
      if (state.observationFilters.actual_model && state.observationFilters.actual_model !== "all") params.set("actualModel", state.observationFilters.actual_model);
    }
    if (state.view === "department") {
      if (state.inspectorTab !== "context") params.set("inspectorTab", state.inspectorTab);
      if (state.inspectorCollapsed) params.set("inspector", "collapsed");
      const runId = focusedRunId();
      const contextId = runId && state.selectedContext[`${runId}/${state.department}`];
      if (contextId) params.set("context", contextId);
      const contextPart = contextId && state.selectedContextPart[`${runId}/${contextId}`];
      if (contextPart) params.set("contextPart", contextPart);
    }
    const next = `${location.pathname}${params.toString() ? `?${params}` : ""}${location.hash || ""}`;
    const method = push ? "pushState" : "replaceState";
    history[method]({}, "", next);
  }

  function icons() {
    const scope = workbench || root;
    if (!scope) return;
    scope.querySelectorAll(".dw-icon-button[aria-label], .dw-tool-button[title], .dw-inline-action[title], .yp-icon[aria-label], .yp-btn[title]").forEach(button => {
      if (button.getAttribute("title")) button.setAttribute("data-tooltip", button.getAttribute("title"));
      if (button.getAttribute("aria-label")) button.setAttribute("data-tooltip", button.getAttribute("aria-label"));
    });
    if (globalThis.lucide && typeof globalThis.lucide.createIcons === "function") {
      globalThis.lucide.createIcons({ attrs: { width: 16, height: 16 } });
    }
  }

  function renderLoading(label = "正在读取真实记录") {
    if (main) main.innerHTML = `<div class="yp-empty"><div class="dw-load-state">${escapeHtml(label)}…</div></div>`;
    renderChrome();
    icons();
  }

  function renderError(error) {
    const message = error?.message || String(error || "读取失败");
    state.error = message;
    if (main) main.innerHTML = `<div class="yp-empty"><div class="dw-load-state error">${escapeHtml(message)}</div><div class="dw-task-tools"><button class="dw-tool-button" type="button" data-action="refresh" title="重新读取"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>重新读取</span></button></div></div>`;
    renderChrome();
    icons();
  }




  function workStatusLabel(status) {
    return WORK_STATUS[status] || status || "未知";
  }

  function boardColumn(item) {
    if (["adopted", "held", "released_unsettled", "stopped"].includes(item.status)) return "done";
    if (item.department === "engineering") return "engineering";
    if (item.department === "quality") return "quality";
    return "product";
  }

  function breadcrumbInner() {
    if (state.view === "providers") {
      return `<button type="button" data-action="home">项目</button><span>/</span><strong>模型与 Provider</strong>`;
    }
    const parts = [`<button type="button" data-action="home">项目</button>`];
    const project = state.project;
    if (!project) return parts.join("");
    const item = focusedWorkItem() || activeWorkItem();
    if (state.view === "overview" && !item) {
      parts.push(`<span>/</span><strong>${text(project.name)}</strong>`);
      return parts.join("");
    }
    parts.push(`<span>/</span><button type="button" data-view="overview">${text(project.name)}</button>`);
    if (item) {
      if (state.view === "overview") parts.push(`<span>/</span><strong>${text(item.title)}</strong>`);
      else parts.push(`<span>/</span><button type="button" data-view="overview">${text(item.title)}</button>`);
    }
    if (state.view === "department") {
      parts.push(`<span>/</span><strong>${text(departmentName(state.department))}</strong>`);
    }
    if (state.view === "observability") {
      const attempt = state.observationDetail?.attempt;
      if (state.observationScreen === "detail" && attempt) {
        const dept = attempt.department || state.department;
        parts.push(`<span>/</span><button type="button" data-department="${escapeHtml(dept || "")}">${text(departmentName(dept))}</button>`);
        parts.push(`<span>/</span><strong>请求 ${text(attempt.attempt != null ? String(attempt.attempt) : "")}</strong>`);
      } else {
        parts.push(`<span>/</span><strong>观测</strong>`);
      }
    }
    return parts.join("");
  }

  function filteredProjects() {
    const q = (state.projectSearch || "").trim().toLowerCase();
    const rows = state.projects || [];
    if (!q) return rows;
    return rows.filter(item => String(item.name || "").toLowerCase().includes(q) || String(item.project_id || "").toLowerCase().includes(q));
  }

  function renderChrome() {
    if (shell) {
      shell.classList.toggle("nav-collapsed", Boolean(state.sidebarCollapsed));
      shell.classList.toggle("show-nav", Boolean(state.mobileNav));
    }
    if (sidebar) {
      const rows = filteredProjects().map(item => {
        const selected = item.project_id === state.projectId;
        const mark = item.active_work_item_id ? "waiting" : item.archived ? "muted" : "";
        return `<button class="yp-project ${selected ? "is-selected" : ""}" type="button" data-project-id="${escapeHtml(item.project_id)}" title="${escapeHtml(item.name)}"><span class="yp-project-mark ${mark}"></span><span>${text(item.name)}</span></button>`;
      }).join("");
      sidebar.innerHTML = `<div class="yp-brand"><i data-lucide="layers-3" aria-hidden="true"></i><span>Yudao</span><button class="yp-icon yp-sidebar-toggle" type="button" data-action="toggle-sidebar" aria-label="${state.sidebarCollapsed ? "展开项目列表" : "折叠项目列表"}"><i data-lucide="${state.sidebarCollapsed ? "panel-left-open" : "panel-left-close"}" aria-hidden="true"></i></button></div><button class="yp-btn primary" type="button" data-action="new-project"><i data-lucide="plus" aria-hidden="true"></i>从想法新建</button><div class="yp-search"><i data-lucide="search" aria-hidden="true"></i><input data-project-search placeholder="搜索项目" value="${escapeHtml(state.projectSearch)}" aria-label="搜索项目"></div><div class="yp-side-label"><span>项目</span></div><div class="yp-project-list">${rows || '<p class="yp-footnote">还没有项目</p>'}</div><div class="yp-side-bottom"><button class="yp-sidebar-link ${state.view === "providers" ? "is-active" : ""}" type="button" data-action="providers"><i data-lucide="cpu" aria-hidden="true"></i><span>模型管理</span></button><p class="yp-footnote">${state.projects.length ? `${state.projects.length} 个项目` : "从想法建立第一个项目"}</p></div>`;
    }
    if (topbar) {
      const project = state.project;
      const active = activeWorkItem();
      const status = project == null ? "未选择项目" : project.archived ? "已归档" : active ? `${workStatusLabel(active.status)} · ${departmentName(active.department) || phaseLabel(active.phase)}` : "空闲";
      const dot = project == null ? "muted" : project.archived ? "muted" : active ? "waiting" : "";
      const providerCrumb = state.view === "providers" ? `<span>/</span><strong>模型与 Provider</strong>` : "";
      const menu = state.projectMenu && project ? `<div class="yp-menu">${project.archived ? `<button type="button" data-action="restore-project"><i data-lucide="archive-restore" aria-hidden="true"></i>恢复</button>` : `<button type="button" data-action="rename-project"><i data-lucide="pencil" aria-hidden="true"></i>重命名</button><button type="button" data-action="pin-project"><i data-lucide="pin" aria-hidden="true"></i>${project.pinned ? "取消置顶" : "置顶"}</button><button type="button" data-action="archive-project"><i data-lucide="archive" aria-hidden="true"></i>归档</button>`}</div>` : "";
      topbar.innerHTML = `<div class="yp-row"><button class="yp-icon yp-mobile-toggle" type="button" data-action="toggle-mobile-nav" aria-label="打开项目列表"><i data-lucide="menu" aria-hidden="true"></i></button><nav class="yp-breadcrumb" aria-label="位置">${breadcrumbInner()}</nav></div><div class="yp-row"><button class="yp-btn quiet" type="button" data-action="providers">模型与 Provider</button><span class="yp-auto"><span class="yp-dot ${dot}"></span><span>${text(status)}</span></span>${project ? `<div class="yp-menu-wrap"><button class="yp-icon" type="button" data-action="toggle-project-menu" aria-label="项目菜单"><i data-lucide="more-horizontal" aria-hidden="true"></i></button>${menu}</div>` : ""}</div>`;
    }
  }

  function projectTabsMarkup() {
    if (!state.project) return "";
    const tab = (view, department, label) => {
      const active = view === "department" ? state.view === "department" && state.department === department : state.view === view;
      const attr = view === "department" ? `data-department="${department}"` : `data-view="${view}"`;
      return `<button class="yp-tab ${active ? "is-selected" : ""}" type="button" ${attr}>${label}</button>`;
    };
    const secondary = state.view === "overview" ? `<div class="yp-secondary-tabs">${[["handoffs", "流转"], ["board", "协作看板"], ["materials", "资料与依据"], ["settings", "项目设置"]].map(([id, label]) => `<button class="yp-tab ${state.overviewPane === id ? "is-selected" : ""}" type="button" data-overview-pane="${id}">${label}</button>`).join("")}</div>` : "";
    return `<nav class="yp-tabs" aria-label="项目页面">${tab("overview", null, "概览")}${tab("department", "product", "产品")}${tab("department", "engineering", "工程")}${tab("department", "quality", "质检")}${tab("observability", null, "观测")}</nav>${secondary}`;
  }

  function dhComposerMarkup({ formId, draftAttr, draftKey, department, placeholder }) {
    const archived = isWritable() === false;
    const busy = Boolean(state.creating || state.inputSubmitting);
    if (!hasInProgress()) {
      return `<form class="yp-composer" id="${formId}" data-department-form="${escapeHtml(department || "")}" data-dh-form="1"><textarea ${draftAttr} rows="3" placeholder="${escapeHtml(placeholder)}" ${archived ? "disabled" : ""}>${escapeHtml(currentDraft(department ? state.deptDrafts : state.globalDrafts, draftKey))}</textarea><div class="yp-composer-footer"><span class="yp-small">${archived ? "归档项目只读" : "没有进行中的事项时，不会调用模型"}</span><div class="yp-dh-actions"><button class="yp-btn" type="submit" data-dh-action="record" ${archived || busy ? "disabled" : ""}>记录原文</button><button class="yp-btn primary" type="submit" data-dh-action="start" ${archived || busy ? "disabled" : ""}>作为新事项开始</button></div></div><p class="yp-error dw-action-error" role="alert" ${state.error ? "" : "hidden"}>${text(state.error, "")}</p></form>`;
    }
    return "";
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
    const latest = (data.events || []).filter(event => event.department === key).at(-1);
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

  function uiHost() {
    return {
      escapeHtml, text, displayValue, number, count, safeClass, json,
      departmentName, attemptStatusLabel, formatTime, duration,
      usageValue, usageRawValue, usageCostValue, usageValueMarkup,
      attemptRequestedText, attemptActualText, requestStateMarkup,
      focusedRunId, focusedWorkItem, workItems, state,
      contextDetailFor, attemptIdFromContext, contextSourceLabel,
      observationTaskText, projectTabsMarkup,
    };
  }


  function contextMarkup(department, data) {
    return globalThis.YudaoContextView.render(uiHost(), department, data);
  }

  function providerMarkup(provider) {
    const value = provider || {};
    const rows = [["提供方", value.provider], ["模型", value.model], ["协议", value.protocol], ["温度", value.temperature], ["上下文窗", value.context_window], ["最大输出", value.max_output_tokens]];
    return `<div class="dw-inspect-panel" id="dw-panel-provider" role="tabpanel" aria-labelledby="dw-tab-provider"><h3>Provider 配置</h3><dl class="dw-data-list">${rows.map(([key, item]) => `<div class="dw-data-row"><dt>${key}</dt><dd>${text(item)}</dd></div>`).join("")}</dl><p class="dw-small">以上为该部门最近一次模型请求记录的调用目标。</p></div>`;
  }


  function contextDetailFor(attemptId) {
    const runId = focusedRunId();
    return attemptId && runId ? state.contextDetails.get(`${runId}/${attemptId}`) || null : null;
  }

  function promptMarkup(department, data) {
    const config = state.promptConfigs[department] || {};
    const selectedAttempt = state.selectedContext[`${focusedRunId()}/${department}`];
    const selectedDetail = contextDetailFor(selectedAttempt);
    const snapshotPrompt = selectedDetail?.context?.parts?.find(item => item.source === "department_rules") || null;
    const adopted = data?.prompt || {};
    const actual = snapshotPrompt ? { version: snapshotPrompt.version, text: snapshotPrompt.text } : adopted;
    return `<div class="dw-inspect-panel" id="dw-panel-prompt" role="tabpanel" aria-labelledby="dw-tab-prompt"><div class="dw-prompt-version"><span>项目当前配置</span><span>${config.source === "configured" ? `配置 v${text(config.version)}` : "默认 v0"}</span></div><pre class="dw-prompt-block">${text(config.text, "当前配置原文不可用")}</pre><div class="dw-prompt-version"><span>所选请求实际 Prompt</span><span>${actual.version ? `run Prompt v${actual.version}` : "尚未绑定请求"}</span></div><pre class="dw-prompt-block">${text(actual.text, "所选请求没有 Prompt 原文")}</pre><p class="dw-small">历史请求不从当前配置回填。</p>${isWritable() ? `<button class="dw-observation-link" type="button" data-prompt-edit="${escapeHtml(department)}" title="配置 Prompt"><i data-lucide="pencil" aria-hidden="true"></i>配置 Prompt</button>` : ""}</div>`;
  }

  function scopeSelectMarkup() {
    const items = workItems();
    const options = [`<option value="" ${!state.workItemId ? "selected" : ""}>整个项目</option>`].concat(items.map(item => `<option value="${escapeHtml(item.work_item_id)}" ${item.work_item_id === state.workItemId ? "selected" : ""}>${text(item.title)} · ${text(workStatusLabel(item.status))}</option>`));
    return `<div class="yp-dept-toolbar"><label class="yp-small">范围 <select class="yp-scope-select" data-work-scope aria-label="部门范围">${options.join("")}</select></label></div>`;
  }

  function departmentComposer(department, data, board) {
    const key = deptDraftKey(department);
    if (!hasInProgress()) {
      return dhComposerMarkup({ formId: "dw-dept-form", draftAttr: `data-dept-draft="${escapeHtml(department)}"`, draftKey: key, department, placeholder: "作为新事项开始，或记录原文" });
    }
    const phase = board?.phase;
    const guidanceBusy = Boolean(state.guidanceSubmitting[`${focusedRunId()}/${department}`]);
    const disabled = board == null || TERMINAL.has(phase) || guidanceBusy || (state.workItemId && state.workItemId !== state.project.active_work_item_id);
    return `<form class="dw-compose" id="dw-dept-form" data-department-form="${escapeHtml(department)}"><div class="dw-compose-meta"><span>当前接收方</span><strong>发给${text(departmentName(department))}</strong></div><textarea class="dw-textarea" rows="3" data-dept-draft="${escapeHtml(department)}" aria-label="发给${escapeHtml(departmentName(department))}" placeholder="追加对话或指导" ${disabled ? "disabled" : ""}>${escapeHtml(currentDraft(state.deptDrafts, key))}</textarea><div class="dw-compose-actions"><span>${TERMINAL.has(phase) ? "事项已结束，不会自动新建" : guidanceBusy ? "正在保存指导" : "保存后由目标部门在下一次安全激活中处理"}</span><button class="dw-primary" type="submit" ${disabled ? "disabled" : ""}><i data-lucide="send" aria-hidden="true"></i>发送指导</button></div></form>`;
  }

  function roomBubble(data, status) {
    const latest = ((data && data.messages) || []).at(-1);
    if (!latest) return status;
    const parsed = parseMessageText(latest.text).text || status;
    return parsed.length > 28 ? `${parsed.slice(0, 28)}…` : parsed;
  }

  function roomLogMarkup(data) {
    const messages = (data && data.messages) || [];
    if (!messages.length) return `<div class="pixel-log-row"><span class="pixel-log-time">—</span><span class="pixel-log-msg">暂无部门消息</span></div>`;
    return messages.map(message => {
      const parsed = parseMessageText(message.text);
      const link = message.event_id ? legacyLink(message.event_id, "", "查看事件") : "";
      return `<div class="pixel-log-row"><span class="pixel-log-time">${text(formatTime(message.created_at || message.time))}</span><span class="pixel-log-msg">${text(message.source)} ${text(parsed.text, "")}</span>${link}</div>`;
    }).join("");
  }

  function deptSettingsMarkup(department) {
    const promptButton = isWritable() ? `<button type="button" data-prompt-edit="${escapeHtml(department)}"><i data-lucide="file-text" aria-hidden="true"></i><span>部门 Prompt 设置</span></button>` : "";
    return `<div class="dept-settings-menu-wrap"><button class="yp-btn" type="button" data-action="toggle-dept-menu" aria-expanded="${state.deptMenu ? "true" : "false"}"><i data-lucide="settings" aria-hidden="true"></i><span>部门设置</span></button><div class="dept-settings-menu" ${state.deptMenu ? "" : "hidden"}><button type="button" data-inspector-tab="provider"><i data-lucide="cpu" aria-hidden="true"></i><span>本次模型</span></button>${promptButton}<button type="button" data-inspector-tab="context"><i data-lucide="file-search" aria-hidden="true"></i><span>Context</span></button><button type="button" data-action="providers"><i data-lucide="sliders-horizontal" aria-hidden="true"></i><span>模型与 Provider</span></button></div></div>`;
  }

  function roomInspectMarkup(department, data) {
    const panel = state.inspectorTab === "provider" ? providerMarkup(data?.provider) : state.inspectorTab === "prompt" ? promptMarkup(department, data) : contextMarkup(department, data);
    return `<section class="pixel-room-inspect" aria-label="${departmentName(department)}检查"><div class="dw-inspector-tabs" role="tablist" aria-label="检查项"><button id="dw-tab-context" class="dw-inspector-tab ${state.inspectorTab === "context" ? "is-active" : ""}" type="button" data-inspector-tab="context" role="tab" aria-selected="${state.inspectorTab === "context"}">Context</button><button id="dw-tab-provider" class="dw-inspector-tab ${state.inspectorTab === "provider" ? "is-active" : ""}" type="button" data-inspector-tab="provider" role="tab" aria-selected="${state.inspectorTab === "provider"}">Provider</button><button id="dw-tab-prompt" class="dw-inspector-tab ${state.inspectorTab === "prompt" ? "is-active" : ""}" type="button" data-inspector-tab="prompt" role="tab" aria-selected="${state.inspectorTab === "prompt"}">Prompt</button></div>${panel}</section>`;
  }

  function renderDepartment(department) {
    const scrollY = captureScroll();
    state.view = "department";
    state.department = department;
    if (!state.project) {
      main.innerHTML = `<div class="yp-empty"><h1>没有选中的项目</h1><p>请先选择项目再进入部门工作区。</p></div>`;
      renderChrome(); icons(); restoreScroll(scrollY); return;
    }
    const data = currentDepartmentData(department);
    const board = state.runPayload?.board;
    const item = focusedWorkItem() || activeWorkItem();
    const status = data ? departmentStatusLabel(data.status, phaseLabel(board?.phase)) : (item ? workStatusLabel(item.status) : "空闲");
    const departmentTask = item ? departmentTitle(department, data || {}, board || { task: item.title }) : departmentName(department);
    const provider = data?.provider || {};
    const modelLabel = provider.model || "未上报";
    const providerLabel = provider.provider || "未上报";
    const room = data ? `<div class="pixel-room-boundary"><div class="pixel-room-header"><strong>ROOM_${escapeHtml(department.toUpperCase())}</strong><span>${text(status)} · ${text(providerLabel)}</span></div><div class="pixel-room-stage"><div class="pixel-room-topwall"><div class="crt-monitor-board"><div class="crt-monitor-text">&gt; TARGET: ${text(departmentTask)}<br>&gt; MODEL: ${text(modelLabel)}<br>&gt; PROTOCOL: ${text(provider.protocol, "未上报")}<br>&gt; STATUS: ${text(status)}</div></div></div><div class="pixel-room-floor"></div><div class="pixel-desk-lane"><div class="pixel-workstation"><div class="pixel-bubble">${text(roomBubble(data, status))}</div><div class="pixel-agent" aria-hidden="true"><div class="pixel-agent-head"><div class="pixel-agent-eye-l"></div><div class="pixel-agent-eye-r"></div></div><div class="pixel-agent-body">${text(departmentName(department))}</div></div><div class="pixel-desk"><div class="pixel-computer"></div></div><span class="pixel-workstation-label">${text(departmentName(department))}主 Agent</span></div></div></div><div class="pixel-room-log dw-timeline" aria-live="polite">${roomLogMarkup(data)}</div></div>` : `<div class="dw-load-state">${hasInProgress() || item ? "正在读取部门消息…" : "当前没有事项。可以用下面的输入作为新事项开始，或记录原文。"}</div>`;
    const input = `<div class="pixel-room-input-box"><div class="pixel-input-head"><strong><i data-lucide="message-square" aria-hidden="true"></i>向${text(departmentName(department))}下达指令或追加人类反馈</strong><span class="yp-small">输入将作为人类指导进入本部门下一次安全激活</span></div>${departmentComposer(department, data, board)}</div>`;
    main.innerHTML = `<div class="dw-page dw-department-page">${projectTabsMarkup()}${scopeSelectMarkup()}<header class="yp-heading dw-dept-header"><div><div class="yp-eyebrow">三部门工作区</div><h1>${text(departmentName(department))}工作间</h1><p class="yp-subtitle">${text(DEPARTMENTS[department].role)} · 运行目标：<strong>${text(modelLabel)}</strong>（${text(providerLabel)}） · ${text(status)}</p></div><div class="yp-heading-actions">${deptSettingsMarkup(department)}</div></header>${room}${input}${roomInspectMarkup(department, data)}<p class="dw-action-error" role="alert" ${state.error ? "" : "hidden"}>${text(state.error, "")}</p></div>`;
    if (data) {
      const timeline = main.querySelector?.(".dw-timeline");
      timeline?.insertAdjacentHTML?.("afterend", guidanceMarkup(data));
    }
    renderChrome(); icons(); restoreScroll(scrollY);
  }



  function requestStateMarkup(item) {
    const status = item.status;
    return `<span class="dw-request-state ${safeClass(status)}"><span class="dw-status-dot ${status === "running" ? "waiting" : status === "failed" ? "issue" : ""}"></span>${text(attemptStatusLabel(item))}</span>`;
  }

  function attemptRowMarkup(item) {
    return globalThis.YudaoTraceView.attemptRowMarkup(uiHost(), item);
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


  function observationShellMarkup() {
    const filters = state.observationFilters;
    const current = state.observationData ? count(state.observationData.running_attempts) : "未知";
    const task = observationTaskText(state.observationFilters.department);
    const items = workItems();
    const workOptions = [`<option value="all" ${filters.work_item === "all" ? "selected" : ""}>全部事项</option>`].concat(items.map(item => `<option value="${escapeHtml(item.work_item_id)}" ${filters.work_item === item.work_item_id ? "selected" : ""}>${text(item.title)}</option>`)).join("");
    return `<div class="dw-observation-page" role="region" aria-label="项目模型请求观测">${projectTabsMarkup()}<header class="dw-observation-head"><div><div class="dw-eyebrow"><span class="dw-status-dot"></span><strong>观测</strong><span>·</span><span>项目</span></div><h1>${state.observationScreen === "detail" ? "模型请求详情" : "模型请求"}</h1><p class="dw-subtitle">请求 · 响应 · usage</p></div><div><span class="dw-current-state"><span class="dw-status-dot waiting"></span>${text(current)} 个请求进行中</span></div></header><div class="dw-observation-scope"><i data-lucide="activity" aria-hidden="true"></i><span>项目范围</span><strong>${text(state.project?.name || task)}</strong><span>·</span><span>${count(state.observationData?.total)} 条记录 · ${count(state.observationData?.total_attempts)} 次已发出</span></div><div class="dw-observation-tabs" role="tablist" aria-label="观测页签"><button id="dw-ob-tab-requests" class="dw-observation-tab ${state.observationTab === "requests" ? "is-active" : ""}" type="button" data-ob-tab="requests" role="tab" aria-controls="dw-observation-content" aria-selected="${state.observationTab === "requests"}">请求记录</button><button id="dw-ob-tab-usage" class="dw-observation-tab ${state.observationTab === "usage" ? "is-active" : ""}" type="button" data-ob-tab="usage" role="tab" aria-controls="dw-observation-content" aria-selected="${state.observationTab === "usage"}">用量统计</button></div>${globalThis.YudaoTraceView.filtersMarkup(uiHost(), filters, workOptions)}<div id="dw-observation-content" role="tabpanel" aria-live="polite"></div><p class="dw-action-error" role="alert" hidden></p></div>`;
  }

  function renderObservability() {
    const scrollY = captureScroll();
    state.view = "observability";
    state.observationScreen = state.selectedAttemptId ? "detail" : "list";
    if (!state.project) {
      main.innerHTML = `<div class="yp-empty"><h1>没有选中的项目</h1><p>选择项目后查看模型请求。</p></div>`;
      renderChrome(); icons(); restoreScroll(scrollY); return;
    }
    main.innerHTML = observationShellMarkup();
    renderChrome();
    icons();
    updateObservationContent();
    restoreScroll(scrollY);
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
    const returnDept = state.observationReturn?.department || item.department;
    main.innerHTML = `<div class="dw-observation-page" role="region" aria-label="模型请求详情"><div class="dw-observation-detail-top"><button class="dw-back" type="button" data-obs-back><i data-lucide="arrow-left" aria-hidden="true"></i>返回请求记录</button><button class="dw-back" type="button" data-obs-return data-department="${escapeHtml(returnDept || "")}"><i data-lucide="corner-up-left" aria-hidden="true"></i>返回${text(departmentName(returnDept))}</button></div><header class="dw-observation-detail-title" style="margin-top:18px"><h1>模型请求详情</h1><p>${text(item.logical_call_id)} · <span class="dw-request-state ${safeClass(item.status)}">${text(attemptStatusLabel(item))}</span></p>${globalThis.YudaoTraceView.detailHeaderExtras(uiHost(), detail)}</header><div class="dw-observation-crumbs" aria-label="请求关联"><span>项目</span><strong>${text(state.project?.name)}</strong><span aria-hidden="true">›</span><span>事项</span><strong>${text(item.title || focusedWorkItem()?.title || "项目范围")}</strong><span aria-hidden="true">›</span><span>部门</span><strong>${text(departmentName(item.department))}</strong><span aria-hidden="true">›</span><span>本轮工作</span><strong>${text(item.work_round)}</strong><span aria-hidden="true">›</span><span>调用</span><strong>${text(item.logical_call_id)}</strong><span aria-hidden="true">›</span><span>尝试</span><strong>第 ${text(item.attempt)}/${text(item.attempt_count)}</strong></div><div class="dw-attempt-bar"><span class="dw-attempt-label">同次调用 · ${text(item.logical_call_id)}</span>${attempts.map(attempt => `<button class="dw-attempt-option ${attempt.status === "failed" ? "failed" : ""} ${attempt.id === item.id ? "is-active" : ""}" type="button" data-obs-attempt="${escapeHtml(attempt.id)}" data-obs-run="${escapeHtml(attempt.run_id || item.run_id || "")}">第 ${text(attempt.attempt)} 次 · ${text(attemptStatusLabel(attempt))}</button>`).join("")}</div><div class="dw-observation-detail-tabs" role="tablist" aria-label="请求详情页签"><button class="dw-detail-tab ${state.observationDetailTab === "overview" ? "is-active" : ""}" type="button" data-ob-detail-tab="overview" role="tab" aria-selected="${state.observationDetailTab === "overview"}">概览</button><button class="dw-detail-tab ${state.observationDetailTab === "request" ? "is-active" : ""}" type="button" data-ob-detail-tab="request" role="tab" aria-selected="${state.observationDetailTab === "request"}">Request</button><button class="dw-detail-tab ${state.observationDetailTab === "response" ? "is-active" : ""}" type="button" data-ob-detail-tab="response" role="tab" aria-selected="${state.observationDetailTab === "response"}">Response</button><button class="dw-detail-tab ${state.observationDetailTab === "events" ? "is-active" : ""}" type="button" data-ob-detail-tab="events" role="tab" aria-selected="${state.observationDetailTab === "events"}">事件</button></div><div id="dw-observation-detail-content" role="tabpanel" aria-live="polite">${detailTabContent()}</div><p class="dw-action-error" role="alert" hidden></p></div>`;
    renderChrome(); icons();
    restoreScroll(scrollY);
  }

  function updateNav() {
    renderChrome();
    if (!main) return;
    main.querySelectorAll(".yp-tab[data-view], .yp-tab[data-department]").forEach(item => {
      const active = item.dataset.view ? item.dataset.view === state.view : state.view === "department" && item.dataset.department === state.department;
      item.classList.toggle("is-selected", active);
      item.classList.toggle("is-active", active);
    });
  }

  function renderCurrent() {
    if (!main) return;
    if (state.view === "providers") return renderProviders();
    if (state.view === "observability" && state.observationScreen === "detail" && state.observationDetail) renderObservationDetail();
    else if (state.view === "observability") renderObservability();
    else if (state.view === "department") renderDepartment(state.department);
    else renderOverview();
  }

  function renderProviders() {
    renderChrome();
    if (globalThis.harnessProviderConfig && typeof globalThis.harnessProviderConfig.mount === "function") {
      globalThis.harnessProviderConfig.mount(main);
    } else if (main) {
      main.innerHTML = `<div class="yp-empty"><h1>模型与 Provider</h1><p>配置界面未能加载。</p></div>`;
    }
    icons();
  }




  function workCardMarkup(item) {
    const dept = item.department ? departmentName(item.department) : "未进入部门";
    return `<button class="yp-work-card" type="button" data-work-item="${escapeHtml(item.work_item_id)}" data-work-department="${escapeHtml(item.department || "product")}"><strong class="yp-work-card-title">${text(item.title)}</strong><div class="yp-work-card-meta"><span class="yp-tag ${item.status === "in_progress" ? "amber" : item.status === "adopted" ? "green" : item.status === "stopped" ? "red" : ""}">${text(workStatusLabel(item.status))}</span><span class="yp-tag outline">${text(dept)}</span></div><p>${text(item.pending_question || item.stop_reason || item.phase || item.text)}</p></button>`;
  }

  function collaborationMarkup() {
    const items = workItems();
    const columns = {
      product: items.filter(item => boardColumn(item) === "product"),
      engineering: items.filter(item => boardColumn(item) === "engineering"),
      quality: items.filter(item => boardColumn(item) === "quality"),
      done: items.filter(item => boardColumn(item) === "done"),
    };
    const col = (key, title, hint) => `<div class="yp-board-col ${key}"><div class="yp-col-head"><div><strong>${title}</strong><p>${hint}</p></div><span class="yp-col-count">${columns[key].length}</span></div><div class="yp-card-stack">${columns[key].map(workCardMarkup).join("") || '<div class="yp-empty-col">暂无事项</div>'}</div></div>`;
    const flow = `<div class="yp-flow">${[["product", "产品"], ["engineering", "工程"], ["quality", "质检"], ["done", "完成"]].map(([key, label], index) => {
      const current = activeWorkItem() && boardColumn(activeWorkItem()) === key;
      return `<div class="yp-flow-step ${current ? "current" : ""}"><div class="yp-flow-head"><span class="yp-flow-marker">${index + 1}</span><strong>${label}</strong></div><div class="yp-flow-items">${columns[key].map(item => `<button class="yp-flow-item" type="button" data-work-item="${escapeHtml(item.work_item_id)}" data-work-department="${escapeHtml(item.department || key)}"><strong>${text(item.title)}</strong><p>${text(workStatusLabel(item.status))}</p></button>`).join("") || '<div class="yp-empty-col">暂无</div>'}</div></div>`;
    }).join("")}</div>`;
    const toggle = `<div class="yp-board-tools"><div class="yp-view-toggle"><button type="button" data-board-mode="flow" class="${state.boardMode === "flow" ? "is-selected" : ""}">流程</button><button type="button" data-board-mode="board" class="${state.boardMode === "board" ? "is-selected" : ""}">看板</button></div><span class="yp-small">卡片不可拖拽，点击进入事项</span></div>`;
    const board = `<div class="yp-board">${col("product", "产品", "需求与方案")}${col("engineering", "工程", "实现与交付")}${col("quality", "质检", "验证与反馈")}${col("done", "完成", "采纳或停止")}</div>`;
    return `<section class="yp-section"><div class="yp-section-title"><h2>协作总览</h2></div>${toggle}${state.boardMode === "board" ? board : flow}</section>`;
  }

  function handoffListMarkup() {
    const recent = (state.project?.overview?.recent || []).slice(0, 12).map(item => `<div class="yp-handoff"><span class="yp-handoff-time">${text(formatTime(item.at || item.created_at, true))}</span><div><strong>${text(item.title || item.type)}</strong><p>${text(item.summary || item.body || "")}</p></div><span class="yp-handoff-status">${text(item.status || "")}</span></div>`).join("");
    return `<section class="yp-section"><div class="yp-section-title"><div><h2>跨部门流转交接</h2><p class="yp-small">需求交接、版本交付与缺陷返工记录</p></div></div><div class="yp-handoff-list">${recent || '<p class="yp-small">还没有项目事件</p>'}</div></section>`;
  }

  function materialsMarkup() {
    const materials = state.project?.materials || [];
    const rows = materials.map(item => `<article class="item"><header><span>${text(item.department ? departmentName(item.department) : "项目")}</span><span>${text(formatTime(item.recorded_at, true))}</span></header><pre class="dw-json">${text(item.text, "原文不可用")}</pre></article>`).join("");
    const runData = state.runPayload;
    return `<section class="yp-section"><div class="yp-section-title"><h2>资料与依据</h2><p class="yp-small">项目材料只记录原文，不注入后续事项</p></div><div class="dw-material-groups"><details class="dw-material-group" open><summary>已记录原文 <span>${count(materials.length)} 条</span></summary><div class="list">${rows || '<p class="dw-small">暂无记录原文</p>'}</div></details></div>${runData ? legacyOverviewMarkup(runData) : ""}</section>`;
  }

  function settingsMarkup() {
    const project = state.project;
    const archived = project.archived;
    return `<section class="yp-section"><div class="yp-section-title"><h2>项目设置</h2></div><div class="yp-form"><div class="yp-field"><span>名称</span><strong>${text(project.name)}</strong></div><div class="yp-field"><span>长期目标</span><p>${text(project.goal)}</p></div><div class="yp-heading-actions">${archived ? `<button class="yp-btn" type="button" data-action="restore-project">恢复项目</button>` : `<button class="yp-btn" type="button" data-action="rename-project">重命名</button><button class="yp-btn" type="button" data-action="pin-project">${project.pinned ? "取消置顶" : "置顶"}</button><button class="yp-btn" type="button" data-action="archive-project">归档</button>`}</div><p class="yp-error dw-action-error" role="alert" ${state.error ? "" : "hidden"}>${text(state.error, "")}</p></div></section>`;
  }

  function overviewComposer() {
    const active = activeWorkItem();
    if (!hasInProgress()) {
      return `<section class="yp-section"><div class="yp-section-title"><h2>当前事项</h2></div>${dhComposerMarkup({ formId: "dw-global-form", draftAttr: 'data-global-draft', draftKey: globalDraftKey(), department: "", placeholder: "描述这次要改变什么，或先记下原文" })}</section>`;
    }
    const board = state.runPayload?.board;
    const phase = board?.phase;
    const disabled = board == null || TERMINAL.has(phase) || state.inputSubmitting === state.runId;
    return `<section class="yp-section"><div class="yp-section-title"><h2>当前事项</h2><span class="yp-tag amber">${text(active.title)}</span></div><div class="dw-global-log">${globalLogMarkup()}</div><form class="yp-composer" id="dw-global-form"><textarea data-global-draft rows="3" placeholder="追加需求" ${disabled ? "disabled" : ""}>${escapeHtml(currentDraft(state.globalDrafts, globalDraftKey()))}</textarea><div class="yp-composer-footer"><span class="yp-small">${TERMINAL.has(phase) ? "事项已结束，不会自动新建" : "提交后进入当前事项的产品入口"}</span><div class="yp-dh-actions">${!TERMINAL.has(phase) ? `<button class="yp-btn" type="button" data-action="cancel">${state.cancelling ? "正在取消" : "取消事项"}</button>` : ""}<button class="yp-btn primary" type="submit" ${disabled ? "disabled" : ""}>发送</button></div></div></form></section>`;
  }

  function renderOverview() {
    const scrollY = captureScroll();
    if (!state.projectId || !state.project) {
      main.innerHTML = `<div class="yp-empty"><div class="yp-eyebrow">Yudao</div><h1>还没有选中的项目</h1><p>从左侧建立或选择一个项目。产品入口只通过项目与事项，不再创建裸 run。</p><button class="yp-btn primary" type="button" data-action="new-project">从想法新建</button></div>`;
      renderChrome(); icons(); restoreScroll(scrollY); return;
    }
    const project = state.project;
    const adoption = project.current_adoption;
    const pending = project.overview?.pending || [];
    const summary = `<div class="yp-project-summary"><div><div class="yp-eyebrow">项目概览</div><h1>${text(project.name)}</h1><p>${text(project.goal)}</p></div><div class="yp-summary-side"><div class="yp-summary-item"><span>当前成果</span><strong>${text(adoption?.summary, "尚未采纳")}</strong></div><div class="yp-summary-item"><span>进行中</span><strong>${text(activeWorkItem()?.title, "无")}</strong></div><div class="yp-summary-item"><span>待决</span><strong>${pending.length ? text(pending[0].summary || pending[0].title) : "无"}</strong></div></div></div>`;
    let body = handoffListMarkup() + overviewComposer();
    if (state.overviewPane === "board") body = collaborationMarkup() + overviewComposer();
    if (state.overviewPane === "materials") body = materialsMarkup();
    if (state.overviewPane === "settings") body = settingsMarkup();
    if (project.archived) body = `<div class="yp-notice"><div><strong>归档只读</strong><p>查询仍可用，写命令会返回冲突。</p></div></div>` + body;
    main.innerHTML = `${summary}${projectTabsMarkup()}${body}<p class="dw-action-error" role="alert" ${state.error ? "" : "hidden"}>${text(state.error, "")}</p>`;
    renderChrome(); icons(); restoreScroll(scrollY);
  }




  function closeStream() {
    if (stream) { stream.close(); stream = null; }
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
  }

  function handleProjectEvent(projectId = state.projectId, token = state.routeToken) {
    if (!projectId || token !== state.routeToken || projectId !== state.projectId) return;
    return loadProject(projectId, token, true);
  }

  function openStream(projectId, token) {
    closeStream();
    if (typeof EventSource !== "function" || !projectId) return;
    try {
      stream = new EventSource(projectPath(projectId, "/stream"));
      const refresh = () => {
        if (token !== state.routeToken || projectId !== state.projectId) return;
        handleProjectEvent(projectId, token);
      };
      stream.addEventListener("project", refresh);
      stream.addEventListener("loop", refresh);
      stream.onerror = () => {
        if (token !== state.routeToken || projectId !== state.projectId) return;
        refresh();
      };
    } catch { stream = null; }
    refreshTimer = setInterval(() => {
      if (token === state.routeToken && projectId === state.projectId) handleProjectEvent(projectId, token);
    }, 5000);
  }

  async function loadRunPayload(runId, token, silent = false) {
    if (!runId) { state.runPayload = null; return null; }
    const seq = ++runRequestSeq;
    try {
      const data = await fetchJSON(apiPath(runId));
      if (token !== state.routeToken || seq !== runRequestSeq) return null;
      if (focusedRunId() && runId !== focusedRunId() && runId !== state.runId) return null;
      state.runId = runId;
      state.runPayload = data;
      state.busy = Boolean(data.worker_active);
      state.error = data.execution_error || state.error || "";
      if (!silent) renderCurrent();
      else if (state.view === "overview") renderOverview();
      else if (state.view === "department") await loadDepartment(state.department, token);
      else if (state.view === "observability" && state.observationScreen === "list") await loadObservationData();
      else if (state.view === "observability" && state.observationScreen === "detail" && state.selectedAttemptId) {
        await loadAttemptDetail(state.selectedAttemptId, { push: false });
      }
      return data;
    } catch (error) {
      if (token !== state.routeToken || seq !== runRequestSeq) return null;
      if (!silent) renderError(error);
      return null;
    }
  }

  async function loadDepartment(department, token) {
    const runId = focusedRunId();
    if (!runId) {
      if (state.view === "department") renderDepartment(department);
      return;
    }
    const dataKey = `${runId}/${department}`;
    const seq = (departmentRequestSeq.get(dataKey) || 0) + 1;
    departmentRequestSeq.set(dataKey, seq);
    state.departmentLoading = true;
    try {
      const data = await fetchJSON(apiPath(runId, `/departments/${encodeURIComponent(department)}`));
      if (token !== state.routeToken || seq !== departmentRequestSeq.get(dataKey)) return;
      state.departmentData.set(dataKey, data);
      state.departmentLoading = false;
      const contexts = Array.isArray(data.contexts) ? data.contexts : [];
      const selected = contexts.find(item => item.id === state.selectedContext[dataKey]) || contexts.filter(item => item.purpose === "work").at(-1) || contexts.at(-1) || null;
      state.selectedContext[dataKey] = selected?.id || null;
      if (state.view === "department" && state.department === department) renderDepartment(department);
      if (selected?.id) await loadContextDetail(selected.id, token, runId);
    } catch (error) {
      if (token !== state.routeToken || seq !== departmentRequestSeq.get(dataKey)) return;
      state.departmentLoading = false;
      renderError(error);
    }
  }

  async function loadContextDetail(attemptId, token = state.routeToken, runId = focusedRunId()) {
    if (!runId || !attemptId) return;
    const contextKey = `${runId}/${attemptId}`;
    const seq = (contextRequestSeq.get(contextKey) || 0) + 1;
    contextRequestSeq.set(contextKey, seq);
    try {
      const detail = await fetchJSON(apiPath(runId, `/model-attempts/${encodeURIComponent(attemptId)}`));
      if (token !== state.routeToken || seq !== contextRequestSeq.get(contextKey)) return;
      state.contextDetails.set(contextKey, detail);
      const currentContext = `${focusedRunId()}/${state.department}`;
      if (state.view === "department" && state.selectedContext[currentContext] === attemptId) renderDepartment(state.department);
    } catch (error) {
      if (token !== state.routeToken || seq !== contextRequestSeq.get(contextKey)) return;
      state.contextDetails.set(contextKey, { context: null, error: error.message });
      if (state.view === "department" && state.selectedContext[`${focusedRunId()}/${state.department}`] === attemptId) renderDepartment(state.department);
    }
  }

  async function loadPromptConfig(department, token = state.routeToken) {
    if (!state.projectId || !department) return;
    try {
      const data = await fetchJSON(projectPath(state.projectId, `/prompts/${encodeURIComponent(department)}`));
      if (token !== state.routeToken) return;
      state.promptConfigs[department] = data;
    } catch (error) {
      if (token === state.routeToken) setStatus(error.message, "error");
    }
  }

  function observationParams() {
    const filters = state.observationFilters;
    return {
      department: filters.department,
      status: filters.status,
      q: filters.q,
      work_item: filters.work_item === "all" ? "" : filters.work_item,
      provider: filters.provider,
      requested_model: filters.requested_model,
      actual_model: filters.actual_model,
      limit: 50,
    };
  }

  async function loadObservationData({ append = false } = {}) {
    if (!state.projectId) return;
    const projectId = state.projectId;
    const token = state.routeToken;
    const seq = ++state.observationSeq;
    const params = observationParams();
    if (append) params.cursor = state.observationData?.next_cursor;
    state.observationMoreLoading = append;
    if (!append) state.observationLoading = true;
    try {
      const requests = await fetchJSON(queryPath(projectPath(projectId, "/model-attempts"), params));
      let usage = state.usageData;
      if (!append || !usage || state.observationTab === "usage") {
        usage = await fetchJSON(queryPath(projectPath(projectId, "/model-usage"), {
          department: params.department, status: params.status, q: params.q, work_item: params.work_item,
          provider: params.provider, requested_model: params.requested_model, actual_model: params.actual_model,
        }));
      }
      if (token !== state.routeToken || projectId !== state.projectId || seq !== state.observationSeq) return;
      const prior = append && state.observationData ? state.observationData.items || [] : [];
      const items = [...prior, ...(requests.items || [])];
      state.observationData = {
        ...requests,
        items,
        running_attempts: items.filter(item => item.status === "running").length,
        total_attempts: requests.total_attempts ?? usage?.coverage?.attempts ?? requests.total,
        prepared_attempts: requests.prepared_attempts ?? usage?.prepared_attempts,
      };
      state.usageData = usage;
      state.observationLoading = false;
      state.observationMoreLoading = false;
      if (state.view === "observability" && state.observationScreen === "list") {
        renderObservability();
        if (state.observationTab === "usage") updateObservationContent();
      }
    } catch (error) {
      if (token !== state.routeToken || projectId !== state.projectId || seq !== state.observationSeq) return;
      state.observationLoading = false;
      state.observationMoreLoading = false;
      renderError(error);
    }
  }

  async function loadAttemptDetail(attemptId, { push = true, runId = null } = {}) {
    const item = (state.observationData?.items || []).find(entry => entry.id === attemptId);
    const detailRun = runId || item?.run_id || focusedRunId();
    if (!detailRun || !attemptId) return;
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
      const detail = await fetchJSON(apiPath(detailRun, `/model-attempts/${encodeURIComponent(attemptId)}`));
      if (token !== state.routeToken || attemptId !== state.selectedAttemptId || seq !== state.detailSeq) return;
      if (item?.title) detail.attempt = { ...detail.attempt, title: item.title, run_id: detailRun };
      else if (detail.attempt) detail.attempt.run_id = detailRun;
      state.observationDetail = detail;
      renderObservationDetail();
      if (alreadyShowing) restoreJsonScroll(jsonScroll);
    } catch (error) {
      if (token !== state.routeToken || seq !== state.detailSeq) return;
      if (!alreadyShowing) renderError(error);
    }
  }




  function clearProjectCaches() {
    state.project = null;
    state.runId = null;
    state.runPayload = null;
    state.departmentData = new Map();
    state.contextDetails = new Map();
    state.observationData = null;
    state.usageData = null;
    state.observationDetail = null;
    state.promptConfigs = {};
    state.selectedHandoff = null;
    state.error = "";
  }

  async function loadProject(projectId, token, silent = false) {
    const seq = ++projectRequestSeq;
    try {
      const data = await fetchJSON(projectPath(projectId));
      if (token !== state.routeToken || projectId !== state.projectId || seq !== projectRequestSeq) return null;
      state.project = data;
      const focused = focusedWorkItem() || activeWorkItem();
      state.runId = focused?.run_id || null;
      if (state.workItemId && !workItemById(state.workItemId)) state.workItemId = null;
      if (!silent) renderCurrent();
      if (state.runId) await loadRunPayload(state.runId, token, silent);
      else if (!silent) renderCurrent();
      else if (state.view === "overview") renderOverview();
      else if (state.view === "department") renderDepartment(state.department);
      if (state.view === "department") {
        await loadPromptConfig(state.department, token);
        await loadDepartment(state.department, token);
      }
      if (state.view === "observability" && state.observationScreen === "list") await loadObservationData();
      if (state.view === "observability" && state.observationScreen === "detail" && state.selectedAttemptId) {
        await loadAttemptDetail(state.selectedAttemptId, { push: false });
      }
      return data;
    } catch (error) {
      if (token !== state.routeToken || seq !== projectRequestSeq) return null;
      if (error.status === 404) {
        state.projectId = null;
        clearProjectCaches();
        if (!silent) renderError(error);
        else renderCurrent();
        return null;
      }
      if (!silent) renderError(error);
      return null;
    }
  }

  async function activateProject(projectId, { push = true, preserveRoute = false } = {}) {
    if (!projectId) return;
    const keepView = preserveRoute;
    closeStream();
    if (state.projectId !== projectId) {
      clearProjectCaches();
      if (!keepView && state.view !== "providers") {
        state.view = "overview";
        state.overviewPane = "collaboration";
        state.workItemId = null;
        state.selectedAttemptId = null;
        state.observationScreen = "list";
        state.observationReturn = null;
      }
    }
    state.projectId = projectId;
    const token = ++state.routeToken;
    if (push) updateRoute({ push: true });
    else updateRoute({ push: false });
    if (state.view !== "providers") renderLoading("正在读取项目");
    await loadProject(projectId, token);
    if (token === state.routeToken && state.projectId === projectId) openStream(projectId, token);
  }

  async function loadProjects(preferredId = null, push = false) {
    try {
      const payload = await fetchJSON("/api/projects");
      if (!Array.isArray(payload.projects)) throw new Error("项目列表格式无效");
      state.projects = payload.projects;
      try {
        const health = await fetchJSON("/api/health");
        state.health = health;
      } catch {}
      const selected = preferredId && state.projects.some(item => item.project_id === preferredId)
        ? preferredId
        : state.projectId && state.projects.some(item => item.project_id === state.projectId)
          ? state.projectId
          : state.projects[0]?.project_id || null;
      if (selected) await activateProject(selected, { push, preserveRoute: Boolean(state.projectId) && !push });
      else {
        renderChrome();
        renderCurrent();
      }
    } catch (error) {
      renderError(error);
    }
  }

  async function refreshCurrent() {
    if (state.view === "providers") {
      renderProviders();
      return;
    }
    if (!state.projectId) return loadProjects();
    const token = state.routeToken;
    await loadProject(state.projectId, token, true);
    await loadProjects(state.projectId, false);
  }

  async function handlePopState() {
    const previousProject = state.projectId;
    routeFromLocation();
    if (state.projectId !== previousProject) {
      closeStream();
      clearProjectCaches();
      const token = ++state.routeToken;
      if (!state.projectId) {
        renderChrome();
        renderCurrent();
        return;
      }
      renderLoading("正在读取项目");
      await loadProject(state.projectId, token);
      if (token === state.routeToken && state.projectId) openStream(state.projectId, token);
      return;
    }
    const token = ++state.routeToken;
    if (state.observationScreen !== "detail") state.observationDetail = null;
    renderCurrent();
    if (state.view === "department") {
      loadPromptConfig(state.department, token);
      loadDepartment(state.department, token);
    }
    if (state.view === "observability" && state.observationScreen === "list") loadObservationData();
    if (state.view === "observability" && state.selectedAttemptId) loadAttemptDetail(state.selectedAttemptId, { push: false });
    if (state.projectId) openStream(state.projectId, token);
  }




  function openProjectDialog() {
    const dialog = document.getElementById("yp-project-dialog");
    const form = document.getElementById("yp-project-dialog-form");
    if (!dialog || !form) return;
    form.elements.name.value = state.newProjectDraft.name;
    form.elements.goal.value = state.newProjectDraft.goal;
    const errorNode = document.getElementById("yp-project-error");
    if (errorNode) errorNode.hidden = true;
    dialog.showModal();
    icons();
    document.getElementById("yp-project-name")?.focus();
  }

  async function createProject(event) {
    event.preventDefault();
    if (state.creating) return;
    if (event.submitter && event.submitter.value === "cancel") return document.getElementById("yp-project-dialog")?.close();
    const form = event.currentTarget;
    const name = form.elements.name.value;
    const goal = form.elements.goal.value;
    if (!name.trim() || !goal.trim()) return;
    state.newProjectDraft = { name, goal };
    state.creating = true;
    const submit = document.getElementById("yp-project-submit");
    if (submit) submit.disabled = true;
    const errorNode = document.getElementById("yp-project-error");
    if (errorNode) errorNode.hidden = true;
    try {
      const result = await fetchJSON("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, goal }) });
      document.getElementById("yp-project-dialog")?.close();
      state.newProjectDraft = { name: "", goal: "" };
      if (result.project_id) {
        state.view = "overview";
        state.overviewPane = "collaboration";
        await loadProjects(result.project_id, true);
      }
    } catch (error) {
      if (errorNode) { errorNode.hidden = false; errorNode.textContent = error.message; }
    } finally {
      state.creating = false;
      if (submit) submit.disabled = false;
    }
  }

  async function startWorkItem(text, extras = {}) {
    if (!state.projectId || state.creating || hasInProgress() || !isWritable()) return;
    const value = String(text || "").trim();
    if (!value) return;
    state.creating = true;
    renderCurrent();
    try {
      const body = { text: value };
      if (extras.max_cycles) body.max_cycles = Number(extras.max_cycles);
      if (extras.context_window) body.context_window = Number(extras.context_window);
      if (extras.title) body.title = extras.title;
      const result = await fetchJSON(projectPath(state.projectId, "/work-items"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      state.workItemId = result.work_item_id;
      state.view = "overview";
      state.overviewPane = "collaboration";
      updateRoute({ push: true });
      await loadProjects(state.projectId, false);
    } catch (error) {
      setStatus(error.message, "error");
      renderCurrent();
    } finally {
      state.creating = false;
    }
  }

  async function recordMaterial(text, department = null) {
    if (!state.projectId || hasInProgress() || !isWritable()) return;
    const value = String(text || "").trim();
    if (!value) return;
    try {
      const body = { text: value };
      if (department) body.department = department;
      await fetchJSON(projectPath(state.projectId, "/materials"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (department) {
        const key = deptDraftKey(department);
        if (state.deptDrafts[key] === text) delete state.deptDrafts[key];
      } else if (state.globalDrafts[globalDraftKey()] === text) delete state.globalDrafts[globalDraftKey()];
      await loadProject(state.projectId, state.routeToken);
      setStatus("原文已记录", "success");
    } catch (error) {
      setStatus(error.message, "error");
      renderCurrent();
    }
  }

  async function cancelRun() {
    const runId = focusedRunId();
    if (!runId || state.cancelling || TERMINAL.has(state.runPayload?.board?.phase)) return;
    state.cancelling = true;
    try {
      await fetchJSON(apiPath(runId, "/cancel"), { method: "POST" });
      await refreshCurrent();
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      state.cancelling = false;
    }
  }

  async function addGlobalInput(form) {
    if (!hasInProgress()) {
      const textarea = form.querySelector("[data-global-draft]");
      const action = state._dhAction || "start";
      const value = textarea?.value || "";
      if (action === "record") return recordMaterial(value);
      return startWorkItem(value, state.workDraft);
    }
    const runId = focusedRunId();
    if (!runId || state.inputSubmitting === runId || TERMINAL.has(state.runPayload?.board?.phase)) return;
    const textarea = form.querySelector("[data-global-draft]");
    const value = textarea?.value || "";
    if (!value.trim()) return;
    const token = state.routeToken;
    const key = globalDraftKey();
    state.globalDrafts[key] = value;
    state.inputSubmitting = runId;
    try {
      await fetchJSON(apiPath(runId, "/inputs"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: value }) });
      if (token !== state.routeToken) return;
      if (state.globalDrafts[key] === value) state.globalDrafts[key] = "";
      await refreshCurrent();
    } catch (error) {
      if (token === state.routeToken) setStatus(error.message, "error");
    } finally {
      if (state.inputSubmitting === runId) state.inputSubmitting = null;
    }
  }

  async function addDepartmentGuidance(form) {
    const department = form?.dataset?.departmentForm;
    const textarea = form.querySelector?.("[data-dept-draft]");
    const value = textarea?.value || "";
    if (!department) return;
    if (!hasInProgress()) {
      const action = state._dhAction || "start";
      if (action === "record") return recordMaterial(value, department);
      return startWorkItem(value, state.workDraft);
    }
    const runId = focusedRunId();
    if (!runId) return;
    if (!value.trim()) return;
    const token = state.routeToken;
    const key = deptDraftKey(department);
    state.deptDrafts[key] = value;
    const submitKey = `${runId}/${department}`;
    state.guidanceSubmitting[submitKey] = true;
    renderDepartment(department);
    try {
      await fetchJSON(apiPath(runId, `/departments/${encodeURIComponent(department)}/guidance`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      });
      if (token !== state.routeToken) return;
      if (state.deptDrafts[key] === value) delete state.deptDrafts[key];
      await loadDepartment(department, token);
      await loadRunPayload(runId, token, true);
      setStatus("部门指导已接收", "success");
    } catch (error) {
      if (token === state.routeToken) setStatus(error.message, "error");
    } finally {
      delete state.guidanceSubmitting[submitKey];
      if (token === state.routeToken && state.view === "department") renderDepartment(department);
    }
  }

  function openPromptDialog(department) {
    const key = `${state.projectId}/${department}`;
    const config = state.promptConfigs[department] || {};
    const currentText = config.text || "";
    state.promptDrafts[key] = state.promptDrafts[key] ?? currentText;
    const dialog = document.getElementById("dw-prompt-dialog");
    const textarea = document.getElementById("dw-prompt-text");
    const meta = document.getElementById("dw-prompt-meta");
    const def = document.getElementById("dw-prompt-default");
    if (!dialog || !textarea) return;
    textarea.value = state.promptDrafts[key];
    if (meta) meta.textContent = `项目 ${state.project?.name || ""} · ${departmentName(department)} · 当前配置 ${config.source === "configured" ? `v${config.version}` : "默认 v0"}`;
    if (def) def.textContent = config.default_text || "";
    dialog.dataset.promptKey = key;
    dialog.dataset.promptDepartment = department;
    dialog.dataset.promptBase = String(config.version ?? 0);
    dialog.dataset.promptRouteToken = String(state.routeToken);
    const errorNode = document.getElementById("dw-prompt-error");
    if (errorNode) errorNode.hidden = true;
    dialog.showModal();
    icons();
    textarea.focus();
  }

  async function savePrompt(event) {
    event.preventDefault();
    if (event.submitter?.value === "cancel") return document.getElementById("dw-prompt-dialog")?.close();
    if (state.promptSubmitting) return;
    const dialog = document.getElementById("dw-prompt-dialog");
    const department = dialog?.dataset.promptDepartment;
    const key = dialog?.dataset.promptKey;
    const textValue = document.getElementById("dw-prompt-text")?.value || "";
    if (!key || !department || !state.projectId) return;
    if (!textValue.trim()) {
      const errorNode = document.getElementById("dw-prompt-error");
      if (errorNode) { errorNode.hidden = false; errorNode.textContent = "Prompt 不能为空白"; }
      return;
    }
    const token = Number(dialog.dataset.promptRouteToken);
    if (token !== state.routeToken) return;
    state.promptDrafts[key] = textValue;
    state.promptSubmitting = true;
    const submit = dialog.querySelector("button[value='default']");
    if (submit) submit.disabled = true;
    const errorNode = document.getElementById("dw-prompt-error");
    if (errorNode) errorNode.hidden = true;
    try {
      const result = await fetchJSON(projectPath(state.projectId, `/prompts/${encodeURIComponent(department)}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textValue, base_version: Number(dialog.dataset.promptBase || 0) }),
      });
      if (token !== state.routeToken) return;
      state.promptConfigs[department] = result;
      delete state.promptDrafts[key];
      dialog.close();
      await loadDepartment(department, token);
      renderCurrent();
    } catch (error) {
      if (error.status === 409 && error.payload?.current) {
        state.promptConfigs[department] = error.payload.current;
        dialog.dataset.promptBase = String(error.payload.current.version ?? 0);
        const meta = document.getElementById("dw-prompt-meta");
        if (meta) meta.textContent = `项目 ${state.project?.name || ""} · ${departmentName(department)} · 当前配置 v${error.payload.current.version}（已更新，草稿仍保留）`;
      }
      if (token === state.routeToken && errorNode) { errorNode.hidden = false; errorNode.textContent = error.message; }
    } finally {
      state.promptSubmitting = false;
      if (submit) submit.disabled = false;
    }
  }

  async function projectCommand(action, body) {
    if (!state.projectId) return;
    try {
      await fetchJSON(projectPath(state.projectId, `/${action}`), {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      state.projectMenu = false;
      await loadProjects(state.projectId, false);
    } catch (error) {
      setStatus(error.message, "error");
      renderCurrent();
    }
  }




  function goDepartment(department, { push = true } = {}) {
    state.view = "department";
    state.department = department;
    state.deptMenu = false;
    state.roomInspect = false;
    state.observationDetail = null;
    state.selectedAttemptId = null;
    const token = ++state.routeToken;
    if (push) updateRoute({ push: true });
    else updateRoute({ push: false });
    renderCurrent();
    loadPromptConfig(department, token);
    loadDepartment(department, token);
    if (state.projectId) openStream(state.projectId, token);
  }

  function goView(view, { push = true } = {}) {
    if (view === "providers") {
      state.view = "providers";
      ++state.routeToken;
      if (push) updateRoute({ push: true });
      renderCurrent();
      return;
    }
    state.view = view === "observability" ? "observability" : "overview";
    if (view !== "observability") {
      state.observationScreen = "list";
      state.observationDetail = null;
      state.selectedAttemptId = null;
    }
    const token = ++state.routeToken;
    if (push) updateRoute({ push: true });
    renderCurrent();
    if (state.projectId) openStream(state.projectId, token);
    if (state.view === "observability" && state.projectId) loadObservationData();
    if (state.view === "overview" && state.projectId) loadProject(state.projectId, token, true);
  }


  function clickHandler(event) {
    const target = event.target.closest?.("button, [data-dh-action]");
    if (!target) return;
    const scope = workbench || root;
    if (scope && !scope.contains(target) && !target.closest("dialog")) return;
    if (target.dataset.action === "toggle-dept-menu") { state.deptMenu = !state.deptMenu; renderDepartment(state.department); return; }
    if (target.dataset.action === "toggle-sidebar") { state.sidebarCollapsed = !state.sidebarCollapsed; renderChrome(); icons(); return; }
    if (target.dataset.action === "toggle-mobile-nav") { state.mobileNav = !state.mobileNav; renderChrome(); icons(); return; }
    if (target.dataset.action === "toggle-project-menu") { state.projectMenu = !state.projectMenu; renderChrome(); icons(); return; }
    if (target.dataset.action === "new-project") return openProjectDialog();
    if (target.dataset.action === "home") { state.view = "overview"; state.overviewPane = "collaboration"; updateRoute({ push: true }); renderCurrent(); return; }
    if (target.dataset.action === "providers") {
      state.view = "providers";
      updateRoute({ push: true });
      renderCurrent();
      return;
    }
    if (target.dataset.action === "refresh") return refreshCurrent();
    if (target.dataset.action === "cancel") return cancelRun();
    if (target.dataset.action === "pin-project") return projectCommand("pin", { pinned: !state.project?.pinned });
    if (target.dataset.action === "archive-project") return projectCommand("archive");
    if (target.dataset.action === "restore-project") return projectCommand("restore");
    if (target.dataset.action === "rename-project") {
      const dialog = document.getElementById("yp-rename-dialog");
      const input = document.getElementById("yp-rename-name");
      if (dialog && input) { input.value = state.project?.name || ""; dialog.showModal(); input.focus(); }
      return;
    }
    if (target.dataset.projectId) {
      state.mobileNav = false;
      return activateProject(target.dataset.projectId, { push: true });
    }
    if (target.dataset.overviewPane) {
      state.view = "overview";
      state.overviewPane = target.dataset.overviewPane;
      updateRoute({ push: true });
      renderOverview();
      return;
    }
    if (target.dataset.boardMode) {
      state.boardMode = target.dataset.boardMode;
      updateRoute({ push: false });
      renderOverview();
      return;
    }
    if (target.dataset.workItem) {
      state.workItemId = target.dataset.workItem;
      const dept = target.dataset.workDepartment;
      if (dept && DEPARTMENTS[dept]) return goDepartment(dept);
      state.view = "overview";
      updateRoute({ push: true });
      const token = ++state.routeToken;
      loadProject(state.projectId, token);
      return;
    }
    if (target.dataset.department && target.dataset.obsReturn === undefined && !target.dataset.obsAttempt) {
      return goDepartment(target.dataset.department);
    }
    if (target.dataset.view) return goView(target.dataset.view);
    if (target.dataset.handoff) {
      state.selectedHandoff = target.dataset.handoff;
      updateRoute({ push: false });
      renderOverview();
      return;
    }
    if (target.dataset.eventId) return openEvent(target.dataset.eventId, target.dataset.document);
    if (target.dataset.obsReturn !== undefined) {
      const snapshot = state.observationReturn;
      applyReturn(snapshot);
      state.observationReturn = null;
      const token = ++state.routeToken;
      updateRoute({ push: true });
      renderCurrent();
      if (state.view === "department") {
        loadPromptConfig(state.department, token);
        loadDepartment(state.department, token);
      }
      restoreScroll(snapshot?.scroll || 0);
      return;
    }
    if (target.dataset.obsBack !== undefined) {
      state.observationScreen = "list";
      state.observationDetail = null;
      state.selectedAttemptId = null;
      updateRoute({ push: true });
      renderObservability();
      if (state.projectId) openStream(state.projectId, state.routeToken);
      loadObservationData();
      return;
    }
    if (target.dataset.obsRequest) return loadAttemptDetail(target.dataset.obsRequest);
    if (target.dataset.obsAttempt) return loadAttemptDetail(target.dataset.obsAttempt, { runId: target.dataset.obsRun || null });
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
      state.observationReturn = snapshotReturn();
      if (currentDepartmentData()?.department) state.observationFilters.department = currentDepartmentData().department;
      if (state.workItemId) state.observationFilters.work_item = state.workItemId;
      return loadAttemptDetail(target.dataset.observeAttempt);
    }
    if (target.dataset.inspectorTab) {
      state.inspectorTab = target.dataset.inspectorTab;
      state.roomInspect = true;
      state.deptMenu = false;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.contextId) {
      state.selectedContext[`${focusedRunId()}/${state.department}`] = target.dataset.contextId;
      updateRoute({ push: false });
      renderDepartment(state.department);
      loadContextDetail(target.dataset.contextId, state.routeToken);
      return;
    }
    if (target.dataset.contextPartSource) {
      const selectedAttempt = state.selectedContext[`${focusedRunId()}/${state.department}`];
      state.selectedContextPart[`${focusedRunId()}/${selectedAttempt}`] = target.dataset.contextPartSource;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.inspectorToggle !== undefined) {
      state.inspectorCollapsed = state.inspectorCollapsed === false;
      updateRoute({ push: false });
      renderDepartment(state.department);
      return;
    }
    if (target.dataset.promptEdit) {
      state.deptMenu = false;
      const department = target.dataset.promptEdit.includes("/") ? target.dataset.promptEdit.split("/").pop() : target.dataset.promptEdit;
      loadPromptConfig(department).then(() => openPromptDialog(department));
      return;
    }
    if (target.dataset.dhAction) {
      state._dhAction = target.dataset.dhAction;
    }
  }

  function inputHandler(event) {
    const target = event.target;
    if (target.matches?.("[data-project-search]")) {
      state.projectSearch = target.value;
      renderChrome();
      return;
    }
    if (target.matches?.("[data-global-draft]")) state.globalDrafts[globalDraftKey()] = target.value;
    if (target.matches?.("[data-dept-draft]")) state.deptDrafts[deptDraftKey(target.dataset.deptDraft)] = target.value;
    if (target.matches?.("[data-obs-search]")) {
      state.observationFilters.q = target.value;
      updateRoute({ push: false });
      clearTimeout(filterTimer);
      filterTimer = setTimeout(() => loadObservationData(), 180);
    }
  }

  function changeHandler(event) {
    const target = event.target;
    if (target.matches?.("[data-work-scope]")) {
      state.workItemId = target.value || null;
      const item = focusedWorkItem();
      state.runId = item?.run_id || activeWorkItem()?.run_id || null;
      const token = ++state.routeToken;
      updateRoute({ push: true });
      renderCurrent();
      if (state.view === "department") {
        loadPromptConfig(state.department, token);
        loadDepartment(state.department, token);
      }
      if (state.runId) loadRunPayload(state.runId, token, true);
      return;
    }
    if (target.matches?.("[data-obs-department]")) state.observationFilters.department = target.value;
    if (target.matches?.("[data-obs-status]")) state.observationFilters.status = target.value;
    if (target.matches?.("[data-obs-work-item]")) state.observationFilters.work_item = target.value;
    if (target.matches?.("[data-obs-provider]")) state.observationFilters.provider = target.value;
    if (target.matches?.("[data-obs-requested-model]")) state.observationFilters.requested_model = target.value;
    if (target.matches?.("[data-obs-actual-model]")) state.observationFilters.actual_model = target.value;
    if (target.matches?.("[data-obs-department], [data-obs-status], [data-obs-work-item], [data-obs-provider], [data-obs-requested-model], [data-obs-actual-model]")) {
      state.observationData = null;
      state.usageData = null;
      updateRoute({ push: false });
      loadObservationData();
    }
  }

  function submitHandler(event) {
    const form = event.target;
    if (form.id === "dw-global-form") {
      event.preventDefault();
      const submitter = event.submitter;
      if (submitter?.dataset?.dhAction) state._dhAction = submitter.dataset.dhAction;
      addGlobalInput(form);
      state._dhAction = null;
    }
    if (form.id === "dw-dept-form") {
      event.preventDefault();
      const submitter = event.submitter;
      if (submitter?.dataset?.dhAction) state._dhAction = submitter.dataset.dhAction;
      addDepartmentGuidance(form);
      state._dhAction = null;
    }
  }

  function bootDialogs() {
    const projectForm = document.getElementById("yp-project-dialog-form");
    projectForm?.addEventListener("input", () => {
      state.newProjectDraft = { name: projectForm.elements.name.value, goal: projectForm.elements.goal.value };
    });
    projectForm?.addEventListener("submit", createProject);
    document.getElementById("dw-prompt-dialog-form")?.addEventListener("submit", savePrompt);
    document.getElementById("dw-prompt-restore")?.addEventListener("click", () => {
      const department = document.getElementById("dw-prompt-dialog")?.dataset.promptDepartment;
      const config = state.promptConfigs[department] || {};
      const textarea = document.getElementById("dw-prompt-text");
      if (textarea) textarea.value = config.default_text || "";
    });
    document.getElementById("yp-rename-dialog-form")?.addEventListener("submit", async event => {
      event.preventDefault();
      if (event.submitter?.value === "cancel") return document.getElementById("yp-rename-dialog")?.close();
      const name = document.getElementById("yp-rename-name")?.value || "";
      const errorNode = document.getElementById("yp-rename-error");
      try {
        await projectCommand("rename", { name });
        document.getElementById("yp-rename-dialog")?.close();
      } catch (error) {
        if (errorNode) { errorNode.hidden = false; errorNode.textContent = error.message; }
      }
    });
  }

  function boot() {
    routeFromLocation();
    const scope = workbench || root;
    scope?.addEventListener("click", clickHandler);
    scope?.addEventListener("input", inputHandler);
    scope?.addEventListener("change", changeHandler);
    scope?.addEventListener("submit", submitHandler);
    globalThis.addEventListener?.("popstate", () => { handlePopState(); });
    bootDialogs();
    loadProjects(state.projectId, false);
  }

  async function openEvent(eventId, documentKind = "") {
    const runId = focusedRunId() || state.runId;
    if (!runId || !eventId) return;
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
      if (token !== state.routeToken || seq !== state.eventSeq) return;
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
      if (sourcesNode && Array.isArray(data.source_events) && data.source_events.length) {
        const seqs = data.source_events.map(item => item.seq).filter(value => typeof value === "number");
        const through = data.payload?.checkpoint?.covered_through_event_id;
        const range = document.createElement("p");
        range.className = "dw-coverage-range";
        range.textContent = seqs.length
          ? `覆盖范围 seq ${Math.min(...seqs)}–${Math.max(...seqs)}${through ? ` · covered_through ${through}` : ""}`
          : (through ? `covered_through ${through}` : "原始事件");
        sourcesNode.appendChild(range);
        data.source_events.forEach(source => {
          const row = document.createElement("button");
          row.type = "button";
          row.className = "dw-observation-link";
          row.dataset.eventId = source.event_id;
          row.textContent = `seq ${source.seq ?? "?"} · ${source.type || "event"} · ${source.event_id}`;
          sourcesNode.appendChild(row);
        });
      }
      if (titleNode && data.compaction_summary) titleNode.textContent = "摘要来源事件";
      if (dialog) dialog.showModal();
    } catch (error) {
      if (token !== state.routeToken || seq !== state.eventSeq) return;
      setStatus(error.message, "error");
      dialog?.close();
    }
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
    loadProjects,
    activateProject,
    loadProject,
    loadRunPayload,
    loadDepartment,
    loadContextDetail,
    loadObservationData,
    loadAttemptDetail,
    openEvent,
    usageMarkup,
    contextMarkup,
    promptMarkup,
    createProject,
    startWorkItem,
    recordMaterial,
    cancelRun,
    addGlobalInput,
    addDepartmentGuidance,
    openProjectDialog,
    openPromptDialog,
    savePrompt,
    refreshCurrent,
    updateRoute,
    handlePopState,
    handleProjectEvent,
    openStream,
    changeHandler,
    deptDraftKey,
    globalDraftKey,
    snapshotReturn,
    applyReturn,
  };
  globalThis.harnessWeb = api;
  if ((!root && !workbench) || !main || globalThis.__HARNESS_SKIP_BOOT__) return;
  boot();
})();
