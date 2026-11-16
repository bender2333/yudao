// 工单 #1809（「事项与用量」页模型）：
// 保护 R2（独立核验放行与开环完成严格区分，不把开环完成写成放行，按旧组织跑与待你决定准确标注）
// 与 R3（恢复入口按中断/待恢复/未知动作出现，runtime.slots 缺失时不捏造槽位占用数）。

import { test } from "node:test";
import assert from "node:assert/strict";

import type {
  DecisionView,
  OrganizationRole,
  ProjectLoopResult,
  ProjectOverviewResult,
  WorkItemCard,
  WorkItemLoop,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  canQueryRuntimeSlots,
  itemsListView,
  parseRuntimeSlots,
  type ItemCardView,
} from "../../src/renderer/src/views/project/items-page-model.ts";
import type { DepartmentView } from "../../src/renderer/src/views/project/organization.ts";

const DEPARTMENTS: DepartmentView[] = [
  { id: "product", label: "产品" },
  { id: "engineering", label: "工程" },
  { id: "quality", label: "质检" },
];

function orgRole(id: string, label: string): OrganizationRole {
  return { id, label, ref: { position: 0, source: "rule" } };
}

function card(overrides: Partial<WorkItemCard> = {}): WorkItemCard {
  return {
    work_item_id: "w1",
    kind: "feature",
    title: "测试事项",
    text: "事项说明",
    run_id: "r1",
    version: 1,
    created_at: "2026-11-16T01:00:00Z",
    status: "in_progress",
    department: "engineering",
    progress: {
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: null,
    },
    departments: { engineering: { state: "working" } },
    round: 2,
    stop_reason: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
    ...overrides,
  };
}

function loopItem(overrides: Partial<WorkItemLoop> = {}): WorkItemLoop {
  return {
    work_item_id: "w1",
    kind: "feature",
    sign: "W1",
    color_index: 0,
    status: "in_progress",
    department: "engineering",
    progress: {
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: null,
    },
    departments: { engineering: { state: "working" } },
    round: 2,
    started_at: "2026-11-16T01:00:00Z",
    elapsed_sec: 90,
    time_limit_sec: 7200,
    pending_question: null,
    run_id: "r1",
    adoption_id: null,
    recovery_state: "running",
    stop_reason: null,
    last_department: "engineering",
    version: 1,
    organization: {
      form: "loop",
      routing: "cycle",
      roles: [orgRole("product", "产品"), orgRole("engineering", "工程"), orgRole("quality", "质检")],
      verifiers: [],
      completing: null,
      watched: [],
      asks: [],
      rejections: [],
      same_as_project: true,
    },
    ...overrides,
  };
}

function overviewOf(items: WorkItemCard[], statsOverrides: Partial<ProjectOverviewResult["stats"]> = {}): ProjectOverviewResult {
  return {
    project_id: "p1",
    name: "测试项目",
    goal: "测试目标",
    version: 1,
    current_adoption: null,
    work_items: items,
    stats: {
      total: items.length,
      in_progress: items.filter((item) => item.status === "in_progress").length,
      adopted: items.filter((item) => item.status === "adopted").length,
      released_unsettled: items.filter((item) => item.status === "released_unsettled" && item.stop_reason !== "open_loop").length,
      open_loop: items.filter((item) => item.status === "released_unsettled" && item.stop_reason === "open_loop").length,
      stopped: items.filter((item) => item.status === "stopped").length,
      held: items.filter((item) => item.status === "held").length,
      not_started: items.filter((item) => item.status === "not_started").length,
      ...statsOverrides,
    },
  };
}

function loopOf(items: WorkItemLoop[]): ProjectLoopResult {
  return { project_id: "p1", work_items: items, adoptions: [] };
}

function openDecision(workItemId: string): DecisionView {
  return {
    decision_id: `d-${workItemId}`,
    project_id: "p1",
    work_item_id: workItemId,
    run_id: "r1",
    kind: "question",
    status: "open",
    requested_at: "2026-11-16T01:00:00Z",
    request: { title: "需要决定", summary: "请选一项", options: [] },
    answer: null,
    answered_at: null,
    department: "product",
  } as unknown as DecisionView;
}

