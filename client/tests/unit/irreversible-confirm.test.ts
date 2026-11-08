// 不可逆操作的确认规则（工单 #737）：点下去以前先说清后果，并给一次反悔的机会。
// 这一条规则落在两处：移除模型访问定义（取消选用）与取消事项／放弃本次建档。
// 两处都按同一种做法：点下去只换来一次确认，命令要到确认以后才交给服务端；
// 确认按钮用 danger 样式，不做的那个用普通样式，用户从样式就能分出危险性。
// 可逆的操作（归档项目可以「恢复项目」）不加确认，这条规则只在不可逆的操作上生效。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  REMOVE_CONFIRM_CANCEL,
  REMOVE_CONFIRM_CONFIRM,
  REMOVE_CONFIRM_TITLE,
  removalCommand,
  removeConfirmLines,
  type RemovalRequest,
} from "../../src/renderer/src/views/models/model-logic.ts";
import {
  CANCEL_CONFIRM_CANCEL,
  CANCEL_CONFIRM_CONFIRM,
  cancelConfirmLines,
  cancelConfirmTitle,
  cancelItemCommand,
  cancelItemLabel,
  type CancelRequest,
} from "../../src/renderer/src/views/project/cancel-text.ts";

// 已选模型清单里的一行：要移除的那一条访问定义
function removal(over: Partial<RemovalRequest> = {}): RemovalRequest {
  return {
    key: "go/glm-4.6",
    provider_id: "go",
    model_id: "d1",
    upstream_model: "glm-4.6",
    provider_address: "http://a/v1",
    admitted: true,
    ...over,
  };
}

// 「取消事项」这一行：一个正在执行的事项
function cancelRequest(over: Partial<CancelRequest> = {}): CancelRequest {
  return { work_item_id: "w1", base_version: 7, status: "in_progress", ...over };
}

// ---------------------------------------------------------------------------
// 移除模型访问定义
// ---------------------------------------------------------------------------

test("移除访问定义：确认框写明这条定义从这个连接下移除、准入记录作废、依赖它的职能绑定会失效", () => {
  const all = [REMOVE_CONFIRM_TITLE, ...removeConfirmLines({ upstream_model: "glm-4.6", provider_address: "http://a/v1", admitted: true })]
    .join("；");
  assert.match(all, /glm-4\.6/);
  assert.match(all, /http:\/\/a\/v1/);
  assert.match(all, /准入记录作废/);
  assert.match(all, /职能绑定会失效/);
  // 被引用时不移除、引用方写在这一行旁边：确认框交代这条出路，用户不会以为点了就一定移除
  assert.match(all, /拒绝移除/);
  assert.match(all, /引用方/);
});

test("移除访问定义：还没有通过验证的那一行多写一句，进行中的验证一起作废", () => {
  const admitted = removeConfirmLines({ upstream_model: "glm-4.6", provider_address: "http://a/v1", admitted: true }).join("；");
  const testing = removeConfirmLines({ upstream_model: "glm-4.6", provider_address: "http://a/v1", admitted: false }).join("；");
  assert.doesNotMatch(admitted, /进行中的验证/);
  assert.match(testing, /进行中的验证/);
});

test("移除访问定义：点下去只换来一次确认，命令要到确认以后才给出", () => {
  // 点「取消选用」以后：待确认的那一行在，命令还没有
  assert.equal(removalCommand(removal(), false), null);
  // 没有待确认的那一行时，确认也不产生命令
  assert.equal(removalCommand(null, true), null);
  // 确认以后才交出去：参数就是这条定义所属的连接与定义本身
  assert.deepEqual(removalCommand(removal(), true), { provider_id: "go", model_id: "d1" });
});

test("移除访问定义：确认框的两个按钮各一句，取消的那个不叫「取消」（免得与取消选用混起来）", () => {
  assert.equal(REMOVE_CONFIRM_CONFIRM, "确认移除");
  assert.equal(REMOVE_CONFIRM_CANCEL, "先不移除");
});

// ---------------------------------------------------------------------------
// 取消事项／放弃本次建档
// ---------------------------------------------------------------------------

test("取消事项与放弃本次建档：按钮与标题按事项状态取", () => {
  assert.equal(cancelItemLabel("in_progress"), "取消事项");
  assert.equal(cancelItemLabel("awaiting_initial_prd"), "放弃本次建档");
  assert.match(cancelConfirmTitle("in_progress"), /取消/);
  assert.match(cancelConfirmTitle("awaiting_initial_prd"), /放弃/);
});

test("取消事项的确认框写明取消以后不能恢复、只能另建一个事项", () => {
  const all = [cancelConfirmTitle("in_progress"), ...cancelConfirmLines("in_progress")].join("；");
  assert.match(all, /取消以后不能恢复/);
  assert.match(all, /只能另建一个事项/);
});

test("放弃本次建档的确认框写明放弃以后不能恢复、只能另建一个事项，并说清撤回的是等待确认的初始 PRD", () => {
  const all = [cancelConfirmTitle("awaiting_initial_prd"), ...cancelConfirmLines("awaiting_initial_prd")].join("；");
  assert.match(all, /不能恢复/);
  assert.match(all, /只能另建一个事项/);
  assert.match(all, /初始 PRD/);
});

test("取消事项：点下去只换来一次确认，命令要到确认以后才给出", () => {
  assert.equal(cancelItemCommand(cancelRequest(), false), null);
  assert.equal(cancelItemCommand(null, true), null);
  assert.deepEqual(cancelItemCommand(cancelRequest(), true), { work_item_id: "w1", base_version: 7 });
});

test("取消事项：确认框的两个按钮各一句", () => {
  assert.equal(CANCEL_CONFIRM_CONFIRM, "确认取消");
  assert.equal(CANCEL_CONFIRM_CANCEL, "先不取消");
});
