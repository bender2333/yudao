// 动作与回执表格的列与内容（工单 #655、#658）：「登记名」一列按 ADR-0038 删除命令登记以后
// 恒为「没有回执」，表里不再有这一列；「命令」一列显示动作实际执行的命令原文。
//
// 取回与 MCP 调用的行（工单 #238，网络与 MCP docs/design/network-and-mcp.md「调用显示」）：
// 类型、目标、状态（含被拒绝与结果未知）、耗时、结果摘要、外部来源工件的链接与交还给模型的内容；
// 行的文字里不出现 fetch_url、mcp__服务器__工具、refused 这类内部标识。
// 守 R3（页面显示取回与 MCP 调用的状态与结果）与 R2（回执与 evidence.external_source 的交换字段按查询给出的读）。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  actionCells,
  actionKind,
  actionRow,
  externalSourceRef,
  formatMilliseconds,
  returnedText,
  toolOutput,
} from "../../src/renderer/src/views/project/action-table.ts";
import type { ActionReceipt, ActionView, FetchReceipt } from "../../src/renderer/src/api/generated/types.gen.ts";

const HASH = "sha256:" + "a".repeat(64);
const SOURCE_REF = { kind: "external_source", content_hash: HASH, path: `run_demo/aa/${"a".repeat(64)}`, media_type: "text/plain" };

function receipt(overrides: Partial<ActionReceipt> = {}): ActionReceipt {
  return {
    args: {},
    ok: true,
    error: null,
    output_ref: null,
    event_id: "evt_1",
    created_at: "2026-10-22T00:00:00Z",
    ...overrides,
  };
}

function fetchReceipt(overrides: Partial<FetchReceipt> = {}): FetchReceipt {
  return {
    final_url: "https://example.com/final",
    status_code: 200,
    content_type: "text/plain",
    bytes: 1234,
    download_truncated: false,
    content_hash: HASH,
    ref: SOURCE_REF,
    redirects: [],
    duration_ms: 35,
    ...overrides,
  };
}

function action(overrides: Partial<ActionView> = {}): ActionView {
  return {
    action_id: "a_1",
    tool: "bash",
    department: "engineering",
    status: "completed",
    activation_id: null,
    step_id: null,
    input_version: null,
    prompt_version: null,
    created_at: "2026-10-22T00:00:00Z",
    receipt: receipt(),
    ...overrides,
  };
}

test("命令一列显示动作实际执行的命令原文", () => {
  const cells = actionCells(action({
    receipt: receipt({ args: { command: "python -m pytest" } }),
  }));
  assert.equal(cells[1], "python -m pytest");
});

test("没有命令的动作在命令一列留空", () => {
  const cells = actionCells(action({ tool: "read_file", receipt: receipt({ args: { path: "a.py" } }) }));
  assert.equal(cells[1], "");
  assert.equal(actionCells(action({ receipt: null }))[1], "");
});

test("结果按回执写：成功、失败与没有回执", () => {
  assert.equal(actionCells(action({ receipt: receipt({ ok: true }) }))[4], "成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "命令没有成功" }) }))[4], "命令没有成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "" }) }))[4], "失败");
  assert.equal(actionCells(action({ receipt: null }))[4], "没有回执");
});

test("输出引用有的时候写「有（见原始事件）」", () => {
  assert.equal(actionCells(action({ receipt: receipt({ output_ref: { path: "out.txt" } }) }))[5], "有（见原始事件）");
  assert.equal(actionCells(action({ receipt: receipt() }))[5], "无");
});

test("没有部门的动作不写「未知部门」", () => {
  assert.equal(actionCells(action({ department: null }))[2], "");
});

test("动作的种类只由工具名判断：取回、MCP 调用与其余工具", () => {
  assert.equal(actionKind(action({ tool: "fetch_url" })), "fetch");
  assert.equal(actionKind(action({ tool: "mcp__time__echo" })), "mcp");
  assert.equal(actionKind(action({ tool: "read_file" })), "other");
});

test("取回的动作行：类型、目标、状态、耗时、结果与外部来源", () => {
  const row = actionRow(action({
    tool: "fetch_url",
    receipt: receipt({ args: { url: "https://example.com/page" }, fetch: fetchReceipt() }),
  }));
  assert.equal(row.kind, "fetch");
  assert.equal(row.typeName, "网络取回");
  assert.equal(row.target, "https://example.com/page");
  assert.equal(row.statusName, "已完成");
  assert.equal(row.durationText, "35 毫秒");
  assert.equal(row.summaryText, "HTTP 200 · 1,234 字节");
  assert.deepEqual(row.external, {
    eventId: "evt_1",
    kind: "external_source",
    contentHash: HASH,
    path: SOURCE_REF.path,
    mediaType: "text/plain",
  });
  assert.equal(row.returnedText, "");
});

