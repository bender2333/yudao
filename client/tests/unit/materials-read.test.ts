// 资料页读到的内容：读不出来与「本来就没有内容」是两句不同的话（工单 #714）。
// 读取层给出失败信息（工单 #728），这里核对界面按它说的话。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import { originalView, readView } from "../../src/renderer/src/views/project/materials-read.ts";

const REASON = "查询 event.detail 没有返回数据：Internal Server Error";

type Detail = { artifacts: { prd?: string } };
type File = { content: string | null; base64: string | null };

test("读不出来时是「读取失败」，不是「没有原文」", () => {
  const view = originalView<Detail>({ data: null, loading: false, error: REASON }, (data) => data.artifacts.prd ?? "");
  assert.deepEqual(view, { kind: "failed", reason: REASON });
});

test("读成功但原文确实为空时才说没有原文", () => {
  const view = originalView<Detail>({ data: { artifacts: {} }, loading: false, error: null }, (data) => data.artifacts.prd ?? "");
  assert.deepEqual(view, { kind: "empty" });
});

test("读成功有原文时给出原文", () => {
  const view = originalView<Detail>({ data: { artifacts: { prd: "# 需求" } }, loading: false, error: null }, (data) => data.artifacts.prd ?? "");
  assert.deepEqual(view, { kind: "content", text: "# 需求" });
});

test("正在读取时先说正在读取", () => {
  assert.deepEqual(originalView<Detail>({ data: null, loading: true, error: null }, (data) => data.artifacts.prd ?? ""), { kind: "loading" });
});

test("交付文件：读不出来时是「读取失败」，读到了才给内容", () => {
  assert.deepEqual(
    readView<File>({ data: null, loading: false, error: REASON }),
    { kind: "failed", reason: REASON },
  );
  assert.deepEqual(
    readView<File>({ data: { content: "x", base64: null }, loading: false, error: null }),
    { kind: "ready", data: { content: "x", base64: null } },
  );
  assert.deepEqual(readView<File>({ data: null, loading: true, error: null }), { kind: "loading" });
});
