// 模型管理页的纯计算（原型 v8 设计说明第 9.1 节，工单 #93，设计说明第 4.3、4.4、5.1、7 节）。
// 这里只做取值与判断，不触碰网络与界面；页面组件引用这些函数，单元测试直接核对它们。

import type {
  CatalogAdmission,
  CatalogBinding,
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

// 配置状态（Provider 目录文件的读取状态）：保存成功以后显示已加载，不出现英文（工单 #301）
export const CONFIG_STATE_LABELS: Record<string, string> = {
  loaded: "已加载",
  empty: "空目录",
  missing: "没有文件",
  invalid: "文件无法解析",
  deleted: "文件已删除",
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

// 准入列的显示（设计说明第 9.1 节）：测试时间与实际返回的模型；未准入与作废都显示「候选」。
// 视图里 admitted 与 stale 互斥：作废的准入 admitted 为假、stale 为真（#90）
export function admissionLabel(admission: CatalogAdmission | null): string {
  if (!admission || !admission.admitted) {
    return admission?.stale ? "候选（准入已作废）" : "候选";
  }
  return `已准入：${admission.admitted_at ?? ""}${admission.admitted_model ? ` · ${admission.admitted_model}` : ""}`;
}

// 容量的一行取值：窗口与输出上限（设计说明第 4.3 节）
type CapacityValues = { context_window: number | null; max_output_tokens: number | null };

// 容量的问题文字：缺少哪一项或哪一项的关系不成立就写明哪一项，没有问题时为空（工单 #294）
// 界面在「接受容量」旁显示它，目录文档校验用同一个判断，两处的规则不再分开
export function capacityIssueText(row: CapacityValues): string {
  const window = row.context_window;
  const output = row.max_output_tokens;
  if (window === null && output === null) {
    return "缺少窗口与输出上限";
  }
  if (window === null) {
    return "缺少窗口";
  }
  if (output === null) {
    return "缺少输出上限";
  }
  if (output <= 0) {
    return "输出上限必须是正整数";
  }
  if (output > window) {
    return "输出上限不能大于窗口";
  }
  return "";
}

// 容量是否有效：窗口与输出上限有值，输出上限不大于窗口（设计说明第 4.3 节）
export function rowCapacityValid(row: CapacityValues): boolean {
  return capacityIssueText(row) === "";
}

// 未「接受」或修改的行不能保存：这一行的容量必须已确认且有效
export function canSaveRows(rows: { context_window: number | null; max_output_tokens: number | null; capacity_confirmed: boolean }[]): boolean {
  return rows.every((row) => row.capacity_confirmed && rowCapacityValid(row));
}

// 表单能否构成一份合法的目录文档（第 4.6 节的必填项与容量关系）：影响查询只对合法的拟议修改发问。
// 容量按第 4.3 节的同一份判断：窗口与输出上限都必须有值，输出上限不大于窗口
export function formDocumentValid(provider: { id: string; name: string; base_url: string }, rows: FormRow[]): boolean {
  if (provider.id.trim() === "" || provider.name.trim() === "" || provider.base_url.trim() === "") {
    return false;
  }
  return rows.every((row) => {
    if (row.id.trim() === "" || row.model.trim() === "") {
      return false;
    }
    // 推理档位声明的三项一起给出（第 7.1 节）：支持档位与默认档位不能在没有推理参数方式时单独出现
    if (row.reasoning_mode === "" && (row.reasoning_levels.length > 0 || row.default_reasoning_level !== "")) {
      return false;
    }
    return rowCapacityValid({
      context_window: intFromInput(row.context_window),
      max_output_tokens: intFromInput(row.max_output_tokens),
    });
  });
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
export function testKeyOf(payload: { kind: "connection" | "model"; provider_id: string; model_id: string | null }): string {
  return payload.kind === "connection" ? `connection:${payload.provider_id}` : `model:${payload.model_id}`;
}

// 一条测试结果的显示文字（工单 #294）：通过写用时与实际返回的模型，未通过写上游给出的原因；
// 模型行与连接卡片按它显示，用户不必去猜上一次测试的结果
// 连接测试写明读的是哪个模型列表地址：地址不对时不会让人误以为请求地址也通过了（工单 #302）
export function testText(payload: {
  kind: "connection" | "model";
  ok: boolean;
  error: string | null;
  elapsed_ms: number;
  actual_model?: string | null;
  admitted?: boolean | null;
  source_url?: string | null;
}): string {
  if (!payload.ok) {
    const failed = payload.kind === "model"
      ? `模型测试未通过：${payload.error ?? ""}`
      : `连接测试未通过：${payload.error ?? ""}`;
    return payload.kind === "connection" && payload.source_url
      ? `读取模型列表地址 ${payload.source_url} 时${failed}`
      : failed;
  }
  if (payload.kind === "model") {
    const actual = payload.actual_model ? `，实际返回 ${payload.actual_model}` : "";
    return `模型测试通过（${payload.elapsed_ms} 毫秒${actual}${payload.admitted ? "，已准入" : ""}）`;
  }
  return payload.source_url
    ? `已读取模型列表地址 ${payload.source_url}：连接测试通过（${payload.elapsed_ms} 毫秒）`
    : `连接测试通过（${payload.elapsed_ms} 毫秒）`;
}

// 保存会作废准入的影响列表与删除的引用方（设计说明第 4.4、4.5 节，工单 #94）。
// 数据来自应用层查询 catalog.change_impact（工单 #90），界面按它的结果弹确认框与列出引用方。
// 后端按第 4.4、4.5 节的规则算出受影响与将被删除的定义，并汇总部门默认与各项目的项目部门设置两层引用方。
export type ModelImpact = {
  // 保存会作废准入的模型访问定义，与删除 Provider 配置时将一并删除的定义
  impacted: string[];
  deletions: string[];
  // 引用方清单的显示文字：部门默认、各项目的项目部门设置与进行中事项（第 4.4、4.5 节）
  references: string[];
};

// 后端各引用方清单的一项：位置串与它的显示文字
type ImpactDepartmentDefault = { department: string; model_id: string };
type ImpactProjectSetting = { project_id: string; project_name: string; department: string; model_id: string };
type ImpactWorkItem = { project_id: string; project_name: string; work_item_id: string; title: string; department: string };

// 把应用层返回的影响结果（ChangeImpact）读成界面形态：受影响与被删除的定义标识、引用方清单（按第 4.4、4.5 节）
export function collectImpact(impact: {
  impacted?: { model_id: string }[];
  deletions?: { model_id: string }[];
  department_defaults?: ImpactDepartmentDefault[];
  project_settings?: ImpactProjectSetting[];
  work_items?: ImpactWorkItem[];
}): ModelImpact {
  const references: string[] = [];
  for (const item of impact.department_defaults ?? []) {
    references.push(`部门默认：${DEPARTMENT_LABELS[item.department] ?? item.department}`);
  }
  for (const item of impact.project_settings ?? []) {
    const department = DEPARTMENT_LABELS[item.department] ?? item.department;
    references.push(`项目部门设置：${item.project_name}（${department}）`);
  }
  for (const item of impact.work_items ?? []) {
    const department = DEPARTMENT_LABELS[item.department] ?? item.department;
    references.push(`进行中事项：${item.project_name} · ${item.title}（${department}）`);
  }
  return {
    impacted: (impact.impacted ?? []).map((item) => item.model_id),
    deletions: (impact.deletions ?? []).map((item) => item.model_id),
    references,
  };
}

// 保存会作废准入时的确认文字（设计说明第 4.4 节最后一段）：列出受影响的定义、引用方与进行中事项；
// 没有受影响字段或没有引用方时为空，界面据此决定是否弹确认框
export function confirmImpactText(impact: ModelImpact | null): string {
  if (impact === null || impact.references.length === 0
    || (impact.impacted.length === 0 && impact.deletions.length === 0)) {
    return "";
  }
  const definitions = impact.impacted.length > 0 ? impact.impacted.join("、") : impact.deletions.join("、");
  const references = impact.references.join("；");
  return `这次保存会让这些模型访问定义的准入作废，回到候选：${definitions}。`
    + `受影响的引用方：${references}。引用保留，相关角色的下一次模型请求不发送，事项进入待恢复。确认以后保存？`;
}

// 删除 Provider 配置的确认框文字（设计说明第 4.5 节）：被引用时列出引用方，拒绝删除；
// 没有引用时列出将一并删除的定义，确认以后删除
export function providerDeleteConfirmation(impact: ModelImpact | null): string {
  if (impact === null) {
    return "";
  }
  if (impact.references.length > 0) {
    return `这份 Provider 配置仍被引用，不能删除：${impact.references.join("；")}。`;
  }
  const deletions = impact.deletions.length === 0 ? "没有模型访问定义" : impact.deletions.join("、");
  return `删除这份 Provider 配置会一并删除它下面的模型访问定义：${deletions}。确认删除？`;
}

// 移除单条定义被引用时的文字（设计说明第 4.5 节）：列出引用方，拒绝移除
export function modelRemoveReferrers(impact: ModelImpact | null): string {
  if (impact === null || impact.references.length === 0) {
    return "";
  }
  return `这条模型访问定义仍被引用，不能移除：${impact.references.join("；")}。`;
}

// 引用准入已作废的定义时下拉框里保留它的显示（设计说明第 4.4 节表格：保留，显示「无法使用：准入已作废」）
export const STALE_ADMISSION_LABEL = "无法使用：准入已作废";

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

// 模型访问定义 ID 的字符规则与后端 store.py 的简单标识符校验一致：
// 首字符是字母或数字，其余只允许字母、数字、点、减号、下划线、冒号。
// 上游模型 ID 常带「/」（例如 cbcn/deepseek-v4.1-flash），这种写法保存会被拒（工单 #302）
export function sanitizeModelId(value: string): string {
  return value.trim().replace(/[^A-Za-z0-9._:-]+/g, "-").replace(/^[-._:-]+/, "");
}

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

// 点击候选建立的一行：容量与输入方式按第 4.3 节预填并标明来源，容量未经用户「接受」以前不能保存。
// 访问定义 ID 预填为符合规则的写法（上游模型 ID 带「/」时换成「-」，工单 #302），
// 上游模型 ID 保持上游写法原样：请求发往上游时用的就是它
export function rowFromCandidate(candidate: UpstreamCandidate, table: CatalogCapabilityTable, presetId: string): FormRow {
  const prefill = prefillModel(candidate.id, candidate, table, presetId);
  return {
    key: crypto.randomUUID(),
    id: sanitizeModelId(candidate.id) || candidate.id,
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

// 新增 Provider 时的表单：标题为「添加 Provider 配置」，模型访问定义表为空（设计说明第 9.1 节）。
// 请求时限取目录合同的 default_timeout_sec：默认值只有后端一份，客户端不再各写一个数（工单 #294）
export function emptyFormState(defaultTimeoutSec: number): FormState {
  return {
    id: "", name: "", protocol: "responses", base_url: "", credential_ref: "",
    preset_id: CUSTOM_PRESET_ID, models_url: "", timeout_sec: String(defaultTimeoutSec), rows: [],
  };
}

export function normalizeBaseUrl(value: string): string {
  const address = value.trim();
  return address === "" || /^[a-z][a-z\d+.-]*:\/\//i.test(address) ? address : `https://${address}`;
}

function hostDefaults(address: string): Pick<FormState, "id" | "name" | "credential_ref"> | null {
  if (!address || !URL.canParse(normalizeBaseUrl(address))) return null;
  const host = new URL(normalizeBaseUrl(address)).hostname;
  const id = host.toLowerCase();
  const ref = id.toUpperCase().replace(/[^A-Z0-9]+/g, "_");
  return { id, name: id, credential_ref: `${/^[A-Z]/.test(ref) ? "" : "HOST_"}${ref}_KEY` };
}

export function formPatchForPreset(state: FormState, preset: ServicePreset | null): Partial<FormState> {
  const defaults = preset ? { id: preset.id, name: preset.name,
    credential_ref: `${preset.id.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}_KEY` } : null;
  return { preset_id: preset?.id ?? CUSTOM_PRESET_ID, base_url: presetBaseUrlFor(preset, state.protocol),
    models_url: "", ...(defaults ?? { id: "", name: "", credential_ref: "" }) };
}

export function formPatchForBaseUrl(state: FormState, address: string): Partial<FormState> {
  const previous = hostDefaults(state.base_url);
  const next = hostDefaults(address);
  const patch: Partial<FormState> = { base_url: address };
  if (!next) return patch;
  for (const key of ["id", "name", "credential_ref"] as const) {
    if (!state[key] || state[key] === previous?.[key]) patch[key] = next[key];
  }
  return patch;
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

// 表单的一份连接内容：请求时限留空时不提交这个字段，由后端 ProviderInput 的默认值决定（工单 #294）；
// 地址提交前补全协议头，粘贴后直接点「添加」也能保存（设计说明第 4.2 节）
export function providerInputFromForm(state: FormState): Record<string, unknown> {
  const timeout = intFromInput(state.timeout_sec);
  return {
    id: state.id,
    name: state.name,
    protocol: state.protocol,
    base_url: normalizeBaseUrl(state.base_url),
    credential_ref: state.credential_ref,
    ...(timeout === null ? {} : { timeout_sec: timeout }),
    preset_id: state.preset_id,
    models_url: state.models_url,
  };
}

// 自定义服务使用连接地址加 /models；内置方案取预置的模型列表地址。
export function connectionTestable(state: { base_url: string; models_url: string }, preset: ServicePreset | null): boolean {
  return state.models_url.trim() !== "" || state.base_url.trim() !== "" || preset !== null;
}

// 部门默认与项目设置的模型选项：按连接分组的已准入定义（第 9.1 节）
export function admittedModels(
  models: CatalogModel[],
  providers: CatalogProvider[],
  admissions: CatalogAdmission[],
): ModelOption[] {
  return admittedOptions(models, providers, admissions);
}

// 选择的取值与显示（模型管理设计说明第 9.2 节）：
// 模型下拉第一项为「跟随部门默认（当前：…）」，其后是按连接分组的已准入定义；
// 选择第一项即清除项目的模型选择。这里把选项文本与「当前」说明集中在一处，
// 部门设置弹窗与设置页的部门设置共用同一份计算。
export type AdmissionGroup = { provider_id: string; provider_name: string; options: ModelOption[] };

// 已准入定义按连接分组：组名取连接名称，组内按上游模型 ID 排序
export function groupAdmittedModels(models: ModelOption[], providers: CatalogProvider[]): AdmissionGroup[] {
  const groups: AdmissionGroup[] = [];
  for (const provider of providers) {
    const options = models
      .filter((model) => model.provider_id === provider.id)
      .sort((left, right) => left.model.localeCompare(right.model));
    if (options.length > 0) {
      groups.push({ provider_id: provider.id, provider_name: provider.name, options });
    }
  }
  return groups;
}

// 跟随部门的选项文本：待保存的选择为空时写明当前生效的模型（来源与模型名）
export function followDepartmentLabel(current: string): string {
  return current === "" ? "跟随部门默认" : `跟随部门默认（当前：${current}）`;
}

// 当前生效模型的说明：取出生效状态与来源，供跟随选项展示。
// 生效模型由 department.workspace 的 effective 给出，来源文案与选择来源一致
export function currentEffectiveLabel(effective: { state: string; model?: string | null; message?: string | null;
  selection_source?: string | null } | null): string {
  if (effective === null) {
    return "";
  }
  if (effective.state === "unset") {
    return "未设置";
  }
  if (effective.state === "unusable") {
    return `无法使用：${effective.message ?? ""}`;
  }
  return effective.model || "";
}

// 设置的模型取值（连接/定义）：写入项目的模型用它的引用，未写入时为空（跟随部门默认）
export function selectionValue(providerId: string | null | undefined, modelId: string | null | undefined): string {
  return providerId && modelId ? `${providerId}/${modelId}` : "";
}

// 把取值拆回连接与定义：空值表示「跟随部门默认」（清除项目的模型选择）
export function selectionPair(value: string): { provider_id: string | null; model_id: string | null } {
  if (value === "") {
    return { provider_id: null, model_id: null };
  }
  const [provider_id, ...rest] = value.split("/");
  return { provider_id, model_id: rest.join("/") };
}

// 一组设置按第 5.3 节取得的模型访问定义：项目设置写入了就用它，否则用部门默认（catalog 的 bindings）
export function mergedModelId(projectModelId: string | null | undefined, department: string,
  bindings: Record<string, CatalogBinding> | undefined): string {
  if (projectModelId) {
    return projectModelId;
  }
  return bindings?.[department]?.model_id ?? "";
}

// 从目录读出模型的上游名称与推理档位声明：供设置页的跟随说明与档位选项使用。
// 模型不在目录里时返回空
export function modelById(models: CatalogModel[], modelId: string): CatalogModel | null {
  return models.find((item) => item.id === modelId) ?? null;
}

// 一次保存以后要提示的生效说明（设计说明第 9.2 节）
export const DEPARTMENT_SAVE_NOTICE = "从本部门下一次模型请求起生效";

// 连接保存成功以后的提示（工单 #302）：添加与保存两种来源用词不同；表单收起以后仍要看得见
export function saveSuccessText(mode: "add" | "edit"): string {
  return mode === "add" ? "已添加 Provider 配置。" : "已保存 Provider 配置。";
}
