// 规则与参数页的辅助逻辑（工单 #1195）。验收第 6 条：页面辅助逻辑单元测试覆盖
// 分组、界限判断、未接入状态、撤回记录身份和理由。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { ParameterChangeEntry, RuleEntry } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  RECORD_FIELD_LABELS,
  RULES_PAGE_NOTE,
  WITHDRAW_BLOCK_TEXT,
  boundsText,
  changeLine,
  editable,
  groupRules,
  latestChange,
  notWiredText,
  numericBounds,
  recentChanges,
  sameValue,
  valueText,
  withdrawCheck,
  withdrawReason,
} from "../../src/renderer/src/views/system/rules-view.ts";

// 一条登记的替身：字段与生成的 RuleEntry 合同一致（缺省已接入的数值参数）
function entry(overrides: Partial<RuleEntry> = {}): RuleEntry {
  return {
    name: "check_timeout_sec",
    value: 600,
    default_value: 600,
    bounds: [1, 86400],
    kind: "parameter",
    form: "boundary",
    wired: true,
    not_wired_reason: "",
    guards: "检查停住不返回",
    cost: "长检查无法运行",
    relax_when: "按项目记录的检查用时分布设定",
    tighten_when: "同一项目的检查用时分布长期低于现值的四分之一",
    origin: "规则登记第 8 节表格",
    changes: [],
    ...overrides,
  };
}

function change(overrides: Partial<ParameterChangeEntry> = {}): ParameterChangeEntry {
  return {
    old_value: 600,
    new_value: 300,
    reason: "长检查经常超时",
    modified_by: "user:local",
    parameters_version: "abcd1234efgh5678",
    event_id: "evt-2",
    created_at: "2026-10-31T08:00:00+00:00",
    stream_version: 9,
    ...overrides,
  };
}

test("分组按条目名的第一个点之前的部分归组，顺序保持登记给出的顺序", () => {
  const groups = groupRules([
    entry({ name: "run_time_limit_sec" }),
    entry({ name: "check_timeout_sec" }),
    entry({ name: "context.column_limit.catalog" }),
    entry({ name: "context.column_limit.lessons" }),
    entry({ name: "wait.desktop.max_sec" }),
    entry({ name: "onboarding.round_time_limit_sec" }),
  ]);
  assert.deepEqual(groups.map((group) => [group.domain, group.rules.length]), [
    ["其他", 2],
    ["context", 2],
    ["wait", 1],
    ["onboarding", 1],
  ]);
  // 每组内部仍是登记的顺序（登记按名称排列）
  assert.deepEqual(groups[0]?.rules.map((rule) => rule.name), ["run_time_limit_sec", "check_timeout_sec"]);
  assert.deepEqual(groups[1]?.rules.map((rule) => rule.name), ["context.column_limit.catalog", "context.column_limit.lessons"]);
});

test("界限判断：两端的数才认，其余（结构条目的 [0,1] 除外一样认；非两元或非数不认）", () => {
  assert.deepEqual(numericBounds(entry({ bounds: [1, 86400] })), { min: 1, max: 86400 });
  assert.deepEqual(numericBounds(entry({ bounds: [0, 1] })), { min: 0, max: 1 });
  assert.equal(numericBounds(entry({ bounds: [] })), null);
  assert.equal(numericBounds(entry({ bounds: [1] })), null);
  assert.equal(numericBounds(entry({ bounds: ["600", "86400"] })), null);
  // 浮点界限（验证密度一类）同样认
  assert.deepEqual(numericBounds(entry({ bounds: [0.01, 1.0] })), { min: 0.01, max: 1.0 });
});

test("界限显示与编辑门槛：接入了的数值型参数可修改，结构、未接入、非数值只读", () => {
  // 工单正文：check_timeout_sec 与 onboarding.round_time_limit_sec 可以修改全局值
  assert.equal(editable(entry({ name: "check_timeout_sec" })), true);
  assert.equal(editable(entry({ name: "onboarding.round_time_limit_sec", value: 7200, default_value: 7200 })), true);
  // 结构条目只读（提示结构修改走候选流程）
  assert.equal(editable(entry({ kind: "structure", value: true, default_value: true, bounds: [0, 1] })), false);
  // 未接入的条目禁用修改
  assert.equal(editable(entry({ wired: false, not_wired_reason: "还没有代码读取它：执行槽位的调度还没有实现" })), false);
  // 字符串与列表参数只读（登记还没有提供候选约束）
  assert.equal(editable(entry({ value: "text", default_value: "text" })), false);
  assert.equal(editable(entry({ value: [1, 2], default_value: [1, 2] })), false);
  // 布尔型参数（bounds [0,1] 的开关）同样按只读处理：登记没有提供候选约束
  assert.equal(editable(entry({ value: true, default_value: true })), false);
});

