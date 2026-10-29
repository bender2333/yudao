// 恢复页的文字与状态映射（工单 #181，原型 v13 `js/ui/views/recovery.js`）：
// 最后已确认的位置、自动继续的时间、结果未知的动作与它的处理方式、各会话的用量都写成中文，
// 页面上因此不出现 handed_back、work、main 这些内部取值。
// 期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PENDING_NOTE,
  TERMINAL_NOTE,
  actionSessionText,
  autoResumeText,
  handlingKind,
  handlingNote,
  handlingText,
  interruptedAtText,
  lastConfirmedText,
  purposeText,
  sessionUsageRows,
  showsInterruptionRecord,
} from "../../src/renderer/src/views/project/recovery-text.ts";
import type {
  RecoveryOwner,
  RecoverySession,
} from "../../src/renderer/src/api/generated/types.gen.ts";

function owner(over: Partial<RecoveryOwner> = {}): RecoveryOwner {
  const base: RecoveryOwner = {
    epoch: 1,
    since: "2026-10-29T23:30:00+00:00",
    holds_slot: true,
    interrupted_at_event_id: null,
    interrupted_at_text: null,
  };
  return { ...base, ...over };
}

function session(over: Partial<RecoverySession> = {}): RecoverySession {
  const base: RecoverySession = {
    session_id: "ses_main_product",
    department: "product",
    kind: "main",
    elapsed_sec: 0,
    activations: 0,
    model_steps: 0,
  };
  return { ...base, ...over };
}

test("最后已确认的位置写这条事件的文字，没有文字时写第几条事件", () => {
  assert.equal(
    lastConfirmedText({ last_confirmed_text: "结束这次激活：产品提交了有效需求", last_confirmed_position: 12 }),
    "结束这次激活：产品提交了有效需求",
  );
  assert.equal(lastConfirmedText({ last_confirmed_text: null, last_confirmed_position: 12 }), "第 12 条事件");
  assert.equal(lastConfirmedText({ last_confirmed_text: null, last_confirmed_position: 0 }), "还没有已确认的事件");
});

test("自动继续的时间：没有执行权时写还没有自动继续，有执行权时写取得的时间", () => {
  assert.equal(autoResumeText(null), "还没有自动继续");
  assert.equal(autoResumeText(owner({ since: "" })), "还没有自动继续");
  // 时间是本地时区的时刻，只核对它与取得的时间一致（不是「还没有自动继续」这句话）
  assert.notEqual(autoResumeText(owner()), "还没有自动继续");
});

test("中断位置取执行权记下的那句话，没有时写没有记录", () => {
  assert.equal(interruptedAtText(null), "没有记录");
  assert.equal(interruptedAtText(owner()), "没有记录");
  assert.equal(
    interruptedAtText(owner({ interrupted_at_text: "调用工具 bash" })),
    "调用工具 bash",
  );
});

test("处理方式写核实确认或交还会话，并给出各自的标记与说明", () => {
  assert.equal(handlingText("confirmed"), "核实确认");
  assert.equal(handlingText("returned"), "交还会话");
  assert.equal(handlingKind("confirmed"), "succeeded");
  assert.equal(handlingKind("returned"), "asking");
  assert.match(handlingNote("returned"), /交还发出它的会话/);
  assert.match(handlingNote("confirmed"), /没有因此重新执行/);
  assert.match(PENDING_NOTE, /交还发出它的会话/);
});

test("动作的用途写中文，没有用途时只写工具调用", () => {
  assert.equal(purposeText("work"), "工作中的工具调用");
  assert.equal(purposeText("compaction"), "压缩上下文时的调用");
  assert.equal(purposeText(null), "工具调用");
  assert.equal(purposeText(""), "工具调用");
  // 没有登记的取值不原样显示（页面上不出现英文内部取值）
  assert.equal(purposeText("whatever"), "工具调用");
});

test("各会话的用量表写部门、主线或分支与分支的编号", () => {
  const rows = sessionUsageRows([
    session({ session_id: "ses_main_product", department: "product", kind: "main", elapsed_sec: 30, activations: 1, model_steps: 2 }),
    session({ session_id: "ses_main_engineering", department: "engineering", kind: "main", elapsed_sec: 45, activations: 2, model_steps: 3 }),
    session({ session_id: "ses_ask_1", department: "product", kind: "branch", elapsed_sec: 5, activations: 1, model_steps: 1 }),
    session({ session_id: "ses_ask_2", department: "product", kind: "branch", elapsed_sec: 7, activations: 1, model_steps: 1 }),
  ]);
  assert.deepEqual(rows.map((row) => row.label), ["产品 · 部门主线", "工程 · 部门主线", "产品 · 询问分支 1", "产品 · 询问分支 2"]);
  assert.deepEqual(rows.map((row) => row.key), ["ses_main_product", "ses_main_engineering", "ses_ask_1", "ses_ask_2"]);
  assert.deepEqual(
    rows.map((row) => [row.elapsedSec, row.activations, row.modelSteps]),
    [[30, 1, 2], [45, 2, 3], [5, 1, 1], [7, 1, 1]],
  );
});

test("动作所在的会话按用量表解析名字，查不到时写未上报", () => {
  const sessions = [
    session({ session_id: "ses_main_engineering", department: "engineering", kind: "main" }),
    session({ session_id: "ses_ask_1", department: "product", kind: "branch" }),
  ];
  assert.equal(actionSessionText(sessions, "ses_main_engineering"), "工程 · 部门主线");
  assert.equal(actionSessionText(sessions, "ses_ask_1"), "产品 · 询问分支 1");
  assert.equal(actionSessionText(sessions, null), "未上报");
  assert.equal(actionSessionText(sessions, "ses_unknown"), "未上报");
});

test("继续以后运行中的页面仍显示这次中断，其余状态不显示这一块", () => {
  const resumed = owner({ interrupted_at_event_id: "evt_9", interrupted_at_text: "调用工具 bash" });
  assert.equal(showsInterruptionRecord({ state: "running", owner: resumed }), true);
  assert.equal(showsInterruptionRecord({ state: "interrupted", owner: resumed }), true);
  assert.equal(showsInterruptionRecord({ state: "completed", owner: resumed }), false);
  // 没有中断位置（从未中断后继续，或者还没有取得执行权）时不显示
  assert.equal(showsInterruptionRecord({ state: "running", owner: owner() }), false);
  assert.equal(showsInterruptionRecord({ state: "running", owner: null }), false);
});

test("四种结束方式各有自己的说明", () => {
  assert.deepEqual(Object.keys(TERMINAL_NOTE).sort(), ["cancelled", "completed", "paused", "stopped"]);
  assert.match(TERMINAL_NOTE.completed, /已完成的运行不再继续/);
});
