// 工具与扩展页的纯计算（工单 #239）。验收第 1、2 条：取回记录与 MCP 服务器的显示跟随
// tools.registry 的结果，修改入口指向项目设置页；其余三块标出所属阶段，页面上没有开发者措辞。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  ToolsRegistryResult,
  ToolsRegistryServerView,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  PENDING_SECTIONS,
  TOOLS_QUERY,
  TOOLS_WORDING,
  fetchResultText,
  fetchRows,
  mcpProjects,
  pageWording,
  probeStaleNote,
  probeStatusText,
  projectSettingsHash,
  stageText,
} from "../../src/renderer/src/views/system/tools-logic.ts";

// 一台服务器的替身：字段与生成的 ToolsRegistryServerView 合同一致
function server(overrides: Partial<ToolsRegistryServerView> = {}): ToolsRegistryServerView {
  return {
    name: "time",
    transport: "stdio",
    departments: ["product", "engineering"],
    tool_snapshot: null,
    config_digest: "digest-a",
    probe: {
      finished_at: null,
      ok: null,
      error: null,
      config_digest: "",
    },
    ...overrides,
  };
}

// 取回与 MCP 各一次的登记结果：两个项目各有不同的 MCP 服务器与一次取回
function registry(): ToolsRegistryResult {
  return {
    projects: [
      {
        project_id: "p-1",
        name: "回声工具",
        mcp_servers: {
          time: server({
            name: "time",
            departments: ["product", "engineering", "quality"],
            config_digest: "digest-a",
            probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: true, error: null, config_digest: "digest-a" },
            tool_snapshot: { tools: [
              { name: "echo", description: "回显给定的文本" },
              { name: "now", description: "现在的本机时间" },
            ] },
          }),
        },
        fetch_records: [
          { at: "2026-11-03T05:00:00+00:00", url: "http://127.0.0.1:9/echo", ok: true, error: null },
          { at: "2026-11-03T03:00:00+00:00", url: "http://127.0.0.1:9/old", ok: false, error: "连接被拒绝" },
        ],
      },
      {
        project_id: "p-2",
        name: "文本整理",
        mcp_servers: {
          search: server({
            name: "search",
            transport: "http",
            departments: ["product"],
            config_digest: "digest-b",
          }),
        },
        fetch_records: [
          { at: "2026-11-03T04:00:00+00:00", url: "http://127.0.0.1:9/notes", ok: true, error: null },
        ],
      },
    ],
  };
}

test("取回记录合成一张表：最近的在前，带项目名与结果", () => {
  const rows = fetchRows(registry());
  assert.deepEqual(rows.map((row) => [row.url, row.project, row.result]), [
    ["http://127.0.0.1:9/echo", "回声工具", "成功"],
    ["http://127.0.0.1:9/notes", "文本整理", "成功"],
    ["http://127.0.0.1:9/old", "回声工具", "失败"],
  ]);
  // 时间原样带出，页面按它排版
  assert.deepEqual(rows.map((row) => row.at), [
    "2026-11-03T05:00:00+00:00",
    "2026-11-03T04:00:00+00:00",
    "2026-11-03T03:00:00+00:00",
  ]);
  assert.ok(rows.every((row) => row.time !== ""));
});

test("取回记录的空态与没有结果时的说法", () => {
  assert.deepEqual(fetchRows(null), []);
  assert.deepEqual(fetchRows({ projects: [] }), []);
  assert.deepEqual(fetchRows({ projects: [{ project_id: "p", name: "空", mcp_servers: {} }] }), []);
  assert.equal(fetchResultText({ ok: true }), TOOLS_WORDING.fetchSucceeded);
  assert.equal(fetchResultText({ ok: false }), TOOLS_WORDING.fetchFailed);
  assert.equal(fetchResultText({}), TOOLS_WORDING.fetchUnknown);
});

