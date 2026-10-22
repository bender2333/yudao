// 模型服务不可用时顶栏的提示（工单 #718）：可用时不显示；不可用时写出服务端的说明。

import { test } from "node:test";
import assert from "node:assert/strict";

import { providerNotice } from "../../src/renderer/src/shell/provider-status.ts";

test("模型服务不可用时给出提示，写出服务端的说明", () => {
  const notice = providerNotice({ available: false, reason: "provider_unavailable", message: "缺少凭据 YUDAO_EVAL_API_KEY" });
  assert.notEqual(notice, null);
  assert.equal(notice!.label, "模型服务不可用");
  assert.equal(notice!.detail, "缺少凭据 YUDAO_EVAL_API_KEY");
});

test("模型服务可用时不显示", () => {
  assert.equal(providerNotice({ available: true, reason: null, message: null }), null);
});

test("还没有读到状态时不显示", () => {
  assert.equal(providerNotice(null), null);
  assert.equal(providerNotice(undefined), null);
});

test("服务端没有给说明时用原因顶上", () => {
  const notice = providerNotice({ available: false, reason: "provider_unavailable", message: null });
  assert.equal(notice!.detail, "provider_unavailable");
});
