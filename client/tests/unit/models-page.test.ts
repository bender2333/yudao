// 模型管理页这一层的纯计算（工单 #1297）：候选从目录里怎么来、已选模型清单怎么来、
// 部门默认保存时要写的一整份、目录里的定义转成保存时要写的一份。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  candidateRowsOf,
  departmentBindings,
  departmentTierBindings,
  modelInputOf,
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
