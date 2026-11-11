// 事项面板的模型（工单 #1708，docs/design/project-organization.md 4.14「事项面板与全部事项」与第 5 节补充条第 13 条）。
//
// 守 R3：路线图走到「项目页只有两页」这一步，设计说明写明事项面板要回答的三件事——走到哪、为什么停、
// 接下来能做什么；判不出的层写「不判定」并写缺哪条事实，以开环完成结束的写「开环完成：没有人核验」，
// 结束的事项没有取消入口。页面不自己判这些，都照查询给的事实写，所以这一层可以用单元测试看。
//
// 停止原因的清单取自接口给的那份（harness/definitions/stop_reasons.json），页面另抄一份会漏行；
// 这一条的用例逐项对上，缺一行就失败。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import type {
  LoopLayer,
  ProjectLoopResult,
  ProjectOverviewResult,
  RunLoopsResult,
  RunRecoveryResult,
  WorkItemCard,
  WorkItemLoop,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  itemPanel,
  pickStatusText,
  stopReasonText,
  type ItemPanelFacts,
} from "../../src/renderer/src/views/project/item-panel-model.ts";

// ---- 构一份事实（形状与字段名照 generated/types.gen.ts，只写这一版用得到的）

function item(over: Record<string, unknown> = {}): WorkItemLoop {
  return {
    work_item_id: "w1",
    kind: "task",
    sign: "做一张事项面板",
    color_index: 1,
    status: "in_progress",
    department: "engineering",
    progress: null,
    departments: null,
    round: 2,
    started_at: "2026-11-11T02:00:00Z",
    elapsed_sec: 600,
    time_limit_sec: 3600,
    pending_question: null,
    run_id: "run-1",
    adoption_id: null,
    recovery_state: null,
    stop_reason: null,
    last_department: null,
    version: 3,
    refs: {},
    organization: null,
    ...over,
  } as WorkItemLoop;
}

function card(over: Record<string, unknown> = {}): WorkItemCard {
  return {
    work_item_id: "w1",
    kind: "task",
    title: "做一张事项面板",
    text: "把选事项一行里的标题点开，看这件事走到哪",
    run_id: "run-1",
    version: 3,
    created_at: "2026-11-11T02:00:00Z",
    status: "in_progress",
    department: "engineering",
    progress: null,
    departments: null,
    round: 2,
    stop_reason: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
    ...over,
  } as WorkItemCard;
}

function loopOf(...items: WorkItemLoop[]): ProjectLoopResult {
  return { project_id: "p1", work_items: items, adoptions: [] } as ProjectLoopResult;
}

function overviewOf(...cards: WorkItemCard[]): ProjectOverviewResult {
  return {
    project_id: "p1",
    name: "事项面板",
    goal: "把项目页收成两页",
    version: 1,
    current_adoption: null,
    stats: {
      total: cards.length,
      in_progress: 0,
      adopted: 0,
      released_unsettled: 0,
      open_loop: 0,
      stopped: 0,
      held: 0,
      not_started: 0,
    },
    work_items: cards,
    start_point: null,
  } as ProjectOverviewResult;
}

function amount(used: number, limit: number, unlimited = false) {
  return { used, limit, unlimited };
}

function layer(name: string, state: string, missing: string | null,
               amounts: Record<string, ReturnType<typeof amount>> = {}): LoopLayer {
  return { name, state, missing, amounts } as LoopLayer;
}

function loops(over: Record<string, unknown> = {}): RunLoopsResult {
  return {
    run_id: "run-1",
    project_id: "p1",
    work_item_id: "w1",
    status: "stopped",
    stop_reason: null,
    parameters: {},
    method: {},
    layers: [],
    activations: [],
    rounds: 2,
    trend: null,
    ...over,
  } as RunLoopsResult;
}

