// 节点面板的模型（工单 #1712）：面板从上到下接住旧职能页的内容，每一段给出哪几句话。
// 设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」、
// 「项目页上的内容在哪里看」；页面的验收见 #1707 的补充条第 15 条。
//
// 断言落在模型给出的文字与结构上：面板怎么摆、按钮长什么样由页面负责，真实页面交给发布以后的走查与试用。
// 引用的模块写成带 .ts 的名字：node --test 直接跑 TypeScript，不带扩展名找不到模块。

import { test } from "node:test";
import assert from "node:assert/strict";

import type { AskView, DepartmentWorkspaceResult } from "../../src/renderer/src/api/generated/types.gen.ts";
import type { LoopNode } from "../../src/renderer/src/views/project/loop-graph-model.ts";
import { parseRoute } from "../../src/renderer/src/shell/routing.ts";
import {
  NO_ASK_TEXT,
  NO_GUIDANCE_TEXT,
  NO_LAST_CALL_TEXT,
  NO_MACHINE_TEXT,
  NO_STATE_TEXT,
  NO_WAIT_TEXT,
  NOT_REPORTED_TEXT,
  entryLinks,
  guidanceFacts,
  lastRequestFacts,
  liveOutputShown,
  nodePanelView,
  stateText,
  waitedTextFor,
  workshopFacts,
} from "../../src/renderer/src/views/project/node-panel-model.ts";

function node(overrides: Partial<LoopNode> = {}): LoopNode {
  return {
    id: "engineering",
    label: "工程",
    stateWord: "",
    state: "",
    working: false,
    waiting: [],
    verifier: false,
    oldOnly: false,
    others: 0,
    ...overrides,
  };
}

// 工作间（department.workspace）里面板要读的那几项；其余字段面板不读，按最小的一份给。
function workspace(over: Record<string, unknown> = {}): DepartmentWorkspaceResult {
  return {
    room: {
      machine: "build-01",
      waiting_provider: false,
      remote_unknown: false,
      mailbox: 0,
      roles: [],
      pipes: { out: 0, letters_waiting: 0 },
      summaries: 0,
      pinned_notes: 0,
    },
    last_call: null,
    guidance: [],
    ...over,
  } as unknown as DepartmentWorkspaceResult;
}

// 一条询问（run.asks 的 AskView）：面板只读发出的人、状态与开始时间。
function ask(over: Partial<AskView> = {}): AskView {
  return {
    id: "a1",
    requester: "engineering",
    recipient: "quality",
    question: "这一版检查过了吗",
    status: "进行中",
    chain: [],
    depth: 0,
    start_position: 0,
    started_at: "2026-11-11T08:00:00Z",
    ...over,
  } as AskView;
}

test("状态与原因取图上节点的字，没有状态时写一句", () => {
  assert.equal(stateText(node({ state: "一轮工作中（检查回执）" })), "一轮工作中（检查回执）");
  assert.equal(stateText(node()), NO_STATE_TEXT);
});

test("在等什么取节点上开着的询问，按行给", () => {
  const view = nodePanelView(node({ waiting: ["在等待产品的回答"] }), null, "p1", "w1");
  assert.deepEqual(view.waiting, ["在等待产品的回答"]);
});

test("不在工作的职能没有实时输出那一段，正在工作的才有", () => {
  assert.equal(liveOutputShown(node({ working: false })), false);
  assert.equal(liveOutputShown(node({ working: true })), true);
  // 整份正文里也是同一个结论
  assert.equal(nodePanelView(node({ working: false }), null, "p1", "w1").live, false);
  assert.equal(nodePanelView(node({ working: true }), null, "p1", "w1").live, true);
});

