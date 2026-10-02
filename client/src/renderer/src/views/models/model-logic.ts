// 模型管理页的纯计算（原型 v8 设计说明第 9.1 节，工单 #93，设计说明第 4.3、4.4、5.1、7 节）。
// 这里只做取值与判断，不触碰网络与界面；页面组件引用这些函数，单元测试直接核对它们。

import type {
  CatalogAdmission,
  CatalogCapabilityTable,
  CatalogCredential,
  CatalogModel,
  CatalogProvider,
} from "../../api/generated/types.gen";

// 服务方案预置表里的一项（查询 catalog 的 presets.presets 交回；合同是开放字典，这里声明界面用到的字段）
export type ServicePreset = {
  id: string;
  name: string;
  auth: string;
  base_urls: Record<string, string>;
  models_url: string;
  docs_url: string;
  source: string;
  notes: string;
};

// 推理档位全集，由低到高（ADR-0006，与后端 REASONING_LEVELS 一致）
export const REASONING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

// 推理参数方式与它相符的协议（设计说明第 7.4 节）
export const REASONING_MODE_PROTOCOLS: Record<string, string[]> = {
  effort: ["responses", "chat_completions"],
  adaptive: ["messages"],
  budget: ["messages"],
};

// 推理参数方式的说明文字（设计说明第 7.4 节的上游参数）
export const REASONING_MODE_LABELS: Record<string, string> = {
  effort: "effort（请求带档位名）",
  adaptive: "adaptive（Messages 的自适应思考）",
  budget: "budget（Messages 的思考预算）",
};

// 三种协议与预置表 base_urls 的键一致；fake 只在测试与演示启动时出现，界面不提供
export const UI_PROTOCOLS = ["responses", "chat_completions", "messages"] as const;

export const PROTOCOL_LABELS: Record<string, string> = {
  responses: "Responses",
  chat_completions: "Chat Completions",
  messages: "Anthropic Messages",
};

export const DEPARTMENT_LABELS: Record<string, string> = {
  product: "产品",
  engineering: "工程",
  quality: "质检",
};

// 「自定义」表示不使用预置表（设计说明第 4.1 节），连接保存空的 preset_id
export const CUSTOM_PRESET_ID = "";

// 一份服务方案在某协议下的请求基址；自定义方案没有预置地址
export function presetBaseUrlFor(preset: ServicePreset | null, protocol: string): string {
  return preset?.base_urls?.[protocol] ?? "";
}

export function presetById(presets: ServicePreset[], presetId: string): ServicePreset | null {
  return presets.find((item) => item.id === presetId) ?? null;
}

// 凭据状态（设计说明第 9.1 节）：缺失，或来源为内存、环境、.env
export function credentialStatusLabel(credential: CatalogCredential): string {
  if (!credential.configured) {
    return "缺失";
  }
  switch (credential.source) {
    case "override":
      return "来源：内存";
    case "env":
      return "来源：环境";
    case "dotenv":
      return "来源：.env";
    case "none":
      return "不需要凭据";
    default:
      return `来源：${credential.source}`;
  }
}

// 准入摘要（设计说明第 9.1 节）：按连接统计「已准入 x · 候选 y」。
// 已准入且未作废的定义计入已准入，其余定义计入候选
export function admissionSummary(provider: CatalogProvider, admissions: CatalogAdmission[]): { admitted: number; candidates: number } {
  const byModel: Record<string, CatalogAdmission> = {};
  for (const admission of admissions) {
    if (admission.provider_id === provider.id) {
      byModel[admission.model_id] = admission;
    }
  }
  let admitted = 0;
  for (const model of provider.models) {
    const record = byModel[model.id];
    if (record?.admitted && !record.stale) {
      admitted += 1;
    }
  }
  return { admitted, candidates: provider.models.length - admitted };
}

export function admissionFor(model: CatalogModel, admissions: CatalogAdmission[]): CatalogAdmission | null {
  return admissionOf(model.provider_id, model.id, admissions);
}

// 表单的行只有 id 与所属连接，按这两个值取准入记录
export function admissionOf(providerId: string, modelId: string, admissions: CatalogAdmission[]): CatalogAdmission | null {
  return admissions.find((item) => item.provider_id === providerId && item.model_id === modelId) ?? null;
}

