// 外部来源按页阅读（工单 #238；网络与 MCP docs/design/network-and-mcp.md「调用显示」「结果、工件与证据」；
// 查询 evidence.external_source 的交换字段见应用层与接口层 docs/design/app-and-interface.md「查询清单」）：
// 一份外部来源的来源、最终地址、状态码与摘要值，以及正文按页切分与页码说明。
//
// 用 node --test 运行，不依赖服务与网络：组件文件按 CommonJS 转译以后加载，纯函数直接调用（与
// away-report-coverage.test.ts 的做法相同）。守 R2（按查询给出的字段显示来源、最终地址、状态码与摘要值）
// 与 R3（外部来源可以按页阅读）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import type { ExternalSourceEvidenceResult } from "../../src/renderer/src/api/generated/types.gen";
import { formatTime } from "../../src/renderer/src/views/project/labels.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
interface NodeModuleInternal {
  _compile(content: string, filename: string): void;
}

const React = require("react");
const globalScope = globalThis as Record<string, unknown>;
globalScope["React"] = React;

function loader(module: NodeJS.Module, filename: string) {
  const code = fs.readFileSync(filename, "utf8");
  const js = ts.transpileModule(code, {
    compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const internalModule = module as unknown as NodeModuleInternal;
  internalModule._compile(js, filename);
}
require.extensions[".tsx"] = loader;
require.extensions[".ts"] = loader;

interface SourcePage {
  page: number;
  pages: number;
  startLine: number;
  endLine: number;
  lines: string[];
}

const { LINES_PER_PAGE, contentLines, pageLabel, pageOf, sourceFields, sourceText } = require(
  "../../src/renderer/src/views/project/external-source.tsx",
) as {
  LINES_PER_PAGE: number;
  contentLines: (content: string) => string[];
  pageLabel: (view: SourcePage, totalLines: number) => string;
  pageOf: (content: string, totalLines: number, page: number, pageSize?: number) => SourcePage;
  sourceText: (source: string) => string;
  sourceFields: (data: ExternalSourceEvidenceResult) => {
    source: string;
    finalUrl: string;
    statusCode: string;
    contentHash: string;
    fetchedAt: string;
    totalLines: string;
  };
};

const HASH = "sha256:" + "b".repeat(64);

function lines(count: number): string {
  return Array.from({ length: count }, (_value, index) => `第 ${index + 1} 行`).join("\n");
}

test("正文按行切开：换行统一，末尾的一个换行不另算一行", () => {
  assert.deepEqual(contentLines("a\r\nb\rc"), ["a", "b", "c"]);
  assert.deepEqual(contentLines("a\nb\n"), ["a", "b"]);
  assert.deepEqual(contentLines(""), []);
});

test("按页切分：第一页、末页、页码夹在范围里、没有正文", () => {
  const content = lines(250);
  const first = pageOf(content, 250, 1);
  assert.equal(first.page, 1);
  assert.equal(first.pages, 2);
  assert.equal(first.startLine, 1);
  assert.equal(first.endLine, 200);
  assert.equal(first.lines.length, 200);
  assert.equal(first.lines[0], "第 1 行");
  assert.equal(first.lines[199], "第 200 行");

  const last = pageOf(content, 250, 2);
  assert.equal(last.startLine, 201);
  assert.equal(last.endLine, 250);
  assert.equal(last.lines.length, 50);
  assert.equal(last.lines[49], "第 250 行");

  assert.equal(pageOf(content, 250, 99).page, 2);
  assert.equal(pageOf(content, 250, -3).page, 1);
  assert.equal(pageOf(content, 250, 1, 100).pages, 3);
  assert.equal(pageOf(content, 250, 3, 100).endLine, 250);

  const empty = pageOf("", 0, 5);
  assert.deepEqual(empty, { page: 1, pages: 1, startLine: 0, endLine: 0, lines: [] });
});

test("页码说明写第几行到第几行、总共几行与第几页", () => {
  const content = lines(250);
  assert.equal(pageLabel(pageOf(content, 250, 1), 250), "第 1–200 行，共 250 行（第 1/2 页）");
  assert.equal(pageLabel(pageOf(content, 250, 2), 250), "第 201–250 行，共 250 行（第 2/2 页）");
  assert.equal(pageLabel(pageOf("", 0, 1), 0), "这份外部来源没有正文");
  assert.equal(LINES_PER_PAGE, 200);
});

test("来源字段按查询给出的写：来源、最终地址、状态码、摘要值、取得时间与总行数", () => {
  const data: ExternalSourceEvidenceResult = {
    source: "https://example.com/page",
    content_hash: HASH,
    fetched_at: "2026-11-01T02:03:04Z",
    total_lines: 250,
    content: lines(250),
    final_url: "https://example.com/final",
    status_code: 200,
    content_type: "text/plain",
  };
  const fields = sourceFields(data);
  assert.equal(fields.source, "https://example.com/page");
  assert.equal(fields.finalUrl, "https://example.com/final");
  assert.equal(fields.statusCode, "200");
  assert.equal(fields.contentHash, HASH);
  assert.equal(fields.totalLines, "250");
  assert.equal(fields.fetchedAt, formatTime("2026-11-01T02:03:04Z"));
});

test("MCP 的结果没有最终地址与状态码时照实写「未上报」，来源写服务器与工具名", () => {
  const fields = sourceFields({
    source: "mcp:time:echo",
    content_hash: HASH,
    fetched_at: "2026-11-01T02:03:04Z",
    total_lines: 1,
    content: "你好\n",
  });
  assert.equal(fields.finalUrl, "未上报");
  assert.equal(fields.statusCode, "未上报");
  assert.equal(fields.source, "服务器 time · 工具 echo");
  assert.equal(sourceText("https://example.com/page"), "https://example.com/page");
});
