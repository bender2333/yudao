// 模型管理页这一层的纯计算（工单 #1297）：候选从目录里怎么来、已选模型清单怎么来、
// 部门默认保存时要写的一整份、目录里的定义转成保存时要写的一份。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  candidateRowsOf,
  candidatesLocked,
  collectingProvider,
  departmentBindings,
  departmentTierBindings,
  fetchNoteText,
  fetchSummaryOf,
  modelInputOf,
  providerInputOf,
  providerModelsWithImageToggled,
  selectedModelRows,
} from "../../src/renderer/src/views/models/model-logic.ts";
import type {
  CatalogAdmission,
  CatalogBinding,
  CatalogCandidate,
  CatalogModel,
  CatalogProvider,
} from "../../src/renderer/src/api/generated/types.gen";

// 一份连接与它的最近一次取到的候选
function provider(id: string, baseUrl: string, candidates: CatalogCandidate[] | null): CatalogProvider {
  return {
    id,
    name: id,
    base_url: baseUrl,
    credential_ref: `${id.toUpperCase()}_KEY`,
    timeout_sec: 600,
    preset_id: "",
    models_url: "",
    credential: { ref: `${id.toUpperCase()}_KEY`, configured: true, source: "dotenv", has_override: false, version: 1 },
    credential_configured: true,
    models: [],
    latest_candidates: candidates === null ? null : {
      provider_id: id,
      status: "ok",
      source_url: `${baseUrl}/models`,
      fetched_at: "2026-10-30T10:00:00Z",
      candidates,
      error: null,
    },
  };
}

function candidate(id: string, over: Partial<CatalogCandidate> = {}): CatalogCandidate {
  return {
    id,
    protocol: "chat_completions",
    protocol_source: "capability_table",
    context_window: 200000,
    context_window_source: "models_url",
    max_output_tokens: 32000,
    max_output_tokens_source: "models_url",
    input_modalities: ["text"],
    input_modalities_source: "models_url",
    provider: null,
    reasoning: null,
    applicable: true,
    ...over,
  };
}

function model(id: string, over: Partial<CatalogModel> = {}): CatalogModel {
  return {
    id,
    provider_id: "go",
    model: id,
    protocol: "chat_completions",
    context_window: 200000,
    max_output_tokens: 32000,
    capability_source: "窗口：上游模型列表 · 输出上限：上游模型列表",
    accepts_required_tool_call: true,
    input_modalities: ["text"],
    reasoning_levels: ["low", "high"],
    default_reasoning_level: "low",
    reasoning_mode: "effort",
    ...over,
  };
}

test("候选从各连接最近一次取到的结果里来，取不到的那份不出现", () => {
  const rows = candidateRowsOf({
    providers: [
      provider("go", "http://a/v1", [candidate("glm-4.6"), candidate("vision-1")]),
      provider("other", "http://b/v1", null),
    ],
  });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].provider_id, "go");
  assert.equal(rows[0].provider_address, "http://a/v1");
  assert.equal(rows[0].candidate.id, "glm-4.6");
});

test("已选模型清单：正在选用的与已启用的都在，只是躺在目录里的不在", () => {
  const admissions: CatalogAdmission[] = [
    { model_id: "d1", provider_id: "go", admitted: true, stale: false, admitted_at: "2026-10-30T10:00:00Z",
      admitted_model: "glm-4.6-real", protocol: "chat_completions", base_url: "http://a/v1",
      credential_ref: "GO_KEY", model: "glm-4.6" },
  ];
  const rows = selectedModelRows({
    providers: [provider("go", "http://a/v1", [])],
    models: [
      model("d1", { model: "glm-4.6" }),
      model("d2", { model: "slow", context_window: null, max_output_tokens: null }),
      model("d3", { model: "idle" }),
    ],
    admissions,
    selections: [{ provider_id: "go", model_id: "d2", model: "slow", sequence: 3, status: "capacity_unknown",
      missing: ["context_window"], error: null }],
  });
  assert.deepEqual(rows.map((row) => row.model_id).sort(), ["d1", "d2"]);
  assert.equal(rows.find((row) => row.model_id === "d1")?.status, "enabled");
  assert.equal(rows.find((row) => row.model_id === "d2")?.status, "capacity_unknown");
  assert.deepEqual(rows.find((row) => row.model_id === "d2")?.missing, ["context_window"]);
});

