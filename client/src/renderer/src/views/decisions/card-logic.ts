// 决定卡片的材料整理（原型 v8 设计说明第 6 节，原型 v9 的 Y9.cards.materialRows 与 Y9.cards.face）。
// 首页与项目页面共用一份整理逻辑：卡片显示的材料与给像素画面用的纯文字版本由同一个函数产出，
// 材料按决定种类从决定请求携带的事实里读出。这里是纯函数，界面与单元测试都直接调用。

import type { DecisionView } from "../../api/generated/types.gen";
import { DECISION_KIND, label } from "../project/labels.ts";

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
      push("停止原因", request.stop_reason);
      push("停止时所处阶段", request.resumed_at_phase);
      break;
    case "unknown_action":
      push("动作", request.action_id);
      push("工具", request.tool);
      push("所属部门", dept(request.department));
      push("契约是否声明可以重复", request.repeatable ? "可以重复执行" : "不能重复执行");
      for (const fact of Array.isArray(request.facts) ? request.facts : []) {
        if (typeof fact === "string") {
          rows.push({ term: "事实", value: fact });
        }
      }
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
  // 待恢复的决定：前往模型管理与本项目的部门设置（原型 v8 第 6 节的材料表）
  if (decision.kind === "model_unavailable") {
    links.push({ label: "前往模型管理", href: "#/sys/models" });
    if (decision.project_id) {
      links.push({ label: "前往本项目的部门设置", href: `#/p/${decision.project_id}/settings` });
    }
  }
  // 请求显式给出的页面（合同以后增加时也生效）
  const target = typeof request.view === "string" ? request.view : "";
  if (target !== "") {
    links.push({ label: "在项目中查看", href: target });
  }
  return links;
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
  if (decision.work_item_id !== null) {
    return `#/p/${decision.project_id}/w/${decision.work_item_id}/recovery`;
  }
  return `#/p/${decision.project_id}/overview`;
}

// 挡住了什么：被阻塞的事项，以及同一项目中排在它后面的事项数量（v8 第 6 节）。
// 不挡住任何事项的请求按 muted 显示（例如不阻塞的已阅通知）。
export function blockedText(decision: DecisionView): { text: string; muted: boolean } {
  if (decision.blocks === "" || decision.blocked === null) {
    return { text: "不挡住事项", muted: true };
  }
  const parts: string[] = [];
  if (decision.blocked.work_item_id !== null) {
    parts.push(`挡住「${decision.blocked.work_item_id}」`);
  } else {
    parts.push("挡住本事项");
  }
  if (decision.blocked.queued_after > 0) {
    parts.push(`同一项目中排在它后面的事项 ${decision.blocked.queued_after} 个`);
  }
  return { text: parts.join("，"), muted: false };
}

// 给像素画面用的纯文字版本（原型 v9 的 Y9.cards.face）：与页面卡片同一份材料，不含界面元素。
// where 是「项目 · 事项」，由调用处按快照把标识解析成名称；解析不到时回落到标识。
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
  const project = names?.projectName || decision.project_id || "项目流";
  const item = names?.workItemTitle || decision.work_item_id;
  const request = (decision.request ?? {}) as Record<string, unknown>;
  const options = (request.options ?? []) as { id: string; label: string; note_required?: boolean }[];
  return {
    id: decision.decision_id,
    kind: decision.kind,
    version: decision.version,
    title: label(DECISION_KIND, decision.kind),
    work_item_id: decision.work_item_id,
    where: item ? `${project} · ${item}` : project,
    waited: `已等待 ${waitedSeconds(decision.requested_at, now)} 秒`,
    blocks: blockedText(decision).text,
    rows: materialRows(decision),
    links: decisionLinks(decision),
    options: options.map((option) => ({ id: option.id, label: option.label, note_required: Boolean(option.note_required) })),
  };
}

// 等待回答的请求按发出时间排列（v8 第 4.3 节：跨项目，按发出时间）
export function sortByRequested(decisions: DecisionView[]): DecisionView[] {
  return [...decisions].sort((a, b) => {
    const left = new Date(a.requested_at).getTime();
    const right = new Date(b.requested_at).getTime();
    return (Number.isNaN(left) ? 0 : left) - (Number.isNaN(right) ? 0 : right);
  });
}