// 准入列的显示（设计说明第 9.1 节）：测试时间与实际返回的模型；未准入显示「候选」，作废显示作废
export function admissionLabel(admission: CatalogAdmission | null): string {
  if (!admission || !admission.admitted) {
    return "候选";
  }
  if (admission.stale) {
    return "候选（准入已作废）";
  }
  return `已准入：${admission.admitted_at ?? ""}${admission.admitted_model ? ` · ${admission.admitted_model}` : ""}`;
}

// 容量是否有效：窗口与输出上限有值，输出上限不大于窗口（设计说明第 4.3 节）
export function rowCapacityValid(row: { context_window: number | null; max_output_tokens: number | null }): boolean {
  if (row.context_window === null || row.max_output_tokens === null) {
    return false;
  }
  return row.max_output_tokens > 0 && row.max_output_tokens <= row.context_window;
}

// 未「接受」或修改的行不能保存：这一行的容量必须已确认且有效
export function canSaveRows(rows: { context_window: number | null; max_output_tokens: number | null; capacity_confirmed: boolean }[]): boolean {
  return rows.every((row) => row.capacity_confirmed && rowCapacityValid(row));
}

// 预填一条模型访问定义（设计说明第 4.3 节）：上游模型列表优先，其次模型能力表，都没有时留空；
// 输入方式取能力表（含 image → 文本与图像，否则只有文本），能力表没有记录或自定义方案时只有文本。
// 返回每个值的来源，界面据此标明（上游模型列表 / 能力表 / 默认）
export type PrefillSource = "models_url" | "capability_table" | "default";

// 事件 catalog_candidates_collected 里的一个候选：来源字段由后端按第 4.3 节给出
export type UpstreamCandidate = {
  id: string;
  context_window?: number | null;
  max_output_tokens?: number | null;
  context_window_source?: string;
  max_output_tokens_source?: string;
  input_modalities?: string[];
  input_modalities_source?: string;
};

export type PrefillValue = {
  context_window: number | null;
  max_output_tokens: number | null;
  input_modalities: string[];
  sources: {
    context_window: PrefillSource | null;
    max_output_tokens: PrefillSource | null;
    input_modalities: PrefillSource;
  };
};

function capabilityEntry(table: CatalogCapabilityTable, presetId: string, modelId: string): Record<string, unknown> | null {
  if (!presetId) {
    return null;
  }
  const entries = table.presets?.[presetId];
  if (!Array.isArray(entries)) {
    return null;
  }
  for (const entry of entries) {
    if (entry.model === modelId) {
      return entry;
    }
  }
  return null;
}

export function prefillModel(modelId: string, upstream: UpstreamCandidate | null, table: CatalogCapabilityTable, presetId: string): PrefillValue {
  const entry = capabilityEntry(table, presetId, modelId);
  const upstreamWindow = upstream?.context_window ?? null;
  const upstreamOutput = upstream?.max_output_tokens ?? null;
  const tableWindow = typeof entry?.context_window === "number" ? entry.context_window : null;
  const tableOutput = typeof entry?.max_output_tokens === "number" ? entry.max_output_tokens : null;

  const contextWindow = upstreamWindow ?? tableWindow;
  const windowSource: PrefillSource | null =
    upstreamWindow !== null ? "models_url" : tableWindow !== null ? "capability_table" : null;

  const maxOutput = upstreamOutput ?? tableOutput;
  const outputSource: PrefillSource | null =
    upstreamOutput !== null ? "models_url" : tableOutput !== null ? "capability_table" : null;

  const listed = entry?.input_modalities;
  const hasImage = Array.isArray(listed) && listed.includes("image");
  return {
    context_window: contextWindow,
    max_output_tokens: maxOutput,
    input_modalities: hasImage ? ["text", "image"] : ["text"],
    sources: {
      context_window: windowSource,
      max_output_tokens: outputSource,
      input_modalities: entry ? "capability_table" : "default",
    },
  };
}