function cardsById(groups: { cards: ItemCardView[] }[]): Map<string, ItemCardView> {
  const map = new Map<string, ItemCardView>();
  for (const group of groups) {
    for (const entry of group.cards) {
      map.set(entry.workItemId, entry);
    }
  }
  return map;
}

test("保护 R2：独立核验放行与开环完成严格区分，按旧组织跑、待你决定与恢复入口按事实标注", () => {
  const items: WorkItemCard[] = [
    card({
      work_item_id: "w-run",
      title: "进行中且旧组织",
      status: "in_progress",
      department: "custom_qa",
      departments: { custom_qa: { state: "working" } },
    }),
    card({ work_item_id: "w-ask", title: "待确认PRD", status: "awaiting_initial_prd", department: null, departments: {} }),
    card({ work_item_id: "w-rel", title: "独立核验放行件", status: "released_unsettled", stop_reason: "released", department: null, departments: {} }),
    card({ work_item_id: "w-open", title: "开环完成件", status: "released_unsettled", stop_reason: "open_loop", department: null, departments: {} }),
    card({
      work_item_id: "w-adopt", title: "已采纳的旧开环件", status: "adopted", stop_reason: "open_loop",
      department: null, departments: {},
    }),
    card({
      work_item_id: "w-stop", title: "已停止件", status: "stopped", stop_reason: "time_limit",
      stop_note: "超出单次时间上限", stopped_at: "2026-11-16T02:00:00Z", department: null, departments: {},
    }),
  ];

  const loop = loopOf([
    loopItem({
      work_item_id: "w-run",
      round: 4,
      elapsed_sec: 90,
      time_limit_sec: 7200,
      recovery_state: "interrupted",
      organization: {
        form: "loop",
        routing: "cycle",
        same_as_project: false,
        roles: [orgRole("custom_qa", "专项核验")],
        verifiers: [],
        completing: null,
        watched: [],
        asks: [],
        rejections: [],
      },
    }),
    loopItem({
      work_item_id: "w-stop",
      status: "stopped",
      recovery_state: "waiting_resume",
      organization: {
        form: "loop",
        routing: "cycle",
        same_as_project: false,
        roles: [],
        verifiers: [],
        completing: null,
        watched: [],
        asks: [],
        rejections: [],
      },
    }),
  ]);

  const view = itemsListView({
    projectId: "p1",
    selectedWorkItemId: "w-run",
    overview: overviewOf(items),
    loop,
    decisions: [openDecision("w-run")],
    departments: DEPARTMENTS,
    filter: "all",
  });

  assert.ok(view !== null);
  assert.deepEqual(view.stats, {
    total: 6,
    inProgress: 1,
    waitingDecision: 2,
    released: 1,
    openLoop: 1,
    stopped: 1,
  });

  const byId = cardsById(view.groups);
  const runCard = byId.get("w-run")!;
  assert.equal(runCard.selected, true);
  assert.equal(runCard.round, 4);
  assert.equal(runCard.departmentText, "专项核验在工作");
  assert.equal(runCard.elapsedText, "1 分 30 秒 / 2 小时 0 分");
  assert.equal(runCard.oldOrganization, true);
  assert.equal(runCard.waitingDecision, true);
  assert.equal(runCard.conversationHash, "#/p/p1/conversation?w=w-run");
  assert.equal(runCard.recoveryHash, "#/p/p1/w/w-run/recovery");

  const relCard = byId.get("w-rel")!;
  assert.equal(relCard.verifiedReleased, true);
  assert.equal(relCard.openLoop, false);
  assert.equal(relCard.openLoopNote, null);

  const openCard = byId.get("w-open")!;
  assert.equal(openCard.verifiedReleased, false);
  assert.equal(openCard.openLoop, true);
  assert.equal(openCard.statusText, "开环完成");
  assert.equal(openCard.openLoopNote, "开环完成：没有人核验");
  assert.ok(!openCard.statusText.includes("放行"), "开环完成卡片的状态词不出现放行");

  const adoptCard = byId.get("w-adopt")!;
  assert.equal(adoptCard.openLoop, false);
  assert.equal(adoptCard.verifiedReleased, false);
  assert.equal(adoptCard.statusText, "已采纳");

  const stopCard = byId.get("w-stop")!;
  assert.equal(stopCard.oldOrganization, false, "已停止事项不再标为按旧组织跑");
  assert.equal(stopCard.stopReasonText, "运行时间已达上限");
  assert.equal(stopCard.stopNote, "超出单次时间上限");
  assert.equal(stopCard.recoveryHash, "#/p/p1/w/w-stop/recovery");

  const releasedOnly = itemsListView({
    projectId: "p1",
    selectedWorkItemId: null,
    overview: overviewOf(items),
    loop,
    decisions: [],
    departments: DEPARTMENTS,
    filter: "released",
  })!;
  assert.deepEqual([...cardsById(releasedOnly.groups).keys()], ["w-rel"]);

  const openLoopOnly = itemsListView({
    projectId: "p1",
    selectedWorkItemId: null,
    overview: overviewOf(items),
    loop,
    decisions: [],
    departments: DEPARTMENTS,
    filter: "open_loop",
  })!;
  assert.deepEqual([...cardsById(openLoopOnly.groups).keys()], ["w-open"]);
});