test("同一个定义有两条进度时取序号大的那一条", () => {
  const rows = selectedModelRows({
    providers: [provider("go", "http://a/v1", [])],
    models: [model("d1", { model: "glm-4.6" })],
    admissions: [],
    selections: [
      { provider_id: "go", model_id: "d1", model: "glm-4.6", sequence: 1, status: "testing", missing: [], error: null },
      { provider_id: "go", model_id: "d1", model: "glm-4.6", sequence: 2, status: "failed", missing: [], error: "上游拒绝" },
    ],
  });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "failed");
  assert.equal(rows[0].error, "上游拒绝");
});

test("部门默认保存时写的是一整份：换了模型，其余部门照旧", () => {
  const bindings: Record<string, CatalogBinding> = {
    product: { provider_id: "go", model_id: "d1", requested_tier: "low" },
    engineering: { provider_id: "go", model_id: "d2", requested_tier: null },
  };
  const written = departmentBindings(
    { bindings, models: [model("d1"), model("d2"), model("d3")] },
    "quality",
    "d3",
  );
  assert.deepEqual(Object.keys(written).sort(), ["engineering", "product", "quality"]);
  assert.equal(written.product.requested_tier, "low");
  assert.equal(written.quality.requested_tier, null);
});

test("改请求档位时模型不动", () => {
  const bindings: Record<string, CatalogBinding> = {
    product: { provider_id: "go", model_id: "d1", requested_tier: "low" },
    quality: { provider_id: "go", model_id: "d2", requested_tier: null },
  };
  const written = departmentTierBindings({ bindings }, "product", "high");
  assert.equal(written.product.model_id, "d1");
  assert.equal(written.product.requested_tier, "high");
  assert.equal(written.quality.requested_tier, null);
});

test("目录里的定义转成保存时要写的一份：字段原样带过去", () => {
  const written = modelInputOf(model("d1"));
  assert.equal(written.id, "d1");
  assert.equal(written.model, "d1");
  assert.equal(written.protocol, "chat_completions");
  assert.deepEqual(written.input_modalities, ["text"]);
  assert.deepEqual(written.reasoning_levels, ["low", "high"]);
  assert.equal(written.default_reasoning_level, "low");
  assert.equal(written.accepts_required_tool_call, true);
});

// ---------------------------------------------------------------------------
// 获取模型列表这条操作的状态（工单 #1355）
// ---------------------------------------------------------------------------

// 一份连接最近一次获取的结果；status 不是 ok 时带服务端给的原因
function providerWithResult(status: "ok" | "unknown", fetchedAt: string, error: string | null = null): CatalogProvider {
  return {
    ...provider("go", "http://a/v1", status === "ok" ? [candidate("glm-4.6")] : []),
    latest_candidates: {
      provider_id: "go",
      status,
      source_url: "http://a/v1/models",
      fetched_at: fetchedAt,
      candidates: status === "ok" ? [candidate("glm-4.6")] : [],
      error,
    },
  };
}

test("结果没变就是还在取候选", () => {
  const collecting = collectingProvider({ providers: [providerWithResult("ok", "2026-10-30T10:00:00Z")] },
    { provider_id: "go", fetched_at: "2026-10-30T10:00:00Z", status: "ok" });
  assert.equal(collecting, "go");
});

test("第一次取候选：还没有结果时也算在取", () => {
  const collecting = collectingProvider({ providers: [provider("go", "http://a/v1", null)] },
    { provider_id: "go", fetched_at: null, status: null });
  assert.equal(collecting, "go");
});