// 默认档位只能从已选的支持档位中选择（设计说明第 4.3、7.1 节）
export function defaultLevelOptions(supported: string[]): string[] {
  return REASONING_LEVELS.filter((level) => supported.includes(level));
}

// 推理参数方式只列出与协议相符的选项（设计说明第 7.4 节）
export function reasoningModeOptions(protocol: string): string[] {
  return Object.keys(REASONING_MODE_PROTOCOLS).filter((mode) => REASONING_MODE_PROTOCOLS[mode].includes(protocol));
}

export type ProviderChange = Pick<CatalogProvider, "base_url" | "credential_ref" | "protocol">;

export type ModelChange = Pick<CatalogModel, "id" | "model" | "reasoning_mode">;

export type BindingEntry = { provider_id: string; model_id: string };

// 保存会作废准入的修改之前，按第 4.4 节列出受影响的引用方（部门默认的哪个部门）。
// 判断的字段：连接一侧的地址、凭据引用、协议；定义一侧的上游模型 ID、推理参数方式
export function affectedReferences(
  provider: CatalogProvider,
  before: ProviderChange,
  models: ModelChange[],
  modelsBefore: ModelChange[],
  bindings: Record<string, BindingEntry>,
): string[] {
  const providerAffected =
    provider.base_url !== before.base_url ||
    provider.credential_ref !== before.credential_ref ||
    provider.protocol !== before.protocol;
  const affectedModels: Record<string, boolean> = {};
  for (const model of models) {
    const previous = modelsBefore.find((item) => item.id === model.id);
    if (previous && (previous.model !== model.model || previous.reasoning_mode !== model.reasoning_mode)) {
      affectedModels[model.id] = true;
    }
  }
  const affected: string[] = [];
  for (const [department, binding] of Object.entries(bindings)) {
    if (binding.provider_id !== provider.id) {
      continue;
    }
    if (providerAffected || affectedModels[binding.model_id]) {
      affected.push(department);
    }
  }
  return affected;
}

// 数字输入：空文本交回 null（窗口与「未选择」的档位都留空），非数字也交回 null，由校验拒绝
export function intFromInput(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isInteger(value) ? value : null;
}

// 预填来源的标注文字（设计说明第 4.3 节「界面标明每个预填值的来源」）
export const PREFILL_SOURCE_LABELS: Record<string, string> = {
  models_url: "上游模型列表",
  capability_table: "能力表",
  default: "默认",
};

// 一条测试的标识：连接测试按连接，模型测试按定义；事件回来时按同一把键找回界面上的「测试中」
export function testKey(kind: "connection" | "model", providerId: string, modelId: string | null): string {
  return kind === "connection" ? `connection:${providerId}` : `model:${modelId}`;
}

// 保存会作废准入时的提示文字（第 4.4 节）：列出受影响的部门默认；进行中的事项由事项页面显示
export function impactNotice(departments: string[]): string {
  if (departments.length === 0) {
    return "";
  }
  const names = departments.map((item) => DEPARTMENT_LABELS[item] ?? item).join("、");
  return `保存以后这些部门默认引用的准入作废，回到候选：${names}。引用保留，相关角色的下一次模型请求不发送，事项进入待恢复。`;
}

export type ModelOption = { id: string; model: string; provider_id: string; provider_name: string };

// 部门默认与项目设置的模型选项：按连接分组的已准入定义（准入作废的不列出，第 9.1 节）
export function admittedOptions(models: CatalogModel[], providers: CatalogProvider[], admissions: CatalogAdmission[]): ModelOption[] {
  return models
    .filter((model) => {
      const record = admissionFor(model, admissions);
      return record !== null && record.admitted && !record.stale;
    })
    .map((model) => ({
      id: model.id,
      model: model.model,
      provider_id: model.provider_id,
      provider_name: providers.find((item) => item.id === model.provider_id)?.name ?? model.provider_id,
    }))
    .sort((left, right) => `${left.provider_name}/${left.id}`.localeCompare(`${right.provider_name}/${right.id}`));
}

