#!/usr/bin/env node
// 核对一轮试用的 result.json，并从同一份记录生成事实表格。格式见 method/records.md。
// 用法：
//   node report.mjs --check <result.json> [--json] [--secret-env 名字,名字] [--render <输出.md>]
//   node report.mjs --init <result.json> --task-set <版本> --material <版本> --commit <提交> [ID=]<导出> [更多导出…]
// 退出码：0 合法（完整或部分完成）；1 真实性、证据或脱敏检查失败；2 命令用法或文件读取错误。
// 只用 Node 内置模块；不联网，不发布；输出里不出现任何敏感值，只给文件与位置。

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve, isAbsolute, basename, relative } from "node:path";
import { pathToFileURL } from "node:url";
import {
  loadExport, summarize, eventIndex, attemptIndex, compareConfigs, checkManifest, compareManifests,
  manifestVsExport, hasWheelIdentity, tally, judgmentOf, parseTime, dur, num, pct,
} from "./records.mjs";

const REPRO = ["reproduced", "not_observed", "not_triggered", "conditions_differ", "evidence_review", "not_run"];
const JUDGE = ["confirmed", "rejected", "pending"];
const REPAIR = ["none", "planned", "in_progress", "fixed", "wontfix", "unknown"];
const VERIFY = ["not_run", "passed", "failed", "partial", "unknown"];
const TEXT_EXT = /\.(md|json|txt|log|export|html|mjs|ps1|yml|yaml)$/i;

// ---------- 文本辅助 ----------
const lineOf = (text, index) => { let n = 1; for (let i = text.indexOf("\n"); i !== -1 && i < index; i = text.indexOf("\n", i + 1)) n++; return n; };
// 按明确的行号引用原文，不在工具里解析 Markdown 结构。
export function excerptLines(text, start, end = start) {
  const lines = text.split(/\r?\n/);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > lines.length) throw new Error("文本行范围无效");
  return lines.slice(start - 1, end);
}

