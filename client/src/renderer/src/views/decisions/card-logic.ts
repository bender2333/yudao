// 决定卡片的材料整理（原型 v8 设计说明第 6 节，原型 v10 的 Y10.cards.materialRows 与 Y10.cards.face）。
// 首页与项目页面共用一份整理逻辑：卡片显示的材料与给像素画面用的纯文字版本由同一个函数产出，
// 材料按决定种类从决定请求携带的事实里读出。这里是纯函数，界面与单元测试都直接调用。

import type { DecisionView } from "../../api/generated/types.gen";
import { DECISION_KIND, STOP_REASON, label } from "../project/labels.ts";

export type MaterialRow = { term: string; value: string };
export type MaterialLink = { label: string; href: string };

// 决定请求的载荷：决定请求携带的材料与选项（类型由生成的合同给出，未知种类按原样显示）
type Payload = Record<string, unknown>;

const DEPARTMENT_NAMES: Record<string, string> = { product: "产品", engineering: "工程", quality: "质检", operations: "运维" };

// 等待时长：从发出时间到现在，按秒向上取整（界面不自行推进状态，取的是当前时间与发出时间的差）
export function waitedSeconds(requestedAt: string, now: number): number {
  const requested = new Date(requestedAt).getTime();
  if (Number.isNaN(requested)) {
    return 0;
  }
  return Math.max(0, Math.round((now - requested) / 1000));
}

// 初始 PRD 的材料（第 138 号工单，设计第 3.2 节）：PRD 摘要与工件引用、现有结构说明、
// 基线核验汇总、快照来源与轮次。上一轮的修改意见原文由卡片按事项补一行（工单 #138），
// 修改意见的工件路径是内部引用，不显示给用户。
// 载荷由 InitialPrdRequested 给出，每一项都按接口合同的原样显示，没有上报的项目写「未上报」。
function initialPrdRows(request: Payload, push: (term: string, value: unknown) => void): void {
  const prd = (request.prd ?? {}) as Payload;
  const structure = (request.structure ?? {}) as Payload;
  const review = (request.baseline_review ?? {}) as Payload;
  const snapshot = (request.snapshot ?? {}) as Payload;
  push("轮次", `第 ${typeof request.round === "number" ? request.round : "?"} 轮`);
  push("初始 PRD 摘要", showText(prd.summary, "没有摘要"));
  push("PRD.md 工件", refPath(prd.prd_ref));
  push("PRD 指纹", fingerprint(prd.content_hash));
  push("现有结构说明", refPath(structure.structure_ref));
  push("结构说明指纹", fingerprint(structure.code_tree_digest));
  push("基线核验汇总", baselineSummary(review));
  push("快照来源", showText(snapshot.source, "未上报"));
  push("快照提交", provenanceText(snapshot.provenance));
  push("快照规模", `文件 ${countText(snapshot.files)} 项，目录 ${countText(snapshot.directories)} 项，共 ${bytesText(snapshot.bytes)} 字节`);
}

// 工件引用给出的路径：引用的 path 就是工件的相对路径（PRD.md 与 STRUCTURE.md 按它显示）
function refPath(value: unknown): string {
  const ref = (value ?? {}) as Payload;
  return showText(ref.path, "未上报");
}

// 指纹只显示前 12 位：完整值由资料页按轮的原始材料给出
function fingerprint(value: unknown): string {
  const shown = showText(value, "");
  return shown === "" ? "未上报" : shown.slice(0, 12);
}

// 空值与空串写成给定的占位文字：界面不补造内容
function showText(value: unknown, empty: string): string {
  return typeof value === "string" && value.trim() !== "" ? value : empty;
}

// 快照的 git 来源（harness/projects.py 给项目上下文的同一份文案）：没有仓库时写明采集时的目录内容
function provenanceText(value: unknown): string {
  const provenance = (value ?? {}) as Payload;
  const commit = showText(provenance.commit, "");
  if (commit === "") {
    return "没有 git 仓库，快照采集时的目录内容";
  }
  const branch = showText(provenance.branch, "未知");
  return `git 提交 ${commit}（分支 ${branch}，${provenance.dirty ? "有未提交的修改" : "没有未提交的修改"}）`;
}

// 基线核验汇总（设计第 3.2 节）：按核实结果分组的条数、现有缺陷、遗漏的能力与其他失败
function baselineSummary(review: Payload): string {
  const conclusions = listOf(review.conclusions);
  const counts: Record<string, number> = {};
  for (const item of conclusions) {
    const status = text(item.status);
    if (status !== "") {
      counts[status] = (counts[status] ?? 0) + 1;
    }
  }
  const names: Record<string, string> = {
    verified: "已核实", read_only: "只读", existing_defect: "现有缺陷", unsupported: "不支持",
  };
  const parts = [`核验 ${conclusions.length} 条要求`];
  for (const status of Object.keys(names)) {
    const count = counts[status];
    if (count !== undefined) {
      parts.push(`${names[status]} ${count} 条`);
    }
  }
  parts.push(`遗漏的能力 ${listOf(review.omissions).length} 条`);
  parts.push(`其他失败 ${listOf(review.other_failures).length} 条`);
  return parts.join("；");
}