// 部门默认的档位选项：来自所选模型的声明；已保存的档位不在声明内时额外保留并标明按模型限制（第 7.3 节）
export function tierOptions(supported: string[], saved: string | null | undefined): { value: string; label: string }[] {
  const options = defaultLevelOptions(supported).map((level) => ({ value: level, label: level }));
  if (saved && !options.some((item) => item.value === saved)) {
    options.push({ value: saved, label: `${saved}（不在该模型的支持档位内，请求按模型限制）` });
  }
  return options;
}

// —— 添加与编辑表单的状态（纯数据；form.tsx 只渲染它，判断都在这里） ——

export type FormRow = {
  // 表格行的稳定标识：已存在的定义用它的 id，新增行用随机值
  key: string;
  id: string;
  model: string;
  // 窗口与输出上限保存为文本，空字符串表示没有值（未「接受」时留空）
  context_window: string;
  max_output_tokens: string;
  capacity_confirmed: boolean;
  accepts_required_tool_call: boolean;
  image_input: boolean;
  reasoning_levels: string[];
  default_reasoning_level: string;
  reasoning_mode: string;
  // 能力来源的标注：预填值来自哪里就写哪里（第 4.3 节「界面标明每个预填值的来源」）
  capability_source: string;
  // 已保存的行提交时带着容量值即视为已确认；新增行必须由用户点「接受」
  saved: boolean;
};

export type FormState = {
  id: string;
  name: string;
  protocol: string;
  base_url: string;
  credential_ref: string;
  preset_id: string;
  models_url: string;
  timeout_sec: string;
  rows: FormRow[];
};

// 一次采集回来的候选清单（事件 catalog_candidates_collected 的 payload）
export type CandidateState = {
  status: "ok" | "unknown";
  source_url: string;
  fetched_at: string;
  candidates: UpstreamCandidate[];
  error: string | null;
};

export function numberToText(value: number | null): string {
  return value === null ? "" : String(value);
}

// 预填值的来源标注（第 4.3 节「界面标明每个预填值的来源」）
export function prefillSourceText(prefill: PrefillValue): string {
  const parts: string[] = [];
  if (prefill.sources.context_window) {
    parts.push(`窗口：${PREFILL_SOURCE_LABELS[prefill.sources.context_window] ?? prefill.sources.context_window}`);
  }
  if (prefill.sources.max_output_tokens) {
    parts.push(`输出上限：${PREFILL_SOURCE_LABELS[prefill.sources.max_output_tokens] ?? prefill.sources.max_output_tokens}`);
  }
  parts.push(`输入方式：${PREFILL_SOURCE_LABELS[prefill.sources.input_modalities] ?? prefill.sources.input_modalities}`);
  return parts.join(" · ");
}

// 点击候选建立的一行：容量与输入方式按第 4.3 节预填并标明来源，容量未经用户「接受」以前不能保存
export function rowFromCandidate(candidate: UpstreamCandidate, table: CatalogCapabilityTable, presetId: string): FormRow {
  const prefill = prefillModel(candidate.id, candidate, table, presetId);
  return {
    key: crypto.randomUUID(),
    id: candidate.id,
    model: candidate.id,
    context_window: numberToText(prefill.context_window),
    max_output_tokens: numberToText(prefill.max_output_tokens),
    capacity_confirmed: false,
    accepts_required_tool_call: true,
    image_input: prefill.input_modalities.includes("image"),
    reasoning_levels: [],
    default_reasoning_level: "",
    reasoning_mode: "",
    capability_source: prefillSourceText(prefill),
    saved: false,
  };
}

// 手动添加的一行：没有预填，容量留空，来源标为手动
export function rowFromManual(index: number): FormRow {
  return {
    key: crypto.randomUUID(),
    id: `model-${index + 1}`,
    model: "",
    context_window: "",
    max_output_tokens: "",
    capacity_confirmed: false,
    accepts_required_tool_call: true,
    image_input: false,
    reasoning_levels: [],
    default_reasoning_level: "",
    reasoning_mode: "",
    capability_source: "手动",
    saved: false,
  };
}

// 新增 Provider 时的表单：标题为「添加 Provider 配置」，模型访问定义表为空（设计说明第 9.1 节）
export function emptyFormState(): FormState {
  return {
    id: "", name: "", protocol: "responses", base_url: "", credential_ref: "",
    preset_id: CUSTOM_PRESET_ID, models_url: "", timeout_sec: "60", rows: [],
  };
}