// 脱敏：位置与类别，不带匹配到的内容
const SECRET_PATTERNS = [
  ["sk-", /\bsk-[A-Za-z0-9_-]{20,}/g],
  ["github-token", /\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})/g],
  ["google-key", /\bAIza[0-9A-Za-z_-]{30,}/g],
  ["bearer", /\bBearer\s+[A-Za-z0-9._~+/=-]{24,}/g],
  ["private-key", /-----BEGIN [A-Z ]*PRIVATE KEY-----/g],
];
function redactDiagnostic(text, names = []) {
  let value = String(text);
  for (const [, pattern] of SECRET_PATTERNS) value = value.replace(pattern, "[REDACTED]");
  for (const name of new Set(["YUDAO_EVAL_API_KEY", "YUDAO_VISION_API_KEY", ...names])) {
    const secret = process.env[name];
    if (secret?.length >= 8) value = value.split(secret).join("[REDACTED]");
  }
  return value;
}
const print = (text) => console.log(redactDiagnostic(text, String(process.env.YUDAO_TRIAL_SECRET_ENV ?? "").split(",")));
const PATH_PATTERNS = [
  ["本机盘符路径", /(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?!Users[\\/]+<)/g],
  ["本机用户目录", /(?<![A-Za-z0-9.])\/(?:Users|home)\/[^\s"'`|)]+/g],
];
function scanText(text, file, { secrets, paths, envValues }) {
  const hits = [];
  const push = (kind, idx) => hits.push({ file, line: lineOf(text, idx), kind });
  for (const [name, re] of secrets ? SECRET_PATTERNS : []) for (const m of text.matchAll(re)) push(`疑似密钥(${name})`, m.index);
  for (const [name, re] of paths ? PATH_PATTERNS : []) for (const m of text.matchAll(re)) push(name, m.index);
  for (const [name, value] of secrets ? envValues : []) {
    for (let i = text.indexOf(value); i !== -1; i = text.indexOf(value, i + value.length)) push(`环境变量 ${name} 的值`, i);
  }
  return hits;
}

// ---------- 检查 ----------
export function check(resultPath, { secretEnv = [] } = {}) {
  const dir = dirname(resolve(resultPath));
  const errors = [];
  const warnings = [];
  const missing = [];
  const err = (code, where, message) => {
    const safe = { code, where: redactDiagnostic(where, secretEnv), message: redactDiagnostic(message, secretEnv) };
    if (!errors.some((x) => x.code === code && x.where === safe.where && x.message === safe.message)) errors.push(safe);
  };
  const warn = (code, where, message) => warnings.push({ code, where: redactDiagnostic(where, secretEnv), message: redactDiagnostic(message, secretEnv) });

  let result;
  try {
    result = JSON.parse(readFileSync(resolve(resultPath), "utf8"));
  } catch (e) {
    return { ok: false, status: "failed", errors: [{ code: "result_unreadable", where: basename(resultPath), message: e.code === "ENOENT" ? "文件不存在" : "JSON 无法解析" }], warnings, missing, summary: null, ctx: null };
  }

  // 路径：相对 result 所在目录，不收绝对路径
  const looksAbsolute = (p) => isAbsolute(p) || /^[A-Za-z]:/.test(p) || p.startsWith("\\\\");
  const refCache = new Map();
  const localPath = (p, where) => {
    if (typeof p !== "string" || !p) { err("path_invalid", where, "路径缺失"); return null; }
    if (looksAbsolute(p)) { err("path_absolute", where, "引用必须是相对 result.json 所在目录的路径"); return null; }
    const abs = resolve(dir, p.split("#")[0]);
    if (!existsSync(abs)) { err("path_missing", where, `文件不存在：${p}`); return null; }
    return abs;
  };
  const exportCache = new Map();
  const getExport = (p, where) => {
    const abs = localPath(p, where);
    if (!abs) return null;
    if (!exportCache.has(abs)) {
      try {
        const data = loadExport(abs);
        exportCache.set(abs, { path: p, data, r: summarize(data, p), events: eventIndex(data), attempts: attemptIndex(data) });
      } catch {
        err("export_unreadable", where, `不是可读取的 run 导出：${p}`);
        exportCache.set(abs, null);
      }
    }
    return exportCache.get(abs);
  };
  const getJson = (p, where) => {
    const abs = localPath(p, where);
    if (!abs) return null;
    if (!refCache.has(abs)) {
      try { refCache.set(abs, JSON.parse(readFileSync(abs, "utf8"))); } catch { err("json_unreadable", where, `JSON 无法解析：${p}`); refCache.set(abs, null); }
    }
    return refCache.get(abs);
  };
  const textOf = (abs) => readFileSync(abs, "utf8");

  const checkSource = (src, where) => {
    if (typeof src !== "string" || !src) { err("source_missing", where, "需要来源（相对路径或 https 链接）"); return false; }
    if (/^https:\/\/\S+$/.test(src)) return true; // 链接只记录，不联网核验
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(src)) { err("source_invalid", where, "来源链接必须是 https"); return false; }
    return !!localPath(src, where);
  };
  const checkEvidence = (list, where, { required = true } = {}) => {
    if (!Array.isArray(list) || !list.length) { if (required) err("evidence_missing", where, "至少需要一条证据引用"); return 0; }
    let ok = 0;
    list.forEach((ev, i) => {
      const w = `${where}[${i}]`;
      const abs = localPath(ev?.path, w);
      if (!abs) return;
      if (ev.event_id || ev.attempt_id) {
        const ex = getExport(ev.path, w);
        if (!ex) return;
        if (ev.event_id && !ex.events.has(ev.event_id)) { err("evidence_event_not_found", w, `导出里没有事件 ${ev.event_id}`); return; }
        if (ev.attempt_id && !ex.attempts.has(ev.attempt_id)) { err("evidence_attempt_not_found", w, `导出里没有尝试 ${ev.attempt_id}`); return; }
      }
      if (ev.line !== undefined) {
        if (!TEXT_EXT.test(ev.path) || /\.export$/i.test(ev.path)) { err("evidence_line_unsupported", w, "line 只能指向文本文件"); return; }
        const n = textOf(abs).split(/\r?\n/).length;
        if (!Number.isInteger(ev.line) || ev.line < 1 || ev.line > n) { err("evidence_line_out_of_range", w, `行号 ${ev.line} 不在 1..${n}`); return; }
      }
      ok++;
    });
    return ok;
  };
  const needMissing = (scope, item, auto = true) => {
    // 缺项必须写明原因：自动检出的缺项在 missing 里找同名声明
    const decl = declared.find((d) => d.scope === scope && d.item === item);
    if (!decl) { missing.push({ scope, item, reason: null }); err("missing_undeclared", scope, `缺项「${item}」没有在 missing 里写明原因`); return; }
    missing.push({ scope, item, reason: decl.reason });
  };

  // ----- 顶层 -----
  const need = (cond, code, where, msg) => { if (!cond) err(code, where, msg); };
  need(result.schema_version === 1, "schema", "schema_version", "schema_version 必须是 1");
  for (const k of ["task_set", "material_version"]) need(typeof result[k] === "string" && result[k], "schema", k, `${k} 缺失`);
  need(typeof result.tested_commit === "string" && /^[0-9a-f]{7,40}$/.test(result.tested_commit), "schema", "tested_commit", "tested_commit 缺失或不是 7 到 40 位十六进制");
  need(Array.isArray(result.tasks) && result.tasks.length > 0, "schema", "tasks", "tasks 必须是非空数组");

  const declared = [];
  const declare = (scope, list) => {
    for (const [i, d] of (list ?? []).entries()) {
      if (!d || typeof d.item !== "string" || typeof d.reason !== "string" || !d.reason.trim()) err("missing_reason", `${scope}.missing[${i}]`, "缺项需要 item 和非空 reason");
      else declared.push({ scope, item: d.item, reason: d.reason });
    }
  };
  declare("top", result.missing);

  // ----- 实例 manifest -----
  const manifests = new Map();
  const getManifest = (p, where) => {
    if (!p) return null;
    const abs = localPath(p, where);
    if (!abs) return null;
    if (!manifests.has(abs)) {
      const m = getJson(p, where);
      const errs = m ? checkManifest(m) : [];
      errs.forEach((e) => err("manifest_invalid", where, `${p}：${e}`));
      manifests.set(abs, m && !errs.length ? m : null);
    }
    return manifests.get(abs);
  };
  const listedInstances = new Set();
  (result.instances ?? []).forEach((p, i) => { const abs = localPath(p, `instances[${i}]`); if (abs) { listedInstances.add(abs); getManifest(p, `instances[${i}]`); } });

  // ----- 任务 -----
  const tasks = new Map();
  const readouts = [];
  const ids = new Set();
  const runTasks = new Map();
  (result.tasks ?? []).forEach((t, i) => {
    const where = `tasks[${i}]`;
    const id = t?.id;
    const scope = `task:${id}`;
    if (!/^(F1|R1|X\d+)$/.test(id ?? "")) { err("task_id", where, "id 必须是 F1、R1 或 X<数字>"); return; }
    if (ids.has(id)) err("task_id", where, `任务 ${id} 重复`);
    ids.add(id);
    need(t.kind === (id.startsWith("X") ? "exploration" : "fixed"), "task_kind", where, `${id} 的 kind 必须是 ${id.startsWith("X") ? "exploration" : "fixed"}`);
    declare(scope, t.missing);

    const ex = t.export_path ? getExport(t.export_path, `${where}.export_path`) : null;
    if (!t.export_path) needMissing(scope, "run_export");
    const entry = { t, ex, scope, manifest: null, delivered: !!ex && ex.r.deliveryAccepted.length > 0 };
    tasks.set(id, entry);
    if (ex) {
      if (runTasks.has(ex.r.runId)) err("task_duplicate_run", where, "不同任务不能复用同一份运行结果");
      runTasks.set(ex.r.runId, id);
      readouts.push({ id, r: ex.r });
      for (const inc of ex.r.inconsistencies) err(inc.code, `${where}.export_path`, inc.detail);
    }

    // 试用者耗时与导出事件窗口
    const ps = t.phase_started_at === undefined ? null : parseTime(t.phase_started_at);
    const pf = t.phase_finished_at === undefined ? null : parseTime(t.phase_finished_at);
    if ((t.phase_started_at !== undefined && ps === null) || (t.phase_finished_at !== undefined && pf === null)) err("phase_time", where, "phase_started_at/phase_finished_at 必须是带时区偏移的 ISO 时间");
    if (ps !== null && pf !== null && pf < ps) err("phase_time", where, "phase_finished_at 早于 phase_started_at");
    entry.phaseMs = ps !== null && pf !== null && pf >= ps ? pf - ps : null;
    if (ex && ps !== null && pf !== null && ex.r.events.first?.ms != null) {
      const { first, last } = ex.r.events;
      if (first.ms < ps || last.ms > pf) warn("phase_window_difference", where, "观察阶段与事件窗口不同，报告分别呈现两种来源，不用观察者自报时间替换事件时间");
    }

    // 实例身份
    if (t.instance_path) {
      const abs = localPath(t.instance_path, `${where}.instance_path`);
      if (abs && !listedInstances.has(abs)) err("instance_not_listed", where, "instance_path 必须同时列在顶层 instances 里");
      const m = getManifest(t.instance_path, `${where}.instance_path`);
      entry.manifest = m;
      if (m) {
        if (m.task_set !== result.task_set) err("identity_mismatch", where, `实例的 task_set(${m.task_set}) 与 result(${result.task_set}) 不同`);
        if (m.material_version !== result.material_version) err("identity_mismatch", where, `实例的 material_version(${m.material_version}) 与 result(${result.material_version}) 不同`);
        if (typeof result.tested_commit === "string" && !(m.commit.startsWith(result.tested_commit) || result.tested_commit.startsWith(m.commit))) err("identity_mismatch", where, `实例的 commit(${m.commit.slice(0, 8)}) 与 tested_commit(${result.tested_commit.slice(0, 8)}) 不同`);
        if (!hasWheelIdentity(m)) err("wheel_identity", where, "缺少可核对的 wheel 身份，先核对实际运行版本");
        if (!m.models.length) needMissing(scope, "model_configuration");
        if (ex?.r.events.first?.ms != null) {
          const starts = [m, ...(m.process_history ?? [])].map((item) => parseTime(item.process_started_at)).filter((value) => value !== null);
          if (starts.length && ex.r.events.first.ms < Math.min(...starts)) err("instance_time_mismatch", where, "运行早于该实例及其重启历史，不能把当前实例身份补造为旧现场身份");
        }
        if (ex) for (const d of manifestVsExport(m, ex.r.configs)) err("instance_export_mismatch", `${where}`, `${d.department}${d.purpose ? "/" + d.purpose : ""} 的 ${d.field}：实例声明 ${JSON.stringify(d.manifest)}，导出 ${JSON.stringify(d.export)}`);
      }
    } else err("instance_identity", where, "缺少实际运行身份；可离线读取事件，发布前须核对实例版本");

    for (const k of ["novice_path", "expert_path"]) if (t[k]) localPath(t[k], `${where}.${k}`);
    if (t.kind === "fixed") {
      if (!t.novice_path) needMissing(scope, "novice");
      if (!t.expert_path) needMissing(scope, "expert");
    }

    // 评分：F1 需要；R1 不需要
    if (id === "F1") {
      const s = t.score ?? {};
      const w = `${where}.score`;
      if (!["done", "missing", "not_applicable"].includes(s.status)) err("score_status", w, "score.status 必须是 done、missing 或 not_applicable");
      else if (s.status === "done") {
        const scored = getJson(s.path, `${w}.path`);
        if (scored) {
          for (const field of ["completion", "correctness"]) if (typeof scored[field] !== "number" || !Number.isFinite(scored[field]) || scored[field] < 0 || scored[field] > 1) err("score_content", w, `评分文件的 ${field} 不是 0..1 的数值`);
          if (scored.material_version !== result.material_version) err("score_material", w, "评分文件的材料版本与本轮不同");
          if (!scored.scorer_version) err("score_content", w, "评分文件缺少 scorer_version");
          entry.scored = scored;
        }
        if (!entry.delivered) warn("score_without_delivery", w, "导出里没有 delivery_accepted，却有评分");
      }
      else if (s.status === "missing") {
        if (typeof s.reason !== "string" || !s.reason.trim()) err("score_reason", w, "评分缺项需要 reason");
        else { missing.push({ scope, item: "score", reason: s.reason }); }
        if (!entry.delivered) warn("score_missing_no_delivery", w, "没有交付，评分可改标 not_applicable");
      } else {
        if (typeof s.reason !== "string" || !s.reason.trim()) err("score_reason", w, "not_applicable 需要 reason");
        if (entry.delivered) err("score_not_applicable_but_delivered", w, "导出里已有 delivery_accepted，评分不能标 not_applicable");
      }
    } else if (t.score?.path) localPath(t.score.path, `${where}.score.path`);
  });
  for (const must of ["F1", "R1"]) {
    if (!tasks.has(must)) {
      const decl = declared.find((d) => d.scope === "top" && d.item === `task:${must}`);
      if (decl) missing.push({ scope: "top", item: `task:${must}`, reason: decl.reason });
      else { missing.push({ scope: "top", item: `task:${must}`, reason: null }); err("task_missing", "tasks", `每轮必须有 ${must}；没做时在顶层 missing 里写 task:${must} 与原因`); }
    }
  }

  // ----- 第一眼 -----
  const fiState = new Map();
  const fi = Array.isArray(result.first_impressions) ? result.first_impressions : [];
  const fiEntries = [];
  fi.forEach((e, i) => {
    const w = `first_impressions[${i}]`;
    const abs = localPath(e?.path, `${w}.path`);
    if (!tasks.has(e?.task_id)) { err("first_impression_task", w, `task_id ${e?.task_id} 不在 tasks 里`); return; }
    if (!abs) return;
    let lines;
    try { lines = excerptLines(textOf(abs), e.start_line ?? e.line, e.end_line ?? e.start_line ?? e.line); }
    catch { err("first_impression_range", w, "需要来源中的有效 start_line/end_line 或 line"); return; }
    if (!lines.some((line) => line.trim())) { err("first_impression_empty", w, "引用片段没有内容"); return; }
    fiEntries.push({ ...e, lines });
  });
  for (const [id, en] of tasks) {
    const p = en.t.novice_path;
    if (!p) continue;
    const abs = resolve(dir, p);
    if (!existsSync(abs)) continue;
    const mentions = textOf(abs).includes("第一眼");
    const included = fiEntries.filter((e) => e.task_id === id).length;
    if (included) fiState.set(id, { state: "included", included });
    else { fiState.set(id, { state: "missing", mentions }); needMissing(en.scope, "first_impressions"); }
  }

  // ----- 问题 -----
  const checkStatus = (obj, allowed, where, name) => {
    const s = obj?.status ?? "unknown";
    if (!allowed.includes(s)) { err(`${name}_status`, where, `${name}.status 必须是 ${allowed.join("、")}`); return null; }
    return s;
  };
  const checkRecord = (f, where, { inCurrent }) => {
    if (!f?.id || typeof f.id !== "string") err("finding_id", where, "id 缺失");
    if (!["defect", "experience"].includes(f?.kind)) err("finding_kind", where, "kind 必须是 defect 或 experience");
    const j = f?.judgment ?? { status: "pending" };
    const js = checkStatus(j, JUDGE, `${where}.judgment`, "judgment");
    if ((js === "confirmed" || js === "rejected")) checkSource(j.source, `${where}.judgment.source`);
    const rp = checkStatus(f?.repair, REPAIR, `${where}.repair`, "repair");
    if (rp === "fixed") checkSource(f.repair.source, `${where}.repair.source`);
    const vf = checkStatus(f?.verification, VERIFY, `${where}.verification`, "verification");
    if (["passed", "failed", "partial"].includes(vf)) {
      checkSource(f.verification.source, `${where}.verification.source`);
      if (!f.verification.commit && !f.verification.instance_path) err("verification_version", `${where}.verification`, "验证结果需要写明对应的 commit 或 instance_path");
      if (rp !== "fixed") err("verification_without_repair", `${where}.verification`, "修复进度不是 fixed，不能有修复后验证结果");
    }
    if (f?.tracker?.source) checkSource(f.tracker.source, `${where}.tracker.source`);
  };

  const findings = result.findings ?? [];
  const fIds = new Set();
  const reproRows = [];
  findings.forEach((f, i) => {
    const where = `findings[${i}]`;
    checkRecord(f, where, { inCurrent: true });
    if (fIds.has(f.id)) err("finding_id", where, `问题 ${f.id} 重复`);
    fIds.add(f.id);
    const task = tasks.get(f.task_id);
    if (!task) err("finding_task", where, `task_id ${f.task_id} 不在 tasks 里`);
    for (const k of ["title", "steps", "expected", "actual"]) if (typeof f[k] !== "string" || !f[k].trim()) err("finding_text", where, `${k} 缺失`);
    checkEvidence(f.evidence, `${where}.evidence`);

    // 复现
    const r = f.reproduction ?? { status: "not_run", reason: undefined };
    const rw = `${where}.reproduction`;
    if (!REPRO.includes(r.status)) { err("repro_status", rw, `status 必须是 ${REPRO.join("、")}`); return; }
    const row = { id: f.id, status: r.status, build: "—", config: "—", trigger: r.trigger_reached ?? null };
    reproRows.push(row);
    const needReason = () => { if (typeof r.reason !== "string" || !r.reason.trim()) err("repro_reason", rw, `${r.status} 需要 reason`); };
    if (r.status === "not_run") { needReason(); if (r.reason) missing.push({ scope: `finding:${f.id}`, item: "reproduction", reason: r.reason }); return; }
    if (["not_triggered", "conditions_differ", "evidence_review"].includes(r.status)) needReason();
    if (r.status === "not_triggered" && r.trigger_reached !== false) err("repro_trigger", rw, "not_triggered 要求 trigger_reached 为 false");
    if (r.evidence) checkEvidence(r.evidence, `${rw}.evidence`, { required: false });

    const needsRun = ["reproduced", "not_observed", "conditions_differ", "not_triggered"].includes(r.status);
    const rex = r.export_path ? getExport(r.export_path, `${rw}.export_path`) : null;
    const rman = r.instance_path ? getManifest(r.instance_path, `${rw}.instance_path`) : null;
    if (rex && rman) for (const d of manifestVsExport(rman, rex.r.configs)) err("instance_export_mismatch", rw, `复现实例的 ${d.department}/${d.field} 与实际调用不一致`);
    if (r.instance_path) { const a = localPath(r.instance_path, `${rw}.instance_path`); if (a && !listedInstances.has(a)) err("instance_not_listed", rw, "instance_path 必须同时列在顶层 instances 里"); }
    let cfg = null;
    let build = null;
    if (rex && task?.ex) { cfg = compareConfigs(task.ex.r.configs, rex.r.configs); row.config = cfg.comparable ? "相同" : cfg.diffs.some((d) => d.level === "blocking") ? `不同（${[...new Set(cfg.diffs.filter((d) => d.level === "blocking").map((d) => `${d.key} ${d.field}`))].join("；")}）` : "未知"; }
    if (rman && task?.manifest) { build = compareManifests(task.manifest, rman); row.build = build.sameBuild ? "相同" : build.diffs.length ? `不同（${build.diffs.map((d) => d.field).join("、")}）` : `未知（${build.unknown.join("、")}）`; }
    else if (needsRun) row.build = "未知（缺实例身份）";
    row.sameConditions = !!(cfg?.comparable && build?.sameBuild);

    if (r.status === "reproduced" || r.status === "not_observed") {
      if (!r.export_path || !r.instance_path) err("repro_incomplete", rw, `${r.status} 需要复现运行的 export_path 和 instance_path`);
      if (r.trigger_reached !== true) err("repro_trigger", rw, `${r.status} 要求 trigger_reached 为 true`);
      if (rman && task?.manifest && resolve(rman.data_dir) === resolve(task.manifest.data_dir)) err("repro_shared_data", rw, "独立复现需要新的数据目录，不能复用原现场的数据目录");
      checkEvidence(r.evidence, `${rw}.evidence`);
      if (rex && task?.ex && rex.r.runId === task.ex.r.runId) err("repro_same_run", rw, "同一份运行不能作为独立重跑；重读原证据应标为 evidence_review");
      if (rex && !(r.evidence ?? []).some((ev) => ev?.event_id && resolve(dir, ev.path) === resolve(dir, r.export_path) && rex.events.has(ev.event_id))) err("repro_trigger_evidence", rw, "需要复现导出中的事件引用证明触发条件与观察结果");
      if (!row.sameConditions) {
        const why = [];
        if (!task?.manifest) why.push("原运行缺实例身份");
        if (!rman) why.push("复现运行缺实例身份");
        if (build && !build.sameBuild) why.push(build.diffs.length ? `构建不同(${build.diffs.map((d) => d.field).join("、")})` : `构建身份未知(${build.unknown.join("、")})`);
        if (!cfg) why.push("缺少可比较的导出");
        else if (!cfg.comparable) why.push(cfg.diffs.some((d) => d.level === "blocking") ? `部门配置不同(${cfg.diffs.filter((d) => d.level === "blocking").map((d) => `${d.key} ${d.field}`).join("；")})` : "部门配置有未知项");
        err("repro_conditions_not_verified", rw, `${r.status} 需要两次运行的构建与部门配置一致；当前：${why.join("，")}。条件不同时请标 conditions_differ，只重读旧证据请标 evidence_review`);
      }
    }
    if (r.status === "conditions_differ" && row.sameConditions) warn("repro_conditions_same", rw, "两次运行的构建与配置实际相同，conditions_differ 需要说明差异在哪里");
    if (r.status === "evidence_review" && r.export_path) warn("repro_review_with_run", rw, "evidence_review 只重读证据，却带了 export_path");
  });

  // ----- 回查历史 -----
  const history = result.history ?? [];
  history.forEach((h, i) => {
    checkRecord(h, `history[${i}]`, { inCurrent: false });
    if (h?.tracker?.state && !["OPEN", "CLOSED"].includes(h.tracker.state)) err("history_tracker", `history[${i}].tracker`, "tracker.state 必须是 OPEN 或 CLOSED");
  });

  // ----- 脱敏 -----
  const envNames = new Set(["YUDAO_EVAL_API_KEY", ...secretEnv, ...String(process.env.YUDAO_TRIAL_SECRET_ENV ?? "").split(",").filter(Boolean)]);
  for (const ex of exportCache.values()) for (const c of ex?.r.credentialRefs ?? []) envNames.add(c);
  const envValues = [...envNames].map((n) => [n, process.env[n]]).filter(([, v]) => typeof v === "string" && v.length >= 8);
  const publish = new Set();
  for (const p of result.publish ?? []) {
    const abs = localPath(p, "publish");
    if (abs) publish.add(abs);
  }
  const leaks = scanText(readFileSync(resolve(resultPath), "utf8"), basename(resultPath), { secrets: true, paths: false, envValues });
  let scanned = 1;
  const relName = (abs) => (abs.startsWith(dir) ? abs.slice(dir.length + 1).replace(/\\/g, "/") : basename(abs));
  for (const abs of publish) {
    if (!TEXT_EXT.test(abs)) continue;
    const isPublish = publish.has(abs);
    scanned++;
    leaks.push(...scanText(readFileSync(abs, "utf8"), relName(abs), { secrets: true, paths: isPublish, envValues }));
  }
  for (const e of fiEntries) leaks.push(...scanText(e.lines.join("\n"), `${e.path}:${e.start_line ?? e.line}`, { secrets: true, paths: true, envValues }));
  for (const p of result.handoffs ?? []) {
    const abs = localPath(p, "handoffs");
    if (abs) { scanned++; leaks.push(...scanText(textOf(abs), basename(p), { secrets: true, paths: false, envValues })); }
  }
  for (const l of leaks.slice(0, 50)) err(l.kind.startsWith("本机") ? "redaction_path" : "redaction_secret", `${l.file}:${l.line}`, `发布前需要清理：${l.kind}`);
  if (leaks.length > 50) err("redaction_more", "—", `另有 ${leaks.length - 50} 处未列出`);

  for (const declaredItem of declared) {
    if (!missing.some((item) => item.scope === declaredItem.scope && item.item === declaredItem.item)) missing.push(declaredItem);
  }
  // ----- 汇总 -----
  const status = errors.length ? "failed" : missing.length ? "partial" : "complete";
  const summary = {
    tallyCurrent: tally(findings),
    tallyHistory: tally(history),
    redaction: { filesScanned: scanned, publishFiles: publish.size, envValuesCompared: envValues.length, envNamesChecked: envNames.size },
    tasks: readouts.map(({ id, r }) => ({ id, run: r.runId, status: r.status, stopReason: r.stopReason, wallMs: r.events.wallMs, attempts: r.attempts.count })),
  };
  return {
    ok: !errors.length, status, errors, warnings, missing, summary,
    ctx: { result, tasks, reproRows, fiState, fiEntries, history, findings, manifests: [...manifests.values()].filter(Boolean), dir, secretEnvNames: [...envNames] },
  };
}

// ---------- 事实表格 ----------
const esc = (s) => String(s ?? "—").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
const md = (head, rows) => [`| ${head.join(" | ")} |`, `| ${head.map(() => "---").join(" | ")} |`, ...rows.map((r) => `| ${r.map(esc).join(" | ")} |`)].join("\n");
const rate = (c, d) => (d ? `${((c / d) * 100).toFixed(0)}%（${c}/${d}）` : "—（没有明确裁决，分母为 0）");
const cost = (v) => (v === null || v === undefined ? "未报告" : v);
const JUDGE_ZH = { confirmed: "成立", rejected: "不成立", pending: "待定" };
const REPRO_ZH = { reproduced: "已复现", not_observed: "同条件触发后未出现", not_triggered: "未触发", conditions_differ: "条件不同", evidence_review: "仅复核证据", not_run: "未复现" };

export function render(rep) {
  const { result, tasks, reproRows, fiState, fiEntries, history, findings, manifests, dir } = rep.ctx;
  const out = [];
  const statusZh = { complete: "完整", partial: "部分完成" }[rep.status];
  out.push(`## 事实表格${result.title ? `：${result.title}` : ""}`);
  out.push("");
  out.push(`报告状态：**${statusZh}**。任务集 ${result.task_set}，材料 ${result.material_version}，被测提交 ${result.tested_commit}。以下数字由 report.mjs 从本轮导出即时读出，表格不含估算值；「—」或「未报告」表示来源没有给出。`);
  out.push("");

  out.push("### 缺项");
  out.push(rep.missing.length ? md(["范围", "项目", "原因"], rep.missing.map((m) => [m.scope, m.item, m.reason])) : "无缺项。");
  out.push("");

  out.push("### 被测实例");
  out.push(manifests.length
    ? md(["提交", "wheel SHA-256", "技能提交", "端口", "进程", "状态", "身份核对时间", "部门模型（模型名/协议/窗口/输出上限）"],
      manifests.map((m) => [m.commit, m.wheel?.sha256 ?? "无（未装 wheel）", `${m.skill_commit}${m.skill_worktree_dirty ? "（含未提交修改，资源摘要另存）" : ""}`, m.port, m.pid, m.status, m.identity_checked_at, m.models.map((x) => `${x.department}: ${x.model}/${x.protocol}/${num(x.context_window)}/${num(x.max_output_tokens)}`).join("；")]))
    : "没有实例身份记录。");
  out.push("");

  out.push("### 任务读数");
  const rows = [];
  for (const [id, en] of tasks) {
    const r = en.ex?.r;
    if (!r) continue;
    rows.push([id, r.runId, `${r.status}/${r.stopReason ?? "—"}`, `${r.events.first?.at ?? "—"} 至 ${r.events.last?.at ?? "—"}`, dur(r.events.wallMs), dur(en.phaseMs), r.attempts.count, dur(r.attempts.spanMs), num(r.totals.input_tokens), num(r.totals.output_tokens), cost(r.totals.cost), r.deliveryAccepted.map((d) => d.at).join("；") || "无", r.terminal ? `${r.terminal.type} ${r.terminal.at}` : "—"]);
  }
  out.push(md(["任务", "运行", "状态/停止原因", "事件窗口", "事件墙钟", "试用者耗时", "尝试", "步骤跨度", "输入 token", "输出 token", "费用", "交付收下", "结束事件"], rows));
  out.push("");
  out.push("### 交付评分");
  out.push(md(["任务", "评分状态", "完成度", "正确性", "评分器", "说明"], [...tasks].map(([id, en]) => [id, en.t.score?.status ?? "not_applicable", en.scored?.completion ?? "—", en.scored?.correctness ?? "—", en.scored?.scorer_version ?? "—", en.t.score?.reason ?? ""])))
  out.push("");

  out.push("### 部门配置（来自导出的 call_target；上游模型是发给模型服务的名字，本地别名是配置里的名字）");
  const cr = [];
  for (const [id, en] of tasks) for (const c of en.ex?.r.configs ?? []) cr.push([id, `${c.department}/${c.purpose}`, c.requested_model, c.model_id, c.actual_models.join("、") || "未回报", c.protocol, num(c.context_window), num(c.max_output_tokens), c.requested_tier ?? "—", c.attempts]);
  out.push(md(["任务", "部门/目的", "上游模型", "本地别名", "回报的实际模型", "协议", "窗口", "输出上限", "档位", "尝试"], cr));
  out.push("");

  out.push("### 压缩与最大输入");
  const kr = [];
  for (const [id, en] of tasks) {
    const r = en.ex?.r;
    if (!r) continue;
    const c = r.compaction;
    kr.push([id, `${c.logicalCalls}（成功 ${c.logicalCallsSucceeded}）`, `${c.attempts}（成功 ${c.responseSuccess}／失败 ${c.responseFailed}）`, c.checkpointEvents, c.projectionRecords, r.maxIn ? `${num(r.maxIn.tokens)}（${r.maxIn.department}/${r.maxIn.purpose}，窗口 ${num(r.maxIn.window)}）` : "—", r.maxRatio ? `${pct(r.maxRatio.tokens, r.maxRatio.window)}（${r.maxRatio.department}/${r.maxRatio.purpose}）` : "—", r.overWindow]);
  }
  out.push(md(["任务", "压缩请求", "压缩尝试", "检查点事件", "投影记录", "最大单次输入", "最高窗口占比（按该次窗口）", "超窗口次数"], kr));
  out.push("");

  out.push("### 试用发现");
  out.push(findings.length ? md(["编号", "类别", "标题", "任务", "复现", "裁决", "修复", "修复后验证"],
    findings.map((f) => [f.id, f.kind === "defect" ? "缺陷主张" : "体验候选", f.title, f.task_id, REPRO_ZH[f.reproduction?.status ?? "not_run"], JUDGE_ZH[judgmentOf(f)], f.repair?.status ?? "unknown", `${f.verification?.status ?? "unknown"}${f.verification?.commit ? `（${String(f.verification.commit).slice(0, 8)}）` : ""}`])) : "本轮没有记录问题。");
  out.push("");
  if (reproRows.length) {
    out.push("### 复现条件比较");
    out.push(md(["问题", "复现状态", "触发条件", "实例身份与计划", "实际部门调用"], reproRows.map((r) => [r.id, REPRO_ZH[r.status], r.trigger === null ? "—" : r.trigger ? "已到达" : "未到达", r.build, r.config])));
    out.push("");
  }

  const t1 = tally(findings);
  const t2 = tally(history);
  out.push("### 裁决统计");
  out.push("缺陷命中率 = 成立 /（成立 + 不成立）；待定不进分母；工单关闭状态不产生裁决。体验候选的「成立」记为采纳。");
  out.push("");
  const tr = (name, t) => [name, t.defect.confirmed, t.defect.rejected, t.defect.pending, rate(t.defect.confirmed, t.defectDenominator), t.experience.confirmed, t.experience.rejected, t.experience.pending, rate(t.experience.confirmed, t.experienceDenominator)];
  out.push(md(["范围", "缺陷成立", "缺陷不成立", "缺陷待定", "缺陷命中率", "体验采纳", "体验不采纳", "体验待定", "采纳率"], [tr("本轮", t1), ...(history.length ? [tr("回查的历史问题", t2)] : [])]));
  out.push("");

  if (history.length) {
    out.push("### 回查的历史问题");
    out.push(md(["编号", "类别", "标题", "裁决", "裁决来源", "工单状态", "修复", "回归验证"],
      history.map((h) => [h.id, h.kind === "defect" ? "缺陷" : "体验候选", h.title, JUDGE_ZH[judgmentOf(h)], h.judgment?.source ?? "—", h.tracker ? `${h.tracker.state}${h.tracker.reason ? `/${h.tracker.reason}` : ""}${judgmentOf(h) === "pending" && h.tracker.state === "CLOSED" ? "（已关闭，未见裁决）" : ""}` : "—", h.repair?.status ?? "unknown", `${h.verification?.status ?? "unknown"}${h.verification?.commit ? `（${String(h.verification.commit).slice(0, 8)}）` : ""}`])));
    out.push("");
  }

  out.push("### 第一眼观感收录");
  const fr = [];
  for (const [id, s] of fiState) fr.push([id, s.state === "included" ? `已收录 ${s.included} 处原始片段，内容由专家逐项核对` : s.mentions ? "来源提及第一眼，尚未收录；原因见缺项" : "没有收录第一眼；原因见缺项"]);
  out.push(fr.length ? md(["任务", "状态"], fr) : "没有可核对的来源文件。");
  out.push("");
  if (fiEntries.length) {
    out.push("### 附录：第一眼原话（按来源文件原样引用，未改写）");
    for (const e of fiEntries) {
      out.push("");
      out.push(`来源 ${e.path}，任务 ${e.task_id}：`);
      out.push("");
      const body = [...e.lines];
      while (body.length && !body[0].trim()) body.shift();
      while (body.length && !body.at(-1).trim()) body.pop();
      for (const l of body) out.push(l.trim() ? `> ${l}` : ">");
    }
    out.push("");
  }
  return out.join("\n");
}

// ---------- 初始化 ----------
export function init(resultPath, { taskSet, material, commit, exports }) {
  const dir = dirname(resolve(resultPath));
  const rel = (p) => relative(dir, resolve(p)).replaceAll("\\", "/");
  const tasks = [];
  const notes = [];
  let xi = 0;
  for (const spec of exports) {
    const m = /^(F1|R1|X\d+)=(.+)$/.exec(spec);
    const path = m ? m[2] : spec;
    const name = basename(path);
    let id = m?.[1];
    if (!id) {
      if (/repro/i.test(name)) { notes.push(`${name} 看起来是复现运行，不作为任务；请在对应问题的 reproduction.export_path 里引用`); continue; }
      id = /r1/i.test(name) ? "R1" : tasks.some((t) => t.id === "F1") ? `X${++xi}` : "F1";
    }
    const data = loadExport(path);
    const r = summarize(data, name);
    const delivered = r.deliveryAccepted.length > 0;
    const task = { id, kind: id.startsWith("X") ? "exploration" : "fixed", export_path: rel(path), instance_path: null, novice_path: null, expert_path: null };
    if (id === "F1") task.score = delivered ? { status: "missing", reason: "" } : { status: "not_applicable", reason: "导出里没有 delivery_accepted 事件" };
    task.missing = !id.startsWith("X") ? [{ item: "novice", reason: "" }, { item: "expert", reason: "" }] : [];
    tasks.push(task);
    notes.push(`${id} ← ${name}：运行 ${r.runId}，状态 ${r.status}/${r.stopReason ?? "—"}，${delivered ? "有" : "无"}交付`);
  }
  const doc = { schema_version: 1, task_set: taskSet, material_version: material, tested_commit: commit, title: "", instances: [], tasks, findings: [], first_impressions: [], history: [], missing: [] };
  writeFileSync(resolve(resultPath), JSON.stringify(doc, null, 2) + "\n", { flag: "wx" });
  return notes;
}

// ---------- 命令行 ----------
function printReport(rep) {
  const label = { complete: "完整", partial: "部分完成", failed: "未通过" }[rep.status];
  print(`结果：${label}`);
  if (rep.errors.length) { print(`\n错误 ${rep.errors.length} 条：`); for (const e of rep.errors) print(`- [${e.code}] ${e.where}：${e.message}`); }
  if (rep.warnings.length) { print(`\n警告 ${rep.warnings.length} 条：`); for (const e of rep.warnings) print(`- [${e.code}] ${e.where}：${e.message}`); }
  if (rep.missing.length) { print(`\n缺项 ${rep.missing.length} 条：`); for (const m of rep.missing) print(`- ${m.scope} / ${m.item}：${m.reason ?? "（未写原因）"}`); }
  if (rep.summary && rep.ok) {
    const t = rep.summary.tallyCurrent;
    const rd = rep.summary.redaction;
    print(`\n脱敏检查：扫描 ${rd.filesScanned} 个文件（其中发布文件 ${rd.publishFiles} 个），与 ${rd.envValuesCompared}/${rd.envNamesChecked} 个环境变量的值比较（值不输出）`);
    print(`\n本轮缺陷命中率：${rate(t.defect.confirmed, t.defectDenominator)}；待定 ${t.defect.pending}；体验采纳 ${t.experience.confirmed}／不采纳 ${t.experience.rejected}／待定 ${t.experience.pending}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argv = process.argv.slice(2);
  const opt = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
  const flags = new Set(["--check", "--init", "--json", "--render", "--secret-env", "--task-set", "--material", "--commit"]);
  const positional = [];
  for (let i = 0; i < argv.length; i++) { if (flags.has(argv[i])) { if (argv[i] !== "--json") i++; } else positional.push(argv[i]); }
  const usage = (m) => { console.error(`${m}\n用法：node report.mjs --check <result.json> [--json] [--secret-env 名字,名字] [--render <输出.md>]\n      node report.mjs --init <result.json> --task-set <版本> --material <版本> --commit <提交> [ID=]<导出>…`); process.exit(2); };

  if (argv.includes("--init")) {
    const target = opt("--init");
    const [taskSet, material, commit] = [opt("--task-set"), opt("--material"), opt("--commit")];
    if (!target || !taskSet || !material || !commit || !positional.length) usage("--init 需要 result.json 路径、--task-set、--material、--commit 和至少一个导出");
    if (existsSync(resolve(target))) usage(`${basename(target)} 已存在，不覆盖`);
    for (const n of init(target, { taskSet, material, commit, exports: positional })) print(n);
    print(`已写入 ${basename(target)}；instance_path、missing 里的原因和 novice_path 需要填写后再 --check`);
    process.exit(0);
  }
  if (argv.includes("--check")) {
    const target = opt("--check");
    if (!target) usage("--check 需要 result.json 路径");
    const rep = check(target, { secretEnv: (opt("--secret-env") ?? "").split(",").filter(Boolean) });
    let rendered = null;
    const renderTo = opt("--render");
    if (renderTo && rep.ok) {
      const text = render(rep);
      const values = rep.ctx.secretEnvNames.map((name) => [name, process.env[name]]).filter(([, value]) => value?.length >= 8);
      const hits = scanText(text, basename(renderTo), { secrets: true, paths: true, envValues: values });
      if (hits.length) { rep.ok = false; rep.status = "failed"; for (const h of hits) rep.errors.push({ code: "redaction_render", where: `${h.file}:${h.line}`, message: `生成的表格含 ${h.kind}，未写入` }); }
      else { writeFileSync(resolve(renderTo), text + "\n"); rendered = basename(renderTo); }
    }
    if (argv.includes("--json")) {
      const { ctx, ...rest } = rep;
      print(JSON.stringify({ ...rest, rendered }, null, 1));
    } else {
      printReport(rep);
      if (rendered) print(`\n已写入 ${rendered}`);
      else if (renderTo) print("\n检查未通过，未写入表格");
    }
    process.exit(rep.errors.length ? (rep.errors.some((e) => e.code === "result_unreadable") ? 2 : 1) : 0);
  }
  usage("需要 --check 或 --init");
}
