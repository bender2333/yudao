// 模型管理页的纯计算（工单 #93、#94）：预填、档位选项、准入汇总与显示、影响列表与引用方、凭据状态。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  REASONING_LEVELS,
  UI_PROTOCOLS,
  CUSTOM_PRESET_ID,
  STALE_ADMISSION_LABEL,
  admittedOptions,
  capacityIssueText,
  collectImpact,
  confirmImpactText,
  connectionTestable,
  defaultLevelOptions,
  defaultModelsUrl,
  effectiveModelsUrl,
  emptyFormState,
  formDocumentValid,
  formStateFromProvider,
  formPatchForBaseUrl,
  formPatchForPreset,
  groupAdmittedModels,
  intFromInput,
  MODEL_OPTION_COLLATOR,
  modelRemoveReferrers,
  patchRowCapacity,
  prefillModel,
  prefillSourceText,
  presetBaseUrlFor,
  presetById,
  normalizeBaseUrl,
  providerDeleteConfirmation,
  providerInputFromForm,
  reasoningModeOptions,
  rowFromCandidate,
  rowFromManual,
  rowSavable,
  rowToModelInput,
  rowsSavable,
  testKeyOf,
  testText,
  tierOptions,
  credentialStatusLabel,
  admissionSummary,
  admissionFor,
  admissionLabel,
  rowCapacityValid,
  canSaveRows,
  candidateToRow,
  canJoinCandidates,
  sanitizeModelId,
  saveSuccessText,
} from "../../src/renderer/src/views/models/model-logic.ts";

const PRESETS = [
  {
    id: "opencode-go",
    name: "OpenCode Go",
    auth: "api_key",
    default_protocol: "chat_completions",
    base_urls: {
      responses: "https://opencode.ai/zen/go/v1",
      chat_completions: "https://opencode.ai/zen/go/v1",
      messages: "https://opencode.ai/zen/go/v1",
    },
    models_url: "https://opencode.ai/zen/go/v1/models",
    docs_url: "https://opencode.ai/docs/go/",
    source: "https://opencode.ai/docs/go/#endpoints",
    notes: "",
  },
];

const TABLE = {
  revision: "2026-10-01.1",
  snapshot_date: "2026-10-01",
  source: "https://models.dev",
  presets: {
    "opencode-go": [
      {
        model: "deepseek-v4-flash",
        protocol: "chat_completions",
        input_modalities: ["text"],
        output_modalities: ["text"],
        context_window: 1000000,
        max_output_tokens: 128000,
        tool_call: true,
        reasoning: true,
      },
      {
        protocol: "responses",
        model: "vision-model",
        input_modalities: ["text", "image"],
        output_modalities: ["text"],
        context_window: 256000,
        max_output_tokens: 32000,
        tool_call: true,
        reasoning: false,
      },
    ],
  },
};



test("凭据状态用词（设计说明第 9.1 节）：缺失、内存、环境、.env", () => {
  assert.equal(credentialStatusLabel({ configured: false, source: "missing" }), "缺失");
  assert.equal(credentialStatusLabel({ configured: true, source: "override" }), "来源：内存");
  assert.equal(credentialStatusLabel({ configured: true, source: "env" }), "来源：环境");
  assert.equal(credentialStatusLabel({ configured: true, source: "dotenv" }), "来源：.env");
});

test("准入摘要按连接统计「已准入 x · 候选 y」", () => {
  const provider = {
    id: "p1",
    models: [
      { id: "m1", provider_id: "p1" },
      { id: "m2", provider_id: "p1" },
      { id: "m3", provider_id: "p1" },
      { id: "m4", provider_id: "p1" },
    ],
  };
  const admissions = [
    { model_id: "m1", provider_id: "p1", admitted: true, stale: false },
    { model_id: "m2", provider_id: "p1", admitted: true, stale: true },
    { model_id: "m3", provider_id: "p1", admitted: false, stale: false },
    // 别的连接不计入
    { model_id: "m9", provider_id: "other", admitted: true, stale: false },
  ];
  assert.deepEqual(admissionSummary(provider, admissions), { admitted: 1, candidates: 3 });
});

test("准入列显示测试时间与实际返回的模型；候选与作废各自显示", () => {
  assert.equal(admissionLabel(null), "候选");
  assert.equal(
    admissionLabel({ admitted: true, stale: false, admitted_at: "2026-10-02T01:00:00Z", admitted_model: "glm-4.6" }),
    "已准入：2026-10-02T01:00:00Z · glm-4.6",
  );
  // 视图里 admitted 与 stale 互斥：作废的准入 admitted 为假、stale 为真
  assert.equal(admissionLabel({ admitted: false, stale: true }), "候选（准入已作废）");
  assert.equal(admissionLabel({ admitted: false, stale: false }), "候选");
  const admissions = [{ model_id: "m1", provider_id: "p1", admitted: true, stale: false }];
  assert.equal(admissionFor({ id: "m1", provider_id: "p1" }, admissions)?.admitted, true);
  assert.equal(admissionFor({ id: "m2", provider_id: "p1" }, admissions), null);
});