test("保护 R3：runtime.slots 能力门控与空态不捏造数字，未知动作触发恢复入口", () => {
  assert.equal(canQueryRuntimeSlots(null), false);
  assert.equal(canQueryRuntimeSlots({ queries: [{ name: "project.overview" }] }), false);
  assert.equal(canQueryRuntimeSlots({ queries: [{ name: "runtime.slots" }] }), true);

  assert.equal(parseRuntimeSlots(null), null);
  assert.equal(parseRuntimeSlots({}), null);
  assert.deepEqual(parseRuntimeSlots({ used: 1, total: 2, waiting: 3 }), {
    used: 1,
    total: 2,
    waiting: 3,
    text: "已占用 1 / 2 · 等槽位 3",
  });

  assert.equal(
    itemsListView({
      projectId: "p1",
      selectedWorkItemId: null,
      overview: null,
      loop: null,
      departments: DEPARTMENTS,
      filter: "all",
    }),
    null,
  );

  const empty = itemsListView({
    projectId: "p1",
    selectedWorkItemId: null,
    overview: overviewOf([]),
    loop: loopOf([]),
    departments: DEPARTMENTS,
    filter: "all",
  })!;
  assert.equal(empty.emptyText, "项目还没有事项");
  assert.equal(empty.runtimeSlots, null);
  assert.equal(empty.loopSlotText, "没有事项正在执行，没有事项在等执行槽位");

  const filteredOut = itemsListView({
    projectId: "p1",
    selectedWorkItemId: null,
    overview: overviewOf([card({ work_item_id: "w1", status: "in_progress" })]),
    loop: loopOf([loopItem({ work_item_id: "w1", recovery_state: "running" })]),
    departments: DEPARTMENTS,
    filter: "stopped",
    unknownActionsByItem: { w1: 1 },
  })!;
  assert.equal(filteredOut.emptyText, "当前筛选下没有事项");

  const unknownRecovery = itemsListView({
    projectId: "p1",
    selectedWorkItemId: null,
    overview: overviewOf([card({ work_item_id: "w1", status: "in_progress" })]),
    loop: loopOf([loopItem({ work_item_id: "w1", recovery_state: "running" })]),
    departments: DEPARTMENTS,
    filter: "all",
    unknownActionsByItem: { w1: 2 },
  })!;
  assert.equal(cardsById(unknownRecovery.groups).get("w1")?.recoveryHash, "#/p/p1/w/w1/recovery");
});
