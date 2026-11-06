// 工具与扩展页（原型 v13 的 ui/views/sys-tools.js，网络与 MCP docs/design/network-and-mcp.md「系统「工具与扩展」页」，工单 #239）：
// 只读汇总各项目最近的取回记录，与各项目在设置里写明的 MCP 服务器、最近一次状态与其中的工具。
// 浏览器工具、computer use 与只读观察者三块还没有接入，各自标出所属阶段。
// 数据取自 tools.registry；页面上写什么字都在 tools-logic.ts 里，这里只按它渲染。

import type { Capabilities, ToolsRegistryResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Block } from "../../shell/kit";
import { Empty, KeyValue, Loading, Table } from "../project/common";
import { type SnapshotState, useSnapshot } from "../project/use-snapshot";
import {
  PENDING_SECTIONS, TOOLS_QUERY, TOOLS_WORDING, fetchRows, mcpProjects, stageText,
} from "./tools-logic";

const VIEW_ID = "page.sys.tools";

export function ToolsPage(props: { app: ClientApp; capabilities: Capabilities }) {
  const listed = props.capabilities.queries.some((query) => query.name === TOOLS_QUERY);
  // 能力清单里没有这一条查询时不发查询：页面说「暂时不能列出」，不说「正在读取数据」
  const registry = useSnapshot<ToolsRegistryResult>(props.app, VIEW_ID, TOOLS_QUERY, {}, !listed);
  return (
    <div className="y10-sys-tools">
      {listed ? (
        <>
          <FetchBlock state={registry} />
          <McpBlock state={registry} />
        </>
      ) : (
        <Block title="工具登记">
          <p className="y10-note note">{TOOLS_WORDING.unavailable}</p>
        </Block>
      )}
      {PENDING_SECTIONS.map((section) => (
        <Block
          key={section.id}
          id={`tools-${section.id}`}
          title={section.title}
          subtitle={section.subtitle}
          data-testid={`tools-${section.id}`}
        >
          <p className="y10-note note" data-testid={`tools-stage-${section.id}`}>{stageText(section)}</p>
          <p className="y10-muted hint">{section.note}</p>
        </Block>
      ))}
    </div>
  );
}

// 网络取回：各项目最近的取回记录合成一张表（时间、地址、项目、结果），最近的在前
function FetchBlock(props: { state: SnapshotState<ToolsRegistryResult> }) {
  const rows = fetchRows(props.state.data);
  return (
    <Block id="tools-fetch" title="网络取回" subtitle="各项目最近的取回记录" data-testid="tools-fetch">
      <Loading state={props.state} />
      {props.state.error !== null ? (
        <p className="y10-note note" role="status">{TOOLS_WORDING.unreadable}：{props.state.error}</p>
      ) : null}
      {props.state.data !== null && rows.length === 0 ? <Empty text={TOOLS_WORDING.noFetchRecords} /> : null}
      {rows.length > 0 ? (
        <Table
          head={["时间", "地址", "项目", "结果"]}
          rows={rows.map((row) => [
            <span key="time">{row.time}</span>,
            <code key="url" className="y10-code">{row.url}</code>,
            <span key="project">{row.project}</span>,
            <span key="result">{row.result}</span>,
          ])}
        />
      ) : null}
    </Block>
  );
}

// MCP 工具：按项目分组，每个项目列出它写明的服务器；修改入口指向这个项目的设置页
function McpBlock(props: { state: SnapshotState<ToolsRegistryResult> }) {
  const projects = mcpProjects(props.state.data);
  return (
    <Block
      id="tools-mcp"
      title="MCP 工具"
      subtitle="各项目在设置里写明的服务器、可以使用的部门、最近一次状态与其中的工具"
      data-testid="tools-mcp"
    >
      <Loading state={props.state} />
      {props.state.error !== null ? (
        <p className="y10-note note" role="status">{TOOLS_WORDING.unreadable}：{props.state.error}</p>
      ) : null}
      {props.state.data !== null && projects.length === 0 ? <Empty text={TOOLS_WORDING.noMcpServers} /> : null}
      {projects.map((project) => (
        <section
          className="y10-mcp-project"
          key={project.projectId}
          data-testid={`tools-mcp-project-${project.projectId}`}
        >
          <header className="y10-mcp-head y10-row">
            <h3 className="y10-h3 sub">{project.name}</h3>
            <a
              className="y10-btn btn"
              href={project.settingsHash}
              data-testid={`tools-mcp-settings-${project.projectId}`}
            >
              {TOOLS_WORDING.settingsLink}
            </a>
          </header>
          {project.servers.map((server) => (
            <section
              className="y10-mcp"
              key={server.name}
              data-testid={`tools-mcp-server-${project.projectId}-${server.name}`}
            >
              <h4 className="y10-h3 sub">{server.name}</h4>
              <KeyValue
                items={[
                  ["可以使用的部门", server.departments === "" ? "没有写明" : server.departments],
                  [
                    "最近一次状态",
                    <span key="status">
                      {server.status}
                      {server.statusAt === "" ? null : <span className="y10-muted hint"> · {server.statusAt}</span>}
                    </span>,
                  ],
                ]}
              />
              {server.staleNote === "" ? null : <p className="y10-note note">{server.staleNote}</p>}
              {server.tools.length > 0 ? (
                <Table
                  head={["工具", "说明"]}
                  rows={server.tools.map((tool) => [
                    <code key="name" className="y10-code">{tool.name}</code>,
                    <span key="description">{tool.description}</span>,
                  ])}
                />
              ) : (
                <p className="y10-note note">{server.toolsNote}</p>
              )}
            </section>
          ))}
        </section>
      ))}
    </Block>
  );
}
