// 询问一行的文字（三部门的循环结构第 4.7 节、原型 v12 设计说明第 3.3 节，工单 #904）：
// 一次询问写状态、询问链、回问标记、时间与问题；有回答时写回答（附带 PRD 时标版本），没能回答写原因。
// 期望值写成字面值，不复用实现的公式：询问链与标记的样子直接写在这里。

import { test } from "node:test";
import assert from "node:assert/strict";
import { askChain, askIndent, askLine } from "../../src/renderer/src/views/project/asks-text.ts";
import type { AskView } from "../../src/renderer/src/api/generated/types.gen.ts";

// 时间由共用的 formatTime 写：这里给空的时间，页面上写「未知时间」，
// 这条用例核对的是询问这一行除了时间以外的文字（时间列由端到端测试看真实数据）
function ask(over: Partial<AskView> = {}): AskView {
  const base: AskView = {
    id: "ses_ask_1",
    requester: "engineering",
    recipient: "product",
    question: "How should unknown flags be handled?",
    status: "已回答",
    answer: null,
    reason: null,
    parent: null,
    chain: ["engineering"],
    depth: 1,
    prd_revision: null,
    start_position: 1,
    end_position: 2,
    started_at: "",
    ended_at: null,
  };
  return { ...base, ...over };
}

test("已回答的询问写状态、询问链、时间、问题与回答", () => {
  assert.equal(
    askLine(ask({ answer: "Print the argument as defined in the current requirement." })),
    "已回答 · 工程 → 产品 · 未知时间 · How should unknown flags be handled? · 回答：Print the argument as defined in the current requirement.",
  );
});

test("进行中的询问没有回答与原因", () => {
  assert.equal(
    askLine(ask({ status: "进行中", question: "输出要保留换行吗？" })),
    "进行中 · 工程 → 产品 · 未知时间 · 输出要保留换行吗？",
  );
});

test("回问写出整条询问链并标「回问」", () => {
  const reask = ask({
    id: "ses_ask_2",
    requester: "product",
    recipient: "engineering",
    parent: "ses_ask_1",
    chain: ["engineering", "product"],
    depth: 2,
    question: "现有的入口在哪里？",
    answer: "入口是 src/echo.py。",
  });
  assert.deepEqual(askChain(reask), ["工程", "产品", "工程"]);
  assert.equal(
    askLine(reask),
    "已回答 · 工程 → 产品 → 工程 · 回问 · 未知时间 · 现有的入口在哪里？ · 回答：入口是 src/echo.py。",
  );
});

test("回答附带 PRD 新版本时标出版本", () => {
  assert.equal(
    askLine(ask({ answer: "按新的验收条件实现。", prd_revision: 2 })),
    "已回答 · 工程 → 产品 · 未知时间 · How should unknown flags be handled? · 回答：按新的验收条件实现。 附带 PRD r2",
  );
});

test("没能回答时写原因", () => {
  assert.equal(
    askLine(ask({ status: "没能回答", question: "执行入口在哪里？", reason: "回答的次数达到上限" })),
    "没能回答 · 工程 → 产品 · 未知时间 · 执行入口在哪里？ · 没能回答：回答的次数达到上限",
  );
});

test("回问按深度缩进：最外层不缩进，每深一层多一格", () => {
  assert.equal(askIndent(ask({ depth: 1 })), "0px");
  assert.equal(askIndent(ask({ depth: 2 })), "16px");
  assert.equal(askIndent(ask({ depth: 3 })), "32px");
});
