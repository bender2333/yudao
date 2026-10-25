// 用量口径的单元测试（工单 #301、#744）：请求记录表格的「用量」列、请求详情的「用量」行
// 与用量统计页签说的是同一件事，由同一个函数算出，同一份数据得出同一句话。
// 工单 #744 的现象：请求记录写「未上报」、详情页写「8,993 token」、用量统计写「上报 99」——
// 三处对同一批请求的说法不同。用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";
import { reportedCountText, usageText, usageView } from "../../src/renderer/src/views/project/usage-text.ts";

// 服务端给的用量：上报了总量、没有报进出的两段（上游只给总量，用户使用记录 U93 的形状）
function totalOnly(): Record<string, unknown> {
  return {
    reported: true,
    source: "reported",
    total_tokens: 8993,
    input_tokens: null,
    output_tokens: null,
    cost: null,
    coverage: {
      input_tokens: "missing",
      output_tokens: "missing",
      cache_read_tokens: "missing",
      cache_write_tokens: "missing",
      cost: "missing",
      total_tokens: "reported",
      latency_ms: "measured",
    },
  };
}

test("上报了总量、没报进出两段时写总量，不写未上报", () => {
  assert.equal(
    usageText(totalOnly()),
    "总 8,993 token，输入 未上报，输出 未上报",
  );
});

test("上报了总量时这一句里不出现未上报以外的意思（没有说没上报）", () => {
  // 整句说的是「上报了总量」，进出的两段单独说没报
  const text = usageText(totalOnly());
  assert.equal(text.includes("未上报"), true);
  assert.equal(text.startsWith("总 8,993 token"), true);
  assert.equal(text.includes("总 未上报"), false);
});

test("进出两段都报了时逐项写数值", () => {
  assert.equal(
    usageText({ reported: true, source: "reported", total_tokens: 120, input_tokens: 100, output_tokens: 20 }),
    "总 120 token，输入 100，输出 20",
  );
});

test("什么都没有上报时只写未上报，不填 0", () => {
  assert.equal(usageText({}), "未上报");
  assert.equal(usageText({ reported: false }), "未上报");
  assert.equal(usageText({ reported: false, source: "missing", total_tokens: null }), "未上报");
  // 服务端说没有上报时不写数值（用量统计也只数上报了的那些，两处要对得上）
  assert.equal(usageText({ reported: false, source: "unknown", total_tokens: 7556 }), "未上报");
});

test("服务端没有标记时按数据本身判断（上游只回报合计也要写合计）", () => {
  assert.equal(usageText({ total_tokens: 50 }), "总 50 token，输入 未上报，输出 未上报");
});

test("报了用量但没有 token 数值时写明，不写未上报", () => {
  // 只报了成本或缓存明细：确实上报了，只是没有 token 数值
  assert.equal(
    usageText({ reported: true, source: "reported", total_tokens: null, input_tokens: null, output_tokens: null }),
    "上报了用量，没有 token 数值",
  );
});

test("服务端逐项说明覆盖情况时按它说", () => {
  // coverage 说总量报了、输入没报：按它说
  const view = usageView({
    reported: true,
    total_tokens: 8993,
    input_tokens: null,
    output_tokens: null,
    coverage: { total_tokens: "reported", input_tokens: "missing", output_tokens: "missing" },
  });
  assert.equal(view.reported, true);
  assert.equal(view.total, 8993);
  assert.equal(view.input, null);
  assert.equal(view.output, null);
});

test("coverage 说没报的那一项，即使有数值也不写出来", () => {
  const view = usageView({
    reported: true,
    total_tokens: 100,
    input_tokens: 60,
    coverage: { total_tokens: "reported", input_tokens: "missing" },
  });
  assert.equal(view.total, 100);
  assert.equal(view.input, null);
});

test("页面上不出现英文内部标识与开发者措辞", () => {
  const text = usageText(totalOnly());
  for (const forbidden of ["coverage", "reported", "source", "total_tokens", "input_tokens",
    "output_tokens", "cache_read_tokens", "latency_ms", "missing", "unknown", "[object Object]"]) {
    assert.equal(text.includes(forbidden), false, `这一句里出现了 ${forbidden}`);
  }
});

test("上报用量的请求数：一个都没有时写未上报", () => {
  assert.equal(reportedCountText(0), "未上报");
  assert.equal(reportedCountText(null), "未上报");
  assert.equal(reportedCountText(undefined), "未上报");
});

test("上报用量的请求数：有上报时给出个数", () => {
  assert.equal(reportedCountText(99), "99 个");
  assert.equal(reportedCountText(1), "1 个");
});

