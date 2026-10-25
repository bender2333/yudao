// 命令被拒绝时的说明（工单 #671）：内部原因标识不写进页面。
// 项目各页一直按这个约定写（工单 #319 第 5 项），侧栏的接入表单与顶栏的项目菜单却是另一种写法，
// 这里核对全界面：页面上不出现「（原因 xxx）」这样的内部标识。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync,readFileSync } from "node:fs";
import { dirname,join } from "node:path";
import { fileURLToPath } from "node:url";
import { rejectionLabel } from "../../src/renderer/src/contract/command-problem.ts";
import type { Rejected } from "../../src/renderer/src/api/generated/types.gen.ts";

const here = dirname(fileURLToPath(import.meta.url));
const rendererRoot = join(here, "..", "..", "src", "renderer", "src");

function rejected(reason: string, message: string, currentVersion: number | null = null): Rejected {
  return {
    command_id: "cmd_1",
    reason: reason as Rejected["reason"],
    message,
    current_version: currentVersion,
  };
}

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      found.push(...sourceFiles(path));
    } else if (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) {
      found.push(path);
    }
  }
  return found;
}



test("顶栏项目菜单的拒绝提示只给服务端的消息", () => {
  const text = rejectionLabel(rejected("not_allowed", "现在不能重新开始建档"));
  assert.equal(text, "现在不能重新开始建档");
  assert.equal(text.includes("not_allowed"), false);
});

test("基准版本过期时仍按工单 #319 的做法给出当前版本", () => {
  const text = rejectionLabel(rejected("stale_base", "基准版本已经过期", 7));
  assert.match(text, /基准版本已经过期/);
  assert.match(text, /7/);
  assert.equal(text.includes("stale_base"), false);
});

test("没有登记的原因也只给服务端的消息", () => {
  const text = rejectionLabel(rejected("some_new_reason", "命令被拒绝：写回没有可写回的对象"));
  assert.equal(text, "命令被拒绝：写回没有可写回的对象");
  assert.equal(text.includes("some_new_reason"), false);
});

test("渲染进程的源文件里没有把原因标识写进页面的写法", () => {
  const offenders: string[] = [];
  for (const path of sourceFiles(rendererRoot)) {
    if (readFileSync(path, "utf8").includes("（原因 {")) {
      offenders.push(path);
    }
  }
  assert.deepEqual(offenders, []);
});
