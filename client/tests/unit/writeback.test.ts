// 写回的界面文字（工单 #709）：写回结果与写回设置在页面上怎么写。
// 页面上不出现英文内部标识与开发者措辞：状态与停止原因按中文写，
// 合并请求还只是本地记录这件事照实写明。用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";

import type { WritebackRecordView } from "../../src/renderer/src/api/generated/types.gen.ts";
import { sourceWritebackText, writebackText } from "../../src/renderer/src/views/project/writeback-text.ts";

function record(overrides: Partial<WritebackRecordView>): WritebackRecordView {
  return {
    status: "completed",
    work_item_id: "w1",
    adoption_id: "adopt_1",
    target_commit: "abc123",
    created_at: "2026-10-23T05:00:00+00:00",
    event_id: "pevt_1",
    ...overrides,
  };
}

test("写回成功时写明成果已经回到仓库、推送的分支与目标分支", () => {
  const text = writebackText(record({
    status: "completed",
    branch: "writeback/adopt_1",
    target_branch: "main",
    pull_request_title: "把回声工具改成命令行",
    pull_request_local_only: true,
  }));
  assert.match(text, /成果已经写回仓库/);
  assert.match(text, /writeback\/adopt_1/);
  assert.match(text, /目标分支 main/);
});

test("合并请求还只是本地记录时照实写明，不说已经创建", () => {
  const text = writebackText(record({
    status: "completed",
    branch: "writeback/adopt_1",
    target_branch: "main",
    pull_request_title: "把回声工具改成命令行",
    pull_request_local_only: true,
  }));
  assert.match(text, /只记录在本地/);
  assert.equal(text.includes("已经创建"), false);
});

test("写回停止（冲突）时写明冲突的文件", () => {
  const text = writebackText(record({
    status: "stopped",
    reason: "conflict",
    conflicts: ["src/echo.py", "README.md"],
  }));
  assert.match(text, /写回停止/);
  assert.match(text, /合并出现冲突/);
  assert.match(text, /src\/echo\.py/);
  assert.match(text, /README\.md/);
});

test("写回停止（核验没有通过）时写明原因，不写冲突", () => {
  const text = writebackText(record({ status: "stopped", reason: "verification_failed" }));
  assert.match(text, /最终树核验没有通过/);
  assert.equal(text.includes("冲突"), false);
});

test("无需写回与写回等待各有各的说法", () => {
  assert.match(
    writebackText(record({ status: "not_needed", reason: "changes_already_present" })),
    /变更已经在目标分支上/,
  );
  assert.match(
    writebackText(record({ status: "held", reason: "waiting_previous_adoption" })),
    /前一次采纳还没有合入目标分支/,
  );
});

test("写回已核实写明分支", () => {
  const text = writebackText(record({ status: "verified", branch: "writeback/adopt_1" }));
  assert.match(text, /写回已核实/);
  assert.match(text, /writeback\/adopt_1/);
});

test("页面上不出现英文内部标识与开发者措辞", () => {
  const texts = [
    writebackText(record({ status: "completed", branch: "writeback/adopt_1", target_branch: "main" })),
    writebackText(record({ status: "stopped", reason: "conflict", conflicts: ["a.txt"] })),
    writebackText(record({ status: "not_needed", reason: "changes_already_present" })),
    writebackText(record({ status: "held", reason: "waiting_previous_adoption" })),
  ];
  for (const text of texts) {
    for (const forbidden of ["completed", "stopped", "not_needed", "held", "verified", "conflict",
      "verification_failed", "target_changed", "unrepresentable_path", "missing_source_reference",
      "local_test_boundary", "adoption_id", "pull_request"]) {
      assert.equal(text.includes(forbidden), false, `这一句里出现了 ${forbidden}`);
    }
  }
});

test("源目录的写回设置：没有打开时写未打开", () => {
  assert.equal(sourceWritebackText({ writeback_enabled: false, target_branch: "main", remote: "" }), "未打开");
  assert.equal(sourceWritebackText({}), "未打开");
});

test("源目录的写回设置：打开以后写目标分支与远端", () => {
  assert.equal(
    sourceWritebackText({ writeback_enabled: true, target_branch: "main", remote: "" }),
    "已打开，目标分支 main",
  );
  assert.equal(
    sourceWritebackText({ writeback_enabled: true, target_branch: "main", remote: "origin" }),
    "已打开，目标分支 main，远端 origin",
  );
});

test("源目录的写回设置：打开了却没有目标分支时照实写明", () => {
  assert.equal(
    sourceWritebackText({ writeback_enabled: true, target_branch: "", remote: "" }),
    "已打开，没有填目标分支",
  );
});
