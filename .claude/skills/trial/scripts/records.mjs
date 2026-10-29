// 试用记录的公共函数：读 run 导出、配置快照、实例 manifest 比较、裁决统计。
// 只用 Node 内置模块。readout.mjs 与 report.mjs 都从这里取读数，两处数字同源。

import { readFileSync } from "node:fs";

// ---------- 显示 ----------
const CJK = /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/;
export const vis = (s) => [...String(s ?? "")].reduce((n, ch) => n + (CJK.test(ch) ? 2 : 1), 0);
export const pad = (s, n) => String(s ?? "") + " ".repeat(Math.max(0, n - vis(s)));
export const num = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US"));
export const pct = (a, b) => (a === null || a === undefined || !b ? "—" : ((a / b) * 100).toFixed(1) + "%");
export function dur(ms) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 3 : 1)} 秒`;
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h ? `${h} 小时 ${m} 分 ${r} 秒` : `${m} 分 ${r} 秒`;
}

// ---------- 时间 ----------
// 只接受带时区偏移的 ISO 时间。没有偏移的字符串按本机时区解析会悄悄错位，直接当作未知。
const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/;
export const parseTime = (s) => {
  if (typeof s !== "string" || !HAS_OFFSET.test(s)) return null;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
};

// ---------- 读导出 ----------
// 导出是一个 JSON 文件：{run_id, projection, events[], attempts[], usage{}}，外面可能再包一层 {data}。
export function loadExport(path) {
  const doc = JSON.parse(readFileSync(path, "utf8"));
  const data = doc.data ?? doc;
  if (!data || typeof data !== "object" || !Array.isArray(data.events)) {
    throw new Error(`${path}: 不是 run 导出（缺 events 数组）`);
  }
  return data;
}

export const eventIndex = (data) => new Map(data.events.map((e) => [e.event_id, e]));
export const attemptIndex = (data) => new Map((data.attempts ?? []).map((a) => [a.id, a]));

const sumKnown = (arr, pick) => {
  let n = 0;
  let any = false;
  for (const x of arr) {
    const v = pick(x);
    if (typeof v === "number") { n += v; any = true; }
  }
  return any ? n : null; // 一条都没报告时是未知，不是 0
};

// 关键事件：分类 → 事件类型。run_failed、run_resumed、user_input_received、decision_* 都在其中。
const KEY_EVENTS = new Set([
  "run_created", "input_received", "user_input_received", "run_resumed", "product_input_assigned",
  "spec_accepted", "spec_rejected", "spec_superseded", "contract_accepted", "contract_rejected",
  "department_activated", "department_input", "proposal_submitted", "proposal_rejected",
  "activation_finished", "delivery_submitted", "delivery_accepted", "delivery_rejected",
  "qa_submitted", "review_submitted", "compaction_recorded",
  "decision_requested", "decision_answered", "product_decision_accepted",
  "department_guidance_received", "department_guidance_applied", "department_guidance_responded",
  "action_verified", "ask_started", "ask_answered", "tool_call_required",
  "human_action_requested", "human_action_resolved",
  "run_stopped", "run_failed", "run_done", "error",
]);
const TERMINAL = new Set(["run_failed", "run_stopped", "run_done"]);

const evRef = (e) => (e ? { id: e.event_id, position: e.position ?? null, at: e.created_at ?? null, ms: parseTime(e.created_at), type: e.type } : null);

// 一次读数。所有时间保留原始 ISO 字符串并另给毫秒数；比较和相减只用毫秒。
export function summarize(data, label = "") {
  const attempts = Array.isArray(data.attempts) ? data.attempts : [];
  const events = data.events;
  const proj = data.projection ?? {};
  const usage = data.usage ?? {};
  const totals = usage.totals ?? {};

  const first = evRef(events[0]);
  const last = evRef(events.at(-1));
  const wallMs = first?.ms != null && last?.ms != null ? last.ms - first.ms : null;

  // 步骤时间：尝试的起止
  const starts = attempts.map((a) => parseTime(a.started_at ?? a.created_at)).filter((x) => x !== null);
  const ends = attempts.map((a) => parseTime(a.finished_at)).filter((x) => x !== null);
  const attemptSpanMs = starts.length && ends.length ? Math.max(...ends) - Math.min(...starts) : null;
  const attemptBusyMs = sumKnown(attempts, (a) => a.duration_ms);

  const status = (a) => a.status ?? "?";
  const count = (arr, s) => arr.filter((a) => status(a) === s).length;

  // 部门 × 目的
  const byDeptPurpose = {};
  for (const a of attempts) {
    const k = `${a.department ?? "?"}/${a.purpose ?? "?"}`;
    (byDeptPurpose[k] ??= []).push(a);
  }
  const deptPurpose = Object.entries(byDeptPurpose).map(([key, list]) => ({
    key,
    attempts: list.length,
    success: count(list, "success"),
    failed: count(list, "failed"),
    cancelled: count(list, "cancelled"),
    running: count(list, "running"),
    other: list.filter((a) => !["success", "failed", "cancelled", "running"].includes(status(a))).length,
    input: sumKnown(list, (a) => a.usage?.input_tokens),
    output: sumKnown(list, (a) => a.usage?.output_tokens),
    unreported: list.filter((a) => typeof a.usage?.input_tokens !== "number").length,
  }));

  // 配置：部门 × 目的 × 实际用的 call_target。没有 call_target 的字段是 null。
  const cfgMap = new Map();
  for (const a of attempts) {
    const c = a.call_target ?? {};
    const row = {
      department: a.department ?? null,
      purpose: a.purpose ?? null,
      model_id: c.model_id ?? null, // 本地别名
      requested_model: c.requested_model ?? a.requested_model ?? null, // 发给上游的名字
      protocol: c.protocol ?? null,
      context_window: c.context_window ?? null,
      max_output_tokens: c.configured_max_output_tokens ?? null,
      requested_tier: c.requested_tier ?? null,
      reasoning_mode: c.reasoning_mode ?? null,
      default_reasoning_level: c.default_reasoning_level ?? null,
      input_modalities: Array.isArray(c.input_modalities) ? [...c.input_modalities].sort() : null,
    };
    const k = JSON.stringify(row);
    const cur = cfgMap.get(k) ?? { ...row, actual_models: new Set(), attempts: 0 };
    cur.attempts++;
    const actual = a.actual_model ?? a.model;
    if (actual) cur.actual_models.add(actual);
    cfgMap.set(k, cur);
  }
  const configs = [...cfgMap.values()].map((r) => ({ ...r, actual_models: [...r.actual_models].sort() }));

  // 输入最大值：绝对值与该次尝试自己窗口下的比值是两件事，分别取
  let maxIn = null;
  let maxRatio = null;
  let overWindow = 0;
  for (const a of attempts) {
    const t = a.usage?.input_tokens;
    if (typeof t !== "number") continue;
    const w = a.call_target?.context_window ?? null;
    const row = { tokens: t, window: w, ratio: w ? t / w : null, attemptId: a.id, department: a.department ?? null, purpose: a.purpose ?? null, status: a.status ?? null };
    if (!maxIn || t > maxIn.tokens) maxIn = row;
    if (row.ratio !== null && (!maxRatio || row.ratio > maxRatio.ratio)) maxRatio = row;
    if (row.ratio !== null && row.ratio > 1) overWindow++;
  }

  // 压缩：尝试总数、响应成功、检查点是三个读数
  const comp = attempts.filter((a) => a.purpose === "compaction");
  const logical = new Map();
  for (const a of comp) {
    const k = a.logical_call_id ?? a.id;
    logical.set(k, (logical.get(k) ?? false) || a.status === "success");
  }
  const projCompactions = Array.isArray(proj.compactions) ? proj.compactions : [];
  const types = {};
  for (const e of events) types[e.type ?? "?"] = (types[e.type ?? "?"] ?? 0) + 1;
  const compaction = {
    attempts: comp.length,
    responseSuccess: count(comp, "success"),
    responseFailed: count(comp, "failed"),
    responseOther: comp.length - count(comp, "success") - count(comp, "failed"),
    logicalCalls: logical.size,
    logicalCallsSucceeded: [...logical.values()].filter(Boolean).length,
    checkpointEvents: types.compaction_recorded ?? 0,
    projectionRecords: projCompactions.length,
    coveredThrough: projCompactions.map((c) => c.checkpoint?.covered_through_event_id ?? null),
  };

  const failures = attempts
    .filter((a) => a.status && a.status !== "success")
    .map((a) => ({
      id: a.id,
      at: a.started_at ?? a.created_at ?? null,
      department: a.department ?? null,
      purpose: a.purpose ?? null,
      step: a.step ?? null,
      status: a.status,
      error: a.error ?? null,
      errorType: a.diagnostics?.error_type ?? a.error_class ?? null,
      input: a.usage?.input_tokens ?? null,
      durationMs: a.duration_ms ?? null,
      contextEventId: a.context_event_id ?? null,
    }));

  const keyEvents = [];
  for (const e of events) {
    if (!KEY_EVENTS.has(e.type)) continue;
    const prev = keyEvents.at(-1);
    if (prev && prev.type === e.type) { prev.n++; prev.lastId = e.event_id; continue; }
    keyEvents.push({ ...evRef(e), stop: e.stop_reason ?? "", n: 1, lastId: e.event_id });
  }
  const terminal = [...events].reverse().find((e) => TERMINAL.has(e.type));

  // 数字矛盾：同一个量在两个来源里不一致
  const inconsistencies = [];
  const att = (k) => sumKnown(attempts, (a) => a.usage?.[k]);
  if (typeof totals.attempts === "number" && totals.attempts !== attempts.length) {
    inconsistencies.push({ code: "usage_attempt_count", detail: `usage.totals.attempts=${totals.attempts}，attempts 数组 ${attempts.length} 条` });
  }
  for (const k of ["input_tokens", "output_tokens", "cache_read_tokens", "total_tokens"]) {
    const sum = att(k);
    if (typeof totals[k] === "number" && sum !== null && totals[k] !== sum) {
      inconsistencies.push({ code: `usage_${k}`, detail: `usage.totals.${k}=${totals[k]}，逐次尝试相加 ${sum}` });
    }
  }
  const deptList = usage.departments ?? [];
  if (typeof totals.attempts === "number" && deptList.length) {
    const s = sumKnown(deptList, (d) => d.attempts);
    if (s !== null && s !== totals.attempts) inconsistencies.push({ code: "usage_department_attempts", detail: `部门尝试数相加 ${s}，合计 ${totals.attempts}` });
  }
  if (first?.ms == null || last?.ms == null) {
    inconsistencies.push({ code: "event_time_unparsable", detail: "首尾事件时间缺失或缺时区偏移，墙钟未知" });
  }

  return {
    file: label,
    runId: data.run_id ?? proj.run_id ?? null,
    status: proj.status ?? null,
    stopReason: proj.stop_reason ?? null,
    cycles: proj.cycle_count ?? null,
    workItem: proj.work_item_id ?? null,
    models: (usage.models ?? []).map((m) => m.key ?? m.label ?? null),
    events: { count: events.length, first, last, wallMs },
    attempts: {
      count: attempts.length,
      byStatus: Object.fromEntries([...new Set(attempts.map(status))].map((s) => [s, count(attempts, s)])),
      spanMs: attemptSpanMs,
      busyMs: attemptBusyMs,
    },
    totals, // 原样：cost 为 null 就是未报告
    attemptSums: { input_tokens: att("input_tokens"), output_tokens: att("output_tokens"), cache_read_tokens: att("cache_read_tokens"), total_tokens: att("total_tokens"), cost: att("cost") },
    departments: deptList.map((d) => ({
      key: d.key ?? d.label ?? null,
      attempts: d.attempts ?? null,
      input: d.input_tokens ?? null,
      output: d.output_tokens ?? null,
      cache: d.cache_read_tokens ?? null,
      total: d.total_tokens ?? null,
      latencyMs: d.latency_ms ?? null,
      cost: d.cost ?? null,
    })),
    deptPurpose,
    configs,
    maxIn,
    maxRatio,
    overWindow,
    compaction,
    failures,
    keyEvents,
    terminal: evRef(terminal) && { ...evRef(terminal), stopReason: terminal.stop_reason ?? null },
    deliveryAccepted: events.filter((e) => e.type === "delivery_accepted").map(evRef),
    inconsistencies,
    types,
    credentialRefs: [...new Set(configs.length ? attempts.map((a) => a.call_target?.credential_ref).filter(Boolean) : [])],
  };
}

export const readExport = (path) => summarize(loadExport(path), path);

// ---------- 配置比较 ----------
// 阻断项决定复现条件是否相同；别名和档位只提示。model_id 是本地别名，requested_model 是上游名字，不混用。
const REQUIRED_FIELDS = ["requested_model", "protocol", "context_window", "max_output_tokens"];
const BLOCK_FIELDS = [...REQUIRED_FIELDS, "requested_tier", "reasoning_mode", "default_reasoning_level", "input_modalities"];
const INFO_FIELDS = ["model_id"];

const groupConfigs = (rows) => {
  const m = new Map();
  for (const r of rows) {
    const k = `${r.department}/${r.purpose}`;
    (m.get(k) ?? m.set(k, []).get(k)).push(r);
  }
  return m;
};
const valuesOf = (rows, f) => [...new Set(rows.map((r) => JSON.stringify(r[f] ?? null)))].sort();

export function compareConfigs(rowsA, rowsB) {
  const ga = groupConfigs(rowsA);
  const gb = groupConfigs(rowsB);
  const shared = [...ga.keys()].filter((k) => gb.has(k));
  const diffs = [];
  const unknown = [];
  for (const k of shared) {
    for (const f of [...BLOCK_FIELDS, ...INFO_FIELDS]) {
      const va = valuesOf(ga.get(k), f);
      const vb = valuesOf(gb.get(k), f);
      const level = BLOCK_FIELDS.includes(f) ? "blocking" : "info";
      if ((va.includes("null") || vb.includes("null")) && REQUIRED_FIELDS.includes(f)) unknown.push({ key: k, field: f });
      else if (va.join("|") !== vb.join("|")) diffs.push({ key: k, field: f, a: va.map((x) => JSON.parse(x)), b: vb.map((x) => JSON.parse(x)), level });
    }
  }
  return {
    shared,
    onlyA: [...ga.keys()].filter((k) => !gb.has(k)),
    onlyB: [...gb.keys()].filter((k) => !ga.has(k)),
    diffs,
    unknown,
    comparable: shared.length > 0 && unknown.length === 0 && !diffs.some((d) => d.level === "blocking"),
  };
}

// ---------- 实例 manifest ----------
const SHA256 = /^[0-9a-f]{64}$/;
const COMMIT = /^[0-9a-f]{7,40}$/;
const isInt = (v) => Number.isInteger(v);

export function checkManifest(m) {
  const errs = [];
  const need = (cond, msg) => { if (!cond) errs.push(msg); };
  need(m && typeof m === "object", "manifest 不是对象");
  if (!m || typeof m !== "object") return errs;
  need(m.schema_version === 1, "schema_version 必须是 1");
  need(typeof m.commit === "string" && COMMIT.test(m.commit), "commit 缺失或不是 7 到 40 位十六进制");
  need(m.wheel === null || (m.wheel && typeof m.wheel === "object"), "wheel 必须是 {path,sha256}，没有 wheel 时为 null");
  if (m.wheel?.sha256 != null) need(SHA256.test(m.wheel.sha256), "wheel.sha256 不是 64 位十六进制");
  if (m.wheel) need(typeof m.wheel.path === "string" && m.wheel.path.length > 0, "wheel.path 缺失");
  for (const k of ["python", "package_path", "working_directory", "data_dir", "status", "task_set", "material_version"]) need(typeof m[k] === "string" && m[k], `${k} 缺失`);
  need(typeof m.skill_commit === "string" && m.skill_commit, "skill_commit 缺失");
  need(isInt(m.port), "port 必须是整数");
  need(isInt(m.pid), "pid 必须是整数");
  for (const k of ["process_started_at", "identity_checked_at"]) need(parseTime(m[k]) !== null, `${k} 缺失或缺时区偏移`);
  need(typeof m.package_path === "string" && m.package_path.replaceAll("\\", "/").includes("/site-packages/"), "package_path 未指向独立安装的 site-packages");
  need(Array.isArray(m.models), "models 必须是数组，未配置时用空数组并注明缺项");
  for (const [i, x] of (m.models ?? []).entries()) {
    need(x && typeof x.department === "string" && typeof x.model === "string" && typeof x.protocol === "string", `models[${i}] 缺 department/model/protocol`);
    need(isInt(x?.context_window) && isInt(x?.max_output_tokens), `models[${i}] 的 context_window/max_output_tokens 必须是整数`);
  }
  need(new Set((m.models ?? []).map((x) => x?.department)).size === m.models?.length, "models 中的部门重复");
  return errs;
}

export const hasWheelIdentity = (m) => typeof m?.wheel?.sha256 === "string" && SHA256.test(m.wheel.sha256);
const sameCommit = (a, b) => typeof a === "string" && typeof b === "string" && (a.startsWith(b) || b.startsWith(a));

// 两个实例是否同一构建。身份缺失（例如 editable 安装没有 wheel SHA）是未知，不算相同。
export function compareManifests(a, b) {
  const unknown = [];
  const diffs = [];
  if (!hasWheelIdentity(a) || !hasWheelIdentity(b)) unknown.push("wheel.sha256");
  else if (a.wheel.sha256 !== b.wheel.sha256) diffs.push({ field: "wheel.sha256", a: a.wheel.sha256, b: b.wheel.sha256 });
  if (!sameCommit(a?.commit, b?.commit)) diffs.push({ field: "commit", a: a?.commit ?? null, b: b?.commit ?? null });
  for (const field of ["task_set", "material_version"]) {
    if (!a?.[field] || !b?.[field]) unknown.push(field);
    else if (a[field] !== b[field]) diffs.push({ field, a: a[field], b: b[field] });
  }
  const departmentPlan = (m) => [...(m?.models ?? [])]
    .map(({ department, model, protocol, context_window, max_output_tokens, requested_tier, reasoning_mode, default_reasoning_level, input_modalities }) => ({ department, model, protocol, context_window, max_output_tokens, requested_tier: requested_tier ?? null, reasoning_mode: reasoning_mode ?? null, default_reasoning_level: default_reasoning_level ?? null, input_modalities: input_modalities ?? null }))
    .sort((x, y) => x.department.localeCompare(y.department));
  if (!a?.models?.length || !b?.models?.length) unknown.push("models");
  else if (JSON.stringify(departmentPlan(a)) !== JSON.stringify(departmentPlan(b))) diffs.push({ field: "models", a: departmentPlan(a), b: departmentPlan(b) });
  return { sameBuild: unknown.length === 0 && diffs.length === 0, unknown, diffs };
}

// manifest 声明的部门模型与导出里实际的 call_target 是否一致。model 可以写本地别名，也可以写上游名字。
export function manifestVsExport(m, rows) {
  const diffs = [];
  for (const r of rows) {
      const x = (m.models ?? []).find((candidate) => candidate.department === r.department);
      if (!x) { diffs.push({ department: r.department, field: "department", manifest: null, export: r.requested_model }); continue; }
      if (x.model !== r.model_id && x.model !== r.requested_model) diffs.push({ department: x.department, purpose: r.purpose, field: "model", manifest: x.model, export: { model_id: r.model_id, requested_model: r.requested_model } });
      if (x.protocol !== r.protocol) diffs.push({ department: x.department, purpose: r.purpose, field: "protocol", manifest: x.protocol, export: r.protocol });
      if (x.context_window !== r.context_window) diffs.push({ department: x.department, purpose: r.purpose, field: "context_window", manifest: x.context_window, export: r.context_window });
      if (x.max_output_tokens !== r.max_output_tokens) diffs.push({ department: x.department, purpose: r.purpose, field: "max_output_tokens", manifest: x.max_output_tokens, export: r.max_output_tokens });
  }
  return diffs;
}

// ---------- 裁决统计 ----------
// 没有写明裁决的问题一律待定；工单关闭不产生裁决。
export const judgmentOf = (f) => f?.judgment?.status ?? "pending";

export function tally(items) {
  const blank = () => ({ confirmed: 0, rejected: 0, pending: 0 });
  const out = { defect: blank(), experience: blank() };
  for (const f of items) (out[f.kind] ?? out.defect)[judgmentOf(f)]++;
  const d = out.defect.confirmed + out.defect.rejected;
  out.defectHitRate = d ? out.defect.confirmed / d : null;
  out.defectDenominator = d;
  // 体验候选：confirmed 记为采纳
  const e = out.experience.confirmed + out.experience.rejected;
  out.experienceAcceptRate = e ? out.experience.confirmed / e : null;
  out.experienceDenominator = e;
  return out;
}
