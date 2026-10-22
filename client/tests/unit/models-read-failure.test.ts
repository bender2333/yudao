// 模型管理页与它的 JSON 编辑器在读取失败时的说法（工单 #776）：
// 读不出来时给失败提示与服务端给的原文；本来就没有内容时不是失败。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  canSaveDocument,
  jsonDialogFailureText,
} from "../../src/renderer/src/views/models/model-logic.ts";

test("目录文档读不出来：编辑器说明读不出来与服务端给的原文", () => {
  const reason = "查询 catalog.document 没有返回数据：Internal Server Error";
  assert.equal(jsonDialogFailureText(reason), `读取失败：${reason}`);
});

test("没有失败：编辑器没有失败提示（本来就没有内容与读不出来是两回事）", () => {
  assert.equal(jsonDialogFailureText(null), null);
  assert.equal(jsonDialogFailureText(""), null);
});

test("空文档不让保存：读不出来时按保存会把目录写成空的", () => {
  assert.equal(canSaveDocument(""), false);
  assert.equal(canSaveDocument("   \n "), false);
  assert.equal(canSaveDocument('{"providers": [], "models": []}'), true);
});
