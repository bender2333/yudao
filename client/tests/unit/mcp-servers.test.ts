// 「MCP 服务器」一节的纯计算（工单 #237）：保存参数的组装、表单的必填与格式、整份文档与工具清单快照的
// 保留、凭据名称与状态、列表与探测结果的说法。页面只按这些函数的取值渲染，单元测试直接核对它们。
// 守 R1（第一环的合同：客户端交给 mcp_servers.save 与 tool_server.probe 的参数、页面上写给人看的说法）。
// 用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";

import type {
  McpCredentialStatusView, McpProbeResultView, McpServerSettingView,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  MCP_DEFAULTS, configurationSignature, credentialNames, credentialNamesOfSettings, credentialState,
  credentialVersion, departmentsText, draftChangesConfiguration, draftIssue, draftOfServer, emptyDraft,
  mcpDocumentPayload, mcpServerPayload, probeFailureText, probeIsStale, probeOf, probeStateLabel,
  saveNotice, sectionNote, serverInfoText, snapshotTools, splitLines, toolCountText, toolRows, transportLabel,
  variableDrafts, variablesPayload,
} from "../../src/renderer/src/views/project/mcp-servers-logic.ts";
import { credentialStatusLabel } from "../../src/renderer/src/views/models/model-logic.ts";

function server(overrides: Partial<McpServerSettingView> = {}): McpServerSettingView {
  return {
    name: "time",
    transport: "stdio",
    command: "uvx",
    args: ["mcp-server-time"],
    env: { API_KEY: { kind: "credential", value: "", credential_ref: "MCP_TIME_KEY" } },
    url: "",
    headers: {},
    departments: ["product", "engineering", "quality"],
    startup_timeout_sec: 60,
    call_timeout_sec: 120,
    output_limit: 20000,
    tool_snapshot: null,
    config_digest: "digest-a",
    ...overrides,
  };
}

