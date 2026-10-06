// 请求详情里失败类型与结束原因两行的取值（工单 #305 第 4 项验收）。
// 空输出按失败处理以后，页面上要能从一条请求记录看到「为什么这次没成功」与「流自己说的结束原因」：
// 失败类型取内核记录的分类（空输出记 empty_output），结束原因取诊断里提供方给出的值。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { failureRows, failureType, finishReason } from "../../src/renderer/src/views/project/attempt-failure.ts";

test("空输出的请求详情给出失败类型与流给出的结束原因", () => {
  const attempt = {
    status: "failed",
    error_class: "empty_output",
    reason: "empty_output",
    error: "Model response contained no output items",
    retryable: true,
    diagnostics: {
      error_type: "empty_output",
      finish_reason: "max_tokens",
      usage_reported: true,
      output_tokens: 2048,
      max_output_tokens: 2048,
      has_reasoning: true,
    },
  };
  assert.deepEqual(failureRows(attempt), [["失败类型", "empty_output"], ["结束原因", "max_tokens"]]);
});

test("结束原因按各协议自己的写法原样显示", () => {
  assert.equal(finishReason({ diagnostics: { finish_reason: "length" } }), "length");
  assert.equal(finishReason({ diagnostics: { finish_reason: "completed" } }), "completed");
});

test("失败类型先取记录上的分类，其次取诊断里的错误种类", () => {
  assert.equal(failureType({ error_class: "provider_timeout", diagnostics: { error_type: "timeout" } }), "provider_timeout");
  assert.equal(failureType({ reason: "provider_unavailable", diagnostics: { error_type: "credential_rejected" } }), "provider_unavailable");
  assert.equal(failureType({ diagnostics: { error_type: "connection" } }), "connection");
});

test("成功的请求没有失败类型，缺失的结束原因写明未上报", () => {
  assert.deepEqual(failureRows({ status: "success", diagnostics: {} }),
    [["失败类型", "没有"], ["结束原因", "未上报"]]);
  assert.deepEqual(failureRows({}), [["失败类型", "没有"], ["结束原因", "未上报"]]);
});

test("诊断写成列表或空值时按未上报处理，不抛错", () => {
  assert.equal(finishReason({ diagnostics: [] }), "未上报");
  assert.equal(failureType({ error_class: "", reason: "", diagnostics: "none" }), "没有");
  assert.equal(finishReason({ diagnostics: { finish_reason: "" } }), "未上报");
});
