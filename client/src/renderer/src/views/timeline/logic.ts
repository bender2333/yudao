// 时间轴与回放的纯逻辑（原型 v8 设计说明第 5.5 节、原型 v9 的 ui/replay.js，工单 #180）。
// 刻度只取关键事实：首页取 home.away_report 的关键事实列表，概览按项目筛选；刻度按种类着色。
// 没有关键事实的时间段直接跳过，时间轴上用折断符号表示跳过的时长。
// 这里是纯函数，界面与单元测试都直接调用；播放的推进（定时器）由组件负责。

import type { ReportFact } from "../../api/generated/types.gen";

// 关键事实的种类：由应用层按事件的种类与载荷判定（harness/app/home.py 的 _fact_kind），
// 客户端按它给出刻度着色、图例与标题。取值与原型 v9 contract/registry.js 的 KEY_KINDS 一致
export type KeyKind = "handoff" | "ask" | "answer" | "rework" | "release" | "adopt" | "fault" | "repair" | "deploy" | "wait" | "decision";

export const KEY_KINDS: Record<KeyKind, { label: string; color: string }> = {
  handoff: { label: "交接", color: "#4f8fd6" },
  ask: { label: "询问", color: "#7c6bd6" },
  answer: { label: "回答", color: "#9d8ff0" },
  rework: { label: "返工", color: "#d64f4f" },
  release: { label: "放行", color: "#3fa76a" },
  adopt: { label: "采纳", color: "#1f7a4a" },
  fault: { label: "故障", color: "#c2331f" },
  repair: { label: "修复", color: "#e08a2e" },
  deploy: { label: "部署与回滚", color: "#2f8f9d" },
  wait: { label: "进入与离开等待", color: "#8a8f99" },
  decision: { label: "决定请求", color: "#d4a017" },
};

// 应用层给出的种类取值是否为本客户端认识的刻度种类
export function isKeyKind(value: string | null | undefined): value is KeyKind {
  return value !== null && value !== undefined && value in KEY_KINDS;
}

// 相邻关键事实相隔超过这个时长时画折断符号（原型 v9 的 GAP_SEC）
export const GAP_SEC = 2 * 3600;

// 播放速度的三档（原型 v9 的 SPEEDS）
export const SPEEDS = [1, 2, 4] as const;
export type Speed = (typeof SPEEDS)[number];

// 每一步的基准时长（毫秒，原型 v9 的 BASE_MS）
export const BASE_MS = 1600;

// 一条关键事实：位置、时间、种类与说明。kind 由应用层给出，不是刻度种类的不作为时间轴上的刻度
export interface FactTick {
  position: number;
  at: string;
  type: string;
  label: string;
  project_id: string | null;
  work_item_id: string | null;
  kind: KeyKind;
}

// 时间轴上相邻刻度之间的一段：刻度本身，或跳过一段时间段的折断符号
export type TimelinePart =
  | { kind: "tick"; index: number; tick: FactTick }
  | { kind: "break"; gapSec: number };

// 把关键事实列表转成刻度：只保留有种类的事实（不是刻度种类的不显示），按位置排列；位置相同的事实合并为一条
export function ticksOf(facts: ReportFact[], project?: string | null): FactTick[] {
  const rows: FactTick[] = [];
  const seen = new Set<number>();
  for (const fact of facts) {
    if (project && fact.project_id !== project) {
      continue;
    }
    if (seen.has(fact.position) || !isKeyKind(fact.kind)) {
      continue;
    }
    seen.add(fact.position);
    rows.push({
      position: fact.position,
      at: fact.at,
      type: fact.type,
      label: fact.label,
      project_id: fact.project_id,
      work_item_id: fact.work_item_id,
      kind: fact.kind,
    });
  }
  rows.sort((a, b) => a.position - b.position);
  return rows;
}

// 时间轴上的分段：刻度之间相隔超过 GAP_SEC 时插入一个折断符号
export function partsOf(ticks: FactTick[]): TimelinePart[] {
  const parts: TimelinePart[] = [];
  ticks.forEach((tick, index) => {
    if (index > 0) {
      const gap = secondsBetween(ticks[index - 1].at, tick.at);
      if (gap > GAP_SEC) {
        parts.push({ kind: "break", gapSec: gap });
      }
    }
    parts.push({ kind: "tick", index, tick });
  });
  return parts;
}

// 报告项展开时的高亮刻度：报告的来源事件位置与时间轴刻度位置相同即高亮（原型 v9 的 replay.highlight）
export function ticksInRefs(refs: number[], ticks: FactTick[]): number[] {
  const known = new Set(ticks.map((tick) => tick.position));
  return refs.filter((position) => known.has(position));
}

// 时间差（秒）：任一时间无法解析时返回 0
export function secondsBetween(fromIso: string, toIso: string): number {
  const from = new Date(fromIso).getTime();
  const to = new Date(toIso).getTime();
  if (Number.isNaN(from) || Number.isNaN(to)) {
    return 0;
  }
  return Math.max(0, Math.round((to - from) / 1000));
}

// 一段时长的中文写法（折断符号的说明与「回放中」的时间）
export function durationText(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} 秒`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)} 分`;
  }
  if (seconds < 24 * 3600) {
    return `${Math.round(seconds / 3600)} 小时`;
  }
  return `${Math.round(seconds / (24 * 3600))} 天`;
}