function recovery(over: Record<string, unknown> = {}): RunRecoveryResult {
  return {
    work_item_id: "w1",
    run_id: "run-1",
    state: "completed",
    reason: null,
    executable: false,
    last_confirmed_position: 10,
    last_confirmed_event_id: "e-10",
    last_confirmed_text: "质检放行了第 2 版",
    unfinished_actions: [],
    unknown_actions: [],
    verifications: [],
    next_legal_action: null,
    can_continue: false,
    cannot_continue_reason: null,
    unusable: [],
    limits: {},
    sessions: [],
    owner: null,
    late_results: [],
    upgrade: null,
    ...over,
  } as unknown as RunRecoveryResult;
}

function facts(over: Partial<ItemPanelFacts> = {}): ItemPanelFacts {
  return {
    workItemId: "w1",
    loop: loopOf(item()),
    overview: overviewOf(card()),
    loops: loops(),
    recovery: recovery(),
    ...over,
  };
}

function term(panel: NonNullable<ReturnType<typeof itemPanel>>, key: string): string {
  const fact = panel.head.find((entry) => entry.key === key);
  assert.ok(fact, `面板第一段没有 ${key} 这一行`);
  return fact.text;
}

// ---- 停在哪一层、凭什么判

test("打回以后停滞的事项写出停在哪一层与判定依据", () => {
  const panel = itemPanel(facts({
    loop: loopOf(item({ status: "stopped", stop_reason: "max_cycles", round: 4 })),
    overview: overviewOf(card({
      status: "stopped",
      stop_reason: "max_cycles",
      stop_note: "质检第三次打回，循环次数已经到上限",
    })),
    loops: loops({
      stop_reason: "max_cycles",
      rounds: 4,
      parameters: { "convergence.rounds": 6 },
      method: { trend_switch_rounds: 3, flip_threshold: 2 },
      layers: [
        layer("project_loop", "converging", null, { model_steps: amount(12, 60) }),
        layer("work_item", "stalled", null, { elapsed_ms: amount(600000, 3600000) }),
        layer("run", "stalled", null, { elapsed_ms: amount(600000, 3600000), model_steps: amount(12, 60) }),
      ],
    }),
  }));
  assert.ok(panel, "事项在查询结果里，面板应该做得出来");
  assert.equal(term(panel, "status"), "已停止");
  // 面板标题上写的是中文说法，不写 machine 键
  assert.equal(panel.statusText, "已停止");
  assert.equal(term(panel, "round"), "第 4 轮");
  assert.ok(panel.stop, "停止的事项要写停止那一段");
  assert.equal(panel.stop.reason, "循环次数已达上限");
  assert.equal(panel.stop.note, "质检第三次打回，循环次数已经到上限");
  const stalled = panel.layers.filter((entry) => entry.stateLabel === "停滞");
  assert.equal(stalled.length, 2, "停滞的是事项与运行两层");
  assert.deepEqual(stalled.map((entry) => entry.layer).sort(), ["run", "work_item"]);
  const run = stalled.find((entry) => entry.layer === "run");
  assert.ok(run);
  assert.equal(run.layerLabel, "运行");
  assert.notEqual(run.used, "", "已用量与上限要写出来");
  assert.ok(run.basis.length > 0, "点开一层要看到判定依据");
  assert.ok(run.basis.some((line) => line.includes("判定方式")), "判定依据里写这一层凭什么判");
  assert.ok(panel.ruleText !== "", "面板写清三项参数的口径");
  assert.ok(panel.ruleText.includes("趋势检验"), "判定方式写清轮数与趋势的分界");
});

// ---- 用量到上限

test("因时间上限停下的写明朝一项用量到了上限", () => {
  const panel = itemPanel(facts({
    loop: loopOf(item({ status: "stopped", stop_reason: "time_limit", elapsed_sec: 3600, time_limit_sec: 3600 })),
    overview: overviewOf(card({ status: "stopped", stop_reason: "time_limit" })),
    loops: loops({
      stop_reason: "time_limit",
      layers: [
        layer("work_item", "boundary", null, { elapsed_ms: amount(3600000, 3600000) }),
        // 不设上限的一项不算到上限
        layer("run", "boundary", null, {
          elapsed_ms: amount(3600000, 3600000),
          model_steps: amount(999, 10, true),
        }),
      ],
    }),
  }));
  assert.ok(panel?.stop);
  assert.ok(panel.limitLines.length > 0, "到了上限要写哪一项");
  assert.ok(panel.limitLines.some((line) => line.includes("已用时间")), "时间上限写已用时间这一项");
  assert.ok(panel.limitLines.some((line) => line.includes("到上限")));
  assert.ok(!panel.limitLines.some((line) => line.includes("职能步数")), "不设上限的一项不写到上限");
});

