// 模型管理页的纯计算（工单 #93、#94）：预填、档位选项、准入汇总与显示、影响列表与引用方、凭据状态。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  REASONING_LEVELS,
  UI_PROTOCOLS,
  CUSTOM_PRESET_ID,
  STALE_ADMISSION_LABEL,
  admittedOptions,
  collectImpact,
  confirmImpactText,
  connectionTestable,
  defaultLevelOptions,
  emptyFormState,
  formDocumentValid,
  formStateFromProvider,
  intFromInput,
  modelRemoveReferrers,
  patchRowCapacity,
  prefillModel,
  prefillSourceText,
  presetBaseUrlFor,
  presetById,
  providerDeleteConfirmation,
  reasoningModeOptions,
  rowFromCandidate,
  rowFromManual,
  rowSavable,
  rowToModelInput,
  rowsSavable,
  testKey,
  tierOptions,
  credentialStatusLabel,
  admissionSummary,
  admissionFor,
  admissionLabel,
  rowCapacityValid,
  canSaveRows,
} from "../../src/renderer/src/views/models/model-logic.ts";

const PRESETS = [
  {
    id: "opencode-go",
    name: "OpenCode Go",
    auth: "api_key",
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
        input_modalities: ["text"],
        output_modalities: ["text"],
        context_window: 1000000,
        max_output_tokens: 128000,
        tool_call: true,
        reasoning: true,
      },
      {
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

test("协议清单与预置表的请求基址：三种协议都能取到基址", () => {
  assert.deepEqual([...UI_PROTOCOLS], ["responses", "chat_completions", "messages"]);
  const preset = presetById(PRESETS, "opencode-go");
  assert.ok(preset);
  for (const protocol of UI_PROTOCOLS) {
    assert.equal(presetBaseUrlFor(preset, protocol), "https://opencode.ai/zen/go/v1");
  }
  // 自定义方案（没有预置条目）取不到基址，地址由用户填写
  assert.equal(presetById(PRESETS, CUSTOM_PRESET_ID), null);
  assert.equal(presetBaseUrlFor(null, "responses"), "");
});

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

test("容量逐行确认：未接受或无效的行不能保存（验收第 3 项）", () => {
  assert.equal(rowCapacityValid({ context_window: null, max_output_tokens: 100 }), false);
  assert.equal(rowCapacityValid({ context_window: 1000, max_output_tokens: null }), false);
  assert.equal(rowCapacityValid({ context_window: 1000, max_output_tokens: 2000 }), false);
  assert.equal(rowCapacityValid({ context_window: 1000, max_output_tokens: 1000 }), true);
  const rows = [
    { context_window: 1000, max_output_tokens: 100, capacity_confirmed: true },
    { context_window: 1000, max_output_tokens: 100, capacity_confirmed: false },
  ];
  assert.equal(canSaveRows(rows), false);
  assert.equal(canSaveRows([rows[0]]), true);
  assert.equal(canSaveRows([]), true);
});

test("预填取上游模型列表优先，其次能力表，来源逐项标明（设计说明第 4.3 节）", () => {
  const fromUpstream = prefillModel(
    "deepseek-v4-flash",
    { id: "deepseek-v4-flash", context_window: 500000, max_output_tokens: 64000 },
    TABLE,
    "opencode-go",
  );
  assert.equal(fromUpstream.context_window, 500000);
  assert.equal(fromUpstream.sources.context_window, "models_url");
  assert.equal(fromUpstream.max_output_tokens, 64000);
  assert.equal(fromUpstream.sources.max_output_tokens, "models_url");
  // 输入方式始终取能力表
  assert.deepEqual(fromUpstream.input_modalities, ["text"]);
  assert.equal(fromUpstream.sources.input_modalities, "capability_table");

  const fromTable = prefillModel("deepseek-v4-flash", { id: "deepseek-v4-flash" }, TABLE, "opencode-go");
  assert.equal(fromTable.context_window, 1000000);
  assert.equal(fromTable.sources.context_window, "capability_table");
  assert.equal(fromTable.max_output_tokens, 128000);
  assert.equal(fromTable.sources.max_output_tokens, "capability_table");

  const vision = prefillModel("vision-model", null, TABLE, "opencode-go");
  assert.deepEqual(vision.input_modalities, ["text", "image"]);

  // 两处都没有：容量留空；输入方式默认只有文本（不推测）
  const unknown = prefillModel("not-in-the-table", { id: "not-in-the-table" }, TABLE, "opencode-go");
  assert.equal(unknown.context_window, null);
  assert.equal(unknown.sources.context_window, null);
  assert.equal(unknown.max_output_tokens, null);
  assert.deepEqual(unknown.input_modalities, ["text"]);
  assert.equal(unknown.sources.input_modalities, "default");

  // 自定义服务方案：能力表没有条目，容量只有上游列表的值
  const custom = prefillModel("deepseek-v4-flash", { id: "deepseek-v4-flash", context_window: 500000 }, TABLE, CUSTOM_PRESET_ID);
  assert.equal(custom.context_window, 500000);
  assert.equal(custom.sources.context_window, "models_url");
  assert.equal(custom.sources.input_modalities, "default");
});

test("默认档位只能从已选的支持档位中选择；推理参数方式只列出与协议相符的选项（验收第 4 项）", () => {
  assert.deepEqual(defaultLevelOptions(["low", "high"]), ["low", "high"]);
  assert.deepEqual(defaultLevelOptions(["high", "low", "bogus"]), ["low", "high"]);
  assert.deepEqual(defaultLevelOptions([]), []);
  assert.deepEqual(reasoningModeOptions("responses"), ["effort"]);
  assert.deepEqual(reasoningModeOptions("chat_completions"), ["effort"]);
  assert.deepEqual(reasoningModeOptions("messages"), ["adaptive", "budget"]);
  assert.deepEqual(reasoningModeOptions("fake"), []);
  assert.deepEqual([...REASONING_LEVELS], ["minimal", "low", "medium", "high", "xhigh", "max"]);
});

test("影响列表按第 4.4 节读回：受影响定义、引用方与进行中事项", () => {
  const impact = collectImpact({
    impacted: [{ model_id: "m1", provider_id: "p1" }],
    deletions: [],
    department_defaults: [{ department: "product", model_id: "m1", provider_id: "p1" }],
    project_settings: [{ project_id: "pr1", project_name: "示例项目", department: "quality", model_id: "m1", provider_id: "p1" }],
    work_items: [{ project_id: "pr1", project_name: "示例项目", work_item_id: "w1", title: "实现回声工具", department: "product" }],
  });
  assert.deepEqual(impact.impacted, ["m1"]);
  assert.deepEqual(impact.deletions, []);
  assert.equal(impact.references.length, 3);
  assert.match(impact.references[0], /部门默认：产品/);
  assert.match(impact.references[1], /项目部门设置：示例项目（质检）/);
  assert.match(impact.references[2], /进行中事项：示例项目 · 实现回声工具（产品）/);

  // 确认文字：没有引用方、没有受影响定义时为空（界面据此决定不弹确认框）
  assert.equal(confirmImpactText(null), "");
  assert.equal(confirmImpactText(collectImpact({ impacted: [{ model_id: "m1", provider_id: "p1" }] })), "");
  const text = confirmImpactText(impact);
  assert.match(text, /准入作废/);
  assert.match(text, /m1/);
  assert.match(text, /受影响的引用方/);
  assert.match(text, /确认以后保存/);
});

test("删除 Provider 配置与移除定义的文字按第 4.5 节：被引用时列出引用方，无引用时列出将一并删除的定义", () => {
  const referenced = collectImpact({
    deletions: [{ model_id: "m1", provider_id: "p1" }],
    department_defaults: [{ department: "quality", model_id: "m1", provider_id: "p1" }],
  });
  assert.match(providerDeleteConfirmation(referenced), /仍被引用，不能删除/);
  assert.match(providerDeleteConfirmation(referenced), /部门默认：质检/);
  assert.match(modelRemoveReferrers(referenced), /仍被引用，不能移除/);
  assert.match(modelRemoveReferrers(referenced), /部门默认：质检/);

  const unreferenced = collectImpact({ deletions: [{ model_id: "m1", provider_id: "p1" }, { model_id: "m2", provider_id: "p1" }] });
  assert.match(providerDeleteConfirmation(unreferenced), /一并删除/);
  assert.match(providerDeleteConfirmation(unreferenced), /m1、m2/);
  assert.equal(modelRemoveReferrers(unreferenced), "");
  assert.equal(providerDeleteConfirmation(null), "");

  assert.equal(STALE_ADMISSION_LABEL, "无法使用：准入已作废");
});

test("表单能否构成合法目录文档：必填项与容量关系（第 4.6 节）", () => {
  const provider = { id: "p1", name: "P", base_url: "https://x/v1" };
  const row = {
    ...rowFromManual(0),
    id: "m1", model: "glm", context_window: "1000", max_output_tokens: "100", capacity_confirmed: true,
  };
  assert.equal(formDocumentValid(provider, [row]), true);
  // 窗口可以留空，只填输出上限
  assert.equal(formDocumentValid(provider, [{ ...row, context_window: "" }]), true);
  // 输出上限必须有值且为正，且不大于窗口
  assert.equal(formDocumentValid(provider, [{ ...row, max_output_tokens: "" }]), false);
  assert.equal(formDocumentValid(provider, [{ ...row, max_output_tokens: "0" }]), false);
  assert.equal(formDocumentValid(provider, [{ ...row, max_output_tokens: "2000" }]), false);
  // 定义的上游模型 ID 不能为空
  assert.equal(formDocumentValid(provider, [{ ...row, model: "" }]), false);
  // 连接三项必填
  assert.equal(formDocumentValid({ ...provider, name: "" }, [row]), false);
  assert.equal(formDocumentValid({ ...provider, base_url: "" }, [row]), false);
  // 没有容量的手动行：不构成合法文档
  assert.equal(formDocumentValid(provider, [rowFromManual(0)]), false);
});

test("表单的取舍值：空文本与非法数字都交回 null", () => {
  assert.equal(intFromInput(""), null);
  assert.equal(intFromInput("   "), null);
  assert.equal(intFromInput("abc"), null);
  assert.equal(intFromInput("1.5"), null);
  assert.equal(intFromInput("128000"), 128000);
});

test("添加时的表单为空，编辑时恢复服务方案、协议与已保存的定义（验收第 2 项）", () => {
  const empty = emptyFormState();
  assert.equal(empty.rows.length, 0);
  assert.equal(empty.preset_id, CUSTOM_PRESET_ID);
  assert.equal(empty.protocol, "responses");

  const provider = {
    id: "p1", name: "OpenCode Go", protocol: "chat_completions", base_url: "https://open/zen/go/v1",
    credential_ref: "KEY", timeout_sec: 45, preset_id: "opencode-go", models_url: "",
    credential: { ref: "KEY", configured: true, source: "dotenv", has_override: false, version: 1 },
    credential_configured: true,
    models: [
      {
        id: "m1", provider_id: "p1", model: "glm-4.6", context_window: 1000, max_output_tokens: 100,
        capability_source: "能力表 2026-10-01.1", accepts_required_tool_call: true,
        input_modalities: ["text", "image"], reasoning_levels: ["low", "high"],
        default_reasoning_level: "high", reasoning_mode: "effort",
      },
    ],
  };
  const state = formStateFromProvider(provider);
  assert.equal(state.preset_id, "opencode-go");
  assert.equal(state.protocol, "chat_completions");
  assert.equal(state.base_url, "https://open/zen/go/v1");
  assert.equal(state.timeout_sec, "45");
  assert.equal(state.rows.length, 1);
  assert.equal(state.rows[0].context_window, "1000");
  assert.equal(state.rows[0].image_input, true);
  assert.equal(state.rows[0].saved, true);
  // 已保存的行带着容量值提交即视为已确认
  assert.equal(rowSavable(state.rows[0]), true);
});

test("点击候选预填并标明来源；未「接受」的行不能保存（验收第 3 项）", () => {
  const row = rowFromCandidate({ id: "deepseek-v4-flash", context_window: 500000, max_output_tokens: 64000 }, TABLE, "opencode-go");
  assert.equal(row.id, "deepseek-v4-flash");
  assert.equal(row.context_window, "500000");
  assert.equal(row.capacity_confirmed, false);
  assert.equal(rowSavable(row), false);
  assert.equal(rowsSavable([row]), false);
  // 来源标注：窗口与输出上限来自上游模型列表，输入方式来自能力表
  assert.match(row.capability_source, /窗口：上游模型列表/);
  assert.match(row.capability_source, /输出上限：上游模型列表/);
  assert.match(row.capability_source, /输入方式：能力表/);
  // 点击「接受」以后可以保存
  assert.equal(rowsSavable([{ ...row, capacity_confirmed: true }]), true);
  // 修改窗口同样视为已确认，来源改为手动
  assert.deepEqual(patchRowCapacity(row, "context_window", "123"), { capacity_confirmed: true, context_window: "123", capability_source: "手动" });

  // 能力表里有图像输入的模型：预填为文本与图像
  const vision = rowFromCandidate({ id: "vision-model" }, TABLE, "opencode-go");
  assert.equal(vision.image_input, true);
  assert.equal(vision.context_window, "256000");
  assert.match(vision.capability_source, /窗口：能力表/);

  // 两处都没有：容量留空，不能保存
  const unknown = rowFromCandidate({ id: "not-in-the-table" }, TABLE, "opencode-go");
  assert.equal(unknown.context_window, "");
  assert.equal(rowSavable({ ...unknown, capacity_confirmed: true }), false);

  // 手动添加的行：没有预填，来源为手动
  const manual = rowFromManual(0);
  assert.equal(manual.capability_source, "手动");
  assert.equal(manual.id, "model-1");
  assert.equal(manual.capacity_confirmed, false);
});

test("提交的形状：档位与输入方式按声明写入，默认档位不在支持档位时为未选择（验收第 4 项）", () => {
  const row = {
    ...rowFromCandidate({ id: "m1", context_window: 1000, max_output_tokens: 100 }, TABLE, "opencode-go"),
    capacity_confirmed: true,
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
  assert.equal(input.capacity_confirmed, true);
  // 默认档位不属于支持档位时交回 null（默认档位只能从已选的支持档位中选择）
  assert.equal(rowToModelInput({ ...row, default_reasoning_level: "max" }).default_reasoning_level, null);
  // 不支持图像时只有文本
  assert.deepEqual(rowToModelInput({ ...row, image_input: false }).input_modalities, ["text"]);
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

test("测试标识与连接测试可用性：连接按连接，模型按定义；没有地址时不提供连接测试", () => {
  assert.equal(testKey("connection", "p1", null), "connection:p1");
  assert.equal(testKey("model", "p1", "m1"), "model:m1");
  assert.equal(connectionTestable({ models_url: "" }, PRESETS[0]), true);
  assert.equal(connectionTestable({ models_url: "https://x/models" }, null), true);
  assert.equal(connectionTestable({ models_url: "" }, null), false);
});

test("预填来源的文字标注", () => {
  const value = prefillModel("deepseek-v4-flash", { id: "deepseek-v4-flash", context_window: 500000 }, TABLE, "opencode-go");
  const text = prefillSourceText(value);
  assert.match(text, /窗口：上游模型列表/);
  assert.match(text, /输出上限：能力表/);
  assert.match(text, /输入方式：能力表/);
});