test("请求结束以后不再算在取：成功换了结果时间", () => {
  const collecting = collectingProvider({ providers: [providerWithResult("ok", "2026-10-30T10:05:00Z")] },
    { provider_id: "go", fetched_at: "2026-10-30T10:00:00Z", status: "ok" });
  assert.equal(collecting, null);
});

test("请求失败以后同样复位：失败换成空的结果时间与原因", () => {
  const failed = providerWithResult("unknown", "", "模型列表请求 http://a/v1/models 返回 HTTP 401");
  assert.equal(collectingProvider({ providers: [failed] },
    { provider_id: "go", fetched_at: "2026-10-30T10:00:00Z", status: "ok" }), null);
  // 原因在连接卡片旁显示
  assert.deepEqual(fetchSummaryOf(failed),
    { text: "模型列表请求 http://a/v1/models 返回 HTTP 401", kind: "error" });
});

test("没有这次获取、或者这份连接已经不在了，都不算在取", () => {
  assert.equal(collectingProvider({ providers: [provider("go", "http://a/v1", [])] }, null), null);
  assert.equal(collectingProvider({ providers: [] },
    { provider_id: "go", fetched_at: null, status: null }), null);
  assert.equal(collectingProvider(null, { provider_id: "go", fetched_at: null, status: null }), null);
});

test("候选区只在页面自己的命令在途时暂停：页面刚打开、后台取候选都不停住操作", () => {
  // 页面刚打开：不引入「一打开就禁用」（工单验收第 3 条）
  assert.equal(candidatesLocked({ busy: false, connecting: false }), false);
  // 请求在途：停住，同时候选区上方写明在做什么
  assert.equal(candidatesLocked({ busy: true, connecting: false }), true);
  assert.equal(candidatesLocked({ busy: false, connecting: true }), true);
  // 服务端在后台取候选（collecting）时页面照常可以操作
  assert.equal(candidatesLocked({ busy: false, connecting: false }), false);
});

test("说明写在候选区上方：请求在途、取候选、空闲三种", () => {
  assert.match(fetchNoteText({ connecting: true, collecting: false }), /正在获取模型列表/);
  assert.match(fetchNoteText({ connecting: true, collecting: false }), /暂停操作/);
  assert.match(fetchNoteText({ connecting: false, collecting: true }), /正在获取模型列表/);
  assert.match(fetchNoteText({ connecting: false, collecting: true }), /可以继续/);
  assert.equal(fetchNoteText({ connecting: false, collecting: false }), "");
});

test("连接卡片上的最近一次结果：成功写数量与时间，没取过写没有取过", () => {
  assert.equal(fetchSummaryOf(providerWithResult("ok", "2026-10-30T10:00:00Z")).text,
    "已获取 1 个模型 · 2026-10-30T10:00:00Z");
  assert.deepEqual(fetchSummaryOf(provider("go", "http://a/v1", null)),
    { text: "还没有获取过模型列表。", kind: "none" });
});

test("已选用模型保留准入与输入方式，手动切换图像输入只更新该模型并保留其余定义与连接字段", () => {
  const p = provider("go", "http://a/v1", []);
  const m1 = model("d1", { model: "ag/gemini-3.8-flash-high", input_modalities: ["text"] });
  const m2 = model("d2", { model: "glm-4.6", input_modalities: ["text", "image"] });
  const rows = selectedModelRows({
    providers: [p],
    models: [m1, m2],
    admissions: [
      {
        model_id: "d1", provider_id: "go", admitted: true, stale: false,
        admitted_at: "2026-11-16T00:00:00Z", admitted_model: "gemini-3.8-flash",
        protocol: "chat_completions", base_url: "http://a/v1",
        credential_ref: "GO_KEY", model: "ag/gemini-3.8-flash-high",
      },
    ],
    selections: [
      { provider_id: "go", model_id: "d2", model: "glm-4.6", sequence: 1, status: "testing", missing: [], error: null },
    ],
  });
  assert.equal(rows.find((row) => row.model_id === "d1")?.status, "enabled");
  assert.deepEqual(rows.find((row) => row.model_id === "d1")?.input_modalities, ["text"]);
  assert.equal(rows.find((row) => row.model_id === "d1")?.admitted_model, "gemini-3.8-flash");
  assert.deepEqual(rows.find((row) => row.model_id === "d2")?.input_modalities, ["text", "image"]);

  assert.deepEqual(providerInputOf(p), {
    id: "go",
    name: "go",
    base_url: "http://a/v1",
    credential_ref: "GO_KEY",
    timeout_sec: 600,
    preset_id: "",
    models_url: "",
  });

  const savedOn = providerModelsWithImageToggled([m1, m2], "d1", true);
  assert.deepEqual(savedOn[0].input_modalities, ["text", "image"]);
  assert.equal(savedOn[0].protocol, "chat_completions");
  assert.deepEqual(savedOn[1].input_modalities, ["text", "image"]);

  const savedOff = providerModelsWithImageToggled([m1, m2], "d2", false);
  assert.deepEqual(savedOff[0].input_modalities, ["text"]);
  assert.deepEqual(savedOff[1].input_modalities, ["text"]);
});

