// 决定卡片纯逻辑的单元测试（原型 v8 设计说明第 6 节，工单 #175）：
// 材料按决定种类整理、挡住的对象、等待时长、「在项目中查看」的目标、按发出时间排列，
// 以及给像素画面用的纯文字版本与页面卡片共用同一份材料。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  blockedText,
  decisionLinks,
  face,
  materialRows,
  sortByRequested,
  viewHref,
  waitedSeconds,
} from "../../src/renderer/src/views/decisions/card-logic.ts";

function decision(overrides) {
  return {
    decision_id: "d1",
    project_id: "p1",
    work_item_id: "w1",
    run_id: "r1",
    kind: "model_unavailable",
    blocks: "run",
    version: 3,
    status: "open",
    requested_at: "2026-10-02T10:00:00Z",
    blocked: { work_item_id: "w1", queued_after: 2 },
    request: {
      kind: "model_unavailable",
      blocks: "run",
      options: [
        { id: "continue", label: "继续执行" },
        { id: "stop", label: "停止事项" },
      ],
      description: "工程部门的模型引用无法使用",
      facts: [],
      department: "engineering",
      target: { model_id: "glm-4.6" },
      reason: "provider_unavailable",
      message: "Missing configuration: provider credential",
    },
    answer: null,
    ...overrides,
  };
}

test("待恢复的决定：材料列出部门、模型与具体问题", () => {
  const rows = materialRows(decision());
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["部门"], "工程");
  assert.equal(map["模型"], "glm-4.6");
  assert.equal(map["具体问题"], "Missing configuration: provider credential");
  assert.equal(map["说明"], "工程部门的模型引用无法使用");
});

test("结果未知的动作：材料写明契约是否声明可以重复", () => {
  const rows = materialRows(
    decision({
      kind: "unknown_action",
      blocks: "action",
      request: {
        kind: "unknown_action",
        blocks: "action",
        options: [{ id: "re_execute", label: "重新执行" }],
        description: "动作结果未知",
        facts: ["evt_1"],
        department: "engineering",
        action_id: "act_9",
        tool: "run_command",
        action_kind: "command",
        repeatable: true,
      },
    }),
  );
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["动作"], "act_9");
  assert.equal(map["契约是否声明可以重复"], "可以重复执行");
});

test("挡住的对象：写明被阻塞的事项与排在后面的事项数量", () => {
  assert.deepEqual(blockedText(decision()), { text: "挡住「w1」，同一项目中排在它后面的事项 2 个", muted: false });
  const idle = decision({ blocks: "", blocked: null });
  assert.deepEqual(blockedText(idle), { text: "不挡住事项", muted: true });
});

test("等待时长：按发出时间到现在的差，负差按零", () => {
  const requested = "2026-10-02T10:00:00Z";
  const now = new Date("2026-10-02T10:05:30Z").getTime();
  assert.equal(waitedSeconds(requested, now), 330);
  assert.equal(waitedSeconds(requested, new Date("2026-10-02T09:00:00Z").getTime()), 0);
});

test("「在项目中查看」的目标：待恢复落到该事项的恢复页，没有事项时落到项目概览", () => {
  assert.equal(viewHref(decision()), "#/p/p1/w/w1/recovery");
  assert.equal(viewHref(decision({ work_item_id: null })), "#/p/p1/overview");
  assert.equal(viewHref(decision({ project_id: null, work_item_id: null })), null);
});

test("待恢复的决定：材料里的跳转前往模型管理与本项目的部门设置", () => {
  const links = decisionLinks(decision());
  assert.deepEqual(links.map((link) => link.href), ["#/sys/models", "#/p/p1/settings"]);
  assert.deepEqual(links.map((link) => link.label), ["前往模型管理", "前往本项目的部门设置"]);
});

test("等待回答的请求按发出时间排列", () => {
  const rows = sortByRequested([
    decision({ decision_id: "b", requested_at: "2026-10-02T11:00:00Z" }),
    decision({ decision_id: "a", requested_at: "2026-10-02T09:00:00Z" }),
    decision({ decision_id: "c", requested_at: "2026-10-02T10:00:00Z" }),
  ]);
  assert.deepEqual(rows.map((row) => row.decision_id), ["a", "c", "b"]);
});

test("给像素画面用的纯文字版本与页面卡片共用同一份材料", () => {
  const now = new Date("2026-10-02T10:01:00Z").getTime();
  const card = face(decision(), now);
  assert.equal(card.id, "d1");
  assert.equal(card.title, "模型引用无法使用，等待恢复");
  assert.equal(card.blocks, "挡住「w1」，同一项目中排在它后面的事项 2 个");
  assert.deepEqual(card.rows, materialRows(decision()));
  assert.deepEqual(card.options.map((option) => option.id), ["continue", "stop"]);
});

test("给画面用的卡片内容带上决定版本、项目与事项、链接与选项的说明标记", () => {
  const now = new Date("2026-10-02T10:01:00Z").getTime();
  const card = face(decision({ request: { ...decision().request, options: [{ id: "revise", label: "提出修改", note_required: true }] } }), now, {
    projectName: "文本工具",
    workItemTitle: "实现逐行处理",
  });
  assert.equal(card.version, 3);
  assert.equal(card.work_item_id, "w1");
  assert.equal(card.where, "文本工具 · 实现逐行处理");
  assert.equal(card.waited, "已等待 60 秒");
  assert.deepEqual(card.links.map((link) => link.href), ["#/sys/models", "#/p/p1/settings"]);
  assert.equal(card.options[0].note_required, true);
  // 没有给出名称时回落到标识
  const bare = face(decision(), now);
  assert.equal(bare.where, "p1 · w1");
});