test("提交的形状：档位与输入方式按声明写入，默认档位不在支持档位时为未选择（验收第 4 项）", () => {
  const row = {
    ...rowFromCandidate({ id: "m1", context_window: 1000, max_output_tokens: 100 }, TABLE, "opencode-go",
                        presetById(PRESETS, "opencode-go")),
    image_input: true,
    reasoning_levels: ["low", "high"],
    default_reasoning_level: "high",
    reasoning_mode: "effort",
  };
  const input = rowToModelInput(row);
  assert.equal(input.context_window, 1000);
  assert.equal(input.max_output_tokens, 100);
  assert.deepEqual(input.input_modalities, ["text", "image"]);
  assert.equal(input.default_reasoning_level, "high");
  // 默认档位不属于支持档位时交回 null（默认档位只能从已选的支持档位中选择）
  assert.equal(rowToModelInput({ ...row, default_reasoning_level: "max" }).default_reasoning_level, null);
  // 不支持图像时只有文本
  assert.deepEqual(rowToModelInput({ ...row, image_input: false }).input_modalities, ["text"]);
});

test("连接提交的请求时限：填了取填的值，留空不提交该字段（工单 #294）", () => {
  const state = emptyFormState(600);
  assert.equal(providerInputFromForm(state).timeout_sec, 600);
  assert.equal(providerInputFromForm({ ...state, timeout_sec: "45" }).timeout_sec, 45);
  // 留空时整个字段不出现，后端 ProviderInput 的默认值生效，客户端不写第二个数
  assert.equal("timeout_sec" in providerInputFromForm({ ...state, timeout_sec: "" }), false);
});

test("部门默认的选项只含已准入且未作废的定义，档位选项保留按模型限制的已存值（第 9.1 节）", () => {
  const providers = [
    { id: "p1", name: "OpenCode Go" },
    { id: "p2", name: "其他连接" },
  ];
  const models = [
    { id: "m1", provider_id: "p1", model: "glm-4.6" },
    { id: "m2", provider_id: "p1", model: "kimi-k2" },
    { id: "m3", provider_id: "p2", model: "deepseek" },
  ];
  const admissions = [
    { model_id: "m1", provider_id: "p1", admitted: true, stale: false },
    { model_id: "m2", provider_id: "p1", admitted: true, stale: true },
    { model_id: "m3", provider_id: "p2", admitted: true, stale: false },
  ];
  const options = admittedOptions(models, providers, admissions);
  assert.deepEqual(options.map((item) => item.id), ["m3", "m1"]);
  assert.equal(options.find((item) => item.id === "m1")?.provider_name, "OpenCode Go");

  assert.deepEqual(tierOptions(["low", "medium"], "low"), [
    { value: "low", label: "low" },
    { value: "medium", label: "medium" },
  ]);
  // 已保存的档位不在支持档位内：额外保留这一项并标明按模型限制
  const kept = tierOptions(["low"], "max");
  assert.equal(kept.length, 2);
  assert.match(kept[1].label, /按模型限制/);
});




test("模型测试的结果显示在模型行：通过写用时，未通过写原因（工单 #294）", () => {
  const passed = testText({
    kind: "model", ok: true, elapsed_ms: 1234, actual_model: "glm-4.6", admitted: true, error: null,
  });
  assert.match(passed, /模型测试通过/);
  assert.match(passed, /1234 毫秒/);
  // 失败时写出上游给出的原因
  const failed = testText({ kind: "model", ok: false, elapsed_ms: 12, error: "401 unauthorized", admitted: null });
  assert.match(failed, /模型测试未通过/);
  assert.match(failed, /401 unauthorized/);
  // 事件按同一把键找回界面上的这一行
  assert.equal(testKeyOf({ kind: "model", model_id: "m1" }), "model:m1");
  assert.equal(testKeyOf({ kind: "connection", provider_id: "p1" }), "connection:p1");
});



test("连接测试结果写明读取的模型列表地址（工单 #302）", () => {
  const passed = testText({
    kind: "connection", ok: true, elapsed_ms: 123, error: null,
    source_url: "https://cbcn.com/v1/models",
  });
  assert.equal(passed, "已读取模型列表地址 https://cbcn.com/v1/models：连接测试通过（123 毫秒）");
  // 未通过时同样写明是哪个地址没有读到，不让人误以为请求地址也通过了
  const failed = testText({
    kind: "connection", ok: false, elapsed_ms: 8, error: "HTTP 401",
    source_url: "https://cbcn.com/v1/models",
  });
  assert.match(failed, /https:\/\/cbcn\.com\/v1\/models/);
  assert.match(failed, /HTTP 401/);
  // 模型测试不写地址：它证明的是这一条定义可调
  const model = testText({ kind: "model", ok: true, elapsed_ms: 50, actual_model: "glm-4.6", admitted: true, error: null });
  assert.doesNotMatch(model, /模型列表地址/);
});



