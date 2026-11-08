// 循环图的事实推出（工单 #1638，项目的组织设计说明 4.14「项目页是循环图加对话」、4.15「循环图跟着组织长」）。
//
// 守的是三环里的 R1（事实照实说）：图上画出来的节点、箭头、版本、结论与两端，全部从事项冻结的组织、
// 流转记录与成果材料推出，测试直接喂这三样事实，核对界面上会出现的字与结构，不经过界面。
//
// 覆盖工单验收要的三种组织（产品 · 工程 · 质检、产品 · 工程、工程）、打回之后的新一版与事项切换。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  END, SOURCE, arrowsOf, graphOf, layoutOf, outcomeOf, otherCounts, pickItem, versionsOf,
  type FlowRecordLike, type FrozenOrganization, type LoopItemView, type MaterialsView,
} from "../../src/renderer/src/views/project/loop-graph-model.ts";

/** 产品 · 工程 · 质检（harness/definitions/organization.json 的那一份，结构一样）。 */
function threeDepartments(): FrozenOrganization {
  return {
    form: "three",
    routing: "watched_outputs",
    roles: [
      { id: "product", label: "产品" },
      { id: "engineering", label: "工程" },
      { id: "quality", label: "质检" },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["delivery_spec"] }] }],
    completing: null,
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec" },
      { source: "quality", recipient: "engineering", outcome: "defect_record" },
      { source: "engineering", recipient: "quality", outcome: "delivery_spec" },
      { source: "product", recipient: "quality", outcome: "product_spec" },
    ],
    asks: [
      { requester: "product", recipient: "engineering" },
      { requester: "engineering", recipient: "product" },
    ],
    rejections: [{ verifier: "quality", role: "engineering", outcome: "delivery_spec" }],
  };
}

/** 产品 · 工程（直做，工程接来源；产品只在询问时回答）。 */
function productEngineering(): FrozenOrganization {
  return {
    form: "several",
    routing: "direct",
    roles: [{ id: "product", label: "产品" }, { id: "engineering", label: "工程" }],
    verifiers: [],
    completing: null,
    watched: [],
    asks: [
      { requester: "product", recipient: "engineering" },
      { requester: "engineering", recipient: "product" },
    ],
    rejections: [],
  };
}

/** 工程（一个职能直做）。 */
function engineeringOnly(): FrozenOrganization {
  return {
    form: "single",
    routing: "direct",
    roles: [{ id: "engineering", label: "工程" }],
    verifiers: [],
    completing: { id: "engineering", label: "工程" },
    watched: [],
    asks: [],
    rejections: [],
  };
}

function record(fields: Partial<FlowRecordLike> & Pick<FlowRecordLike, "flow_id" | "kind" | "position">): FlowRecordLike {
  return {
    event_id: `evt-${fields.flow_id}`, content: "", direction_from: null, direction_to: null, round: null, ...fields,
  };
}

function item(fields: Partial<LoopItemView> & Pick<LoopItemView, "work_item_id">): LoopItemView {
  return { kind: "change", status: "in_progress", round: 1, started_at: "2026-11-01T00:00:00Z", ...fields };
}

function working(departments: Record<string, string>): Record<string, { state: string; note?: string }> {
  const out: Record<string, { state: string; note?: string }> = {};
  for (const [id, state] of Object.entries(departments)) {
    out[id] = { state };
  }
  return out;
}

