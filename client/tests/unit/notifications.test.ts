// 系统通知与标签页标题的单元测试（网页界面的提供与发布设计说明第 5.3 节，工单 #375）。
// 核对事件到通知的翻译：三类通知的标记、标题与正文，点开决定卡片所需的标识，以及标题里的数量。
// 浏览器通知的发出与权限由端到端用例在真实 Chromium 里核对（client/tests/e2e/notifications.spec.ts）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { pageTitle, noticeForEvent, type NoticeNames } from "../../src/renderer/src/shell/notifications.ts";
import type { EventObject } from "../../src/renderer/src/api/generated/types.gen";

const names: NoticeNames = {
  projectName: (id) => (id === "proj_1" ? "结算台账" : (id ?? "")),
  workItemTitle: (id) => (id === "witem_1" ? "导出对账单" : (id ?? "")),
};

function event(type: string, payload: Record<string, unknown>): EventObject {
  return {
    type,
    position: 12,
    previous: 11,
    event_id: "pevt_7",
    at: "2026-10-08T02:00:00Z",
    stream: "project:proj_1",
    stream_version: 7,
    project_id: "proj_1",
    work_item_id: "witem_1",
    run_id: "run_1",
    department: "product",
    role: null,
    actor: "system:orchestrator",
    command_id: null,
    label: "决定请求",
    payload,
  } as unknown as EventObject;
}

test("决定请求的通知写明项目与事项，点击以后打开这张决定卡片", () => {
  const notice = noticeForEvent(event("decision_requested", { kind: "initial_prd", options: [] }), names);
  // 标记取决定请求的身份：决定请求的身份就是发出它的事件的编号（harness/projection.py）
  assert.equal(notice?.tag, "pevt_7");
  assert.equal(notice?.decisionId, "pevt_7");
  assert.equal(notice?.title, "需要你决定");
  assert.equal(notice?.body, "结算台账 · 导出对账单：接入已有项目的初始需求文档等待确认");
});

test("模型引用无法使用的决定请求，标题写明在等待模型服务", () => {
  const notice = noticeForEvent(event("decision_requested", { kind: "model_unavailable", options: [] }), names);
  assert.equal(notice?.title, "等待模型服务，需要你决定");
  assert.equal(notice?.body, "结算台账 · 导出对账单：模型引用无法使用，等待恢复");
});

test("项目流上的决定请求给出同样的通知，事项还没有取到时正文写标识", () => {
  const notice = noticeForEvent(event("project_decision_requested", { kind: "initial_prd", options: [] }), {
    projectName: (id) => (id === "proj_1" ? "结算台账" : ""),
    workItemTitle: () => "",
  });
  assert.equal(notice?.tag, "pevt_7");
  assert.equal(notice?.body, "结算台账 · ：接入已有项目的初始需求文档等待确认");
});

test("等待模型服务：模型重试的通知写明项目、事项、部门的模型与重试的间隔", () => {
  const notice = noticeForEvent(
    event("model_retry_scheduled", { requested_model: "glm-4.6", delay_sec: 4 }),
    names,
  );
  assert.equal(notice?.tag, "pevt_7");
  // 重试通知没有去处：点击以后没有对应的决定卡片
  assert.equal(notice?.decisionId, null);
  assert.equal(notice?.title, "等待模型服务");
  assert.equal(notice?.body, "结算台账 · 导出对账单：产品部门的模型 glm-4.6 暂时不可用，4 秒后重试");
});

test("与通知无关的事件不发通知", () => {
  assert.equal(noticeForEvent(event("run_done", { reason: "completed" }), names), null);
});

test("标签页的标题：有待决定的事时显示数量，没有时不显示数字", () => {
  assert.equal(pageTitle(2, "Yudao"), "(2) Yudao");
  assert.equal(pageTitle(0, "Yudao"), "Yudao");
});