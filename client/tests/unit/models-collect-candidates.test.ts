// 模型管理页新建连接时点「获取模型列表」（工单 #843）：
// 连接没有保存时按服务端合同采不到候选（设计说明第 4.3 节只对已保存的连接采集），
// 页面要写清楚先保存什么、为什么，不能让点击既没有反应也不发请求。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  collectCandidatesAction,
  collectCandidatesHint,
} from "../../src/renderer/src/views/models/model-logic.ts";

test("新建连接时点「获取模型列表」：页面说明先保存，不发起采集", () => {
  const action = collectCandidatesAction("add");
  assert.equal(action.kind, "explain");
  if (action.kind !== "explain") return;
  // 先做什么：保存这份连接；为什么：采集按已保存的连接执行
  assert.equal(action.message.includes("保存"), true);
  assert.equal(action.message.includes("连接"), true);
});

test("已保存的连接照旧采集", () => {
  assert.equal(collectCandidatesAction("edit").kind, "collect");
});

test("候选区一直显示下一步：新建时有提醒，已保存时没有", () => {
  assert.equal(collectCandidatesHint("add"), "获取模型列表要先保存这份连接。");
  assert.equal(collectCandidatesHint("edit"), "");
});

test("说明是中文，不出现英文内部标识与开发者措辞", () => {
  const action = collectCandidatesAction("add");
  assert.equal(action.kind, "explain");
  if (action.kind !== "explain") return;
  const texts = [action.message, collectCandidatesHint("add")];
  for (const text of texts) {
    // 内部标识（命令名、字段名、拒绝原因）与英文都不写进页面
    assert.equal(/[A-Za-z]/.test(text), false);
    for (const internal of ["catalog.candidates.collect", "provider_id", "not_found", "mode", "add", "edit"]) {
      assert.equal(text.includes(internal), false);
    }
  }
});
