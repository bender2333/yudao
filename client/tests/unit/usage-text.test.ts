// 用量口径的单元测试（工单 #301）：请求记录表格的「用量」列与请求详情的「用量」行
// 共用 usageText，上游只回报合计时两处都写合计。用 node --test 运行。
import { test } from "node:test";
import assert from "node:assert/strict";
import { usageText } from "../../src/renderer/src/views/project/usage-text.ts";

test("上报过的用量写合计、输入与输出", () => {
  assert.equal(
    usageText({ total_tokens: 120, input_tokens: 100, output_tokens: 20, reported: true }),
    "120 token，输入 100，输出 20",
  );
});

test("没有 reported 但有合计时同样写合计", () => {
  assert.equal(usageText({ total_tokens: 50 }), "50 token，输入 未上报，输出 未上报");
});

test("既没有上报也没有合计时写未上报", () => {
  assert.equal(usageText({}), "未上报");
  assert.equal(usageText({ reported: false }), "未上报");
});