test("产品 · 工程 · 质检：三个节点，PRD、交付、缺陷记录的箭头写版本与第几轮，打回与放行标在那一版上", () => {
  const organization = threeDepartments();
  const flow: FlowRecordLike[] = [
    record({ flow_id: "f-prd-eng", kind: "PRD 新版本", position: 3, direction_from: "product", direction_to: "engineering", content: "状态机的 PRD：6 个状态、9 条转换", round: 1 }),
    record({ flow_id: "f-prd-qua", kind: "PRD 新版本", position: 4, direction_from: "product", direction_to: "quality", content: "状态机的 PRD（质检拿它独立判断）", round: 1 }),
    record({ flow_id: "f-del-1", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "quality", content: "状态机第 1 版", round: 1 }),
    record({ flow_id: "f-def-1", kind: "问题反馈", position: 8, direction_from: "quality", direction_to: "engineering", content: "已取消的订单还能被标记为已支付", round: 1 }),
    record({ flow_id: "f-del-2", kind: "版本交付", position: 10, direction_from: "engineering", direction_to: "quality", content: "状态机第 2 版", round: 2 }),
  ];
  const materials: MaterialsView = {
    contracts: [{ event_id: "evt-f-prd-eng", revision: 1 }, { event_id: "evt-f-prd-qua", revision: 1 }],
    deliveries: [
      { event_id: "evt-f-del-1", revision: 1, summary: "状态机第 1 版", files: ["orders/state.ts"] },
      { event_id: "evt-f-del-2", revision: 2, summary: "状态机第 2 版：6 个状态、9 条转换", files: ["orders/state.ts", "orders/state.test.ts"] },
    ],
    reviews: [{ event_id: "evt-review-2", verdict: "release" }],
  };
  const graph = graphOf({
    item: item({
      work_item_id: "w0", status: "adopted", round: 2,
      departments: working({ product: "waiting", engineering: "waiting", quality: "waiting" }),
      organization, progress: { conclusion: "release" },
    }),
    flow, materials,
  });

  // 节点三个，顺序是产品 → 工程 → 质检；质检带核验标记
  assert.deepEqual(graph.chain.map((node) => node.label), ["产品", "工程", "质检"]);
  assert.deepEqual(graph.chain.map((node) => node.verifier), [false, false, true]);
  assert.equal(graph.side.length, 0);

  // 来源与结束
  assert.equal(graph.sourceText, "你的输入");
  assert.equal(graph.endTone, "ok");
  assert.equal(graph.endText, "完成 · 质检放行");

  // 产品 → 工程 的 PRD：版本与第几轮
  const prd = graph.gaps[1][0];
  assert.equal(prd.outcome, "PRD");
  assert.equal(prd.version, 1);
  assert.equal(prd.round, 1);

  // PRD 给质检的那条另起一行（跨过工程）
  assert.equal(graph.skip.length, 1);
  assert.equal(graph.skip[0].to, "quality");

  // 工程与质检之间：交付 v1（第 1 轮，质检打回）→ 缺陷记录 v1（回头）→ 交付 v2（第 2 轮，放行）
  const between = graph.gaps[2];
  assert.deepEqual(between.map((arrow) => [arrow.outcome, arrow.version, arrow.round]),
    [["交付", 1, 1], ["缺陷记录", 1, 1], ["交付", 2, 2]]);
  assert.deepEqual(between[0].verdict, { tone: "reject", by: "质检", text: "质检打回" });
  assert.equal(between[1].verdict, null);
  assert.deepEqual(between[1].from, "quality");
  assert.deepEqual(between[1].to, "engineering");
  // 缺陷记录回头画（箭头朝左），交付朝右
  assert.equal(between[1].back, true);
  assert.equal(between[0].back, false);
  assert.deepEqual(between[2].verdict, { tone: "release", by: "质检", text: "放行 · 质检" });
  assert.deepEqual(between[2].files, ["orders/state.ts", "orders/state.test.ts"]);
});

test("打回之后交出的新一版是新的一条箭头，还没放行时结束写「质检放行才结束」", () => {
  const organization = threeDepartments();
  const flow: FlowRecordLike[] = [
    record({ flow_id: "d1", kind: "版本交付", position: 4, direction_from: "engineering", direction_to: "quality", round: 1 }),
    record({ flow_id: "q1", kind: "问题反馈", position: 5, direction_from: "quality", direction_to: "engineering", round: 1 }),
    record({ flow_id: "d2", kind: "版本交付", position: 8, direction_from: "engineering", direction_to: "quality", round: 2 }),
    record({ flow_id: "q2", kind: "问题反馈", position: 9, direction_from: "quality", direction_to: "engineering", round: 2 }),
  ];
  const deliver = arrowsOf(item({ work_item_id: "w1", organization }), organization, flow,
    { deliveries: [
      { event_id: "evt-d1", revision: 1 }, { event_id: "evt-d2", revision: 2 },
    ] }, {}, "product").filter((arrow) => arrow.outcome === "交付");
  assert.deepEqual(deliver.map((arrow) => [arrow.version, arrow.round, arrow.verdict?.tone]),
    [[1, 1, "reject"], [2, 2, "reject"]]);
  const graph = graphOf({
    item: item({ work_item_id: "w1", organization, departments: working({ engineering: "working" }) }),
    flow, materials: null,
  });
  assert.equal(graph.endText, "质检放行才结束");
  assert.equal(graph.chain.find((node) => node.id === "engineering")?.working, true);
});

