// 模型管理页的纯计算（工单 #1297）：筛选、搜索与分批，各状态的文字，
// 「不可用的按钮旁写明缺哪一项」，取消选用被拒绝时的引用方，以及项目设置页仍要用的取值。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEPARTMENTS,
  FIRST_BATCH,
  MORE_BATCH,
  admittedModels,
  candidateBatch,
  candidateKey,
  capacityInputIssue,
  capacityKnown,
  capacityMissingText,
  connectIssue,
  currentEffectiveLabel,
  departmentBindings,
  departmentTierBindings,
  filterCandidates,
  followDepartmentLabel,
  groupAdmittedModels,
  matchesFilter,
  matchesSearch,
  mergedModelId,
  modelById,
  moreCount,
  removalRejectionText,
  selectedModelRows,
  selectionStatusKind,
  selectionStatusLabel,
  tierOptions,
} from "../../src/renderer/src/views/models/model-logic.ts";

// 一个候选：窗口与输出上限已知，协议按服务端给的值
function candidate(id, over = {}) {
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

const ROWS = [
  { provider_id: "go", provider_address: "http://127.0.0.1:1/v1", candidate: candidate("glm-4.6") },
  { provider_id: "go", provider_address: "http://127.0.0.1:1/v1", candidate: candidate("vision-1", {
    input_modalities: ["text", "image"], reasoning: true,
  }) },
  { provider_id: "go", provider_address: "http://127.0.0.1:1/v1", candidate: candidate("no-capacity", {
    context_window: null, context_window_source: null, max_output_tokens: null, max_output_tokens_source: null,
  }) },
  { provider_id: "go", provider_address: "http://127.0.0.1:1/v1", candidate: candidate("image-only", {
    applicable: false, output_modalities: ["image"],
  }) },
];

// —— 搜索 ——

test("搜索按名称、提供方与上游模型 ID 匹配，空搜索全都留下", () => {
  assert.equal(matchesSearch(ROWS[0], ""), true);
  assert.equal(matchesSearch(ROWS[0], "GLM"), true);
  assert.equal(matchesSearch(ROWS[0], "glm"), true);
  assert.equal(matchesSearch(ROWS[0], "没有"), false);
  const named = [{ provider_id: "go", provider_address: "http://x/v1",
    candidate: candidate("deepseek/deepseek-v4", { provider: "deepseek" }) }];
  assert.equal(matchesSearch(named[0], "deepseek"), true);
  // 提供方也在搜索范围里
  assert.equal(matchesSearch(named[0], "provider"), false);
});

// —— 筛选 ——

test("可自动配置的筛选只留容量已知的候选", () => {
  const rows = filterCandidates(ROWS, "", "auto", new Set());
  assert.deepEqual(rows.map((row) => row.candidate.id), ["glm-4.6", "vision-1"]);
  assert.equal(capacityKnown(ROWS[2].candidate), false);
});

test("支持图像、支持推理、全部模型与已选用的筛选各按自己的条件", () => {
  assert.deepEqual(
    filterCandidates(ROWS, "", "vision", new Set()).map((row) => row.candidate.id),
    ["vision-1"],
  );
  assert.deepEqual(
    filterCandidates(ROWS, "", "reasoning", new Set()).map((row) => row.candidate.id),
    ["vision-1"],
  );
  assert.equal(filterCandidates(ROWS, "", "all", new Set()).length, 4);
  const selected = new Set([candidateKey("go", "no-capacity")]);
  assert.deepEqual(
    filterCandidates(ROWS, "", "selected", selected).map((row) => row.candidate.id),
    ["no-capacity"],
  );
  assert.equal(matchesFilter(ROWS[3], "auto", new Set()), false);
});

test("搜索与筛选一起时两边都要过", () => {
  const rows = filterCandidates(ROWS, "vision", "auto", new Set());
  assert.deepEqual(rows.map((row) => row.candidate.id), ["vision-1"]);
  assert.deepEqual(filterCandidates(ROWS, "vision", "reasoning", new Set()).length, 1);
});

// —— 分批 ——

test("候选先显示 8 个，之后每次再显示 12 个", () => {
  const many = Array.from({ length: 30 }, (_, index) => ({
    provider_id: "go",
    provider_address: "http://x/v1",
    candidate: candidate(`m-${index}`),
  }));
  const first = candidateBatch(many, FIRST_BATCH);
  assert.equal(first.shown.length, 8);
  assert.equal(first.remaining, 22);
  const second = candidateBatch(many, FIRST_BATCH + MORE_BATCH);
  assert.equal(second.shown.length, 20);
  assert.equal(second.remaining, 10);
  assert.equal(moreCount(22), 12);
  assert.equal(moreCount(5), 5);
});

// —— 状态的文字 ——

test("选用的状态按设计说明第 9.5 节的用词", () => {
  assert.equal(selectionStatusLabel("completing"), "补全参数");
  assert.equal(selectionStatusLabel("waiting"), "等待验证");
  assert.equal(selectionStatusLabel("testing"), "验证调用");
  assert.equal(selectionStatusLabel("failed"), "验证失败");
  assert.equal(selectionStatusLabel("capacity_unknown"), "容量未知");
  assert.equal(selectionStatusLabel("not_in_list"), "不在新的模型列表中");
  assert.equal(selectionStatusLabel("enabled"), "已启用");
  assert.equal(selectionStatusKind("failed"), "failed");
  assert.equal(selectionStatusKind("capacity_unknown"), "unknown");
  assert.equal(selectionStatusKind("testing"), "running");
});

// —— 不可用的按钮旁写明缺哪一项 ——

test("「获取模型」不可用时写明缺的是地址还是 Key", () => {
  assert.equal(connectIssue({ address: "", api_key: "", credential_saved: false }), "填写服务地址");
  assert.equal(connectIssue({ address: "   ", api_key: "k", credential_saved: false }), "填写服务地址");
  assert.equal(
    connectIssue({ address: "https://api.example.com/v1", api_key: "", credential_saved: false }),
    "填写 API Key",
  );
  // 已有凭据的连接不用再填 Key
  assert.equal(
    connectIssue({ address: "https://api.example.com/v1", api_key: "", credential_saved: true }),
    "",
  );
  // 地址不成样子时先说地址
  assert.equal(
    connectIssue({ address: "ftp://api.example.com/v1", api_key: "k", credential_saved: true }),
    "服务地址要用 http 或 https",
  );
  assert.equal(
    connectIssue({ address: "https://api.example.com/v1", api_key: "k", credential_saved: false }),
    "",
  );
});

test("容量未知写明缺哪一项，手填的容量不合法时也写明哪一项", () => {
  assert.equal(capacityMissingText(["context_window", "max_output_tokens"]), "缺少窗口与输出上限");
  assert.equal(capacityMissingText(["context_window"]), "缺少窗口");
  assert.equal(capacityMissingText(["max_output_tokens"]), "缺少输出上限");
  assert.equal(capacityMissingText([]), "");

  assert.equal(capacityInputIssue(null, null), "填写窗口与输出上限");
  assert.equal(capacityInputIssue(200000, null), "填写输出上限");
  assert.equal(capacityInputIssue(null, 32000), "填写窗口");
  assert.equal(capacityInputIssue(200000, 32000), "");
  assert.equal(capacityInputIssue(1000, 32000), "输出上限不能大于窗口");
  assert.equal(capacityInputIssue(200000, 0), "输出上限必须是正整数");
});

// —— 取消选用被拒绝时的引用方 ——

test("服务端给的位置串换成看得懂的引用方", () => {
  assert.equal(
    removalRejectionText("仍被引用，无法移除：bindings.product、bindings.engineering、bindings.quality"),
    "仍被引用，无法移除：部门默认：产品、部门默认：工程、部门默认：质检",
  );
  assert.equal(
    removalRejectionText("仍被引用，无法移除：projects.p1.department_settings.quality"),
    "仍被引用，无法移除：项目部门设置：质检",
  );
  // 不是位置串时原样给出
  assert.equal(removalRejectionText("目录已经变化，请重新读取以后再提交"), "目录已经变化，请重新读取以后再提交");
});

// —— 已选模型清单 ——

test("已选模型清单只列正在选用或已启用的定义", () => {
  const catalog = {
    providers: [{ id: "go", base_url: "http://x/v1" }],
    models: [
      { id: "d1", provider_id: "go", model: "glm-4.6", protocol: "chat_completions", context_window: 200000,
        max_output_tokens: 32000, capability_source: "窗口：上游模型列表", accepts_required_tool_call: true,
        input_modalities: ["text"], reasoning_levels: [], default_reasoning_level: null, reasoning_mode: "" },
      { id: "d2", provider_id: "go", model: "slow", protocol: "chat_completions", context_window: null,
        max_output_tokens: null, capability_source: "", accepts_required_tool_call: true,
        input_modalities: ["text"], reasoning_levels: [], default_reasoning_level: null, reasoning_mode: "" },
      { id: "d3", provider_id: "go", model: "idle", protocol: "chat_completions", context_window: 1,
        max_output_tokens: 1, capability_source: "", accepts_required_tool_call: true,
        input_modalities: ["text"], reasoning_levels: [], default_reasoning_level: null, reasoning_mode: "" },
    ],
    admissions: [{ model_id: "d1", provider_id: "go", admitted: true, stale: false, admitted_at: "2026-10-30T10:00:00Z",
      admitted_model: "glm-4.6-real" }],
    selections: [{ provider_id: "go", model_id: "d2", model: "slow", sequence: 1, status: "capacity_unknown",
      missing: ["context_window", "max_output_tokens"], error: null }],
  };
  const rows = selectedModelRows(catalog);
  assert.deepEqual(rows.map((row) => row.model_id).sort(), ["d1", "d2"]);
  const enabled = rows.find((row) => row.model_id === "d1");
  assert.equal(enabled.status, "enabled");
  assert.equal(enabled.admitted_model, "glm-4.6-real");
  const unknown = rows.find((row) => row.model_id === "d2");
  assert.equal(unknown.status, "capacity_unknown");
  assert.deepEqual(unknown.missing, ["context_window", "max_output_tokens"]);
  assert.equal(unknown.provider_address, "http://x/v1");
});

// —— 部门使用的保存 ——

test("换一个部门的模型时其余两个部门照当前的值一起写回去", () => {
  const catalog = {
    bindings: {
      product: { provider_id: "go", model_id: "d1", requested_tier: "low" },
      engineering: { provider_id: "go", model_id: "d2", requested_tier: null },
    },
    models: [
      { id: "d1", provider_id: "go", model: "a" },
      { id: "d2", provider_id: "go", model: "b" },
      { id: "d3", provider_id: "go", model: "c" },
    ],
  };
  const bindings = departmentBindings(catalog, "quality", "d3");
  assert.deepEqual(Object.keys(bindings).sort(), ["engineering", "product", "quality"]);
  assert.equal(bindings.product.model_id, "d1");
  assert.equal(bindings.product.requested_tier, "low");
  assert.equal(bindings.engineering.model_id, "d2");
  assert.equal(bindings.quality.model_id, "d3");
  // 选「未设置」时这个部门不再写，别的部门不动
  const cleared = departmentBindings(catalog, "quality", "");
  assert.equal(cleared.quality, undefined);
  assert.equal(cleared.product.model_id, "d1");
});

test("改请求档位时模型不动，只换这一个部门的档位", () => {
  const catalog = {
    bindings: {
      product: { provider_id: "go", model_id: "d1", requested_tier: "low" },
      quality: { provider_id: "go", model_id: "d2", requested_tier: null },
    },
  };
  const bindings = departmentTierBindings(catalog, "product", "high");
  assert.equal(bindings.product.requested_tier, "high");
  assert.equal(bindings.product.model_id, "d1");
  assert.equal(bindings.quality.requested_tier, null);
});

// —— 项目设置页仍要用的取值 ——

test("部门默认与项目设置的模型选项按连接分组", () => {
  const models = [
    { id: "d1", provider_id: "go", model: "glm-4.6" },
    { id: "d2", provider_id: "go", model: "vision-1" },
  ];
  const providers = [{ id: "go", name: "OpenCode Go" }, { id: "other", name: "别的" }];
  const admissions = [
    { model_id: "d1", provider_id: "go", admitted: true, stale: false },
    { model_id: "d2", provider_id: "go", admitted: false, stale: false },
  ];
  const options = admittedModels(models, providers, admissions);
  assert.deepEqual(options.map((item) => item.id), ["d1"]);
  const groups = groupAdmittedModels(options, providers);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].provider_name, "OpenCode Go");
});

test("档位选项、跟随说明与设置的取值", () => {
  assert.deepEqual(tierOptions(["low", "high"], null).map((item) => item.value), ["low", "high"]);
  assert.equal(tierOptions(["low"], "max")[1].label, "max（不在该模型的支持档位内，请求按模型限制）");
  assert.equal(followDepartmentLabel(""), "跟随部门默认");
  assert.equal(followDepartmentLabel("glm-4.6"), "跟随部门默认（当前：glm-4.6）");
  assert.equal(currentEffectiveLabel(null), "");
  assert.equal(currentEffectiveLabel({ state: "unset" }), "未设置");
  assert.equal(currentEffectiveLabel({ state: "unusable", message: "准入已作废" }), "无法使用：准入已作废");
  assert.equal(currentEffectiveLabel({ state: "ok", model: "glm-4.6" }), "glm-4.6");
});

test("项目设置的模型取值与合并", () => {
  assert.equal(modelById([{ id: "d1", model: "glm-4.6" }], "d1").model, "glm-4.6");
  assert.equal(modelById([], "d1"), null);
  assert.deepEqual(DEPARTMENTS, ["product", "engineering", "quality"]);
});