function listOf(value: unknown): Payload[] {
  return Array.isArray(value) ? value.filter((item): item is Payload => item !== null && typeof item === "object") : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function countText(value: unknown): string {
  return Array.isArray(value) ? String(value.length) : "未上报";
}

function bytesText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "未上报";
}

// 每种决定请求需要的材料：来源是决定请求的载荷（原型 v8 设计说明第 6 节的表）。
// 种类在合同里以后增加时，把它的材料写在这里；未知种类返回空表，不伪造内容。
export function materialRows(decision: DecisionView): MaterialRow[] {
  const request = (decision.request ?? {}) as Payload;
  const rows: MaterialRow[] = [];
  const push = (term: string, value: unknown) => {
    const shown = typeof value === "number" ? String(value) : typeof value === "string" ? value : "";
    if (shown !== "") {
      rows.push({ term, value: shown });
    }
  };
  const dept = (value: unknown) => {
    const key = typeof value === "string" ? value : "";
    return key === "" ? "" : DEPARTMENT_NAMES[key] ?? key;
  };
  switch (decision.kind) {
    case "model_unavailable":
      push("部门", dept(request.department));
      push("模型", (request.target as Payload | null | undefined)?.model_id);
      push("具体问题", request.message);
      push("原因", request.reason);
      break;
    case "no_tool_call":
    case "workspace_unrepresentable":
      push("部门", dept(request.department));
      push("停止原因", typeof request.stop_reason === "string" && request.stop_reason !== ""
        ? label(STOP_REASON, request.stop_reason) : "");
      break;
    case "kernel_modification":
      push("改动的内核路径", Array.isArray(request.kernel_paths) ? request.kernel_paths.join("\n") : "");
      push("差异", request.diff);
      break;
    case "initial_prd":
      initialPrdRows(request, push);
      break;
    default:
      break;
  }
  // 决定请求自带的说明按行列出，保证任何种类都能看到请求给出的说明
  push("说明", request.description);
  return rows;
}

// 「在项目中查看」与材料里的跳转：决定请求给出目标页面，没有时按种类落到对应页面
export function decisionLinks(decision: DecisionView): MaterialLink[] {
  const request = (decision.request ?? {}) as Payload;
  const links: MaterialLink[] = [];
  // 待恢复的决定：前往模型管理与本项目的部门设置（原型 v8 第 6 节的材料表）。
  // 部门设置落在设置页的那一节上（工单 #1161）：路径带上节名，设置页据此滚到部门设置
  if (decision.kind === "model_unavailable") {
    links.push({ label: "前往模型管理", href: "#/sys/models" });
    if (decision.project_id) {
      links.push({ label: "前往本项目的部门设置", href: `#/p/${decision.project_id}/settings?section=departments` });
    }
  }
  // 初始 PRD 的两个工件：PRD.md 与 STRUCTURE.md 指向资料页，资料页按轮展示的正是这两个工件的内容
  const materials = decision.kind === "initial_prd" ? materialsHref(decision) : null;
  if (materials !== null) {
    for (const fileName of ["PRD.md", "STRUCTURE.md"]) {
      links.push({ label: fileName, href: materials });
    }
  }
  // 请求显式给出的页面（合同以后增加时也生效）
  const target = typeof request.view === "string" ? request.view : "";
  if (target !== "") {
    links.push({ label: "在项目中查看", href: target });
  }
  return links;
}

// 初始 PRD 决定所属项目的资料页：资料页按轮列出初始 PRD 与结构说明的原文，
// 带上卡片的轮次供资料页定位（工单 #573）
function materialsHref(decision: DecisionView): string | null {
  const request = (decision.request ?? {}) as Payload;
  if (decision.project_id === null) {
    return null;
  }
  const workItem = typeof request.work_item_id === "string" ? request.work_item_id : decision.work_item_id;
  const round = typeof request.round === "number" ? request.round : null;
  const query = new URLSearchParams();
  if (workItem !== null && workItem !== "") {
    query.set("w", workItem);
  }
  if (round !== null) {
    query.set("round", String(round));
  }
  const suffix = query.toString();
  return `#/p/${decision.project_id}/materials${suffix ? `?${suffix}` : ""}`;
}

