// 检验方式的声明表与夹具一致（工单 #151）：
// 质检逐条结论里的六种检验方式在页面上显示中文名，代码名与「是否可执行」的取值在夹具
// client/tests/fixtures/check-methods.json 里；服务端那一份是 harness/tests/fixtures/check_methods.json，
// 服务端测试核对两份相同、服务端的封闭取值与它那份一致。
// 这里核对客户端声明表覆盖夹具：缺一行、名字不同、可执行不同都失败并写明是哪个代码名。
// 守第 13 节的 R2（两端交换的词表是合同）。用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  CHECK_METHODS,
  checkMethodProblems,
  type CheckMethodFixtureRow,
} from "../../src/renderer/src/translate/coverage.ts";

const METHODS: CheckMethodFixtureRow[] = (
  JSON.parse(readFileSync(new URL("../fixtures/check-methods.json", import.meta.url), "utf8")) as {
    methods: CheckMethodFixtureRow[];
  }
).methods;

test("声明表覆盖夹具里的六种检验方式，名字与可执行都相同", () => {
  assert.equal(METHODS.length, 6, "夹具里的检验方式不是六种");
  assert.deepEqual(checkMethodProblems(METHODS), []);
  assert.equal(Object.keys(CHECK_METHODS).length, METHODS.length);
});

test("夹具多出一种检验方式而声明表没有补那一行时，核对失败并写明代码名", () => {
  const extra: CheckMethodFixtureRow[] = [
    ...METHODS,
    { code: "probe", label: "探针", executable: true },
  ];
  const problems = checkMethodProblems(extra);
  assert.ok(problems.some((problem) => problem.includes("probe") && problem.includes("没有一行")), problems.join("\n"));
});

test("声明表里的一种方式与夹具的可执行不同或名字不同时，核对失败", () => {
  const table = {
    ...CHECK_METHODS,
    check: { label: "命令检查", executable: false },
    trial: { label: "试用", executable: true },
  };
  const problems = checkMethodProblems(METHODS, table);
  assert.ok(problems.some((problem) => problem.includes("check") && problem.includes("可执行")), problems.join("\n"));
  assert.ok(problems.some((problem) => problem.includes("trial") && problem.includes("名字")), problems.join("\n"));
});