test("MCP 调用的动作行：目标写服务器与工具名，别名不写到页面上", () => {
  const row = actionRow(action({
    tool: "mcp__time__echo",
    receipt: receipt({ args: { text: "你好" } }),
  }), {
    output: { server: "time", tool: "echo", duration_ms: 12, ref: SOURCE_REF },
  });
  assert.equal(row.kind, "mcp");
  assert.equal(row.typeName, "MCP 调用");
  assert.equal(row.target, "time · echo");
  assert.equal(row.durationText, "12 毫秒");
  assert.equal(row.summaryText, "成功");
  assert.equal(row.external?.contentHash, HASH);
  assert.ok(!JSON.stringify([row.typeName, row.target, row.statusName, row.durationText, row.summaryText]).includes("mcp__"));
});

test("被拒绝的动作写「被拒绝」与原因，不给外部来源的链接", () => {
  const reason = "地址指向 Yudao 自己的服务，拒绝取回";
  const row = actionRow(action({
    tool: "fetch_url",
    status: "refused",
    receipt: receipt({ args: { url: "http://127.0.0.1:8765/" }, ok: false, error: reason, refused: true, refused_reason: reason }),
  }));
  assert.equal(row.statusName, "被拒绝");
  assert.equal(row.summaryText, reason);
  assert.equal(row.external, null);
  assert.equal(row.durationText, "未上报");
});

test("结果未知的动作写结果未知与交还给模型的内容", () => {
  const row = actionRow(action({ tool: "mcp__time__echo", status: "unknown", receipt: null }), {
    returned: JSON.stringify({ ok: false, output: null, error: "执行被中断，结果未知，由模型决定是否重新调用。" }),
  });
  assert.equal(row.statusName, "结果未知");
  assert.equal(row.returnedText, "执行被中断，结果未知，由模型决定是否重新调用。");
  assert.equal(row.durationText, "未上报");
  assert.equal(row.summaryText, "没有回执");
});

test("交还的内容解析不出 JSON 时原样显示；为空时不写", () => {
  assert.equal(returnedText("服务器返回了一段不是 JSON 的说明"), "服务器返回了一段不是 JSON 的说明");
  assert.equal(returnedText(null), "");
  assert.equal(returnedText(""), "");
});

test("外部来源的引用只认外部来源工件与完整的四项", () => {
  assert.equal(externalSourceRef(SOURCE_REF, "evt_1")?.contentHash, HASH);
  assert.equal(externalSourceRef(SOURCE_REF, ""), null);
  assert.equal(externalSourceRef({ ...SOURCE_REF, kind: "screenshot" }, "evt_1"), null);
  assert.equal(externalSourceRef({ ...SOURCE_REF, content_hash: "sha256:short" }, "evt_1"), null);
  assert.equal(externalSourceRef(null, "evt_1"), null);
});

test("工具结果工件里的结果对象取出来；没有时不猜", () => {
  assert.deepEqual(toolOutput({ output: { server: "time" } }), { server: "time" });
  assert.equal(toolOutput({ output: "文本" }), null);
  assert.equal(toolOutput(null), null);
});

test("耗时按毫秒写中文", () => {
  assert.equal(formatMilliseconds(0), "0 毫秒");
  assert.equal(formatMilliseconds(999), "999 毫秒");
  assert.equal(formatMilliseconds(1500), "1.5 秒");
  assert.equal(formatMilliseconds(90_000), "2 分");
  assert.equal(formatMilliseconds(Number.NaN), "未上报");
});

test("取回与 MCP 调用行的文字里没有英文内部标识", () => {
  const rows = [
    actionRow(action({ tool: "fetch_url", receipt: receipt({ args: { url: "https://example.com/page" }, fetch: fetchReceipt() }) })),
    actionRow(action({ tool: "mcp__time__echo", receipt: receipt() }), { output: { server: "time", tool: "echo", duration_ms: 5, ref: SOURCE_REF } }),
    actionRow(action({ tool: "fetch_url", status: "refused", receipt: receipt({ ok: false, refused: true, refused_reason: "拒绝" }) })),
    actionRow(action({ tool: "mcp__time__echo", status: "unknown", receipt: null }), { returned: "执行被中断" }),
  ];
  const text = rows.map((row) => [row.typeName, row.target, row.statusName, row.durationText, row.summaryText, row.returnedText].join(" ")).join(" ");
  for (const word of ["fetch_url", "mcp__", "refused", "returned", "duration_ms", "status_code", "external_source", "completed", "unknown"]) {
    assert.equal(text.includes(word), false, `页面文字里出现了 ${word}`);
  }
});
