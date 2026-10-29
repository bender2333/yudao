#!/usr/bin/env node
// 读 run 导出（run.export / run.export 一类文件），打印一次试用的读数。
// 用法：node readout.mjs <导出文件> [更多导出] [--json] [--types]
// 只用 Node 内置模块。导出文件是一行 JSON：{position, data:{run_id, projection, events[], attempts[], usage{}}}

import { readFileSync } from "node:fs";

const argv = process.argv.slice(2);
const files = argv.filter((a) => !a.startsWith("--"));
const wantJson = argv.includes("--json");
const wantTypes = argv.includes("--types");

if (!files.length) {
  console.error("用法：node readout.mjs <run.export> [更多导出] [--json] [--types]");
  process.exit(1);
}

const CJK = /[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFF60\uFFE0-\uFFE6]/;
const vis = (s) => [...String(s ?? "")].reduce((n, ch) => n + (CJK.test(ch) ? 2 : 1), 0);
const pad = (s, n) => String(s ?? "") + " ".repeat(Math.max(0, n - vis(s)));
const num = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US"));
const pct = (a, b) => (a === null || a === undefined || !b ? "—" : ((a / b) * 100).toFixed(1) + "%");

function dur(ms) {
  if (ms === null || ms === undefined) return "—";
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分 ${r} 秒`;
  return `${r} 秒`;
}
const clockOf = (s) => (s ? String(s).slice(11, 19) : "—");
const span = (a, b) => {
  const x = Date.parse(a || "");
  const y = Date.parse(b || "");
  return Number.isFinite(x) && Number.isFinite(y) ? dur(y - x) : "—";
};

const KEY_EVENTS = new Set([
  "run_created", "input_received", "spec_accepted", "spec_rejected", "contract_accepted",
  "contract_rejected", "department_activated", "department_input", "proposal_submitted",
  "proposal_rejected", "activation_finished", "delivery_submitted", "delivery_accepted",
  "delivery_rejected", "qa_submitted", "review_submitted", "compaction_recorded",
  "human_action_requested", "human_action_resolved", "run_stopped", "run_done", "error",
]);

function load(path) {
  const doc = JSON.parse(readFileSync(path, "utf8"));
  const data = doc.data ?? doc;
  const attempts = Array.isArray(data.attempts) ? data.attempts : [];
  const events = Array.isArray(data.events) ? data.events : [];
  const proj = data.projection ?? {};
  const usage = data.usage ?? {};

  const first = events[0]?.created_at ?? null;
  const last = events.at(-1)?.created_at ?? null;
  const totals = usage.totals ?? {};

  // 最大单次输入：只看有回报的尝试
  let maxIn = { tokens: null, id: "—", window: null };
  for (const a of attempts) {
    const v = a.usage?.input_tokens;
    if (typeof v === "number" && (maxIn.tokens === null || v > maxIn.tokens)) {
      maxIn = { tokens: v, id: a.id, window: a.call_target?.context_window ?? null };
    }
  }

  // 按部门 × 目的 × 状态
  const byPurpose = {};
  for (const a of attempts) {
    const k = a.purpose ?? "?";
    byPurpose[k] ??= { success: 0, failed: 0, cancelled: 0, other: 0, input: 0, output: 0 };
    const s = a.status ?? "?";
    if (s === "success") byPurpose[k].success++;
    else if (s === "failed") byPurpose[k].failed++;
    else if (s === "cancelled") byPurpose[k].cancelled++;
    else byPurpose[k].other++;
    byPurpose[k].input += a.usage?.input_tokens ?? 0;
    byPurpose[k].output += a.usage?.output_tokens ?? 0;
  }

  const failures = attempts
    .filter((a) => a.status && a.status !== "success")
    .map((a) => ({
      at: clockOf(a.created_at ?? a.started_at),
      department: a.department ?? "—",
      purpose: a.purpose ?? "—",
      step: a.step ?? "—",
      status: a.status,
      error: a.error ?? "—",
      errorType: a.diagnostics?.error_type ?? a.error_class ?? "—",
      input: a.usage?.input_tokens ?? null,
      durationMs: a.duration_ms ?? null,
      id: a.id,
    }));

  const types = {};
  for (const e of events) types[e.type ?? "?"] = (types[e.type ?? "?"] ?? 0) + 1;

  const keyEvents = [];
  for (const e of events) {
    if (!KEY_EVENTS.has(e.type)) continue;
    const lastOne = keyEvents.at(-1);
    if (lastOne && lastOne.type === e.type) { lastOne.n++; continue; }
    keyEvents.push({ at: clockOf(e.created_at), type: e.type, stop: e.stop_reason ?? "", id: e.event_id, n: 1 });
  }

  const compactions = Array.isArray(proj.compactions) ? proj.compactions : [];

  return {
    file: path,
    runId: data.run_id ?? proj.run_id ?? "—",
    status: proj.status ?? "—",
    stopReason: proj.stop_reason ?? "—",
    cycles: proj.cycle_count ?? "—",
    workItem: proj.work_item_id ?? "—",
    models: (usage.models ?? []).map((m) => m.key ?? m.label ?? "—"),
    window: first,
    last,
    wall: span(first, last),
    attempts: attempts.length,
    totals,
    departments: (usage.departments ?? []).map((d) => ({
      key: d.key ?? d.label ?? "—",
      attempts: d.attempts ?? 0,
      input: d.input_tokens ?? 0,
      output: d.output_tokens ?? 0,
      cache: d.cache_read_tokens ?? 0,
      total: d.total_tokens ?? 0,
      latencyMs: d.latency_ms ?? 0,
    })),
    byPurpose,
    failures,
    maxIn,
    compactions: compactions.length,
    compactionCovered: compactions.map((c) => c.checkpoint?.covered_through_event_id ?? "—"),
    keyEvents,
    types,
  };
}

const rows = files.map(load);

if (wantJson) {
  console.log(JSON.stringify(rows.length === 1 ? rows[0] : rows, null, 1));
  process.exit(0);
}

for (const r of rows) {
  const t = r.totals ?? {};
  console.log(`## ${r.file}`);
  console.log(`- 运行 ${r.runId} · 状态 ${r.status} · 停止原因 ${r.stopReason} · 轮次 ${r.cycles} · 事项 ${r.workItem}`);
  console.log(`- 墙钟 ${clockOf(r.window)} 至 ${clockOf(r.last)}（${r.wall}）· 尝试 ${r.attempts} 次 · 事件 ${Object.values(r.types).reduce((a, b) => a + b, 0)} 条`);
  console.log(`- 模型 ${r.models.join("、") || "—"}`);
  console.log(
    `- 合计 token ${num(t.total_tokens)}（输入 ${num(t.input_tokens)} / 输出 ${num(t.output_tokens)}）· 缓存读 ${num(t.cache_read_tokens)}（${pct(t.cache_read_tokens, t.input_tokens)}）· 延迟合计 ${dur(t.latency_ms)} · 费用 ${t.cost === null || t.cost === undefined ? "未报告" : t.cost}`
  );
  if (r.maxIn.tokens !== null) {
    const w = r.maxIn.window;
    const over = !w ? "" : r.maxIn.tokens > w ? `，配置窗口 ${num(w)}（超出 ${pct(r.maxIn.tokens - w, w)}）` : `，配置窗口 ${num(w)}（占 ${pct(r.maxIn.tokens, w)}）`;
    console.log(`- 最大单次输入 ${num(r.maxIn.tokens)}${over} · ${r.maxIn.id}`);
  }
  console.log();

  if (r.departments.length) {
    const head = ["部门", "尝试", "输入", "输出", "缓存读", "合计", "延迟"];
    const body = r.departments.map((d) => [
      d.key, String(d.attempts), num(d.input), num(d.output), `${num(d.cache)}（${pct(d.cache, d.input)}）`, num(d.total), dur(d.latencyMs),
    ]);
    const widths = head.map((h, i) => Math.max(vis(h), ...body.map((b) => vis(b[i]))));
    const line = (cells) => cells.map((c, i) => pad(c, widths[i])).join("  ");
    console.log(line(head));
    console.log(widths.map((n) => "-".repeat(n)).join("  "));
    for (const b of body) console.log(line(b));
    console.log();
  }

  const p = Object.entries(r.byPurpose);
  if (p.length) {
    console.log("按目的：" + p.map(([k, v]) => `${k} 成功 ${v.success}／失败 ${v.failed}／取消 ${v.cancelled}${v.other ? `／其他 ${v.other}` : ""}`).join("；"));
    console.log();
  }

  console.log(`压缩记录 ${r.compactions} 条${r.compactionCovered.length ? `（覆盖到 ${r.compactionCovered.join("、")}）` : ""}`);
  if (r.failures.length) {
    console.log();
    console.log(`失败与取消 ${r.failures.length} 次：`);
    const head = ["时间", "部门", "目的", "步", "状态", "错误", "错误类型", "输入 token", "耗时"];
    const body = r.failures.map((f) => [
      f.at, f.department, f.purpose, String(f.step), f.status, f.error, f.errorType, num(f.input), dur(f.durationMs),
    ]);
    const widths = head.map((h, i) => Math.max(vis(h), ...body.map((b) => vis(b[i]))));
    const line = (cells) => cells.map((c, i) => pad(c, widths[i])).join("  ");
    console.log(line(head));
    console.log(widths.map((n) => "-".repeat(n)).join("  "));
    for (const b of body) console.log(line(b));
  } else {
    console.log("失败与取消：无");
  }

  const show = r.keyEvents.filter((e) => !["model_stream_progress", "model_requested"].includes(e.type));
  if (show.length) {
    console.log();
    console.log(`关键事件 ${show.length} 条：` + show.map((e) => `${e.at} ${e.type}${e.n > 1 ? `×${e.n}` : ""}${e.stop ? `（${e.stop}）` : ""}`).join(" → "));
  }

  if (wantTypes) {
    console.log();
    console.log("事件种类：" + Object.entries(r.types).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join("、"));
  }
  console.log();
}
