// 循环图的事实推出（工单 #1638，项目的组织设计说明 4.14「项目页是循环图加对话」、4.15「循环图跟着组织长」）。
//
// 守的是三环里的 R1（事实照实说）：图上画出来的节点、箭头、版本、结论与两端，全部从事项冻结的组织、
// 流转记录与成果材料推出，测试直接喂这三样事实，核对界面上会出现的字与结构，不经过界面。
//
// 覆盖工单验收要的三种组织（产品 · 工程 · 质检、产品 · 工程、工程）、打回之后的新一版与事项切换，
// 以及工单 #1642 的累计往来：两个职能之间的询问合成一条线、次数含开着的、已结束的事项也有、点线只看这两个职能。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  END, SOURCE, arrowsOf, askStateText, graphOf, layoutOf, nameOf, outcomeOf, otherCounts, pickItem, versionsOf,
  type AskViewLike, type FlowRecordLike, type FrozenOrganization, type LoopAskLine, type LoopItemView, type MaterialsView,
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

/** 图上画的虚线是一条累计往来时写出它的字：不是累计往来就失败，省得只看到一句 undefined。 */
function pairLabel(line: LoopAskLine): string {
  assert.ok(line.kind === "pair", `不是累计往来：${line.key}`);
  return line.label;
}

/** run.asks 的一次询问（只列循环图读的那几栏）。 */
function ask(fields: Partial<AskViewLike> & Pick<AskViewLike, "id" | "requester" | "recipient">): AskViewLike {
  return { question: "要不要做？", status: "进行中", depth: 1, start_position: 1, ...fields };
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
  assert.deepEqual(graph.asks, []);
  assert.deepEqual(graph.openAsks, []);
  assert.equal(graph.endText, "");
});

test("产品 · 工程：工程问产品时竖线换成写「询问」的虚线，工程写在等待、不挂角标，产品写回答、挂角标", () => {
  const organization = productEngineering();
  const graph = graphOf({
    item: item({
      work_item_id: "w18", organization,
      departments: {
        engineering: { state: "asking", note: "在等待产品的回答" },
        product: { state: "working", note: "回答工程的询问" },
      },
    }),
    flow: [], materials: null,
    current: { form: "several", sources: { user_input: "engineering" } },
    asks: [ask({
      id: "a1", requester: "engineering", recipient: "product",
      question: "退款金额取整到分还是到元？", start_position: 5,
    })],
  });
  const engineering = graph.chain.find((node) => node.id === "engineering");
  const product = graph.side[0]?.node;
  assert.ok(engineering);
  assert.ok(product);
  // 节点上的字与节点详情读同一份状态：状态词，原因写在括号里
  assert.equal(engineering.stateWord, "询问中");
  assert.equal(engineering.state, "询问中（在等待产品的回答）");
  assert.equal(engineering.working, false);
  assert.equal(product.stateWord, "一轮工作中");
  assert.equal(product.state, "一轮工作中（回答工程的询问）");
  assert.equal(product.working, true);
  // 在等的写「在等待某某的回答」（窄屏不画线时写在节点名旁）
  assert.deepEqual(engineering.waiting, ["在等待产品的回答"]);
  assert.deepEqual(product.waiting, []);
  // 一次开着的询问：两端是工程与产品，画在旁边的职能与主线之间的竖线处，询问不是成果、没有版本
  assert.equal(graph.openAsks.length, 1);
  assert.deepEqual([graph.openAsks[0].from, graph.openAsks[0].to, graph.openAsks[0].place, graph.openAsks[0].partner],
    ["engineering", "product", "side", "engineering"]);
  assert.equal(graph.openAsks[0].open, true);
  assert.equal("version" in graph.openAsks[0], false);
  assert.equal(askStateText(graph.openAsks[0]), "还没回答");
  // 「产品 · 工程」里开着询问时，两节点之间的竖线换成这条虚线
  assert.deepEqual(graph.side[0].lines.map((line) => [line.kind, line.from, line.to]),
    [["ask", "engineering", "product"]]);
});