test("产品 · 工程：工程在主线上交付，产品在旁边接询问，不画成先后两步，结束写开环完成", () => {
  const organization = productEngineering();
  const flow: FlowRecordLike[] = [
    record({ flow_id: "in-1", kind: "版本交付", position: 3, direction_from: "engineering", direction_to: null, content: "活动页文案已改" }),
  ];
  const graph = graphOf({
    item: item({
      work_item_id: "w17", organization, status: "released_unsettled",
      departments: working({ engineering: "waiting", product: "waiting" }),
    }),
    flow,
    materials: { deliveries: [{ event_id: "evt-in-1", revision: 1, summary: "活动页文案已改" }] },
    current: { form: "several", sources: { user_input: "engineering" } },
  });
  assert.deepEqual(graph.chain.map((node) => node.label), ["工程"]);
  assert.deepEqual(graph.side.map((part) => part.node.label), ["产品"]);
  assert.equal(graph.side[0].partner, "engineering");
  assert.equal(graph.endText, "开环完成：没有人核验");
  assert.equal(graph.endTone, "open");
  // 交付一条从工程指向图外（没有核验角色）
  assert.deepEqual(graph.gaps[1].map((arrow) => [arrow.outcome, arrow.to]), [["交付", END]]);

  // 接来源的职能：同一份形态时按现在组织的来源取（工程接），换了形态时不拿现在的顶替
  const sameForm = layoutOf(organization, [], organization.roles, { form: "several", sources: { user_input: "engineering" } });
  assert.deepEqual(sameForm.chain, ["engineering"]);
  const changed = layoutOf(organization, [], organization.roles, { form: "single", sources: { user_input: "product" } });
  assert.deepEqual(changed.chain, ["product"]);
  // 换过形态的旧事项已经交出过交付时，按交出的那个职能定主线
  const withFlow = layoutOf(organization, [record({ flow_id: "d", kind: "版本交付", position: 2, direction_from: "engineering" })],
    organization.roles, { form: "single", sources: { user_input: "product" } });
  assert.deepEqual(withFlow.chain, ["engineering"]);
});

test("工程：一行，你的输入 → 工程 → 开环完成", () => {
  const organization = engineeringOnly();
  const graph = graphOf({
    item: item({
      work_item_id: "w8", organization, round: 1, status: "released_unsettled",
      departments: working({ engineering: "waiting" }),
      progress: null,
    }),
    flow: [record({ flow_id: "in-1", kind: "版本交付", position: 2, direction_from: "engineering", direction_to: null })],
    materials: { inputs: [{ version: 1, text: "把 30 天前的日志清掉" }], deliveries: [{ event_id: "evt-in-1", revision: 1 }] },
  });
  assert.deepEqual(graph.chain.map((node) => node.label), ["工程"]);
  assert.equal(graph.side.length, 0);
  assert.deepEqual(graph.gaps[0].map((arrow) => [arrow.outcome, arrow.version, arrow.from, arrow.to]),
    [["原文", 1, SOURCE, "engineering"]]);
  assert.deepEqual(graph.gaps[1].map((arrow) => [arrow.outcome, arrow.to]), [["交付", END]]);
  assert.equal(graph.endText, "开环完成：没有人核验");
});

test("旧事项仍按它冻结的组织画：换过组织以后节点还是那三个，现在的组织里没有的标「只在旧组织里」", () => {
  const organization = threeDepartments();
  const frozen = item({
    work_item_id: "w-old", organization, status: "in_progress", round: 3,
    departments: working({ product: "waiting", engineering: "working", quality: "waiting" }),
  });
  const graph = graphOf({
    item: frozen,
    flow: [record({ flow_id: "p1", kind: "PRD 新版本", position: 2, direction_from: "product", direction_to: "engineering", round: 3 })],
    materials: { contracts: [{ event_id: "evt-p1", revision: 1 }] },
    // 项目现在换成了只有一个职能的「工程」
    current: { form: "single", sources: { user_input: "engineering" } },
    currentRoles: ["engineering"],
    labels: { engineering: "工程" },
  });
  assert.deepEqual(graph.chain.map((node) => node.label), ["产品", "工程", "质检"]);
  assert.deepEqual(graph.chain.map((node) => node.oldOnly), [true, false, true]);
});

test("职能显示名用冻结的那一份；项目现在的组织改了名字时先用现在的名字", () => {
  const organization = threeDepartments();
  const base = {
    item: item({ work_item_id: "w2", organization }), flow: [], materials: null,
  };
  const frozen = graphOf(base);
  assert.deepEqual(frozen.chain.map((node) => node.label), ["产品", "工程", "质检"]);
  const renamed = graphOf({ ...base, labels: { engineering: "开发" } });
  assert.equal(renamed.chain.find((node) => node.id === "engineering")?.label, "开发");
  // 旧组织里的职能没有现在的名字可读，用冻结的那一份
  assert.equal(renamed.chain.find((node) => node.id === "quality")?.label, "质检");
});