test("工作间的事实写执行机器、等模型服务、结果未知、未读指导、等它回答的询问、手边的摘要与笔记各一句", () => {
  const waiting = workshopFacts(workspace({
    room: {
      machine: null, waiting_provider: true, remote_unknown: true, mailbox: 3, roles: [],
      pipes: { out: 0, letters_waiting: 2 }, summaries: 4, pinned_notes: 5,
    },
  }));
  assert.deepEqual(waiting.map((fact) => fact.label), [
    "执行机器", "等模型服务", "结果未知", "未读指导", "等它回答的询问", "手边的摘要与笔记",
  ]);
  assert.equal(waiting[0]?.value, NO_MACHINE_TEXT);
  assert.equal(waiting[1]?.value, "正在等待模型服务");
  assert.equal(waiting[2]?.value, "有结果未知的远程动作");
  assert.equal(waiting[3]?.value, "3 封未读指导");
  assert.equal(waiting[4]?.value, "2 封询问在等它回答");
  assert.equal(waiting[5]?.value, "摘要 4 份、笔记 5 条");
  // 没有等待、没有结果未知、没有未读指导、没有询问时也各有一句，不写空白
  const idle = workshopFacts(workspace({
    room: { machine: "build-01", waiting_provider: false, remote_unknown: false, mailbox: 0, roles: [] },
  }));
  assert.equal(idle[0]?.value, "build-01");
  assert.equal(idle[1]?.value, "没有在等待模型服务");
  assert.equal(idle[2]?.value, "没有结果未知的远程动作");
  assert.equal(idle[3]?.value, "0 封未读指导");
  assert.equal(idle[4]?.value, NO_ASK_TEXT);
  assert.equal(idle[5]?.value, "摘要 0 份、笔记 0 条");
});

test("角色取工作间的角色与它的状态，不写死职能清单", () => {
  const facts = workshopFacts(workspace({
    room: {
      machine: "build-01", waiting_provider: false, remote_unknown: false, mailbox: 0,
      roles: [{ id: "r1", name: "核对的角色", kind: "verifier", status: "idle", task: null }],
    },
  }));
  const roles = facts.filter((fact) => fact.label === "角色");
  assert.equal(roles.length, 1);
  assert.match(roles[0]?.value ?? "", /^核对的角色：/);
});

test("最近一次请求的模型、协议与档位取自工作间", () => {
  const facts = lastRequestFacts(workspace({
    last_call: {
      requested_model: "m-a", actual_model: "m-b", requested_protocol: "openai-chat",
      requested_tier: "高", sent_tier: "中",
    },
  }));
  assert.equal(facts.length, 1);
  assert.equal(facts[0]?.label, "最近一次请求");
  assert.match(facts[0]?.value ?? "", /m-a/);
  assert.match(facts[0]?.value ?? "", /协议 openai-chat/);
  assert.match(facts[0]?.value ?? "", /请求 高，实际发送 中/);
  // 没有请求的模型时写实际使用的；没有报协议、档位时写「未上报」，不写空白
  assert.match(lastRequestFacts(workspace({ last_call: { actual_model: "m-b" } }))[0]?.value ?? "", /m-b/);
  assert.match(
    lastRequestFacts(workspace({ last_call: {} }))[0]?.value ?? "",
    new RegExp(`协议 ${NOT_REPORTED_TEXT}`),
  );
  assert.match(lastRequestFacts(workspace({ last_call: {} }))[0]?.value ?? "", new RegExp(NOT_REPORTED_TEXT));
  assert.equal(lastRequestFacts(workspace())[0]?.value, NO_LAST_CALL_TEXT);
  // 工作间还没有读到时不写这一段
  assert.deepEqual(lastRequestFacts(null), []);
  assert.deepEqual(workshopFacts(null), []);
});

test("指导与处理状态：每条指导一行，写第几版与它看到了哪一步", () => {
  const facts = guidanceFacts(workspace({
    guidance: [
      { guidance_id: "g1", version: 1, text: "先跑检查", status: "received" },
      { guidance_id: "g2", version: 2, text: "再写风险", status: "in_input" },
    ],
  }));
  assert.deepEqual(facts.map((fact) => fact.label), ["指导（第 1 版）", "指导（第 2 版）"]);
  assert.equal(facts[0]?.value, "已接收");
  assert.equal(facts[1]?.value, "已进入模型输入");
  // 没有收到过指导时也有一句，不写空白
  assert.deepEqual(guidanceFacts(workspace()), [{ label: "指导", value: NO_GUIDANCE_TEXT }]);
  // 工作间还没有读到时不写这一段
  assert.deepEqual(guidanceFacts(null), []);
});