test("产品 · 工程 · 质检：相邻的询问在那一格里，隔着职能的另起一行，询问链每层一条", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({
      work_item_id: "w19", organization,
      departments: {
        product: { state: "working", note: "回答工程的询问" },
        engineering: { state: "asking", note: "在等待产品的回答" },
        quality: { state: "asking", note: "在等待产品的回答" },
      },
    }),
    flow: [], materials: null,
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", question: "取整到分？", depth: 1, start_position: 4 }),
      ask({ id: "a2", requester: "quality", recipient: "product", question: "验收条件按哪一版？", depth: 2, start_position: 7 }),
    ],
  });
  // 同时开着两次就有两条：工程问产品在 1 号格；质检问产品隔着工程，另起一行
  assert.deepEqual(graph.openAsks.map((entry) => [entry.from, entry.to, entry.place, entry.gap, entry.depth]),
    [["engineering", "product", "gap", 1, 1], ["quality", "product", "skip", -1, 2]]);
  assert.deepEqual([graph.openAsks[1].fromIndex, graph.openAsks[1].toIndex], [2, 0]);
  // 等的两组都写在等谁；被问的产品在回答，挂「在做」，等回答的不挂
  assert.deepEqual(graph.chain.map((node) => [node.label, node.working]),
    [["产品", true], ["工程", false], ["质检", false]]);
  assert.deepEqual(graph.chain.find((node) => node.id === "engineering")?.waiting, ["在等待产品的回答"]);
  assert.deepEqual(graph.chain.find((node) => node.id === "quality")?.waiting, ["在等待产品的回答"]);
});

test("答完的询问虚线消失，收进往来；回答里修订的 PRD 是新的一条实线箭头", () => {
  const organization = threeDepartments();
  const flow: FlowRecordLike[] = [
    record({ flow_id: "prd-1", kind: "PRD 新版本", position: 2, direction_from: "product", direction_to: "engineering", round: 1 }),
    record({
      flow_id: "prd-2", kind: "PRD 新版本", position: 9, direction_from: "product", direction_to: "engineering",
      round: 2, content: "取整规则：到分",
    }),
  ];
  const graph = graphOf({
    item: item({
      work_item_id: "w20", organization,
      departments: working({ product: "waiting", engineering: "waiting", quality: "waiting" }),
    }),
    flow,
    materials: { contracts: [{ event_id: "evt-prd-1", revision: 1 }, { event_id: "evt-prd-2", revision: 2 }] },
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 5 }),
      ask({ id: "a2", requester: "quality", recipient: "product", status: "没能回答", start_position: 6 }),
    ],
  });
  // 答完与没能回答的都不画线；仍留在节点面板的往来里
  assert.deepEqual(graph.openAsks, []);
  assert.deepEqual(graph.asks.map((entry) => [entry.key, entry.open, askStateText(entry)]),
    [["a1", false, "已回答"], ["a2", false, "没能回答"]]);
  // 修订的 PRD 是新的一版，照常是一条实线成果箭头（LoopArrow 没有虚线之分）
  assert.deepEqual(graph.gaps[1].map((arrow) => [arrow.outcome, arrow.version, arrow.round]),
    [["PRD", 1, 1], ["PRD", 2, 2]]);
});

test("定义上可以询问谁不画成常挂的线：没有开着的询问时图上没有虚线", () => {
  const organization = productEngineering();
  const graph = graphOf({
    item: item({ work_item_id: "w22", organization }),
    flow: [], materials: null,
    current: { form: "several", sources: { user_input: "engineering" } },
  });
  // 冻结的组织里有可以询问谁（双向），但那不是常挂的线；开着的询问从 run.asks 读
  assert.ok((organization.asks ?? []).length > 0);
  assert.deepEqual(graph.openAsks, []);
  assert.deepEqual(graph.side[0]?.lines, []);
});

