// 模型管理页的纯计算（工单 #1297，模型管理设计说明「模型访问定义与准入」、「删除」、「模型管理页」、「用词」）。
// 这里只做取值与判断，不触碰网络与界面；页面组件引用这些函数，单元测试直接核对它们。
//
// 主路径（连接服务 → 搜索筛选候选 → 勾选即补全并验证 → 部门使用）不在客户端预填参数、
// 也不自己判断准入：协议、窗口、输出上限与准入都由服务端给出，这里按服务端的值渲染。

import type {
  CatalogAdmission,
  CatalogBinding,
  CatalogCandidate,
  CatalogModel,
  CatalogProvider,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure.ts";
import { departmentName } from "../project/labels.ts";

// 推理档位全集，由低到高（模型管理设计说明「档位与声明」，与后端 REASONING_LEVELS 一致）
export const REASONING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

// 推理参数方式与它相符的协议
export const REASONING_MODE_PROTOCOLS: Record<string, string[]> = {
  effort: ["responses", "chat_completions"],
  adaptive: ["messages"],
  budget: ["messages"],
};

// 推理参数方式的说明文字（的上游参数）
export const REASONING_MODE_LABELS: Record<string, string> = {
  effort: "effort（请求带档位名）",
  adaptive: "adaptive（Messages 的自适应思考）",
  budget: "budget（Messages 的思考预算）",
};

// 新建的访问定义预填的协议（docs/design/model-management.md「模型访问定义与准入」）
export const DEFAULT_PROTOCOL = "chat_completions";

export const PROTOCOL_LABELS: Record<string, string> = {
  responses: "Responses",
  chat_completions: "Chat Completions",
  messages: "Anthropic Messages",
};

// 部门清单与中文名不在这里写死：部门默认可的部门取自这一版加载的定义（catalog 查询的 departments，
// 工单 #1457）；旧数据里不在定义里的部门按标识显示，调用处也可以给出显示名

// 预填值的来源标注（docs/design/model-management.md「模型访问定义与准入」「界面标明每个预填值的来源」）
export const SOURCE_LABELS: Record<string, string> = {
  models_url: "上游模型列表",
  capability_table: "能力表",
  preset_default: "服务方案默认",
  default: "默认",
  manual: "手动",
};

// 目录文件状态（工单 #301）
export const CONFIG_STATE_LABELS: Record<string, string> = {
  loaded: "已加载",
  empty: "空目录",
  missing: "没有文件",
  invalid: "文件无法解析",
  deleted: "文件已删除",
};

// ---------------------------------------------------------------------------
// 连接服务
// ---------------------------------------------------------------------------

// 地址没有协议头时补上 https://（服务端按同一份规则规范化）
export function normalizeBaseUrl(value: string): string {
  const address = value.trim();
  return address === "" || /^[a-z][a-z\d+.-]*:\/\//i.test(address) ? address : `https://${address}`;
}

// 「获取模型」按钮不可用时写明还缺哪一项（docs/design/model-management.md「模型管理页」）
// 已有凭据的连接不用再填 Key；缺地址或地址不成样子时先说地址
export function connectIssue(input: { address: string; api_key: string; credential_saved: boolean }): string {
  const address = input.address.trim();
  if (address === "") {
    return "填写服务地址";
  }
  const normalized = normalizeBaseUrl(address);
  if (!URL.canParse(normalized)) {
    return "服务地址要写成完整地址，例如 https://api.example.com/v1";
  }
  const protocol = new URL(normalized).protocol;
  if (protocol !== "http:" && protocol !== "https:") {
    return "服务地址要用 http 或 https";
  }
  if (!input.credential_saved && input.api_key.trim() === "") {
    return "填写 API Key";
  }
  return "";
}

// 凭据状态（docs/design/model-management.md「模型管理页」「Key 状态」）：已保存与来源
export function credentialSourceText(source: string): string {
  switch (source) {
    case "override":
      return "进程内存";
    case "dotenv":
      return ".env";
    case "env":
      return "环境";
    case "none":
      return "不需要凭据";
    default:
      return source;
  }
}

// 凭据状态（docs/design/model-management.md「模型管理页」「Key 状态」）：已保存与来源。
// 只读两样东西（工单 #237）：项目设置里的 MCP 服务器一节也用这句话，两处的凭据状态说法一致
export function credentialStatusLabel(credential: { configured: boolean; source: string }): string {
  if (!credential.configured) {
    return "缺失";
  }
  return `已保存 · 来源：${credentialSourceText(credential.source)}`;
}

// ---------------------------------------------------------------------------
// 获取模型列表这条操作的状态（工单 #1355）
// ---------------------------------------------------------------------------

// 一次已经发出去的获取：记下发起时这一份连接的结果（结果时间与状态）。
// 服务端的取得是后台任务，结果以后以事件与新的一份目录出现（工单 #1355 之前页面只靠一条事件复位，
// 事件丢了或者服务端提前结束不写事件时，页面就永远停在忙碌态）
export type PendingFetch = { provider_id: string; fetched_at: string | null; status: string | null };

// 这一份连接最近一次结果的样子：没有结果时两个值都是 null
function latestResult(provider: CatalogProvider): { fetched_at: string | null; status: string | null } {
  return provider.latest_candidates
    ? { fetched_at: provider.latest_candidates.fetched_at, status: provider.latest_candidates.status }
    : { fetched_at: null, status: null };
}

// 还在取候选的连接：目录里这一份的结果与发起时一样，就是这次的结果还没回来。
// 成功与失败都会换掉结果（失败写空的结果时间与 unknown），所以失败也在这里结束，页面回到可以操作的状态。
// 同一份连接连续失败两次时结果一样，这种情况由事件结束（页面另收 catalog_candidates_collected）
export function collectingProvider(
  catalog: { providers: CatalogProvider[] } | null,
  pending: PendingFetch | null,
): string | null {
  if (catalog === null || pending === null) {
    return null;
  }
  const provider = catalog.providers.find((item) => item.id === pending.provider_id);
  if (provider === undefined) {
    return null;
  }
  const latest = latestResult(provider);
  return latest.fetched_at === pending.fetched_at && latest.status === pending.status ? provider.id : null;
}

// 候选区是否暂停操作：只有页面自己发出的命令在途时暂停。
// 服务端在后台取候选时不暂停——取候选可能很久（真实服务上是一趟网络请求），页面不能因此不能用
// （工单 #1355：不能停在「按钮灰着但没写为什么」，也不能靠超时或刷新页面掩盖）
export function candidatesLocked(input: { busy: boolean; connecting: boolean }): boolean {
  return input.busy || input.connecting;
}

// 候选区上方的一句话：请求在途时写明在做什么；取候选时说明可以继续操作；空闲时没有这一句
export function fetchNoteText(input: { connecting: boolean; collecting: boolean }): string {
  if (input.connecting) {
    return "正在获取模型列表…连接与 Key 正在保存，这期间候选区暂停操作。";
  }
  if (input.collecting) {
    return "正在获取模型列表…结果回来以后候选会自动出现，这期间可以继续查看已有的候选。";
  }
  return "";
}

// 连接卡片上取候选时的一句话（工单 #1355：说明写在被操作的对象旁边）
export const CONNECTION_FETCHING_TEXT = "正在获取模型列表…结果会写在这张卡片里。";

// 连接卡片上「最近一次获取」的一行：成功写数量与时间，失败写服务端给的原因（docs/design/model-management.md「模型管理页」）
export function fetchSummaryOf(provider: CatalogProvider): { text: string; kind: "ok" | "error" | "none" } {
  const latest = provider.latest_candidates;
  if (!latest) {
    return { text: "还没有获取过模型列表。", kind: "none" };
  }
  if (latest.status === "ok") {
    return { text: `已获取 ${latest.candidates.length} 个模型 · ${latest.fetched_at}`, kind: "ok" };
  }
  return { text: latest.error ?? "获取模型列表失败。", kind: "error" };
}

// ---------------------------------------------------------------------------
// 候选：搜索、筛选与分批
// ---------------------------------------------------------------------------

// 候选的一行：上游模型列表里的一项，加上它属于哪一份连接
export type CandidateRow = {
  provider_id: string;
  provider_address: string;
  candidate: CatalogCandidate;
};

// 目录里的候选：各连接最近一次取到的模型，按连接汇总
export function candidateRowsOf(catalog: { providers: CatalogProvider[] }): CandidateRow[] {
  const rows: CandidateRow[] = [];
  for (const provider of catalog.providers) {
    const latest = provider.latest_candidates;
    if (!latest || latest.status !== "ok") {
      continue;
    }
    for (const candidate of latest.candidates) {
      rows.push({ provider_id: provider.id, provider_address: provider.base_url, candidate });
    }
  }
  return rows;
}

// 同一个上游模型 ID 在不同连接下是不同的候选，用连接与模型 ID 合成一把键
export function candidateKey(providerId: string, modelId: string): string {
  return `${providerId}::${modelId}`;
}

// 筛选的种类与说法（docs/design/model-management.md「模型访问定义与准入」「按支持图像、支持推理、全部模型与已选用筛选」）
export const CANDIDATE_FILTERS = [
  { id: "auto", label: "可自动配置" },
  { id: "vision", label: "支持图像" },
  { id: "reasoning", label: "支持推理" },
  { id: "all", label: "全部模型" },
  { id: "selected", label: "已选择" },
] as const;

export type CandidateFilterId = (typeof CANDIDATE_FILTERS)[number]["id"];

// 每次显示一批：先 8 个，之后每次再显示 12 个（docs/design/model-management.md「模型访问定义与准入」）
export const FIRST_BATCH = 8;
export const MORE_BATCH = 12;

// 容量已知：窗口与输出上限都有值（docs/design/model-management.md「模型访问定义与准入」「可自动配置」）
export function capacityKnown(candidate: CatalogCandidate): boolean {
  return typeof candidate.context_window === "number" && typeof candidate.max_output_tokens === "number";
}

// 候选能不能选用：上游明确说输出不是文本的不能选（docs/design/model-management.md「模型访问定义与准入」）
export function candidateApplicable(candidate: CatalogCandidate): boolean {
  return candidate.applicable !== false;
}

// 容量未知时写明缺哪一项（docs/design/model-management.md「模型访问定义与准入」）
export function capacityMissingText(missing: readonly string[]): string {
  const window = missing.includes("context_window");
  const output = missing.includes("max_output_tokens");
  if (window && output) {
    return "缺少窗口与输出上限";
  }
  if (window) {
    return "缺少窗口";
  }
  if (output) {
    return "缺少输出上限";
  }
  return "";
}

// 用户手填的容量能不能用：两项都要有值，输出上限不大于窗口（docs/design/model-management.md「模型访问定义与准入」）
// 不能用时写明哪一项不对，页面把它写在这一行旁边
export function capacityInputIssue(window: number | null, output: number | null): string {
  if (window === null && output === null) {
    return "填写窗口与输出上限";
  }
  if (window === null) {
    return "填写窗口";
  }
  if (output === null) {
    return "填写输出上限";
  }
  if (output <= 0) {
    return "输出上限必须是正整数";
  }
  if (output > window) {
    return "输出上限不能大于窗口";
  }
  return "";
}

// 搜索：按名称、提供方与上游模型 ID 匹配
export function matchesSearch(row: CandidateRow, search: string): boolean {
  const text = search.trim().toLowerCase();
  if (text === "") {
    return true;
  }
  const provider = row.candidate.provider ?? "";
  return `${row.candidate.id} ${provider} ${row.provider_address}`.toLowerCase().includes(text);
}

// 筛选：可自动配置、支持图像、支持推理、全部模型与已选择
export function matchesFilter(row: CandidateRow, filter: CandidateFilterId, selected: ReadonlySet<string>): boolean {
  const candidate = row.candidate;
  switch (filter) {
    case "auto":
      return candidateApplicable(candidate) && capacityKnown(candidate);
    case "vision":
      return candidate.input_modalities.includes("image");
    case "reasoning":
      return candidate.reasoning === true;
    case "selected":
      return selected.has(candidateKey(row.provider_id, candidate.id));
    case "all":
    default:
      return true;
  }
}

// 搜索与筛选一起：两边都过了才留下
export function filterCandidates(
  rows: CandidateRow[],
  search: string,
  filter: CandidateFilterId,
  selected: ReadonlySet<string>,
): CandidateRow[] {
  return rows.filter((row) => matchesSearch(row, search) && matchesFilter(row, filter, selected));
}

// 分批显示：先给前 limit 个，剩下的记下来
export type CandidateBatch = { shown: CandidateRow[]; remaining: number };

export function candidateBatch(rows: CandidateRow[], limit: number): CandidateBatch {
  const shown = rows.slice(0, Math.max(0, limit));
  return { shown, remaining: Math.max(0, rows.length - shown.length) };
}

// 「继续显示 N 个模型」按钮上的数字
export function moreCount(remaining: number): number {
  return Math.min(MORE_BATCH, remaining);
}

// ---------------------------------------------------------------------------
// 选用的状态
// ---------------------------------------------------------------------------

// 状态词（设计说明「用词」用词与 docs/design/model-management.md「模型访问定义与准入」的状态机）
export const SELECTION_STATUS_LABELS: Record<string, string> = {
  completing: "补全参数",
  waiting: "等待验证",
  testing: "验证调用",
  failed: "验证失败",
  capacity_unknown: "容量未知",
  not_in_list: "不在新的模型列表中",
  // 已启用是准入有效的样子（docs/design/model-management.md「模型管理页」「已启用」）
  enabled: "已启用",
};

export function selectionStatusLabel(status: string): string {
  return SELECTION_STATUS_LABELS[status] ?? status;
}

// 状态标记的图形（shell/kit.tsx 的图标名）
export function selectionStatusKind(status: string): string {
  switch (status) {
    case "failed":
      return "failed";
    case "capacity_unknown":
      return "unknown";
    case "waiting":
      return "waiting";
    case "testing":
    case "completing":
      return "running";
    default:
      return "idle";
  }
}

// ---------------------------------------------------------------------------
// 已选模型清单
// ---------------------------------------------------------------------------

// 已启用（准入有效）时用的状态词
export const ENABLED_STATUS = "enabled";

// 已选模型的一行：目录里的访问定义加上它此刻的状态
export type SelectedModelRow = {
  /** 连接与上游模型 ID 合成的一把键 */
  key: string;
  provider_id: string;
  /** 目录里的访问定义 id */
  model_id: string;
  upstream_model: string;
  provider_address: string;
  /** 状态机的状态；已启用时是 "enabled" */
  status: string;
  error: string | null;
  missing: string[];
  protocol: string;
  context_window: number | null;
  max_output_tokens: number | null;
  input_modalities: string[];
  accepts_required_tool_call: boolean;
  /** 各值的来源（服务端按 docs/design/model-management.md「模型访问定义与准入」给出） */
  sources: string;
  /** 准入记录：测试时间与实际返回的模型 */
  admitted_at: string | null;
  admitted_model: string | null;
};

// 目录里的一次选用：状态机的一条进度
export type SelectionProgress = {
  provider_id: string;
  model_id: string;
  model: string;
  sequence: number;
  status: string;
  missing: string[];
  error: string | null;
};

// 已选模型清单：目录里有访问定义，并且它正在选用中或已经启用。
// 正在选用：状态机里有一条进度（补全参数、等待验证、验证调用、验证失败、容量未知）。
// 已启用：准入记录有效。
// 两者都没有的定义不在清单里（它只是目录里的一条定义）。
export function selectedModelRows(catalog: {
  providers: CatalogProvider[];
  models: CatalogModel[];
  admissions: CatalogAdmission[];
  selections?: SelectionProgress[];
}): SelectedModelRow[] {
  const progress = new Map<string, SelectionProgress>();
  for (const item of catalog.selections ?? []) {
    const current = progress.get(item.model_id);
    if (current === undefined || current.sequence <= item.sequence) {
      progress.set(item.model_id, item);
    }
  }
  const rows: SelectedModelRow[] = [];
  for (const model of catalog.models) {
    const running = progress.get(model.id);
    const admission = admissionOf(model.provider_id, model.id, catalog.admissions);
    const enabled = admission !== null && admission.admitted && !admission.stale;
    if (running === undefined && !enabled) {
      continue;
    }
    const provider = catalog.providers.find((item) => item.id === model.provider_id);
    rows.push({
      key: candidateKey(model.provider_id, model.model),
      provider_id: model.provider_id,
      model_id: model.id,
      upstream_model: model.model,
      provider_address: provider?.base_url ?? model.provider_id,
      status: running ? running.status : ENABLED_STATUS,
      error: running ? running.error : null,
      missing: running ? running.missing : [],
      protocol: model.protocol,
      context_window: model.context_window,
      max_output_tokens: model.max_output_tokens,
      input_modalities: [...model.input_modalities],
      accepts_required_tool_call: model.accepts_required_tool_call,
      sources: model.capability_source,
      admitted_at: admission?.admitted_at ?? null,
      admitted_model: admission?.admitted_model ?? null,
    });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// 已启用的模型与部门使用
// ---------------------------------------------------------------------------

export type ModelOption = { id: string; model: string; provider_id: string; provider_name: string };

// 模型选项的固定比较：一处定义，两处使用，排序结果不随运行机器的系统语言变化（工单 #519）。
export const MODEL_OPTION_COLLATOR = new Intl.Collator("zh-CN");

// 部门默认与项目设置的模型选项：按连接分组的已准入定义（docs/design/model-management.md「模型管理页」）
export function admittedOptions(
  models: CatalogModel[],
  providers: CatalogProvider[],
  admissions: CatalogAdmission[],
): ModelOption[] {
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
    .sort((left, right) => MODEL_OPTION_COLLATOR.compare(`${left.provider_name}/${left.id}`, `${right.provider_name}/${right.id}`));
}

export function admittedModels(
  models: CatalogModel[],
  providers: CatalogProvider[],
  admissions: CatalogAdmission[],
): ModelOption[] {
  return admittedOptions(models, providers, admissions);
}

export type AdmissionGroup = { provider_id: string; provider_name: string; options: ModelOption[] };

// 已准入定义按连接分组：组名取连接名称，组内按上游模型 ID 排序
export function groupAdmittedModels(models: ModelOption[], providers: CatalogProvider[]): AdmissionGroup[] {
  const groups: AdmissionGroup[] = [];
  for (const provider of providers) {
    const options = models
      .filter((model) => model.provider_id === provider.id)
      .sort((left, right) => MODEL_OPTION_COLLATOR.compare(left.model, right.model));
    if (options.length > 0) {
      groups.push({ provider_id: provider.id, provider_name: provider.name, options });
    }
  }
  return groups;
}

// 表单的行只有 id 与所属连接，按这两个值取准入记录
export function admissionOf(providerId: string, modelId: string, admissions: CatalogAdmission[]): CatalogAdmission | null {
  return admissions.find((item) => item.provider_id === providerId && item.model_id === modelId) ?? null;
}

export function admissionFor(model: CatalogModel, admissions: CatalogAdmission[]): CatalogAdmission | null {
  return admissionOf(model.provider_id, model.id, admissions);
}

// 引用准入已作废的定义时下拉框里保留它的显示（docs/design/model-management.md「修改与准入」表格）
export const STALE_ADMISSION_LABEL = "无法使用：准入已作废";

// ---------------------------------------------------------------------------
// 取消选用被拒绝时的引用方
// ---------------------------------------------------------------------------

// 引用方清单的一项 → 看得懂的文字。部门显示名取这个项目组织或这一版定义里给出的名字（labels，
// 工单 #1457）；没有时按页面上原来的写法（旧数据里的部门）
export function referrerLabel(location: string, labels: Record<string, string> = {}): string {
  const binding = /^bindings\.([a-z_]+)$/.exec(location);
  if (binding) {
    return `部门默认：${labels[binding[1]] ?? departmentName(binding[1])}`;
  }
  const project = /^projects\.([^.]+)\.department_settings\.([a-z_]+)$/.exec(location);
  if (project) {
    return `项目部门设置：${labels[project[2]] ?? departmentName(project[2])}`;
  }
  return location;
}

// 取消选用被拒绝时服务端给的是位置串，这里换成看得懂的文字（docs/design/model-management.md「删除」）
// 例：「仍被引用，无法移除：bindings.product」→「仍被引用，无法移除：部门默认：产品」
export function removalRejectionText(message: string, labels: Record<string, string> = {}): string {
  const index = message.indexOf("：");
  if (index < 0) {
    return message;
  }
  const head = message.slice(0, index + 1);
  const locations = message.slice(index + 1).split("、").map((item) => item.trim()).filter((item) => item !== "");
  if (locations.length === 0) {
    return message;
  }
  return head + locations.map((location) => referrerLabel(location, labels)).join("、");
}

// ---------------------------------------------------------------------------
// 部门使用的保存
// ---------------------------------------------------------------------------

// 一次保存部门默认要写的三项
export type BindingInput = { provider_id: string; model_id: string; requested_tier: string | null };

// 换一个部门的模型以后要写的一整份部门默认：服务端按整份替换（catalog.department_defaults.save），
// 所以其余部门照当前的值一起写回去。部门清单由调用处从目录查询的 departments 给出（工单 #1457）；
// 没有给出时用目录里已有绑定的部门加上这一次要改的部门
export function departmentBindings(
  catalog: { bindings: Record<string, CatalogBinding>; models: CatalogModel[] },
  department: string,
  modelId: string,
  departments?: readonly string[],
): Record<string, BindingInput> {
  const bindings: Record<string, BindingInput> = {};
  for (const dept of departments ?? [...new Set([...Object.keys(catalog.bindings), department])]) {
    const binding = catalog.bindings[dept];
    const chosen = dept === department ? modelId : binding?.model_id ?? "";
    if (chosen === "") {
      continue;
    }
    const model = catalog.models.find((item) => item.id === chosen);
    if (!model) {
      continue;
    }
    bindings[dept] = {
      provider_id: model.provider_id,
      model_id: model.id,
      requested_tier: binding?.requested_tier ?? null,
    };
  }
  return bindings;
}

// 改一个部门的请求档位：模型不动，只换这一个部门的档位
export function departmentTierBindings(
  catalog: { bindings: Record<string, CatalogBinding> },
  department: string,
  tier: string,
  departments?: readonly string[],
): Record<string, BindingInput> {
  const bindings: Record<string, BindingInput> = {};
  for (const dept of departments ?? [...new Set([...Object.keys(catalog.bindings), department])]) {
    const item = catalog.bindings[dept];
    if (!item) {
      continue;
    }
    bindings[dept] = {
      provider_id: item.provider_id,
      model_id: item.model_id,
      requested_tier: dept === department ? (tier === "" ? null : tier) : item.requested_tier ?? null,
    };
  }
  return bindings;
}

// 部门默认涉及的部门：这一版加载的定义里的部门（catalog 查询的 departments，工单 #1457），
// 目录里已有绑定的部门也算（模型管理设计说明「部门默认与角色默认」：部门默认按定义里的每个部门各设一项）
export function departmentsOf(bindings: Record<string, CatalogBinding> | undefined,
                             departments: readonly string[] = []): string[] {
  const merged: string[] = [...departments];
  for (const key of Object.keys(bindings ?? {})) {
    if (!merged.includes(key)) {
      merged.push(key);
    }
  }
  return merged;
}

// 目录里的定义 → 保存时要写的一份（catalog.connection.save 的 models 字段）
export function modelInputOf(model: CatalogModel): Record<string, unknown> {
  return {
    id: model.id,
    model: model.model,
    protocol: model.protocol,
    context_window: model.context_window,
    max_output_tokens: model.max_output_tokens,
    capability_source: model.capability_source,
    accepts_required_tool_call: model.accepts_required_tool_call,
    input_modalities: model.input_modalities,
    reasoning_levels: model.reasoning_levels,
    default_reasoning_level: model.default_reasoning_level,
    reasoning_mode: model.reasoning_mode,
  };
}

// ---------------------------------------------------------------------------
// 档位与项目设置（项目部门设置页与设置页共用）
// ---------------------------------------------------------------------------

// 默认档位只能从已选的支持档位中选择（docs/design/model-management.md「模型访问定义与准入」）
export function defaultLevelOptions(supported: string[]): string[] {
  return REASONING_LEVELS.filter((level) => supported.includes(level));
}

// 推理参数方式只列出与协议相符的选项
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

export function numberToText(value: number | null): string {
  return value === null ? "" : String(value);
}

// 部门默认的档位选项：来自所选模型的声明；已保存的档位不在声明内时额外保留并标明按模型限制
export function tierOptions(supported: string[], saved: string | null | undefined): { value: string; label: string }[] {
  const options = defaultLevelOptions(supported).map((level) => ({ value: level, label: level }));
  if (saved && !options.some((item) => item.value === saved)) {
    options.push({ value: saved, label: `${saved}（不在该模型的支持档位内，请求按模型限制）` });
  }
  return options;
}

// 跟随部门的选项文本：待保存的选择为空时写明当前生效的模型（来源与模型名）
export function followDepartmentLabel(current: string): string {
  return current === "" ? "跟随部门默认" : `跟随部门默认（当前：${current}）`;
}

// 当前生效模型的说明：取出生效状态与来源，供跟随选项展示。
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

// 一组设置按取得的模型访问定义：项目设置写入了就用它，否则用部门默认（catalog 的 bindings）
export function mergedModelId(projectModelId: string | null | undefined, department: string,
  bindings: Record<string, CatalogBinding> | undefined): string {
  if (projectModelId) {
    return projectModelId;
  }
  return bindings?.[department]?.model_id ?? "";
}

// 从目录读出模型的上游名称与推理档位声明：供设置页的跟随说明与档位选项使用。
export function modelById(models: CatalogModel[], modelId: string): CatalogModel | null {
  return models.find((item) => item.id === modelId) ?? null;
}

// 一次保存以后要提示的生效说明
export const DEPARTMENT_SAVE_NOTICE = "从本部门下一次模型请求起生效";

// ---------------------------------------------------------------------------
// 目录文档（高级部分的编辑 JSON）
// ---------------------------------------------------------------------------

/**
 * 编辑 JSON 弹窗里的失败提示（工单 #776）：目录文档读不出来时给失败说明与服务端给的原文；
 * 没有失败时没有提示——「本来就没有内容」与「读不出来」是两回事。
 */
export function jsonDialogFailureText(error: string | null): string | null {
  return error === null || error === "" ? null : readFailureText(error);
}

/**
 * 能不能保存这份目录文档（工单 #776）：空文档不让保存——
 * 目录文档读不出来时文本框是空的，按保存会把目录写成空的。
 */
export function canSaveDocument(text: string): boolean {
  return text.trim() !== "";
}
