#!/usr/bin/env node
// 读 run 导出（run.export 一类文件），打印一次试用的读数。
// 用法：node readout.mjs <导出文件> [更多导出] [--json] [--types]
// 只用 Node 内置模块。读数的计算在 records.mjs，这里只负责命令行与文字排版；其他脚本可以 import 这里导出的函数。

import { pathToFileURL } from "node:url";
import { readExport, dur, num, pct, vis, pad } from "./records.mjs";

export { readExport, summarize, loadExport, compareConfigs } from "./records.mjs";

const cost = (v) => (v === null || v === undefined ? "未报告" : v);
const table = (head, body) => {
  const widths = head.map((h, i) => Math.max(vis(h), ...body.map((b) => vis(b[i]))));
  const line = (cells) => cells.map((c, i) => pad(c, widths[i])).join("  ");
  return [line(head), widths.map((n) => "-".repeat(n)).join("  "), ...body.map(line)].join("\n");
};

export function formatReadout(r, { types = false } = {}) {
  const out = [];
  const t = r.totals ?? {};
  const ev = r.events;
  out.push(`## ${r.file}`);
  out.push(`- 运行 ${r.runId ?? "—"} · 状态 ${r.status ?? "—"} · 停止原因 ${r.stopReason ?? "—"} · 轮次 ${r.cycles ?? "—"} · 事项 ${r.workItem ?? "—"}`);
  out.push(`- 事件窗口 ${ev.first?.at ?? "—"}（位置 ${ev.first?.position ?? "—"}，${ev.first?.id ?? "—"}）至 ${ev.last?.at ?? "—"}（位置 ${ev.last?.position ?? "—"}，${ev.last?.id ?? "—"}）`);
  out.push(`- 墙钟 ${dur(ev.wallMs)}（${ev.wallMs ?? "—"} 毫秒）· 事件 ${ev.count} 条 · 尝试 ${r.attempts.count} 次（${Object.entries(r.attempts.byStatus).map(([k, v]) => `${k} ${v}`).join("、") || "—"}）`);
  out.push(`- 步骤时间：尝试首尾跨度 ${dur(r.attempts.spanMs)} · 各次耗时相加 ${dur(r.attempts.busyMs)}（并发时可超过跨度）`);
  if (r.terminal) out.push(`- 结束事件 ${r.terminal.type} ${r.terminal.at}（${r.terminal.id}，${r.terminal.stopReason ?? "无停止原因"}）`);
  for (const d of r.deliveryAccepted) out.push(`- 交付收下 ${d.at}（${d.id}）`);
  out.push(`- 模型 ${r.models.join("、") || "—"}`);
  out.push(
    `- 合计 token ${num(t.total_tokens)}（输入 ${num(t.input_tokens)} / 输出 ${num(t.output_tokens)}）· 缓存读 ${num(t.cache_read_tokens)}（${pct(t.cache_read_tokens, t.input_tokens)}）· 延迟合计 ${dur(t.latency_ms)} · 费用 ${cost(t.cost)}`
  );
  if (r.maxIn) {
    const m = r.maxIn;
    out.push(`- 最大单次输入 ${num(m.tokens)}（${m.department}/${m.purpose}，${m.status}，该次窗口 ${num(m.window)}，占 ${pct(m.tokens, m.window)}）· ${m.attemptId}`);
  }
  if (r.maxRatio && r.maxRatio.attemptId !== r.maxIn?.attemptId) {
    const m = r.maxRatio;
    out.push(`- 窗口占比最高 ${pct(m.tokens, m.window)}：输入 ${num(m.tokens)} / 窗口 ${num(m.window)}（${m.department}/${m.purpose}，${m.status}）· ${m.attemptId}`);
  }
  if (r.overWindow) out.push(`- 输入超过该次窗口的尝试 ${r.overWindow} 次`);
  out.push("");

  if (r.departments.length) {
    out.push(table(
      ["部门", "尝试", "输入", "输出", "缓存读", "合计", "延迟", "费用"],
      r.departments.map((d) => [d.key, num(d.attempts), num(d.input), num(d.output), `${num(d.cache)}（${pct(d.cache, d.input)}）`, num(d.total), dur(d.latencyMs), String(cost(d.cost))]),
    ));
    out.push("");
  }

  if (r.configs.length) {
    out.push("配置（部门/目的 × 上游模型 × 协议 × 窗口 × 输出上限；别名是本地名字）：");
    out.push(table(
      ["部门/目的", "上游模型", "本地别名", "回报的实际模型", "协议", "窗口", "输出上限", "档位", "尝试"],
      r.configs.map((c) => [`${c.department}/${c.purpose}`, c.requested_model ?? "未知", c.model_id ?? "未知", c.actual_models.join("、") || "未回报", c.protocol ?? "未知", num(c.context_window), num(c.max_output_tokens), c.requested_tier ?? "—", String(c.attempts)]),
    ));
    out.push("");
  }

  if (r.deptPurpose.length) {
    out.push("按部门/目的：" + r.deptPurpose.map((v) => `${v.key} 成功 ${v.success}／失败 ${v.failed}／取消 ${v.cancelled}${v.running ? `／进行中 ${v.running}` : ""}${v.other ? `／其他 ${v.other}` : ""}（输入 ${num(v.input)}，输出 ${num(v.output)}${v.unreported ? `，${v.unreported} 次未回报用量` : ""}）`).join("；"));
    out.push("");
  }

  const c = r.compaction;
  out.push(`压缩：请求 ${c.logicalCalls} 个（${c.logicalCallsSucceeded} 个得到成功响应），尝试 ${c.attempts} 次（响应成功 ${c.responseSuccess}／失败 ${c.responseFailed}${c.responseOther ? `／其他 ${c.responseOther}` : ""}）；检查点事件 ${c.checkpointEvents} 条，投影记录 ${c.projectionRecords} 条${c.coveredThrough.length ? `（覆盖到 ${c.coveredThrough.slice(0, 3).join("、")}${c.coveredThrough.length > 3 ? ` 等 ${c.coveredThrough.length} 个` : ""}）` : ""}`);

  if (r.failures.length) {
    out.push("");
    out.push(`失败、取消与未完成 ${r.failures.length} 次：`);
    out.push(table(
      ["时间", "部门", "目的", "步", "状态", "错误", "错误类型", "输入 token", "耗时", "上下文事件"],
      r.failures.map((f) => [f.at ?? "—", f.department ?? "—", f.purpose ?? "—", String(f.step ?? "—"), f.status, String(f.error ?? "—"), f.errorType ?? "—", num(f.input), dur(f.durationMs), f.contextEventId ?? "—"]),
    ));
  } else {
    out.push("失败与取消：无");
  }

  const show = r.keyEvents.filter((e) => !["model_stream_progress", "model_requested"].includes(e.type));
  if (show.length) {
    out.push("");
    out.push(`关键事件 ${show.length} 组：` + show.map((e) => `${e.at ?? "—"} ${e.type}${e.n > 1 ? `×${e.n}` : ""}${e.stop ? `（${e.stop}）` : ""}[${e.id}]`).join(" → "));
  }

  if (r.inconsistencies.length) {
    out.push("");
    out.push("数字矛盾：" + r.inconsistencies.map((i) => `${i.code}：${i.detail}`).join("；"));
  }

  if (types) {
    out.push("");
    out.push("事件种类：" + Object.entries(r.types).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join("、"));
  }
  return out.join("\n");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argv = process.argv.slice(2);
  const files = argv.filter((a) => !a.startsWith("--"));
  if (!files.length) {
    console.error("用法：node readout.mjs <run.export> [更多导出] [--json] [--types]");
    process.exit(1);
  }
  const rows = files.map(readExport);
  if (argv.includes("--json")) {
    console.log(JSON.stringify(rows.length === 1 ? rows[0] : rows, null, 1));
  } else {
    for (const r of rows) console.log(formatReadout(r, { types: argv.includes("--types") }) + "\n");
  }
}