// 守 R3（模型管理 docs/design/model-management.md「模型管理页」）：连接卡片只在一处呈现完整获取计数与时间
test("ConnectCard 渲染连接卡片时只在明细中保留完整计数，头部状态徽标不重复输出", async () => {
  const { createRequire } = await import("node:module");
  const fs = await import("node:fs");
  const path = await import("node:path");
  const { fileURLToPath } = await import("node:url");
  const req = createRequire(import.meta.url);
  const ts = req("typescript");
  const React = req("react");
  const { renderToStaticMarkup } = req("react-dom/server");
  (globalThis as Record<string, unknown>)["React"] = React;
  const loader = (module: NodeModule, filename: string) => {
    const code = fs.readFileSync(filename, "utf8");
    const js = ts.transpileModule(code, {
      compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    (module as unknown as { _compile(code: string, name: string): void })._compile(js, filename);
  };
  req.extensions[".tsx"] = loader;
  req.extensions[".ts"] = loader;

  const cardPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../src/renderer/src/views/models/connect-card.tsx",
  );
  const { ConnectCard } = req(cardPath);

  const okProvider = providerWithResult("ok", "2026-10-30T10:00:00Z");
  const errProvider = providerWithResult("unknown", "", "服务拒绝了这个 API Key");
  const noneProvider = provider("idle", "http://c/v1", null);

  const baseProps = {
    target: null,
    address: "",
    apiKey: "",
    busy: false,
    fetching: null,
    status: {},
    onTarget: () => {},
    onAddress: () => {},
    onApiKey: () => {},
    onConnect: () => {},
    onRefresh: () => {},
    onRemove: () => {},
  };

  // 成功获取：头部 .mm-count 只写「已获取」，完整计数与时间只在 connection-fetch 出现一次
  const okHtml = renderToStaticMarkup(React.createElement(ConnectCard, { ...baseProps, providers: [okProvider] }));
  const fullSummary = "已获取 1 个模型 · 2026-10-30T10:00:00Z";
  assert.match(okHtml, /class="y10-conn-count mm-count">已获取<\/span>/);
  assert.match(okHtml, /data-testid="connection-fetch">已获取 1 个模型 · 2026-10-30T10:00:00Z<\/p>/);
  assert.equal(okHtml.split(fullSummary).length - 1, 1);

  // 获取失败与未获取保持各自头部状态徽标
  const errHtml = renderToStaticMarkup(React.createElement(ConnectCard, { ...baseProps, providers: [errProvider] }));
  assert.match(errHtml, /class="y10-conn-count mm-count">获取失败<\/span>/);
  assert.match(errHtml, /data-testid="connection-fetch">服务拒绝了这个 API Key<\/p>/);

  const noneHtml = renderToStaticMarkup(React.createElement(ConnectCard, { ...baseProps, providers: [noneProvider] }));
  assert.match(noneHtml, /class="y10-conn-count mm-count">未获取<\/span>/);
  assert.equal(noneHtml.includes('data-testid="connection-fetch"'), false);
});