test("事项切换：默认最近在跑的那一件，地址里写了哪一件就画哪一件", () => {
  const items = [
    item({ work_item_id: "w-a", status: "adopted", started_at: "2026-11-01T00:00:00Z" }),
    item({ work_item_id: "w-b", status: "in_progress", started_at: "2026-11-02T00:00:00Z" }),
    item({ work_item_id: "w-c", status: "in_progress", started_at: "2026-11-03T00:00:00Z" }),
  ];
  assert.equal(pickItem(items, null)?.work_item_id, "w-c");
  assert.equal(pickItem(items, "w-b")?.work_item_id, "w-b");
  assert.equal(pickItem(items, "w-missing")?.work_item_id, "w-c");
  // 没有在跑的事项时取最后一件
  assert.equal(pickItem([items[0]], null)?.work_item_id, "w-a");
  // 别的事项在对应职能上记数
  const counts = otherCounts([
    item({ work_item_id: "w1", status: "in_progress", department: "engineering" }),
    item({ work_item_id: "w2", status: "in_progress", departments: working({ product: "working" }) }),
    item({ work_item_id: "w3", status: "in_progress", department: "engineering" }),
    item({ work_item_id: "w4", status: "adopted", department: "engineering" }),
  ], "w1");
  assert.deepEqual(counts, { engineering: 1, product: 1 });
});

test("状态与标记：核验标记、在做角标、状态与原因写在节点上", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({
      work_item_id: "w3", organization,
      departments: {
        product: { state: "working", note: "在回答工程的询问" },
        engineering: { state: "asking", note: "在等待产品的回答" },
        quality: { state: "waiting" },
      },
    }),
    flow: [], materials: null, others: { engineering: 2 },
  });
  const by = new Map(graph.nodes.map((node) => [node.id, node]));
  assert.equal(by.get("product")?.state, "一轮工作中（在回答工程的询问）");
  assert.equal(by.get("product")?.working, true);
  assert.equal(by.get("engineering")?.state, "询问中（在等待产品的回答）");
  assert.equal(by.get("engineering")?.working, false);
  assert.equal(by.get("engineering")?.others, 2);
  assert.equal(by.get("quality")?.verifier, true);
});

test("不是成果的流转不画成成果箭头：询问没有版本，不混进 PRD、交付与缺陷记录", () => {
  const organization = threeDepartments();
  assert.equal(outcomeOf("询问"), null);
  const arrows = arrowsOf(item({ work_item_id: "w4", organization }), organization, [
    record({ flow_id: "ask-1", kind: "询问", position: 3, direction_from: "engineering", direction_to: "product", content: "要不要发短信？" }),
    record({ flow_id: "d1", kind: "版本交付", position: 4, direction_from: "engineering", direction_to: "quality" }),
  ], { deliveries: [{ event_id: "evt-d1", revision: 1 }] }, {}, "product");
  assert.deepEqual(arrows.map((arrow) => arrow.outcome), ["交付"]);
});

test("逐版看：同一种成果、同两端的几版按出现顺序排在一起", () => {
  const organization = threeDepartments();
  const arrows = arrowsOf(item({ work_item_id: "w5", organization }), organization, [
    record({ flow_id: "d1", kind: "版本交付", position: 3, direction_from: "engineering", direction_to: "quality" }),
    record({ flow_id: "d2", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "quality" }),
    record({ flow_id: "p1", kind: "PRD 新版本", position: 2, direction_from: "product", direction_to: "engineering" }),
  ], { deliveries: [{ event_id: "evt-d1", revision: 1 }, { event_id: "evt-d2", revision: 2 }] }, {}, "product");
  const deliveries = arrows.find((arrow) => arrow.outcome === "交付");
  assert.ok(deliveries);
  assert.deepEqual(versionsOf(arrows, deliveries).map((arrow) => arrow.version), [1, 2]);
});

test("事项没有冻结的组织（形态不在这一版发布里）时没有节点，也没有编出来的箭头", () => {
  const graph = graphOf({ item: item({ work_item_id: "w6", organization: null }), flow: [], materials: null });
  assert.deepEqual(graph.nodes, []);
  assert.deepEqual(graph.gaps, []);
  assert.equal(graph.endText, "");
});