test("等了多久：取它发出、还没答的询问里最早那一封，没有在等时写一句", () => {
  const now = Date.parse("2026-11-11T08:03:20Z");
  const node1 = node();
  assert.equal(waitedTextFor(node1, [ask({ started_at: "2026-11-11T08:03:00Z" })], now), "已等 20 秒");
  // 有多封时取最早的
  assert.equal(waitedTextFor(node1, [
    ask({ id: "a1", started_at: "2026-11-11T08:01:00Z" }),
    ask({ id: "a2", started_at: "2026-11-11T08:03:00Z" }),
  ], now), "已等 2 分 20 秒");
  // 别人发出的询问、已经答完的询问都不算
  assert.equal(waitedTextFor(node1, [
    ask({ requester: "quality" }),
    ask({ id: "a2", status: "已回答", ended_at: "2026-11-11T08:03:10Z" }),
  ], now), NO_WAIT_TEXT);
  // 没有读到询问、没有开始时间时写同一句，不写一个假数
  assert.equal(waitedTextFor(node1, [], now), NO_WAIT_TEXT);
  assert.equal(waitedTextFor(node1, null, now), NO_WAIT_TEXT);
  assert.equal(waitedTextFor(node1, [ask({ started_at: "" })], now), NO_WAIT_TEXT);
  // 整份正文里也带着这一句
  const view = nodePanelView(node1, null, "p1", "w1", [ask({ started_at: "2026-11-11T08:03:00Z" })], now);
  assert.equal(view.waited, "已等 20 秒");
});

test("底部两个入口：职能详情到节点所在职能的详情页，模型请求带着职能筛选", () => {
  const links = entryLinks("p1", "w1", "engineering");
  assert.match(links.detail, /^#\/p\/p1\/dept-detail\/engineering\?/);
  assert.match(links.detail, /w=w1/);
  // 设置页不再有「职能设置」一节（工单 #1713），详情入口不再落到设置页
  assert.doesNotMatch(links.detail, /settings/);
  assert.match(links.requests, /section=requests/);
  assert.match(links.requests, /dept=engineering/);
  assert.match(links.requests, /w=w1/);
  // 没有事项时不写 w
  assert.doesNotMatch(entryLinks("p1", "", "engineering").requests, /(^|[?&])w=/);
  // 地址回到路由以后，设置页那一节是展开的，职能筛选按这个职能生效（工单 #1710 的读法）
  const requests = parseRoute(links.requests);
  assert.equal(requests.settingsSection, "requests");
  assert.equal(requests.requestFilters.department, "engineering");
  assert.equal(requests.workItemId, "w1");
  const detail = parseRoute(links.detail);
  assert.equal(detail.name, "dept-detail");
  assert.equal(detail.department, "engineering");
  assert.equal(detail.workItemId, "w1");
});

test("整份正文：事实按从上到下的顺序给，入口地址取自节点所在的职能", () => {
  const view = nodePanelView(
    node({ id: "quality", label: "质检", state: "一轮工作中", working: true }),
    workspace({ last_call: { requested_model: "m-a", requested_tier: "高", sent_tier: "高" } }),
    "p1",
    "w1",
  );
  assert.equal(view.state, "一轮工作中");
  assert.equal(view.live, true);
  assert.deepEqual(view.facts.map((fact) => fact.label),
    ["执行机器", "等模型服务", "结果未知", "未读指导", "等它回答的询问", "手边的摘要与笔记",
      "最近一次请求", "指导"]);
  assert.equal(view.waited, NO_WAIT_TEXT);
  assert.match(view.links.requests, /dept=quality/);
});

test("面板里不写死职能清单：这份组织以外的职能名一个都不出现", () => {
  // 一个只有「运维」的组织（工单验收：用「工程」的项目面板同样可用，不出现这份组织以外的职能名）
  const view = nodePanelView(
    node({ id: "ops", label: "运维", state: "等待工作" }),
    workspace({
      room: {
        machine: "build-01", waiting_provider: false, remote_unknown: false, mailbox: 0,
        roles: [{ id: "r1", name: "值班的角色", kind: "doer", status: "idle", task: null }],
      },
    }),
    "p1",
    "w1",
  );
  const written = [view.state, ...view.waiting, ...view.facts.map((fact) => `${fact.label}：${fact.value}`),
    view.links.detail, view.links.requests].join("\n");
  assert.match(written, /运维|值班的角色/);
  for (const other of ["产品", "工程", "质检"]) {
    assert.doesNotMatch(written, new RegExp(other));
  }
  assert.match(view.links.requests, /dept=ops/);
});
