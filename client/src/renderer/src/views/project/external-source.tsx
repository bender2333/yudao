// 外部来源按页阅读（网络与 MCP docs/design/network-and-mcp.md「调用显示」「结果、工件与证据」；
// 读取已保存的外部来源由 #1171 的查询 evidence.external_source 提供，工单 #238）：
// 页面按工件引用读一份取回或 MCP 调用的结果，写出它的来源、最终地址、状态码与摘要值，正文按页显示。
//
// 分页与取值的文字都在这个文件的纯函数里，客户端单元测试直接调用；组件只做取数与排版。

import { useState } from "react";
import type { ExternalSourceEvidenceResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { readFailureText } from "../../contract/read-failure";
import type { ExternalSourceRefView } from "./action-table.ts";
import { Empty, KeyValue } from "./common";
import { formatTime } from "./labels";
import { useSnapshot } from "./use-snapshot";

// 一页的行数：正文按行保存，阅读时一页给这么多行
export const LINES_PER_PAGE = 200;

// 一页正文：第几页、共几页、这一页的首末行号（从 1 起）与这一页的行
export interface SourcePage {
  page: number;
  pages: number;
  startLine: number;
  endLine: number;
  lines: string[];
}

// 正文按行切开：换行统一成 \n，末尾的一个换行不另算一行（与服务端 total_lines 的算法一致）
export function contentLines(content: string): string[] {
  if (content === "") {
    return [];
  }
  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  if (lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

// 一页正文：页码夹在 1 到总页数之间；没有正文时只有一页、行号为空
export function pageOf(content: string, totalLines: number, page: number, pageSize: number = LINES_PER_PAGE): SourcePage {
  const total = Number.isFinite(totalLines) && totalLines > 0 ? Math.trunc(totalLines) : 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const wanted = Number.isFinite(page) ? Math.trunc(page) : 1;
  const current = Math.min(Math.max(1, wanted), pages);
  if (total === 0) {
    return { page: 1, pages: 1, startLine: 0, endLine: 0, lines: [] };
  }
  const startLine = (current - 1) * pageSize + 1;
  const endLine = Math.min(current * pageSize, total);
  return {
    page: current,
    pages,
    startLine,
    endLine,
    lines: contentLines(content).slice(startLine - 1, endLine),
  };
}

// 页码说明：第几行到第几行、总共几行、第几页
export function pageLabel(view: SourcePage, totalLines: number): string {
  if (view.startLine === 0) {
    return "这份外部来源没有正文";
  }
  const total = Number.isFinite(totalLines) && totalLines > 0 ? Math.trunc(totalLines) : 0;
  return `第 ${view.startLine}–${view.endLine} 行，共 ${total.toLocaleString("zh-CN")} 行（第 ${view.page}/${view.pages} 页）`;
}

// 来源的写法：取回的来源是地址，原样写；MCP 的来源在应用层记成 mcp:服务器:工具，
// 页面上写成服务器与工具的名称，不写这个内部前缀
export function sourceText(source: string): string {
  const prefix = "mcp:";
  if (source.startsWith(prefix)) {
    const rest = source.slice(prefix.length);
    const separator = rest.indexOf(":");
    if (separator > 0) {
      return `服务器 ${rest.slice(0, separator)} · 工具 ${rest.slice(separator + 1)}`;
    }
  }
  return source;
}

// 来源字段的文字：来源、最终地址、状态码、摘要值、取得时间与总行数。缺的值照实写「未上报」
export interface SourceFields {
  source: string;
  finalUrl: string;
  statusCode: string;
  contentHash: string;
  fetchedAt: string;
  totalLines: string;
}

export function sourceFields(data: ExternalSourceEvidenceResult): SourceFields {
  return {
    source: sourceText(data.source),
    finalUrl: data.final_url ?? "未上报",
    statusCode: data.status_code === null || data.status_code === undefined ? "未上报" : String(data.status_code),
    contentHash: data.content_hash,
    fetchedAt: formatTime(data.fetched_at),
    totalLines: data.total_lines.toLocaleString("zh-CN"),
  };
}

// 一份外部来源：按引用读取，写出来源字段与正文；正文按页显示，翻页只改这一处的页码
export function ExternalSource(props: { app: ClientApp; source: ExternalSourceRefView }) {
  const [page, setPage] = useState(1);
  const state = useSnapshot<ExternalSourceEvidenceResult>(
    props.app,
    `page.external.${props.source.eventId}.${props.source.contentHash}`,
    "evidence.external_source",
    {
      event_id: props.source.eventId,
      kind: props.source.kind,
      content_hash: props.source.contentHash,
      path: props.source.path,
      media_type: props.source.mediaType ?? undefined,
    },
    false,
  );
  if (state.data === null) {
    return (
      <p className="y10-note note">
        {state.error === null ? "正在读取外部来源" : readFailureText(state.error)}
      </p>
    );
  }
  const data = state.data;
  const view = pageOf(data.content, data.total_lines, page);
  const fields = sourceFields(data);
  return (
    <div className="y10-external-source">
      <KeyValue
        items={[
          ["来源", fields.source],
          ["最终地址", fields.finalUrl],
          ["状态码", fields.statusCode],
          ["摘要值", fields.contentHash],
          ["取得时间", fields.fetchedAt],
          ["总行数", fields.totalLines],
        ]}
      />
      {view.lines.length === 0 ? (
        <Empty text="这份外部来源没有正文" />
      ) : (
        <pre className="y10-pre raw y10-external-content">{view.lines.join("\n")}</pre>
      )}
      <div className="y10-external-pager">
        <button
          type="button"
          className="y10-btn small"
          disabled={view.page <= 1}
          onClick={() => setPage(view.page - 1)}
        >
          上一页
        </button>
        <span className="y10-note note">{pageLabel(view, data.total_lines)}</span>
        <button
          type="button"
          className="y10-btn small"
          disabled={view.page >= view.pages}
          onClick={() => setPage(view.page + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