test("未接入状态：显示登记提供的原因，页面不自行书写拒绝原因", () => {
  const reason = "还没有代码读取它：执行槽位的调度还没有实现，现在一次只执行一个事项";
  assert.equal(notWiredText(entry({ wired: false, not_wired_reason: reason })), `未接入运行：${reason}`);
  // 已接入的条目没有这一行
  assert.equal(notWiredText(entry()), "");
  // 登记给了空串的已接入条目不显示
  assert.equal(notWiredText(entry({ wired: true, not_wired_reason: "" })), "");
});

test("撤回记录身份：身份一致且现值等于记录的新值才允许；身份或现值变了都放弃（ABA 防护）", () => {
  const withChange = entry({ value: 300, changes: [change()] });
  // 选中最近一条：现值 300 仍等于记录的新值，允许撤回
  const ok = withdrawCheck(withChange, "evt-2");
  assert.equal(ok.ok, true);
  if (ok.ok) {
    assert.equal(ok.change.event_id, "evt-2");
    assert.equal(ok.change.old_value, 600);
  }
  // 现值经历 A→B→A 又变回 600：数值相同，但最近记录的身份已是 evt-3，放弃撤回
  const aba = entry({
    value: 600,
    changes: [
      change(),
      change({ event_id: "evt-3", old_value: 300, new_value: 600, reason: "改回原值", parameters_version: "ffff000011112222" }),
    ],
  });
  const moved = withdrawCheck(aba, "evt-2");
  assert.deepEqual(moved, { ok: false, reason: "record_moved" });
  // 选中了现在的最近记录但现值又不相等：放弃
  const drifted = entry({ value: 440, changes: [change(), change({ event_id: "evt-4", old_value: 300, new_value: 450 })] });
  assert.deepEqual(withdrawCheck(drifted, "evt-4"), { ok: false, reason: "value_changed" });
  // 没有修改记录的条目没有可撤回的修改
  assert.deepEqual(withdrawCheck(entry(), "evt-2"), { ok: false, reason: "no_change" });
});

test("最近记录取历史最后一条，历史显示按时间倒序", () => {
  const first = change({ event_id: "evt-1", new_value: 450 });
  const second = change({ event_id: "evt-2" });
  const item = entry({ value: 300, changes: [first, second] });
  assert.equal(latestChange(item)?.event_id, "evt-2");
  assert.deepEqual(recentChanges(item).map((item2) => item2.event_id), ["evt-2", "evt-1"]);
  // 没有记录时最近一条为空
  assert.equal(latestChange(entry()), null);
});

test("撤回理由自动加「撤回：」，历史一行写全谁改的、从什么改成什么、理由", () => {
  assert.equal(withdrawReason("长检查经常超时"), "撤回：长检查经常超时");
  const line = changeLine(change());
  assert.match(line, /user:local/);
  assert.match(line, /600/);
  assert.match(line, /300/);
  assert.match(line, /长检查经常超时/);
});

test("值相等比较：数按数值比，其余按内容比；ABA 防护靠身份，不靠数值", () => {
  assert.equal(sameValue(300, 300), true);
  assert.equal(sameValue("300", 300), false);
  assert.equal(sameValue(true, true), true);
  assert.deepEqual(valueText(600), "600");
  assert.deepEqual(valueText("text"), "text");
  assert.deepEqual(valueText(true), "true");
  assert.deepEqual(valueText([1, 2]), "[1,2]");
});

test("界限显示文案写允许范围，没有界限时不写", () => {
  assert.equal(boundsText({ min: 1, max: 86400 }), "允许范围 1 至 86400");
  assert.equal(boundsText(null), "");
});

test("页面说明写明修改只作用于之后创建的 run，四项记录的标签与登记字段对齐", () => {
  // 设计说明：修改只作用于之后创建的 run，正在运行的 run 按自己冻结的值结束
  assert.match(RULES_PAGE_NOTE, /之后创建的 run/);
  assert.match(RULES_PAGE_NOTE, /冻结/);
  // 四项记录：拦截什么、花费多少、放松与收紧的证据（设计说明第 2 节）
  assert.deepEqual(RECORD_FIELD_LABELS.map(([, label]) => label), ["拦截什么", "花费多少", "放松的证据", "收紧的证据"]);
  assert.deepEqual(RECORD_FIELD_LABELS.map(([field]) => field), ["guards", "cost", "relax_when", "tighten_when"]);
});

test("撤回被页面拦下时的三句说明各自说清原因，提交确认写恢复值", () => {
  // 三种拦下情形的文案都能读，且不把服务拒绝原因混进来（页面不书写服务拒绝）
  assert.match(WITHDRAW_BLOCK_TEXT.no_change, /没有修改记录/);
  assert.match(WITHDRAW_BLOCK_TEXT.record_moved, /记录身份/);
  assert.match(WITHDRAW_BLOCK_TEXT.value_changed, /现值/);
  assert.ok(Object.keys(WITHDRAW_BLOCK_TEXT).length === 3);
});