test("没有到上限时不写用量到上限", () => {
  const panel = itemPanel(facts({
    loops: loops({ layers: [layer("run", "converging", null, { elapsed_ms: amount(600000, 3600000) })] }),
  }));
  assert.ok(panel);
  assert.equal(panel.stop, null, "没停的事项没有停止那一段");
  assert.deepEqual(panel.limitLines, []);
});

// ---- 不判定与缺哪条事实

test("缺事实的层写不判定与缺哪条事实", () => {
  const panel = itemPanel(facts({
    loops: loops({
      layers: [layer("work_item", "undetermined", "这一层没有记下判定用量的事件", {})],
    }),
  }));
  assert.ok(panel);
  const row = panel.layers.find((entry) => entry.layer === "work_item");
  assert.ok(row);
  assert.equal(row.layerLabel, "事项");
  assert.equal(row.stateLabel, "不判定");
  assert.equal(row.missing, "这一层没有记下判定用量的事件");
  assert.ok(row.basis.some((line) => line.includes("这一层没有记下判定用量的事件")), "点开要看得到缺哪条事实");
});

// ---- 开环完成

test("以开环完成结束的写开环完成：没有人核验，不写放行", () => {
  const panel = itemPanel(facts({
    loop: loopOf(item({ status: "released_unsettled", stop_reason: "open_loop" })),
    overview: overviewOf(card({ status: "released_unsettled", stop_reason: "open_loop" })),
    loops: loops({ stop_reason: "open_loop", layers: [layer("run", "boundary", null, {})] }),
  }));
  assert.ok(panel?.stop);
  assert.equal(term(panel, "status"), "开环完成：没有人核验");
  assert.equal(panel.stop.openLoop, true);
  assert.equal(panel.stop.reason, "开环完成");
  const words = JSON.stringify([panel.head, panel.stop]);
  assert.ok(!words.includes("放行"), "开环完成不写成放行");
});

// ---- 停止原因的清单与页面上的话逐项对上

test("停止原因清单里每一项都有页面上的话", () => {
  const path = new URL("../../../harness/definitions/stop_reasons.json", import.meta.url);
  const reasons = JSON.parse(readFileSync(path, "utf8")) as Record<string, { label: string }>;
  const keys = Object.keys(reasons);
  assert.ok(keys.length > 0, "清单读不出来时这条用例要失败，不是跳过");
  for (const key of keys) {
    const text = stopReasonText(key);
    assert.notEqual(text, "", `清单里的 ${key} 在页面上没有话`);
    assert.equal(text, reasons[key].label, `清单里的 ${key} 与页面上的话不一样`);
  }
});

test("清单里没有的停止原因不编一句话", () => {
  assert.equal(stopReasonText("no_such_reason"), "");
  assert.equal(stopReasonText(null), "");
});

// ---- 三个入口：取消、恢复与动作核实、导出

test("已结束的事项没有取消", () => {
  for (const status of ["adopted", "released_unsettled", "stopped"]) {
    const panel = itemPanel(facts({
      loop: loopOf(item({ status })),
      overview: overviewOf(card({ status })),
    }));
    assert.ok(panel);
    assert.equal(panel.actions.cancel, null, `${status} 的事项不该有取消入口`);
  }
});