// 「在项目中查看」的目标：请求给出 view 时用它；结果未知的动作落到恢复页；其余落到项目概览
export function viewHref(decision: DecisionView): string | null {
  const request = (decision.request ?? {}) as Payload;
  if (typeof request.view === "string" && request.view !== "") {
    return request.view;
  }
  if (decision.project_id === null) {
    return null;
  }
  // 初始 PRD 的确认：资料页按轮列出各轮的初始 PRD 与确认记录（工单 #138）
  if (decision.kind === "initial_prd") {
    return materialsHref(decision);
  }
  if (decision.work_item_id !== null) {
    return `#/p/${decision.project_id}/w/${decision.work_item_id}/recovery`;
  }
  return `#/p/${decision.project_id}/overview`;
}

// 挡住了什么：被阻塞的事项，以及同一项目中排在它后面的事项数量（v8 第 6 节）。
// 不挡住任何事项的请求按 muted 显示（例如不阻塞的已阅通知）。
// 被挡住的事项写标题，不写事项标识（工单 #802，原型 v11 的 Y11.ui.cards.blocksText 同一写法）：
// 标题由调用处按项目的事项列表解析；挡住的事项就是决定请求所属的事项
// （服务端按这个事项给出挡住的对象，harness/app/decision_queries.py 的 _blocked），
// 取不到标题时写「挡住本事项」，不拿标识凑数。
export function blockedText(decision: DecisionView, workItemTitle = ""): { text: string; muted: boolean } {
  if (decision.blocks === "" || decision.blocked === null) {
    return { text: "不挡住事项", muted: true };
  }
  const parts: string[] = [];
  const title = workItemTitle.trim();
  if (title !== "") {
    parts.push(`挡住「${title}」`);
  }
  if (decision.blocked.queued_after > 0) {
    parts.push(`同一项目中排在它后面的事项 ${decision.blocked.queued_after} 个`);
  }
  return { text: parts.length === 0 ? "挡住本事项" : parts.join("，"), muted: false };
}

// 决定卡片头的一行：项目名与事项标题（工单 #802，原型 v11 的 Y11.ui.cards.render 同一写法）。
// 事项标题由调用处按项目的事项列表解析；取不到时只写项目名，不写事项标识——
// 页面上不出现内部标识（事项范围那一处的做法一样，views/project/scope-name.ts）。
export function metaLine(
  decision: DecisionView,
  names: { projectName: string; workItemTitle: string },
): string {
  const project = names.projectName || decision.project_id || "项目流";
  const item = names.workItemTitle.trim();
  return item === "" ? project : `${project} · ${item}`;
}

// 给像素画面用的纯文字版本（原型 v10 的 Y10.cards.face）：与页面卡片同一份材料，不含界面元素。
// where 是「项目 · 事项」，由调用处按快照把标识解析成名称；解析不到时不写标识（工单 #802）。
// options 保留 note_required（原型选项的标记）：为真时，没有写说明就不提交。
export function face(
  decision: DecisionView,
  now: number,
  names?: { projectName: string; workItemTitle: string },
): {
  id: string;
  kind: string;
  version: number;
  title: string;
  work_item_id: string | null;
  where: string;
  waited: string;
  blocks: string;
  rows: MaterialRow[];
  links: MaterialLink[];
  options: { id: string; label: string; note_required: boolean }[];
} {
  const request = (decision.request ?? {}) as Record<string, unknown>;
  const options = (request.options ?? []) as { id: string; label: string; note_required?: boolean }[];
  return {
    id: decision.decision_id,
    kind: decision.kind,
    version: decision.version,
    title: label(DECISION_KIND, decision.kind),
    work_item_id: decision.work_item_id,
    where: metaLine(decision, { projectName: names?.projectName ?? "", workItemTitle: names?.workItemTitle ?? "" }),
    waited: `已等待 ${waitedSeconds(decision.requested_at, now)} 秒`,
    blocks: blockedText(decision, names?.workItemTitle ?? "").text,
    rows: materialRows(decision),
    links: decisionLinks(decision),
    options: options.map((option) => ({ id: option.id, label: option.label, note_required: Boolean(option.note_required) })),
  };
}

// 选项要求写说明时，没有说明的回答不提交：返回要显示的提示，可以提交时返回空串。
// 像素画面（pixel/floor/card.ts）与页面卡片（views/decisions/card.tsx）都按这条规则处理，
// 提示由同一个函数给出，两处的文字不会分叉。
export function missingNoteText(option: { label: string; note_required?: boolean }, note: string): string {
  if (option.note_required && note.trim() === "") {
    return `「${option.label}」需要在说明里写明修改意见`;
  }
  return "";
}

// 等待回答的请求按发出时间排列（v8 第 4.3 节：跨项目，按发出时间）
export function sortByRequested(decisions: DecisionView[]): DecisionView[] {
  return [...decisions].sort((a, b) => {
    const left = new Date(a.requested_at).getTime();
    const right = new Date(b.requested_at).getTime();
    return (Number.isNaN(left) ? 0 : left) - (Number.isNaN(right) ? 0 : right);
  });
}
