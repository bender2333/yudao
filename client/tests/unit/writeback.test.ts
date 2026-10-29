// 写回的界面文字（工单 #709）：写回结果与写回设置在页面上怎么写。
// 页面上不出现英文内部标识与开发者措辞：状态与停止原因按中文写，
// 合并请求还只是本地记录这件事照实写明。用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";

import type { SourceDirectorySetting, WritebackRecordView } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  CHECK_COMMANDS_LABEL, CHECK_COMMANDS_NOTE, checkCommandsFromText, checkCommandsText, sourceDirectoryPayload,
  writebackText,
} from "../../src/renderer/src/views/project/writeback-text.ts";

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

// 写回检查的命令清单（工单 #815）：一行一条，保存源目录时按填写的清单写回

function sourceDirectory(overrides: Partial<SourceDirectorySetting>): SourceDirectorySetting {
  return {
    name: "回声工具",
    path: "D:/source/echo",
    version: 3,
    writeback_enabled: true,
    remote: "",
    target_branch: "main",
    check_commands: ["uv run pytest -q"],
    credential_ref: null,
    ...overrides,
  };
}

test("写回检查的命令按填写的清单写进源目录的保存参数", () => {
  const payload = sourceDirectoryPayload({
    projectId: "p1",
    existing: sourceDirectory({}),
    name: "回声工具",
    path: "D:/source/echo",
    writebackEnabled: true,
    targetBranch: "main",
    remote: "",
    checkCommands: "uv run pytest -q\nnpm test",
  });
  assert.deepEqual(payload.check_commands, ["uv run pytest -q", "npm test"]);
  assert.equal(payload.project_id, "p1");
  assert.equal(payload.base_version, 3);
});

test("只改名称时写回检查的命令与读出的一致", () => {
  const existing = sourceDirectory({ check_commands: ["uv run pytest -q", "npm test"] });
  const payload = sourceDirectoryPayload({
    projectId: "p1",
    existing,
    name: "回声工具二",
    path: existing.path,
    writebackEnabled: existing.writeback_enabled ?? false,
    targetBranch: existing.target_branch ?? "",
    remote: existing.remote ?? "",
    checkCommands: checkCommandsText(existing.check_commands ?? []),
  });
  assert.equal(payload.name, "回声工具二");
  assert.deepEqual(payload.check_commands, existing.check_commands);
  assert.equal(payload.writeback_enabled, true);
  assert.equal(payload.target_branch, "main");
});

test("空行与两端的空白去掉，行的顺序保持", () => {
  assert.deepEqual(
    checkCommandsFromText("  npm test \r\n\r\n\t\n uv run pytest -q \n"),
    ["npm test", "uv run pytest -q"],
  );
  assert.deepEqual(checkCommandsFromText(""), []);
  assert.deepEqual(checkCommandsFromText(" \n\t\n"), []);
  assert.deepEqual(checkCommandsFromText(checkCommandsText(["a", "b", "c"])), ["a", "b", "c"]);
});

test("凭据引用与基准版本按读出的一行写回，不因保存而清空", () => {
  const payload = sourceDirectoryPayload({
    projectId: "p1",
    existing: sourceDirectory({ credential_ref: "ECHO_TOKEN", version: 7 }),
    name: "回声工具",
    path: "D:/source/echo",
    writebackEnabled: true,
    targetBranch: "main",
    remote: "",
    checkCommands: "",
  });
  assert.equal(payload.credential_ref, "ECHO_TOKEN");
  assert.equal(payload.base_version, 7);
});

test("没有登记源目录时按第一次登记保存", () => {
  const payload = sourceDirectoryPayload({
    projectId: "p2",
    existing: null,
    name: " 回声工具 ",
    path: " D:/source/echo ",
    writebackEnabled: false,
    targetBranch: "",
    remote: "",
    checkCommands: "",
  });
  assert.deepEqual(payload.check_commands, []);
  assert.equal(payload.base_version, 0);
  assert.equal(payload.credential_ref, null);
  assert.equal(payload.name, "回声工具");
  assert.equal(payload.path, "D:/source/echo");
  assert.equal(payload.writeback_enabled, false);
});

test("写回检查的命令在页面上的说明里没有英文内部标识与开发者措辞", () => {
  for (const text of [CHECK_COMMANDS_LABEL, CHECK_COMMANDS_NOTE]) {
    for (const forbidden of ["check_commands", "source_directory", "writeback", "credential_ref", "argv",
      "base_version"]) {
      assert.equal(text.includes(forbidden), false, `这一句里出现了 ${forbidden}`);
    }
  }
});



