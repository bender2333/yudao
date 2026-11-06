// 页面自己的状态文字、颜色、覆盖层名与循环行（画面与播放设计说明「搬出：画面成为单独的应用」的
// 「先补页面」：页面自己用的文字与颜色归页面，不从画面取；工单 #1415）。
//
// 页面在页面上看的这几样各留一份，不从画面（pixel/）与翻译层（translate/）取；画面那边要用的文字自己
// 留一份（translate/face.ts），两份文字不互相引用：改这里不动画面，改画面也不动这里。
//
// 部门状态的文字（角色条上那一格用的 STATUS_TEXT）在 ./labels.ts：roleBarText 在那里，与本文件同属
// 页面的文字，本文件按页面内部的方向引用它，不反向引用，免得两份页面文字互相导入。
//
// 挂画布的几个组件（project/floor-screen.tsx、project/room-screen.tsx、home/building-section.tsx）里的
// 画布接线仍要导入画面与翻译层，那几行留给搬画布的工单；本文件只放页面文字与颜色。

import type { LoopActivation, LoopAmount, LoopLayer, RunLoopsResult } from "../../api/generated/types.gen.ts";
import { departmentName, label, STOP_REASON } from "./labels.ts";

// ---------------------------------------------------------------------------
// 颜色

/**
 * 资料页事项卡片的颜色（原来取自 pixel/registry.ts 的 ITEM_COLORS）：六种，按事项序号轮换，
 * 卡片左侧的色条与画面上的成果同一个颜色。画面上另一份色板（pixel/world/floor.ts）是画布用的，
 * 两者取值不同，页面上这份照原样留。
 */
export const ITEM_COLORS: readonly string[] = Object.freeze([
  "#e8505b", "#f7c948", "#3fc1e8", "#f27ec2", "#8fd14f", "#b98558",
]);

/** 事项列表色点用的色板（原来取自 pixel/world/floor.ts 的 ITEM_COLORS）：与门口小旗、包裹同一种颜色。 */
const DOT_COLORS: readonly string[] = Object.freeze([
  "#d9534f", "#4a90d9", "#5cb85c", "#f0ad4e", "#9b59b6", "#e67e22",
]);

/** 事项的颜色序号到色点：序号超出色板时轮换（原来取自 pixel/world/floor.ts 的 itemColor）。 */
export function itemColor(item: { color_index?: number }): string {
  return DOT_COLORS[(Number(item.color_index) || 0) % DOT_COLORS.length];
}

/**
 * 首页楼下列表的楼层状态词与配色（原来取自 pixel/building/status-text.ts 的 BUILDING_STATUS）：
 * 状态灯的取值就是画面合同 FLOOR_SIGNS 的八个，取值不在表里时调用处按原样写。
 */
export const BUILDING_STATUS: Readonly<Record<string, { text: string; color: string }>> = Object.freeze({
  working: { text: "运行中", color: "#3fbf66" },
  queued: { text: "排队中", color: "#9aa2b0" },
  waiting_slot: { text: "等待执行槽位", color: "#f08a3c" },
  waiting_model: { text: "等待模型服务", color: "#6b7382" },
  waiting_resume: { text: "待恢复", color: "#f7cb46" },
  waiting_user: { text: "等待你的决定", color: "#f7cb46" },
  interrupted: { text: "中断", color: "#474d5a" },
  idle: { text: "空闲", color: "#9aa2b0" },
});

// ---------------------------------------------------------------------------
// 覆盖层

/**
 * 覆盖层按钮上的中文名（原来取自 translate/coverage.ts 的 OVERLAY_LABELS）：页面按能力清单的
 * overlays 挑出按钮条上出现哪几个，没有中文名的覆盖层不出现按钮。
 */
export const OVERLAY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  flow: "流转",
  waiting: "等待",
  recovery: "恢复",
  context_usage: "上下文用量",
  semantic_records: "语义记录",
  sources: "来源",
  loops: "循环",
});

// ---------------------------------------------------------------------------
// 循环与收敛的行（工单 #400）：观测页的「循环」区块用这里的函数把 run.loops 的结果写成表。
// 判定不在页面这一层：状态、已用量与「缺少的事实」都照着查询结果写。

/** 循环树的层的中文名。 */
export const LOOP_LAYER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  project_loop: "项目循环",
  work_item: "事项",
  run: "运行",
  activation: "激活",
  step: "步骤",
});