test("MCP 服务器按项目分组：没有服务器的项目不出现，部门用显示名", () => {
  const projects = mcpProjects(registry());
  assert.deepEqual(projects.map((project) => [project.name, project.servers.length]), [
    ["回声工具", 1],
    ["文本整理", 1],
  ]);
  assert.deepEqual(projects[0].servers[0].departments, "产品、工程、质检");
  assert.deepEqual(projects[1].servers[0].departments, "产品");
  assert.equal(projects[0].servers[0].name, "time");
  // 修改入口：项目设置页
  assert.deepEqual(projects.map((project) => project.settingsHash), [
    "#/p/p-1/settings",
    "#/p/p-2/settings",
  ]);
  // 只有服务器的项目才列：空登记与没有项目时都没有这一块的内容
  assert.deepEqual(mcpProjects(null), []);
  assert.deepEqual(mcpProjects({ projects: [{ project_id: "p", name: "空", mcp_servers: {} }] }), []);
});

test("最近一次状态：没有探测过、失败、成功带工具数", () => {
  assert.equal(probeStatusText(server()), TOOLS_WORDING.neverProbed);
  // 有探测时间而没有成功（失败）时说失败
  const failed = server({ probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: false, error: "启动失败", config_digest: "digest-a" } });
  assert.equal(probeStatusText(failed), TOOLS_WORDING.probeFailed);
  const succeeded = registry().projects[0].mcp_servers.time;
  assert.equal(probeStatusText(succeeded), "成功 · 2 个工具");
  // 工具数与设置里的工具清单快照一致
  const view = mcpProjects(registry())[0].servers[0];
  assert.deepEqual(view.tools.map((tool) => tool.name), ["echo", "now"]);
  assert.equal(view.tools[0].description, "回显给定的文本");
  assert.equal(view.toolsNote, "");
  assert.ok(view.statusAt !== "");
});

test("还没有读取过工具清单时，工具表的位置写那句话", () => {
  const view = mcpProjects(registry())[1].servers[0];
  assert.deepEqual(view.tools, []);
  assert.equal(view.toolsNote, TOOLS_WORDING.toolsNotRead);
  assert.equal(view.status, TOOLS_WORDING.neverProbed);
  assert.equal(view.statusAt, "");
});

test("设置改过以后那一次结果已经过期，成功的探测才提示", () => {
  const stale = server({
    config_digest: "digest-new",
    probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: true, error: null, config_digest: "digest-old" },
  });
  assert.equal(probeStaleNote(stale), TOOLS_WORDING.probeStale);
  // 摘要相同、没有摘要、探测失败时都不这么写
  assert.equal(probeStaleNote(server({
    config_digest: "digest-a",
    probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: true, error: null, config_digest: "digest-a" },
  })), "");
  assert.equal(probeStaleNote(server({
    config_digest: "",
    probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: true, error: null, config_digest: "digest-a" },
  })), "");
  assert.equal(probeStaleNote(server({
    config_digest: "digest-new",
    probe: { finished_at: "2026-11-03T06:00:00+00:00", ok: false, error: "启动失败", config_digest: "digest-old" },
  })), "");
});

test("其余三块各标出所属阶段：浏览器工具在阶段三，computer use 与只读观察者在阶段四", () => {
  assert.deepEqual(PENDING_SECTIONS.map((section) => section.title), ["浏览器工具", "computer use", "只读观察者"]);
  assert.deepEqual(PENDING_SECTIONS.map((section) => section.stage), ["阶段三", "阶段四", "阶段四"]);
  assert.equal(stageText(PENDING_SECTIONS[1]), "所属阶段：阶段四");
  // 过期的「虚拟屏幕上的动作」这个说法不再出现
  for (const section of PENDING_SECTIONS) {
    assert.ok(!`${section.title}${section.subtitle}${section.note}`.includes("虚拟屏幕"), section.title);
  }
});

test("页面上写出的字里没有内部标识与开发者措辞", () => {
  const texts = pageWording();
  assert.ok(texts.length > 0);
  const internal = [
    TOOLS_QUERY, "config_digest", "tool_snapshot", "fetch_records", "mcp_servers", "server_info",
    "tool_server_probe_finished", "mcp_servers.save", "tool_server.probe", "stdio", "streamable",
    "Stage", "project_id", "README", "TODO",
  ];
  for (const text of texts) {
    for (const word of internal) {
      assert.ok(!text.includes(word), `「${text}」里出现了内部标识 ${word}`);
    }
  }
});

test("修改入口的地址按项目标识给出", () => {
  assert.equal(projectSettingsHash("proj-9"), "#/p/proj-9/settings");
});