// 编辑已有连接：按连接保存的服务方案恢复选中项，协议与地址取保存值（设计说明第 9.1 节）
export function formStateFromProvider(provider: CatalogProvider): FormState {
  return {
    id: provider.id,
    name: provider.name,
    protocol: provider.protocol,
    base_url: provider.base_url,
    credential_ref: provider.credential_ref,
    preset_id: provider.preset_id,
    models_url: provider.models_url,
    timeout_sec: String(provider.timeout_sec),
    rows: provider.models.map((model) => ({
      key: model.id,
      id: model.id,
      model: model.model,
      context_window: numberToText(model.context_window),
      max_output_tokens: numberToText(model.max_output_tokens),
      capacity_confirmed: true,
      accepts_required_tool_call: model.accepts_required_tool_call,
      image_input: model.input_modalities.includes("image"),
      reasoning_levels: [...model.reasoning_levels],
      default_reasoning_level: model.default_reasoning_level ?? "",
      reasoning_mode: model.reasoning_mode,
      capability_source: model.capability_source || "手动",
      saved: true,
    })),
  };
}

// 一行是否可保存：容量有值且有效，且已确认（新增行要点「接受」，已保存的行带着容量值即视为已确认）
export function rowSavable(row: FormRow): boolean {
  const capacity = {
    context_window: intFromInput(row.context_window),
    max_output_tokens: intFromInput(row.max_output_tokens),
  };
  const confirmed = row.saved || row.capacity_confirmed;
  return canSaveRows([{ ...capacity, capacity_confirmed: confirmed }]);
}

export function rowsSavable(rows: FormRow[]): boolean {
  return rows.every(rowSavable);
}

// 用户修改窗口或输出上限：视为已确认；新增行的来源标注改成手动（预填值已被替换）
export function patchRowCapacity(row: FormRow, field: "context_window" | "max_output_tokens", text: string): Partial<FormRow> {
  const patch: Partial<FormRow> = { capacity_confirmed: true };
  patch[field] = text;
  if (!row.saved) {
    patch.capability_source = "手动";
  }
  return patch;
}

// 默认档位只在属于支持档位时写入；不在时按「未选择」提交，避免把作废的选择留在目录里
function defaultLevelFor(row: FormRow): string | null {
  return row.reasoning_levels.includes(row.default_reasoning_level) ? row.default_reasoning_level : null;
}

export function rowToModelInput(row: FormRow): Record<string, unknown> {
  return {
    id: row.id,
    model: row.model,
    context_window: intFromInput(row.context_window),
    max_output_tokens: intFromInput(row.max_output_tokens),
    capability_source: row.capability_source,
    capacity_confirmed: row.capacity_confirmed,
    accepts_required_tool_call: row.accepts_required_tool_call,
    input_modalities: row.image_input ? ["text", "image"] : ["text"],
    reasoning_levels: row.reasoning_levels,
    default_reasoning_level: defaultLevelFor(row),
    reasoning_mode: row.reasoning_mode,
  };
}

export function providerInputFromForm(state: FormState): Record<string, unknown> {
  const timeout = intFromInput(state.timeout_sec);
  return {
    id: state.id,
    name: state.name,
    protocol: state.protocol,
    base_url: state.base_url,
    credential_ref: state.credential_ref,
    timeout_sec: timeout === null ? 60 : timeout,
    preset_id: state.preset_id,
    models_url: state.models_url,
  };
}

// 连接测试的可用性：连接与服务方案都没有模型列表地址时不提供连接测试（第 4.3 节）
export function connectionTestable(state: { models_url: string }, preset: ServicePreset | null): boolean {
  return state.models_url.trim() !== "" || preset !== null;
}

// 部门默认与项目设置的模型选项：按连接分组的已准入定义（第 9.1 节）
export function admittedModels(
  models: CatalogModel[],
  providers: CatalogProvider[],
  admissions: CatalogAdmission[],
): ModelOption[] {
  return admittedOptions(models, providers, admissions);
}