/** 收敛状态的中文名：五种状态与「不判定」；文字与颜色同时给出，不只靠颜色区分。 */
export const LOOP_STATE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  converging: "收敛中",
  stalled: "停滞",
  oscillating: "震荡",
  drifting: "漂移",
  boundary: "达到边界",
  undetermined: "不判定",
});

/** 三项判定参数的中文名（观测页写出判定用的规则与轮数）。 */
export const LOOP_PARAMETER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  "convergence.rounds": "收敛判定看最近几轮",
  "convergence.step_window": "步骤停滞看连续几步",
  "convergence.step_repeat": "同一次调用重复几次算震荡",
});

export function loopStateLabel(state: string): string {
  return LOOP_STATE_LABELS[state] ?? state;
}

export function loopLayerLabel(layer: string): string {
  return LOOP_LAYER_LABELS[layer] ?? layer;
}

/** 一个已用量与上限的文字：不设上限时写「不设上限」，数值照写（docs/design/loops-and-convergence.md「收敛的检测」末）。 */
export function amountText(amount: LoopAmount | undefined, unit: string): string {
  if (!amount) return "—";
  return `${amount.used}${unit} / ${amount.unlimited ? "不设上限" : `${amount.limit}${unit}`}`;
}

export interface LoopRow {
  key: string;
  layer: string;
  layerLabel: string;
  instance: string;
  rounds: number | null;
  used: string;
  state: string;
  stateLabel: string;
  stopReason: string;
  missing: string;
}

function loopLayer(loops: RunLoopsResult, name: string): LoopLayer | undefined {
  return loops.layers.find((layer) => layer.name === name);
}

function workSteps(activation: LoopActivation): number {
  // 工作步：压缩步不是工作步（与步骤层的判定口径一致）
  return activation.steps.filter((step) => step.purpose !== "compaction").length;
}

/** 观测页「循环」区块的行：项目循环 → 事项 → run → 各部门的激活 → 每次激活中的步骤循环。 */
export function loopRows(loops: RunLoopsResult | null): LoopRow[] {
  if (loops === null) return [];
  const project = loopLayer(loops, "project_loop");
  const item = loopLayer(loops, "work_item");
  const run = loopLayer(loops, "run");
  const stepLayer = loopLayer(loops, "step");
  const row = (layer: string, instance: string, rounds: number | null, used: string, state: string,
               missing: string | null | undefined): LoopRow => ({
    key: `${layer}|${instance}`,
    layer,
    layerLabel: loopLayerLabel(layer),
    instance,
    rounds,
    used,
    state,
    stateLabel: loopStateLabel(state),
    stopReason: "",
    missing: missing ?? "",
  });
  const rows: LoopRow[] = [
    row("project_loop", "本事项", loops.rounds, amountText(run?.amounts["model_steps"], " 步"),
        project?.state ?? "undetermined", project?.missing),
    row("work_item", "事项树根", loops.rounds, amountText(run?.amounts["elapsed_ms"], " 毫秒"),
        item?.state ?? "undetermined", item?.missing),
  ];
  const runRow = row("run", "运行", loops.rounds,
                     `${amountText(run?.amounts["elapsed_ms"], " 毫秒")}；${amountText(run?.amounts["model_steps"], " 步")}`,
                     run?.state ?? "undetermined", run?.missing);
  runRow.stopReason = loops.stop_reason ? label(STOP_REASON, loops.stop_reason) : "";
  rows.push(runRow);
  loops.activations.forEach((activation, index) => {
    const name = departmentName(activation.department);
    rows.push(row("activation", `${name} · 第 ${index + 1} 次激活`, index + 1, `${workSteps(activation)} 步`,
                  activation.state, activation.missing));
    rows.push(row("step", `${name} · 第 ${index + 1} 次激活 · 步骤循环`, index + 1, `${workSteps(activation)} 步`,
                  stepLayer?.state ?? "undetermined", stepLayer?.missing));
  });
  return rows;
}

/** 观测页写出判定用的规则与轮数：三项冻结值与两个方法常量。 */
export function loopRuleText(loops: RunLoopsResult | null): string {
  if (loops === null) return "";
  const parts = Object.entries(LOOP_PARAMETER_LABELS)
    .filter(([name]) => loops.parameters[name] !== undefined)
    .map(([name, caption]) => `${caption} ${loops.parameters[name]}`);
  parts.push(`轮数达到 ${loops.method["trend_switch_rounds"]} 改用趋势检验，同一条件翻转 ${loops.method["flip_threshold"]} 次算震荡`);
  return parts.join("；");
}