test("五个状态逐条核对节点上的字、「在做」角标与节点详情：等你决定不挂，核验中与等待工作写状态词", () => {
  const organization = threeDepartments();
  const cases: { state: string; note: string | null; word: string; working: boolean }[] = [
    { state: "waiting_user", note: null, word: "等用户", working: false },
    { state: "working", note: "回答产品的询问", word: "一轮工作中", working: true },
    { state: "asking", note: "在等待产品的回答", word: "询问中", working: false },
    { state: "verifying", note: "等质检核验交付 r1", word: "核验中", working: false },
    { state: "waiting", note: null, word: "等待工作", working: false },
  ];
  for (const entry of cases) {
    const graph = graphOf({
      item: item({
        work_item_id: `w-${entry.state}`, organization,
        departments: { engineering: { state: entry.state, note: entry.note } },
      }),
      flow: [], materials: null,
    });
    const node = graph.chain.find((candidate) => candidate.id === "engineering");
    assert.ok(node);
    // 节点上的字与节点详情读同一份状态：状态词，有具体原因时写在括号里
    assert.equal(node.stateWord, entry.word);
    assert.equal(node.state, entry.note === null ? entry.word : `${entry.word}（${entry.note}）`);
    assert.ok(node.state.startsWith(node.stateWord));
    // 「在做」角标只挂在一轮工作中的节点（等你决定、询问中、核验中、等待工作都不挂）
    assert.equal(node.working, entry.working);
    assert.equal(node.working, entry.word === "一轮工作中");
    // 不出现英文内部标识（职能标识是 product / engineering / quality）
    for (const id of ["product", "engineering", "quality"]) {
      assert.ok(!node.state.includes(id), `${entry.state} 的节点字里出现了 ${id}`);
    }
  }
});

test("点节点面板的往来：开着的在前、标「还没回答」，显示名用服务端 label", () => {
  const organization = productEngineering();
  const graph = graphOf({
    item: item({
      work_item_id: "w21", organization,
      departments: {
        product: { state: "asking", note: "在等待开发的回答" },
        engineering: { state: "working", note: "回答需求的询问" },
      },
    }),
    flow: [], materials: null,
    current: { form: "several", sources: { user_input: "engineering" } },
    labels: { product: "需求", engineering: "开发" },
    asks: [
      ask({ id: "done", requester: "engineering", recipient: "product", status: "已回答", question: "旧的问法", start_position: 2 }),
      ask({ id: "open", requester: "product", recipient: "engineering", question: "现在的问法", start_position: 8 }),
    ],
  });
  // 往来按开着的在前排；开着的写「还没回答」，答完的写查询给的状态
  assert.deepEqual(graph.asks.map((entry) => entry.key), ["open", "done"]);
  assert.equal(askStateText(graph.asks[0]), "还没回答");
  assert.equal(askStateText(graph.asks[1]), "已回答");
  // 显示名用服务端给的 label（现在的组织）：节点、等待的那句话、面板里的往来都用它
  assert.equal(nameOf(graph, "product"), "需求");
  assert.equal(nameOf(graph, "engineering"), "开发");
  assert.deepEqual(graph.side.find((part) => part.node.id === "product")?.node.waiting, ["在等待开发的回答"]);
  assert.deepEqual(graph.chain.find((node) => node.id === "engineering")?.waiting, []);
});

// 工单 #1642：累计往来（各职能之间的次数与返工），点询问线只看这两个职能。

test("累计往来：两个职能之间的询问合成一条虚线，次数含开着的，还有开着的写「开着」", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({ work_item_id: "w30", organization }),
    flow: [], materials: null,
    accumulated: true,
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 3 }),
      ask({ id: "a2", requester: "engineering", recipient: "product", status: "已回答", start_position: 6 }),
      ask({ id: "a3", requester: "quality", recipient: "engineering", start_position: 9 }),
    ],
  });
  // 工程问产品两次合成一条；质检问工程一次还开着，次数含它，后面写「开着」
  assert.deepEqual(graph.lines.map((line) => [line.kind, line.from, line.to, pairLabel(line), line.place, line.gap]),
    [
      ["pair", "engineering", "product", "工程问产品 2 次", "gap", 1],
      ["pair", "quality", "engineering", "质检问工程 1 次 · 开着", "gap", 2],
    ]);
  // 次数与方向也留在结构里，不只是那一句话
  const first = graph.lines[0];
  assert.equal(first.kind, "pair");
  if (first.kind === "pair") {
    assert.deepEqual(first.directions.map((entry) => [entry.from, entry.to, entry.count]),
      [["engineering", "product", 2]]);
    assert.equal(first.count, 2);
    assert.equal(first.open, false);
  }
  assert.equal(graph.lines[1].open, true);
  // 合成只换画法：节点上仍写在等谁的回答，节点的往来仍是逐条
  assert.deepEqual(graph.chain.find((node) => node.id === "quality")?.waiting, ["在等待工程的回答"]);
  assert.equal(graph.asks.length, 3);
  // 不出现英文内部标识
  for (const line of graph.lines) {
    for (const id of ["product", "engineering", "quality"]) {
      assert.ok(!pairLabel(line).includes(id), `累计往来的字里出现了 ${id}`);
    }
  }
});