function probe(overrides: Partial<McpProbeResultView> = {}): McpProbeResultView {
  return {
    server_name: "time",
    status: "ok",
    config_digest: "digest-a",
    server_info: { name: "yudao-test-stdio", version: "0.0.1", protocol_version: "2026-07-28" },
    tools: [
      { name: "echo", description: "回显文本", hints: null },
      { name: "big", description: "大结果", hints: { read_only_hint: true, destructive_hint: false } },
    ],
    error: "",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 传输与表单的必填
// ---------------------------------------------------------------------------

test("传输在页面上写成本机进程或 HTTP 服务，不写内部取值以外的说法", () => {
  assert.equal(transportLabel("stdio"), "本机进程（stdio）");
  assert.equal(transportLabel("http"), "HTTP 服务（streamable HTTP）");
});

test("表单的必填与格式给出中文的说法，按钮据此可用", () => {
  const base = emptyDraft(["product", "engineering"]);
  assert.equal(draftIssue(base), "填写名称");

  assert.equal(draftIssue({ ...base, name: "Time" }), "名称只能用小写字母、数字与连字符，并以字母或数字开头");
  assert.equal(draftIssue({ ...base, name: "time" }), "填写命令");

  const http = { ...base, name: "search", transport: "http" as const };
  assert.equal(draftIssue(http), "填写地址");
  assert.equal(draftIssue({ ...http, url: "mcp.example.com/mcp" }), "地址要以 http:// 或 https:// 开头");
  assert.equal(draftIssue({ ...http, url: "https://mcp.example.com/mcp", departments: [] }),
    "选一个可以使用的部门");

  const ready = { ...base, name: "time", command: "uvx" };
  assert.equal(draftIssue(ready), "");
  assert.equal(draftIssue({ ...ready, startup_timeout_sec: "30", output_limit: "0" }), "输出上限要填不小于 1 的整数");
  assert.equal(draftIssue({ ...ready, call_timeout_sec: "abc" }), "调用时限要填不小于 1 的整数");
  assert.equal(draftIssue({ ...ready, startup_timeout_sec: "30", output_limit: "5000" }), "");

  // 变量与请求头：凭据只写名称，名称要能当凭据引用；固定文本不能为空
  const withCredential = { ...ready, startup_timeout_sec: "30", output_limit: "5000",
    env: [{ key: "API_KEY", kind: "credential" as const, value: "", credential_ref: "" }] };
  assert.equal(draftIssue(withCredential), "填写环境变量「API_KEY」的凭据名称");
  assert.equal(draftIssue({ ...withCredential,
    env: [{ key: "API_KEY", kind: "credential", value: "", credential_ref: "1BAD" }] }),
  "凭据「1BAD」只能用字母、数字与下划线，不能以数字开头");
  assert.equal(draftIssue({ ...withCredential,
    env: [{ key: "API_KEY", kind: "text", value: "", credential_ref: "" }] }),
  "填写环境变量「API_KEY」的值");
});

// ---------------------------------------------------------------------------
// 保存参数
// ---------------------------------------------------------------------------

test("stdio 的保存参数带上命令、参数与环境变量，时限留空时不提交", () => {
  const draft = {
    ...emptyDraft(["product", "quality"]),
    name: " time ", transport: "stdio" as const,
    command: " uvx ", args: "mcp-server-time\n  --local-timezone Asia/Shanghai \n",
    env: [
      { key: " API_KEY ", kind: "credential" as const, value: "", credential_ref: " MCP_TIME_KEY " },
      { key: "TZ", kind: "text" as const, value: "Asia/Shanghai", credential_ref: "" },
      { key: "", kind: "text" as const, value: "不提交", credential_ref: "" },
    ],
  };
  assert.deepEqual(mcpServerPayload(draft), {
    name: "time",
    transport: "stdio",
    departments: ["product", "quality"],
    command: "uvx",
    args: ["mcp-server-time", "--local-timezone Asia/Shanghai"],
    env: {
      API_KEY: { kind: "credential", credential_ref: "MCP_TIME_KEY" },
      TZ: { kind: "text", value: "Asia/Shanghai" },
    },
  });
});

test("HTTP 的保存参数带上地址与请求头，填了时限就提交", () => {
  const draft = {
    ...emptyDraft(["product"]),
    name: "search", transport: "http" as const, url: " https://mcp.example.com/mcp ",
    headers: [{ key: "Authorization", kind: "credential" as const, value: "", credential_ref: "EXA_KEY" }],
    startup_timeout_sec: "30", call_timeout_sec: "90", output_limit: "4000",
  };
  assert.deepEqual(mcpServerPayload(draft), {
    name: "search",
    transport: "http",
    departments: ["product"],
    startup_timeout_sec: 30,
    call_timeout_sec: 90,
    output_limit: 4000,
    url: "https://mcp.example.com/mcp",
    headers: { Authorization: { kind: "credential", credential_ref: "EXA_KEY" } },
  });
});

test("参数一行一个，空行与两端的空白去掉", () => {
  assert.deepEqual(splitLines("a\n\n  b  \r\nc"), ["a", "b", "c"]);
  assert.deepEqual(splitLines(""), []);
});

test("已保存的变量与请求头读回表单：凭据只留名称", () => {
  assert.deepEqual(variableDrafts({ API_KEY: { kind: "credential", value: "", credential_ref: "K" },
    TZ: { kind: "text", value: "Asia/Shanghai" } }), [
    { key: "API_KEY", kind: "credential", value: "", credential_ref: "K" },
    { key: "TZ", kind: "text", value: "Asia/Shanghai", credential_ref: "" },
  ]);
  assert.deepEqual(variablesPayload([]), {});
});

// ---------------------------------------------------------------------------
// 整份文档与工具清单快照
// ---------------------------------------------------------------------------

test("已保存的一台服务器读回表单：默认值不重复填出来", () => {
  const draft = draftOfServer(server());
  assert.equal(draft.name, "time");
  assert.equal(draft.transport, "stdio");
  assert.equal(draft.command, "uvx");
  assert.equal(draft.args, "mcp-server-time");
  assert.deepEqual(draft.departments, ["product", "engineering", "quality"]);
  assert.equal(draft.startup_timeout_sec, "");
  assert.equal(draft.call_timeout_sec, "");
  assert.equal(draft.output_limit, "");
  assert.deepEqual(draft.env, [{ key: "API_KEY", kind: "credential", value: "", credential_ref: "MCP_TIME_KEY" }]);
  assert.equal(draftOfServer(server({ startup_timeout_sec: 30 })).startup_timeout_sec, "30");
});

test("配置没有改动时保留原来的工具清单快照，改动以后不再带它", () => {
  const stored = server({ tool_snapshot: { config_digest: "digest-a", tools: [{ name: "echo" }] } });
  const unchanged = draftOfServer(stored);
  assert.equal(draftChangesConfiguration(stored, unchanged), false);
  const kept = mcpDocumentPayload({ time: stored }, unchanged, { previous_name: "time" });
  assert.deepEqual((kept.servers as Record<string, Record<string, unknown>>).time.tool_snapshot,
    stored.tool_snapshot);

  const changed = { ...unchanged, command: "uvx2" };
  assert.equal(draftChangesConfiguration(stored, changed), true);
  const dropped = mcpDocumentPayload({ time: stored }, changed, { previous_name: "time" });
  assert.equal((dropped.servers as Record<string, Record<string, unknown>>).time.tool_snapshot, undefined);
});

test("整份文档带其余服务器，改名去掉原来的名称，删除去掉那一台", () => {
  const other = server({ name: "search", transport: "http", url: "https://mcp.example.com/mcp",
    command: "", args: [], env: {}, headers: {} });
  const time = server();
  const servers = { search: other, time };
  const draft = { ...draftOfServer(time), name: "clock" };

  const renamed = mcpDocumentPayload(servers, draft, { previous_name: "time" });
  assert.deepEqual(Object.keys(renamed.servers as Record<string, unknown>).sort(), ["clock", "search"]);
  // 其余服务器照原样带回去（保存整份文档时不能丢别人的设置）
  assert.deepEqual((renamed.servers as Record<string, McpServerSettingView>).search, other);

  const added = mcpDocumentPayload(servers, { ...emptyDraft(), name: "exa", transport: "http",
    url: "https://exa.example.com/mcp", departments: ["product"] });
  assert.deepEqual(Object.keys(added.servers as Record<string, unknown>).sort(), ["exa", "search", "time"]);

  const removed = mcpDocumentPayload(servers, null, { previous_name: "time" });
  assert.deepEqual(Object.keys(removed.servers as Record<string, unknown>), ["search"]);
});

test("配置的比较把默认值补齐：表单留空与已保存的默认值算同一份配置", () => {
  const payload = mcpServerPayload(draftOfServer(server()));
  assert.equal(configurationSignature(payload), configurationSignature(server()));
  const other = mcpServerPayload({ ...draftOfServer(server()), departments: ["product", "engineering", "quality"] });
  assert.equal(configurationSignature(other), configurationSignature(server()));
});

// ---------------------------------------------------------------------------
// 凭据名称与它们的状态
// ---------------------------------------------------------------------------

test("草稿里出现的凭据名称各记一次，按出现的先后", () => {
  const draft = { ...emptyDraft(), name: "time", command: "uvx",
    env: [
      { key: "A", kind: "credential" as const, value: "", credential_ref: "MCP_KEY" },
      { key: "B", kind: "text" as const, value: "x", credential_ref: "" },
      { key: "C", kind: "credential" as const, value: "", credential_ref: "MCP_KEY" },
      { key: "D", kind: "credential" as const, value: "", credential_ref: "OTHER_KEY" },
    ] };
  assert.deepEqual(credentialNames(draft), ["MCP_KEY", "OTHER_KEY"]);
});

test("保存的设置与草稿里的凭据名称合在一起给", () => {
  const saved = { time: server() };
  const draft = { ...emptyDraft(), name: "search", transport: "http" as const, url: "https://x/mcp",
    headers: [{ key: "Authorization", kind: "credential" as const, value: "", credential_ref: "EXA_KEY" }] };
  assert.deepEqual(credentialNamesOfSettings(saved, draft), ["MCP_TIME_KEY", "EXA_KEY"]);
  assert.deepEqual(credentialNamesOfSettings(undefined, null), []);
});

test("凭据的状态按后端给出的那一项读，没有给出时为空（不猜已设置）", () => {
  const statuses: Record<string, McpCredentialStatusView> = {
    MCP_TIME_KEY: { ref: "MCP_TIME_KEY", configured: true, source: "dotenv", version: 2 },
    EXA_KEY: { ref: "EXA_KEY", configured: false, source: "missing" },
  };
  assert.deepEqual(credentialState(statuses, "MCP_TIME_KEY"), { configured: true, source: "dotenv" });
  assert.deepEqual(credentialState(statuses, "EXA_KEY"), { configured: false, source: "missing" });
  assert.equal(credentialState(statuses, "NOT_LISTED"), null);
  assert.equal(credentialState(undefined, "MCP_TIME_KEY"), null);
  assert.equal(credentialVersion(statuses, "MCP_TIME_KEY"), 2);
  assert.equal(credentialVersion(statuses, "EXA_KEY"), 0);
});

test("凭据状态的说法与模型管理页一致：已保存与来源、缺失", () => {
  assert.equal(credentialStatusLabel({ configured: true, source: "dotenv" }), "已保存 · 来源：.env");
  assert.equal(credentialStatusLabel({ configured: true, source: "override" }), "已保存 · 来源：进程内存");
  assert.equal(credentialStatusLabel({ configured: true, source: "env" }), "已保存 · 来源：环境");
  assert.equal(credentialStatusLabel({ configured: false, source: "missing" }), "缺失");
});

// ---------------------------------------------------------------------------
// 工具清单与探测结果
// ---------------------------------------------------------------------------

test("工具清单快照与探测结果里的工具都读成表格的几行，提示只取服务器标注的", () => {
  const rows = toolRows(probe().tools);
  assert.deepEqual(rows, [
    { name: "echo", description: "回显文本", hints: "" },
    { name: "big", description: "大结果", hints: "只读" },
  ]);
  assert.deepEqual(toolRows(null), []);
  assert.equal(toolCountText(server({ tool_snapshot: { tools: [{ name: "echo" }] } })), "1 个工具");
  assert.equal(toolCountText(server()), "还没有读取工具清单");
  assert.deepEqual(snapshotTools(server()), []);
  assert.deepEqual(snapshotTools(server({ tool_snapshot: { tools: [{ name: "echo" }] } })).map((row) => row.name),
    ["echo"]);
});

test("探测结果的几句话说清楚成功与失败，不写摘要", () => {
  assert.equal(probeStateLabel(null), "还没有探测过");
  assert.equal(probeStateLabel(probe()), "成功 · 2 个工具");
  assert.equal(probeStateLabel(probe({ status: "failed", error: "缺少凭据 MCP_TIME_KEY" })), "失败");
  assert.equal(probeFailureText(probe()), "");
  assert.equal(probeFailureText(probe({ status: "failed", error: "缺少凭据 MCP_TIME_KEY" })),
    "缺少凭据 MCP_TIME_KEY");
  assert.equal(probeFailureText(probe({ status: "failed", error: "" })),
    "这次探测没有成功，原因没有写明。");
  assert.equal(serverInfoText(probe()), "yudao-test-stdio 0.0.1 · 协议 2026-07-28");
  assert.equal(serverInfoText(null), "");
});

test("这次页面里收到的探测结果优先，其次是设置里带的那一次（按服务器名认）", () => {
  const local = probe({ server_name: "time", status: "failed", error: "连接被拒绝" });
  const last = probe({ server_name: "time", config_digest: "digest-a" });
  assert.equal(probeOf("time", last, { time: local }), local);
  assert.equal(probeOf("time", last, {}), last);
  assert.equal(probeOf("search", last, {}), null);
  assert.equal(probeOf("time", null, {}), null);
});

test("配置改过以后旧探测结果不再当可用快照：按后端给的两个摘要比", () => {
  assert.equal(probeIsStale(probe(), server()), false);
  assert.equal(probeIsStale(probe(), server({ config_digest: "digest-b" })), true);
  assert.equal(probeIsStale(probe({ status: "failed" }), server({ config_digest: "digest-b" })), false);
  assert.equal(probeIsStale(null, server()), false);
});

// ---------------------------------------------------------------------------
// 保存与列表的说法
// ---------------------------------------------------------------------------

test("基准版本过期时明说重新读取，不把内部原因写进页面", () => {
  const notice = saveNotice({ kind: "rejected", rejection: {
    command_id: "c1", reason: "stale_base", message: "MCP 服务器设置已经被修改，请重新读取以后提交",
    current_version: 3,
  } });
  assert.equal(notice, "MCP 服务器设置已经被修改，请重新读取以后再保存（服务端当前版本 3）。");
  assert.equal(notice.includes("stale_base"), false);
  // 其余拒绝与服务端自己的说明原样显示
  assert.equal(saveNotice({ kind: "rejected", rejection: {
    command_id: "c1", reason: "not_allowed", message: "「time」的命令不能为空", current_version: null,
  } }), "「time」的命令不能为空");
  assert.equal(saveNotice({ kind: "failed", status: 0 }),
    "这次请求没有送到服务端：联系不上服务，请确认服务还在运行以后再提交。");
});

test("一节与一列的说明：几台服务器、几台读到工具清单、部门用显示名", () => {
  assert.equal(sectionNote(undefined), "项目设置里写明的 MCP 服务器：部门经它们调用工具，工具在事项创建时固定");
  assert.equal(sectionNote({ time: server() }), "1 台服务器，其中 0 台已经读到工具清单");
  assert.equal(sectionNote({ time: server({ tool_snapshot: { tools: [{ name: "echo" }] } }) }),
    "1 台服务器，其中 1 台已经读到工具清单");
  assert.equal(departmentsText(["product", "quality"]), "产品、质检");
  assert.equal(departmentsText([]), "没有选部门");
  assert.equal(departmentsText(undefined), "没有选部门");
});

test("默认期限是一组写在客户端之外也能对齐的值（与后端的默认一致）", () => {
  assert.deepEqual(MCP_DEFAULTS, { startup_timeout_sec: 60, call_timeout_sec: 120, output_limit: 20000 });
});
