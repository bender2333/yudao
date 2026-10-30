// run.export 导出入口的单元测试（工单 #814）：文件名带事项与 run 的标识、
// 整包内容按 run.export 返回的原样序列化、下载入口把文件交给浏览器。
// 用 node:test 运行（client/package.json 的 test 脚本按 glob 收集）。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  runExportBlob,
  runExportFileName,
  runExportJson,
  shortRunId,
  workItemPart,
  type RunExportData,
} from "../../src/renderer/src/contract/run-export.ts";
import { downloadRunExport } from "../../src/renderer/src/views/project/run-export.ts";

// run.export 给出的整包（形状按服务端合同：run_id、projection、events、attempts、usage）
function exportData(overrides: Partial<RunExportData> = {}): RunExportData {
  return {
    run_id: "run_ab12cd34ef56ab78",
    projection: { task: "修复登录页的报错", work_item_id: "wi_1a2b3c4d" },
    events: [{ type: "run_created", position: 1 }],
    attempts: [{ attempt_id: "at_1111", status: "success" }],
    usage: { totals: { attempts: 1 } },
    ...overrides,
  };
}

test("run.export 文件名带事项标题与事项标识（工单 #814）", () => {
  const name = runExportFileName(exportData(), "修复登录页的报错");
  assert.equal(name, "修复登录页的报错_wi_1a2b3c4d-run-ab12cd34.json");
});

test("run.export 文件名在标题缺失时用整包里的任务原文，run 标识取短写", () => {
  const name = runExportFileName(exportData(), null);
  assert.equal(name, "修复登录页的报错_wi_1a2b3c4d-run-ab12cd34.json");
});

test("run.export 文件名把文件名里不允许的字符换成连字符", () => {
  const name = runExportFileName(
    exportData({ projection: { task: "a/b\\c:d*e?f\"g<h>i|j", work_item_id: "wi_x" } }),
    null,
  );
  assert.equal(name, "a-b-c-d-e-f-g-h-i-j_wi_x-run-ab12cd34.json");
});

test("run.export 文件名在事项与任务都缺失时落到 run 标识", () => {
  const name = runExportFileName(exportData({ projection: { work_item_id: null } }), null);
  assert.equal(name, "run-ab12cd34.json");
});

test("run.export 文件名在整包都缺失时仍是合法文件名", () => {
  const name = runExportFileName(exportData({ run_id: "run_99", projection: {} }), "");
  assert.equal(name, "run-99.json");
});

test("run 短写取 run_ 后 16 位的前 8 位，形状不符时原样保留", () => {
  assert.equal(shortRunId("run_ab12cd34ef56ab78"), "run-ab12cd34");
  assert.equal(shortRunId("run_ab12cd34ef56ab7899"), "run-ab12cd34");
  assert.equal(shortRunId("run_99"), "run-99");
  assert.equal(shortRunId("别的形状"), "别的形状");
});

test("事项部分：标题在前标识在后，标题缺失用标识，两者都缺失为空", () => {
  assert.equal(workItemPart("标题", "wi_1"), "标题_wi_1");
  assert.equal(workItemPart(null, "wi_1"), "wi_1");
  assert.equal(workItemPart("   ", "wi_1"), "wi_1");
  assert.equal(workItemPart("标题", null), "标题_");
  assert.equal(workItemPart(null, null), "");
});

test("整包内容按缩进 2 的 JSON 序列化，字段原样保留", () => {
  const data = exportData();
  const text = runExportJson(data);
  assert.equal(text, JSON.stringify(data, null, 2));
  assert.deepEqual(JSON.parse(text), data);
});

test("整包文件是 JSON 的 Blob", () => {
  const blob = runExportBlob(exportData());
  assert.equal(blob.type, "application/json");
});

test("下载入口把整包交给浏览器的下载（href、文件名由保存入口接收）", async () => {
  const saved: { blob: Blob; fileName: string }[] = [];
  const outcome = await downloadRunExport(
    // 查询替身：像合同层一样按名称调用，返回 run.export 的整包；不发网络请求
    {
      queryOne: async () => ({ position: 1, data: exportData() }),
    } as never,
    "run_ab12cd34ef56ab78",
    "修复登录页的报错",
    (blob, fileName) => saved.push({ blob, fileName }),
  );
  assert.deepEqual(outcome, { ok: true, fileName: "修复登录页的报错_wi_1a2b3c4d-run-ab12cd34.json" });
  assert.equal(saved.length, 1);
  assert.equal(saved[0].blob.type, "application/json");
  assert.deepEqual(JSON.parse(await saved[0].blob.text()), exportData());
});

test("查询失败时下载入口给出失败原因，不抛出", async () => {
  const saved: { blob: Blob; fileName: string }[] = [];
  const outcome = await downloadRunExport(
    {
      queryOne: async () => {
        throw new Error("run 不存在: run_x");
      },
    } as never,
    "run_x",
    null,
    (blob, fileName) => saved.push({ blob, fileName }),
  );
  assert.deepEqual(outcome, { ok: false, reason: "run 不存在: run_x" });
  assert.equal(saved.length, 0);
});