test("累计往来不打开时仍然只画开着的询问：关掉就回到开着的那些线", () => {
  const organization = threeDepartments();
  const asks = [
    ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 3 }),
    ask({ id: "a2", requester: "engineering", recipient: "product", status: "已回答", start_position: 6 }),
    ask({ id: "a3", requester: "quality", recipient: "engineering", start_position: 9 }),
  ];
  const off = graphOf({ item: item({ work_item_id: "w31", organization }), flow: [], materials: null, asks });
  assert.deepEqual(off.lines.map((line) => [line.kind, line.key, line.from, line.to]),
    [["ask", "a3", "quality", "engineering"]]);
  const on = graphOf({
    item: item({ work_item_id: "w31", organization }), flow: [], materials: null, asks, accumulated: true,
  });
  assert.deepEqual(on.lines.map((line) => line.kind), ["pair", "pair"]);
});

test("已结束的事项打开累计往来也有线：答完的询问照样按两个职能合成一条", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({
      work_item_id: "w32", organization, status: "adopted", round: 2,
      departments: working({ product: "waiting", engineering: "waiting", quality: "waiting" }),
      progress: { conclusion: "release" },
    }),
    flow: [], materials: null, accumulated: true,
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 4 }),
      ask({ id: "a2", requester: "quality", recipient: "engineering", status: "已回答", start_position: 7 }),
    ],
  });
  assert.deepEqual(graph.lines.map((line) => [pairLabel(line), line.open]),
    [["工程问产品 1 次", false], ["质检问工程 1 次", false]]);
});

test("「产品 · 工程」里累计往来在竖线那一格：工程问产品两次合成一条，还开着就写「开着」", () => {
  const organization = productEngineering();
  const graph = graphOf({
    item: item({ work_item_id: "w33", organization }),
    flow: [], materials: null, accumulated: true,
    current: { form: "several", sources: { user_input: "engineering" } },
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 2 }),
      ask({ id: "a2", requester: "engineering", recipient: "product", start_position: 5 }),
    ],
  });
  assert.deepEqual(graph.lines.map((line) => [line.place, line.partner, pairLabel(line)]),
    [["side", "engineering", "工程问产品 2 次 · 开着"]]);
  // 旁边的职能与主线之间的竖线里画的就是这一条（和开着的询问同一个位置）
  assert.deepEqual(graph.side[0].lines.map((line) => line.key), [graph.lines[0].key]);
});

test("隔着职能的累计往来另起一行：质检问产品两次合成一条跨过工程", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({ work_item_id: "w34", organization }), flow: [], materials: null, accumulated: true,
    asks: [
      ask({ id: "a1", requester: "quality", recipient: "product", status: "已回答", start_position: 2 }),
      ask({ id: "a2", requester: "quality", recipient: "product", status: "已回答", start_position: 5 }),
    ],
  });
  assert.deepEqual(graph.lines.map((line) => [line.place, line.fromIndex, line.toIndex, pairLabel(line)]),
    [["skip", 2, 0, "质检问产品 2 次"]]);
});

test("来回的询问合成一条：两个方向各写几次，还开着的写「开着」", () => {
  const organization = threeDepartments();
  const graph = graphOf({
    item: item({ work_item_id: "w35", organization }), flow: [], materials: null, accumulated: true,
    asks: [
      ask({ id: "a1", requester: "engineering", recipient: "product", status: "已回答", start_position: 2 }),
      ask({ id: "a2", requester: "product", recipient: "engineering", status: "已回答", start_position: 4 }),
      ask({ id: "a3", requester: "engineering", recipient: "product", start_position: 6 }),
    ],
  });
  // 按两个职能合成一条：两个方向各写几次，同一行里用逗号分开，最后写「开着」
  assert.equal(graph.lines.length, 1);
  assert.equal(pairLabel(graph.lines[0]), "工程问产品 2 次，产品问工程 1 次 · 开着");
});