test("进行中的事项可以取消，命令的基准版本取查询给的版本", () => {
  const panel = itemPanel(facts({
    loop: loopOf(item({ status: "in_progress", version: 7 })),
    overview: overviewOf(card({ status: "in_progress" })),
  }));
  assert.ok(panel);
  assert.deepEqual(panel.actions.cancel, { work_item_id: "w1", base_version: 7, status: "in_progress" });
  assert.equal(panel.actions.cancelLabel, "取消事项");
});

test("没有中断与结果未知的动作时没有恢复入口", () => {
  const none = itemPanel(facts({ recovery: recovery({ state: "completed" }) }));
  assert.ok(none);
  assert.equal(none.actions.recovery, null);
  const noData = itemPanel(facts({ recovery: null }));
  assert.ok(noData);
  assert.equal(noData.actions.recovery, null);
});

test("中断或结果未知时有恢复入口并点明是哪些", () => {
  const interrupted = itemPanel(facts({ recovery: recovery({ state: "interrupted" }) }));
  assert.ok(interrupted?.actions.recovery);
  assert.ok(interrupted.actions.recovery.label.includes("恢复"));
  const unknown = itemPanel(facts({
    recovery: recovery({ state: "completed", unknown_actions: [{ action_id: "a1" }] }),
  }));
  assert.ok(unknown?.actions.recovery);
  assert.ok(unknown.actions.recovery.label.includes("结果未知"));
});

test("导出一直有", () => {
  for (const status of ["not_started", "in_progress", "adopted", "released_unsettled", "stopped", "held"]) {
    const panel = itemPanel(facts({
      loop: loopOf(item({ status })),
      overview: overviewOf(card({ status })),
    }));
    assert.ok(panel);
    assert.equal(panel.actions.exportLabel, "导出这次运行", `${status} 的事项也要能导出`);
  }
});

// ---- 每条事实的来源

test("轮次与已用时间带来源，来源取查询给的位置与种类", () => {
  const panel = itemPanel(facts({
    loop: loopOf(item({
      refs: {
        round: { position: 12, source: "host_measurement" },
        elapsed: { position: 20, source: "host_measurement" },
      },
    })),
  }));
  assert.ok(panel);
  const round = panel.head.find((entry) => entry.key === "round");
  assert.ok(round?.source);
  assert.deepEqual(round.source, {
    element: "round",
    elementLabel: "轮次",
    source: "host_measurement",
    sourceLabel: "主机测量",
    position: 12,
  });
  const elapsed = panel.head.find((entry) => entry.key === "elapsed");
  assert.ok(elapsed?.source);
  assert.equal(elapsed.source.position, 20);
  assert.equal(panel.head.find((entry) => entry.key === "status")?.source, null, "状态没有单独一条来源事件");
});

// ---- 等执行槽位

test("排队与挂起的事项写在等执行槽位", () => {
  for (const status of ["not_started", "held"]) {
    const panel = itemPanel(facts({
      loop: loopOf(item({ status })),
      overview: overviewOf(card({ status })),
    }));
    assert.ok(panel);
    assert.ok(panel.slots.some((line) => line.includes("在等执行槽位")), `${status} 的事项要写在等`);
  }
  const running = itemPanel(facts({ loop: loopOf(item({ status: "in_progress" })) }));
  assert.ok(running);
  assert.ok(!running.slots.some((line) => line.includes("这件事项在等")), "在跑的事项不写在等");
});

// ---- 选事项一行的状态旁

test("选事项一行对停止的事项写一句停止原因，开环完成写没有人核验", () => {
  assert.equal(pickStatusText({ status: "stopped", stop_reason: "time_limit" }), "已停止 · 运行时间已达上限");
  assert.equal(pickStatusText({ status: "stopped", stop_reason: "cancelled" }), "已停止 · 运行已被取消");
  assert.equal(pickStatusText({ status: "released_unsettled", stop_reason: "open_loop" }), "开环完成：没有人核验");
  assert.equal(pickStatusText({ status: "in_progress", stop_reason: null }), "进行中");
});

// ---- 事项不在结果里

test("事项不在查询结果里时没有面板", () => {
  assert.equal(itemPanel(facts({ loop: loopOf(), overview: overviewOf() })), null);
});
